# OP25 WebSocket & HTTP Communication Architecture (legacy stack)

> **This describes the LEGACY stack**: `terminal.py` + `http_server.py`
> (waitress WSGI) serving `www/www-static/` or `www/react-app/`, selected with
> `"terminal": { "module": "terminal.py", "terminal_type": "http:0.0.0.0:8080" }`.
> It uses **two ports** (HTTP on N, control WebSocket on N+1), an HTTP POST
> fallback, and per-channel `ws://` audio sinks in the C++ layer.
>
> For the **current** stack — `websocket_server.py` (FastAPI/uvicorn) serving
> `www/dist`, single port, `/ws`, no POST fallback — see
> [README-new-gui.md](README-new-gui.md). The two are configuration-selected
> and do not share a protocol; do not follow this document to configure the new
> one.

This document describes how the legacy React-based GUI communicates with the
Python backend (`multi_rx.py`) over HTTP and WebSockets — covering both the
control channel and the browser audio stream.

---

## Overview

```
Browser (React GUI)
        │
        ├─── Control ────────────────────────────────────────────────┐
        │    WebSocket ws://host:<HTTP_PORT+1>/  (primary)           │
        │    HTTP POST  http://host:<HTTP_PORT>/  (fallback)         │
        │                                                             ▼
        │                                                  http_server.py
        │                                                  (waitress WSGI)
        │                                                       │      │
        │                                    my_output_q ◄─────┘      │ my_recv_q
        │                                         │                    │
        │                                         ▼                    ▲
        │                               multi_rx.py / trunking.py     │
        │                               (demodulation, trunking)       │
        │                               sends state to my_input_q ────┘
        │
        └─── Audio ──────────────────────────────────────────────────►
             WebSocket ws://host:<AUDIO_PORT>/
             (one port per channel, e.g. 9000, 9001, …)
             Raw Int16 PCM, 8 kHz mono, little-endian binary frames
```

---

## Control Channel

### Transport choice

The GUI (`useControl` hook in `src/hooks/useControl.ts`) always tries to
establish a WebSocket connection first.  If the server does not have the Python
`websockets` library installed, the connection fails and all commands are sent
via HTTP POST instead (the fallback path).

| Path | Endpoint | Direction |
|------|----------|-----------|
| WebSocket (primary) | `ws://host:<HTTP_PORT+1>/` | bidirectional |
| HTTP POST (fallback) | `http://host:<HTTP_PORT>/` | request / response |

The WebSocket port is always **HTTP port + 1** (e.g. HTTP on 8080 → WS control
on 8081).

### Command format

All commands — whether sent over WebSocket or HTTP — use the same JSON array
format:

```json
[
  { "command": "update",              "arg1": 0,    "arg2": 0 },
  { "command": "hold",                "arg1": 1234, "arg2": 0 },
  { "command": "get_terminal_config", "arg1": 0,    "arg2": 0 }
]
```

`arg2` is the channel index when a command targets a specific receiver channel.

### Server-side command handling

```
GUI sends command array
        │
        ▼
http_server.py  (_ws_handler  –or–  post_req)
        │   Converts each object to a gr.message and enqueues it:
        │   gr.message().make_from_string(command, -2, arg1, arg2)
        │
        ▼
my_output_q  (GNU Radio message queue)
        │
        ▼
multi_rx.py / trunking.py read from output_q and execute the command
(e.g. hold a talkgroup, skip, adjust tuning, …)
```

### Response / push format

The Python backend continuously sends state updates (trunking status, channel
info, frequency data, etc.) by writing `gr.message` objects to `my_input_q`.
The `queue_watcher` thread in `http_server.py` reads these messages and:

1. Stores them in `my_recv_q` so that HTTP polling clients can collect them on
   the next POST response.
2. Calls `_ws_push()` to immediately broadcast the message as a JSON text frame
   to every connected WebSocket client.

Only messages of type `-4` (JSON payload) are forwarded; these always contain a
`json_type` discriminator field.

```
multi_rx.py writes gr.message(type=-4, json_string) to my_input_q
        │
        ▼
queue_watcher.callback → process_qmsg(msg)
        ├── inserts into my_recv_q  (for HTTP clients)
        └── calls _ws_push(msg.to_string())
                │
                └── asyncio.run_coroutine_threadsafe(_broadcast(), _ws_loop)
                            │
                            └── ws.send(payload)  ← each connected WS client
```

### Response types

Every server response carries a `json_type` field.  The GUI dispatches on this
value in `App.tsx`:

