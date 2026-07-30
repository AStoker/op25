# CLAUDE.md — op25 modernization

Fork of boatbod/op25 (P25/DMR/SmartNet trunking SDR decoder). Working branch:
`feature/updated-gui`. The goal of this branch is to replace the legacy web UI +
WSGI server with a modern React SPA served by a FastAPI/uvicorn backend, and to
keep the whole thing buildable on both **macOS (Apple Silicon)** and
**Raspberry Pi 5 (Debian, GNURadio 3.10)**.

## Target platforms

| Platform | Install script | Python | Notes |
|---|---|---|---|
| macOS (Apple Silicon) | `./install-mac.sh` | venv at `op25/gr-op25_repeater/apps/.venv` seeded from Homebrew gnuradio's private venv | dev/test machine |
| Raspberry Pi 5 (Debian) | `./install.sh` | system `/usr/bin/python3` | deployment target; must stay working |

`op25/gr-op25_repeater/apps/op25_python` is a one-line text file holding the
absolute path of the interpreter to use. It is gitignored and written by the
install script. **Always invoke apps with that interpreter**, e.g.

```bash
cd op25/gr-op25_repeater/apps
$(cat op25_python) multi_rx.py -c richland-single.json -v 1
```

## Two parallel UI stacks — know which one you're touching

The branch currently contains **both** the old and the new stack. They are
selected entirely by the `terminal` block of the JSON config.

### New stack (the target)
```
op25/gr-op25_repeater/www/app/          React 18 + MUI 6 + Vite  (source)
        └─ yarn build → www/dist/       served by websocket_server.py
op25/gr-op25_repeater/apps/websocket_server.py   FastAPI + uvicorn
```
Config selector:
```json
"terminal": { "module": "websocket_server.py", "terminal_type": "ws:0.0.0.0:8080" }
```
- Single port. Static files, control WebSocket, and the audio stream
  (`/api/stream`, WAV over HTTP) all live on it.
- Protocol is `{ "type": ..., "payload": ... }`. Downstream: `SYSTEM_STATE`,
  `SDR_STATUS`, `CALL_ACTIVITY`. Upstream: `CALL_CONTROL`, `SYSTEM_CONTROL`.
- Audio path: decoder UDP → `UdpAudioReceiver` → `AudioStreamManager` →
  browser. Ports are discovered from each channel's `destination`
  (`udp://host:port`, plus `port+1` for the TDMA slot B), defaulting to
  `127.0.0.1:23456/23457`.
- Docs: `www/app/AGENTS.md` (thin).

### Legacy stack (still present, being replaced)
```
op25/gr-op25_repeater/www/react-app/    older React GUI (source)
        └─ yarn build → www/www-static/ served by http_server.py
op25/gr-op25_repeater/apps/http_server.py        waitress WSGI
```
Config selector:
```json
"terminal": { "module": "terminal.py", "terminal_type": "http:0.0.0.0:8080" }
```
- Two ports: HTTP on N, control WebSocket on **N+1**, HTTP POST fallback on N.
- Documented in `README-websockets.md` — note that doc describes the **legacy**
  stack, not `websocket_server.py`.
- `terminal.py` also provides `terminal_type: "curses"` for a TUI.

`www/react-app/AGENTS.md` is the detailed (legacy) protocol reference and is
still the best description of the underlying `multi_rx.py` JSON message shapes
(`json_type: channel_update / trunk_update / rx_update / terminal_config`),
which the new stack reuses.

## Verified working (end-to-end smoke test, 2026-07-30, macOS + RTL-SDR V4)

Live against the real Palmetto 800 system with `richland-single.json`:
RF lock → control-channel decode → trunk/channel/call state over the WebSocket →
React UI fully populated → browser audio. Specifically confirmed:

- Site Information (NAC/WACN/SysID/RFSS-Site/control RX+TX/secondary CCs),
  band plan, frequency grid with per-channel activity counters.
- Talkgroup table (1916 tags loaded from `palmetto_tgs.tsv`), active-call
  display, Call History, and Subscribers (radio IDs + affiliations).
- Upstream commands round-trip: `get_full_config` and `get_terminal_config`
  both return over the WS, and unknown message types produce an `ERROR` frame.
