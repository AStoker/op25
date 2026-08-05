# OP25 new GUI — FastAPI server and WebSocket protocol

This is the reference for the **current** web UI: a React SPA served by
`websocket_server.py` (FastAPI + uvicorn) on a **single port**.

Selected by the `terminal` block of the multi_rx JSON config:

```json
"terminal": {
    "module": "websocket_server.py",
    "terminal_type": "ws:0.0.0.0:8080"
}
```

The older two-port stack (`terminal.py` + `http_server.py`, waitress) is still
present and is documented separately in
[README-websockets.md](README-websockets.md). They are mutually exclusive and
share no protocol.

`multi_rx.py` is the only app that can serve this UI — `rx.py` hardcodes
`from terminal import op25_terminal`.

---

## Layout

```
op25/gr-op25_repeater/
├── apps/websocket_server.py     FastAPI app, WS bridge, audio, call capture
├── apps/ha_bridge.py            call clip segmentation + Home Assistant STT
├── www/app/                     React 18 + MUI 6 + Vite (source)
│   └── yarn build ──► www/dist  committed build artifact, served by the above
```

Everything is on one port: static files, the control WebSocket, and the audio
stream.

```
Browser (React SPA)
   │
   ├── GET  /                     www/dist (SPA fallback for client routes)
   ├── WS   /ws                   control + state, JSON frames
   ├── GET  /api/stream           continuous audio (WAV or raw PCM)
   ├── GET  /api/config           the loaded multi_rx JSON
   ├── GET  /api/audio/channels   selectable audio streams
   ├── GET  /api/calls            captured call clips + transcripts
   ├── GET  /api/calls/{id}/audio.wav
   ├── GET  /api/captures         raw symbol-capture files
   ├── GET  /api/captures/{name}
   └── GET  /api/ha/status        capture / speech-to-text diagnostics
                    │
                    ▼
        ws_terminal thread  ◄── ui_in_q / ui_out_q ──►  multi_rx.py
```

---

## WebSocket protocol

Every frame is `{ "type": <MessageType>, "payload": <object> }`.

### Downstream (server → client)

| Type | Carries |
|---|---|
| `SYSTEM_STATE` | the health payload, **and** every decoder `json_type` without a more specific home: `trunk_update`, `channel_update`, `plot`, `terminal_config`, `full_config`, `ws_instances`, `meta_update` |
| `CALL_ACTIVITY` | `call_log` entries |
| `CALL_AUDIO` | a captured clip (`call_clip`), then again with its transcript (`call_transcript`) |
| `ERROR` | `{ detail }` — unknown message type or invalid JSON |

The decoder tags each of its own messages with `json_type`, so a client
discriminates on both the envelope type and the inner `json_type`. The routing
table is `_JSON_TYPE_TO_MSG` in `websocket_server.py`; anything unlisted falls
through to `SYSTEM_STATE`.

There is no `SDR_STATUS` type. An earlier revision declared one, plus routing
for `chan_status` / `trunked_site_status` / `sys_info`, none of which any
decoder module emits.

#### The health payload

Sent on connect and then once a second:

```json
{ "status": "running", "uptime": 1874, "site_name": "voice channel",
  "trunk_id": "palmetto", "error_detail": "" }
```

`status` is `stopped` before the first decoder message, `running` while updates
are arriving, and `error` after 5 s of silence (`error_detail` says how long).
Consumed by `useSystemState()`, which drives the decoder chip in the header.

#### Call history on connect

`call_log` is a **draining delta feed** — `tk_p25.get_call_log()` clears its
buffer on every read, and the bridge polls once a second whether or not a
browser is attached. The server therefore keeps a 200-entry ring and replays it
on connect as a `call_log` frame with `"replay": true`. Clients must still
accumulate; the ring only covers what the server itself has seen.

### Upstream (client → server)

| Type | Payload |
|---|---|
| `CALL_CONTROL` | `{ command, arg1, arg2 }` — forwarded verbatim to the decoder |
| `SYSTEM_CONTROL` | `{ action: "quit" }` |

`CALL_CONTROL` is a thin pipe onto `multi_rx.process_qmsg`, so every decoder UI
command is reachable: `hold`, `skip`, `lockout`, `whitelist`, `reload`,
`adj_tune`, `set_debug`, `capture`, `dump_tgids`, `dump_buffer`, `toggle_plot`,
`set_freq`, `get_full_config`, `get_terminal_config`, `get_ws_instances`,
`update`. `arg1` is usually a TGID or value and `arg2` the channel msgqid.