| `json_type` | Contents |
|-------------|----------|
| `terminal_config` | Smart-colour rules, tuning step sizes, default channel |
| `channel_update` | Per-receiver channel list with tgid / freq / mode / hold state |
| `trunk_update` | Full trunking state: NAC data, frequency activity, subscriber affiliations |
| `change_freq` | Active channel has tuned to a new frequency / talkgroup |
| `rx_update` | Incremental receiver status (frequency error in Hz) |
| `ws_instances` | Map of channel keys → WebSocket audio endpoint URLs |
| `call_log` | Voice grant log entries |
| `full_config` | Complete JSON configuration including presets and site aliases |
| `plot` | Signal plot data (FFT, constellation, symbol, etc.) |

### Startup sequence

On startup the GUI sends three commands before polling begins:

```
get_terminal_config  → returns terminal_config  (colour rules, steps)
get_full_config      → returns full_config       (presets, site aliases)
get_ws_instances     → returns ws_instances      (audio WS URLs per channel)
```

After that, an `update` command is sent once per second to trigger Python to
flush any pending state messages.

### HTTP fallback polling

When the WebSocket is not available, the HTTP fallback timer fires every
second.  It takes all queued commands, POSTs them to `http://host:<PORT>/`,
and parses the JSON array returned in the response body.  The 200 ms
`time.sleep` inside `post_req` gives Python time to process commands before
the HTTP response is assembled.

---

## Audio Streaming

### Server side

Each receiver channel that should stream browser audio must be given a
`ws://` destination in the channel configuration:

```json
"destination": "udp://127.0.0.1:23456, ws://0.0.0.0:9000"
```

A dedicated WebSocket audio server (separate from `http_server.py`) listens on
the configured port and streams decoded PCM directly to connected browsers.

Multiple channels each need their own port:

```json
Channel 0 → ws://0.0.0.0:9000
Channel 1 → ws://0.0.0.0:9001
Channel 2 → ws://0.0.0.0:9002
```

### Wire format

| Frame type | Content |
|------------|---------|
| Binary | Raw Int16 PCM samples, 8 000 Hz, mono, little-endian |
| Text `{"cmd":"audio_drain"}` | Flush the client's playback queue (transmission end) |
| Text `{"cmd":"audio_drop"}` | Discard the client's playback queue immediately |

### Client side (`useAudio` hook)

1. The GUI first calls `get_ws_instances` and receives a map of
   `{ channelKey: "ws://0.0.0.0:9000" }` from the server.
2. For each endpoint, `useAudio` opens a `WebSocket` and sets
   `ws.binaryType = 'arraybuffer'`.
3. Binary frames are converted to `Int16Array` and scheduled into the Web
   Audio API scheduler (`AudioContext.createBufferSource`) at the correct
   sample rate (8 000 Hz).
4. An `AudioContext` cannot be created until a user gesture has occurred
   (browser security requirement).  The headphones button in `MainDisplay`
   calls `initAudioCtx()` on click, then `toggleAudio(channel)` to unmute.
5. If the connection drops, `ws.onclose` schedules a reconnect after 3 s.

### URL rewriting

Audio endpoint URLs come from the server and may contain `0.0.0.0` or
`127.0.0.1`.  The `useAudio` hook rewrites these so the browser can reach
them:

- If a remote **server URL** is configured in Settings, the hostname is
  replaced with the server's hostname (but the audio *port* is preserved — it
  is independent of the HTTP port).
- Otherwise `0.0.0.0` / `127.0.0.1` are replaced with
  `window.location.hostname`.

---

## CORS

`http_server.py` includes permissive CORS headers on all responses so the GUI
can be served from a different origin (e.g. the Vite dev server during
development):

```
Access-Control-Allow-Origin:  *
Access-Control-Allow-Methods: GET, POST, OPTIONS
Access-Control-Allow-Headers: Content-Type
```

`OPTIONS` preflight requests receive a `204 No Content` response with the
same headers.  To restrict access to a specific origin, change `'*'` in
`CORS_HEADERS` inside `http_server.py`.

---

## Remote access

The **Server URL** setting (stored in `localStorage`) allows the GUI to
connect to an OP25 instance on a different host.  Leave it empty to use the
same origin.

Example: GUI served from a laptop at `http://192.168.1.20:5173`, OP25 running
on a Raspberry Pi at `192.168.1.10:8080`.

```
Settings → Server URL: http://192.168.1.10:8080
```

The GUI then connects to:
- HTTP control:  `http://192.168.1.10:8080/`
- WS control:    `ws://192.168.1.10:8081/`
- Audio ch 0:    `ws://192.168.1.10:9000/`  (hostname rewritten, port kept)