- `/api/stream` serves valid RIFF/WAVE at exactly 8 kHz/16-bit mono with real
  voice content (peak ~28k, ~28% non-silent during normal traffic).
- No JS console errors.

## Audio backends

`sockaudio.py` is the single choke point for local speaker output — `audio.py`,
`rx.py` and `multi_rx.py` all go through `socket_audio`. It has three backends
behind one duck-typed interface (`open/close/setup/write/drain/drop/dump/check`):

| Backend | Library | Platforms |
|---|---|---|
| `pa_sound` | `libpulse-simple.so.0` | Linux only |
| `alsasound` | `libasound.so.2` | Linux only |
| `portaudio_sound` | `sounddevice` / PortAudio | **cross-platform** (CoreAudio on macOS) |

`socket_audio.open_pcm_backend()` picks one. Linux keeps its historical order
(PulseAudio when `device_name` asks for it, else ALSA), falling back to
PortAudio only if neither library loads. Anything not Linux goes straight to
PortAudio, so an existing config that says `"device_name": "pulse"` still works
on a Mac. `device_name` may also name a backend directly (`portaudio`,
`coreaudio`, `alsa`, `pulse`) or a PortAudio device name/index.

**PortAudio needs a jitter buffer, not blocking writes.** The decoder produces
20 ms of audio every 20 ms, so feeding a PortAudio stream directly leaves it
permanently on the edge of empty and it underruns on nearly every callback.
`portaudio_sound` therefore runs a callback plus a ring buffer, priming
`PORTAUDIO_PRIME_MS` (120 ms) before playback starts and re-priming whenever it
runs dry. Do not "simplify" this back to `stream.write()`.

Also do not map `PCM_BUFFER_SIZE` onto PortAudio's `latency`: they are not the
same quantity. Measured on CoreAudio at 8 kHz, requesting 0.5 s yields ~2.5 s of
real delay. `latency='low'` gives ~102 ms. Tunable via
`OP25_PORTAUDIO_LATENCY`, `OP25_PORTAUDIO_PRIME_MS`, `OP25_PORTAUDIO_MAX_MS`.

### Local audio and browser audio on the same channel

A unicast UDP port has exactly one consumer, so `sockaudio` and
`websocket_server`'s `UdpAudioReceiver` cannot share one. Local audio wins:
`_discover_audio_ports()` excludes any port claimed by an `audio.instances[]`
entry. To run both, give the channel a second destination and let discovery find
it (`destination` is comma-separated — `op25_audio.cc:143` tokenizes on `,`):

```json
"destination": "udp://127.0.0.1:23456, udp://127.0.0.1:23458"
```

`terminal.audio_ports` is an explicit override that wins outright.
`apps/richland-mac.json` is a working example of this dual-audio setup.

## Signal plots

The new UI renders plots client-side from raw data rather than displaying
gnuplot images. `wrap_gp.send_plot()` emits `json_type: "plot"` with
`{chan, mode, data: [[x,y],...], xrange, yrange, title}`, matching
`PlotPayload` in `www/app/src/types/op25.ts`. All six modes work: `fft`,
`constellation`, `symbol`, `eye`, `mixer`, `fll`.

Things to know:

- `wrap_gp` skips `attach_gp()` when `out_q` is set, and `multi_rx.py` **always**
  passes `out_q`. So gnuplot is only started if `set_output_dir()` is also
  called, which the `http` terminal does for its PNGs. `rx.py` passes no
  `out_q`, so its curses/x11 plots are unaffected.
- Payloads are decimated to `PLOT_MAX_POINTS` (1200) by striding, not
  truncating, so a long trace still spans its full range.
- Eye traces are overlaid by setting x to the position within the trace, which
  reproduces what gnuplot draws as separate line segments.
- Rate is `http_plot_interval` (default 1.0s) for the `ws` terminal — *not*
  `curses_plot_interval`, which defaults to 0.0 and would emit every buffer.
- The decoder owns plot on/off state and it survives a page reload, so
  `op25Service.tsx` adopts any mode it sees data for. Without that, a reload
  leaves the toggle dark while data streams, and the next click switches the
  decoder off while switching the display on.

## Known remaining gaps