There is no mute command: muting is client-side, because the page simply stops
pulling `/api/stream`.

---

## Audio

The decoder sends voice as UDP PCM. The server binds those ports, re-streams
them over HTTP, and (optionally) slices them into per-call clips.

- Ports are discovered from each channel's `destination` (`udp://host:port`,
  plus `port+1` for slot B). `terminal.audio_ports` overrides outright.
- `GET /api/stream` — every port mixed together. 8 kHz/16-bit/mono WAV by
  default. `rate=` resamples (16 kHz for Home Assistant/Whisper), `format=raw`
  drops the header.
- `GET /api/stream?channel=N` — one config channel. `?port=N` — one exact
  stream, which is how to reach a DMR slot B. `GET /api/audio/channels` lists
  what is available, with byte counters so a client can hide slots that never
  carry anything.
- `ws://` destinations are **not** used by this stack. They are the legacy
  stack's C++ websocketpp sinks; see
  [README-browser-audio.md](README-browser-audio.md).

Slot A and slot B stay separate streams on purpose: on DMR they are two
unrelated conversations, so mixing them would interleave two people.

### Local speaker output at the same time

A unicast UDP port has exactly one consumer, so `sockaudio.py` and this server
cannot share one. Local audio wins — port discovery excludes anything claimed by
an `audio.instances[]` entry. To run both, give the channel a second
destination:

```json
"destination": "udp://127.0.0.1:23456, udp://127.0.0.1:23458"
```

`apps/richland-mac.json` is a working example.

---

## Signal plots

Plots are rendered client-side from raw data rather than as gnuplot PNGs.
`wrap_gp.send_plot()` emits `json_type: "plot"` with
`{chan, mode, data: [[x,y],…], xrange, yrange, title}` for all six modes
(`fft`, `constellation`, `symbol`, `eye`, `mixer`, `fll`).

- Rate is `http_plot_interval` (default 1.0 s) — *not* `curses_plot_interval`,
  which defaults to 0.0 and would emit every buffer.
- Payloads are decimated to 1200 points by striding, so a long trace still
  spans its full range.
- The decoder owns plot on/off state and it survives a page reload, so the UI
  adopts any mode it sees data for.

`rx_update` — the http terminal's list of gnuplot PNG filenames — is gated on
`terminal_type == "http"` in `multi_rx.ui_plot_update()`, so this stack never
receives one. Nothing is missing; the data arrives as `plot` instead.

---

## System types

The payload shape differs by trunking module, and the UI branches on
`system.type` (`utils/systemKind.ts`):

| | P25 | SmartNet | Connect+ |
|---|---|---|---|
| identity | NAC, WACN, SysID, RFSS/Site, LRA | System ID, Site | LCN count, rest channel |
| band plan | yes | — | — |
| adjacent sites | yes | yes | — |
| subscribers (affiliation) | yes | — | — |
| patches | yes | yes | — |
| talkgroup tags + priority | yes | yes | yes |

Fields a system type does not have are **absent**, not zero, and the cards say
so rather than implying data is still coming.

---

## Testing without a browser

`multi_rx.py` holds the dongle, so run one instance and probe it:

```python
async with websockets.connect("ws://127.0.0.1:8080/ws") as ws:
    print(json.loads(await ws.recv()))   # health payload
```

At 1 Hz you should see `SYSTEM_STATE` (health), `SYSTEM_STATE/trunk_update`,
`SYSTEM_STATE/channel_update` and `CALL_ACTIVITY/call_log`.

For UI checks, headless Chrome with `--virtual-time-budget` gives false
negatives — virtual time outruns the real WebSocket handshake, so the app is
frozen at "connecting" in the screenshot even when the backend is healthy.
Drive Chrome over CDP with real `asyncio.sleep()` waits instead.

Python tests: `pytest` from `apps/` (specs are `tests/*_spec.py`), in-process
via FastAPI's `TestClient` — no network or dongle needed. Note that
`TestClient.stream()` hangs on `/api/stream` because it is an unbounded
generator; drive `AudioStreamManager.generate()` directly under asyncio.