1. `www/dist` is a **committed build artifact**. It can drift from `www/app/src`
   — rebuild before testing UI changes.
2. `call_log` is a **draining delta feed**: `tk_p25.get_call_log()` clears the
   buffer on every read, and `ws_terminal` polls once per second whether or not
   a client is attached. Clients must accumulate (the frontend does), and a
   client that connects late permanently misses earlier calls.
3. `gains` values must be **integers** — `multi_rx.py:150` does `int(gain)`, so
   `"LNA:49.6"` raises `ValueError` at startup.
4. Nothing here has been verified on the **Raspberry Pi 5**. The Linux audio
   path in particular is unchanged in its ALSA/PulseAudio ordering but has only
   been exercised through the fallback chain on macOS.

## Testing the running stack without a browser

`multi_rx.py` holds the dongle, so use one instance and probe it. A WS client
is the fastest way to see whether the bridge is alive:

```python
async with websockets.connect("ws://127.0.0.1:8080/ws") as ws:
    print(json.loads(await ws.recv()))   # SYSTEM_STATE snapshot on connect
```

At 1 Hz you should see `SYSTEM_STATE/trunk_update`,
`SYSTEM_STATE/channel_update` and `CALL_ACTIVITY/call_log`.

For UI checks, **headless Chrome with `--virtual-time-budget` gives false
negatives** — virtual time outruns the real WebSocket handshake, so the app is
frozen at "connecting" in the screenshot even when the backend is healthy.
Drive Chrome over CDP with real `asyncio.sleep()` waits instead
(`--headless=new --remote-debugging-port=9222`, then `Page.navigate`, sleep,
`Runtime.evaluate` / `Page.captureScreenshot`).

## Build & run

```bash
# C++/Python GNURadio modules (only needed when op25/*/lib or include changes)
cd build && make -j$(sysctl -n hw.logicalcpu) && sudo make install

# Frontend (new stack)
cd op25/gr-op25_repeater/www/app && yarn install && yarn build   # → ../dist

# Run
cd op25/gr-op25_repeater/apps
$(cat op25_python) multi_rx.py -c richland-single.json -v 1 2> stderr.2
# then open http://localhost:8080
```

Python tests: `pytest` from `apps/` (specs are `tests/*_spec.py`).
`tests/websocket_server_spec.py` covers the new server's static file serving,
SPA fallback, path traversal, method handling and CORS — 21 tests, in-process
via FastAPI's `TestClient`, no network or dongle needed. Requires `httpx`.

## Local config files (gitignored)

`apps/.gitignore` excludes `*.json`, `*.tsv`, `*.sh`, `op25_python` — so real
configs are untracked and live only on the dev machine. Do not assume a clean
checkout has them.

- `richland-single.json` — one RTL-SDR, Palmetto 800 (SC) P25 trunked system,
  **new** `ws:` terminal. This is the primary smoke test.
- `richland.json` — three-dongle version, legacy `http:` terminal.
- `palmetto_tgs.tsv` — talkgroup tags.
- Tracked examples: `cfg.json`, `p25_single_rtl_example.json`, etc.

## Hardware notes

- Dev dongle is an **RTL-SDR Blog V4** (R828D tuner). It needs a librtlsdr with
  V4 support — Homebrew `librtlsdr` 2.0.2 has it. Verify with
  `rtl_test -t`, which should print `RTL-SDR Blog V4 Detected`.
  (`rtl_test -t` then aborts with "No E4000 tuner found" — that is expected and
  not an error.)
- `rtl_test`'s "No supported devices found" while the dongle is plugged in
  usually means another process still holds it — check for a stray `multi_rx.py`.
- On Linux the DVB kernel modules must be blacklisted (`blacklist-rtl.conf`,
  installed by `install.sh`). Not needed on macOS.
- Device selection is by serial: `"args": "rtl=00000001"`.

## Conventions

- Python is 3.10+ only; `websocket_server.py` uses `from __future__ import
  annotations` and PEP 604 unions.
- Do not add subdirectories to the legacy `www-static/` output — `http_server.py`
  strips `/` from request paths. (The new `dist/` server has no such limit.)
- Upstream PRs go to boatbod's `dev` branch; keep fork-specific changes
  reviewable and separate from upstream syncs.
