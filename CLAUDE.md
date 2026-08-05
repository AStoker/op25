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
- Protocol is `{ "type": ..., "payload": ... }`. Downstream: `SYSTEM_STATE`
  (health payload **and** every decoder json_type without a more specific home
  — trunk_update, channel_update, plot, terminal_config, full_config),
  `CALL_ACTIVITY` (call_log), `CALL_AUDIO` (clips + transcripts), `ERROR`.
  Upstream: `CALL_CONTROL` (any decoder UI command), `SYSTEM_CONTROL` (`quit`
  only — muting is client-side).
  There is no `SDR_STATUS`; it was declared but never emitted.
- Audio path: decoder UDP → `UdpAudioReceiver` → `AudioStreamManager` →
  browser. Ports are discovered from each channel's `destination`
  (`udp://host:port`, plus `port+1` for the TDMA slot B), defaulting to
  `127.0.0.1:23456/23457`. There is one manager per port plus an aggregate:
  bare `/api/stream` is the mix, `?channel=N` one channel, `?port=N` one exact
  stream (how to reach a DMR slot B), `/api/audio/channels` lists them.
- Docs: `README-new-gui.md` (protocol + endpoints), `www/app/AGENTS.md`
  (frontend conventions).

### Legacy stack (still present, being replaced)
```
op25/gr-op25_repeater/www/react-app-legacy/    older React GUI (source)
        └─ yarn build → www/www-static/ served by http_server.py
op25/gr-op25_repeater/apps/http_server.py        waitress WSGI
```
Config selector:
```json
"terminal": { "module": "terminal.py", "terminal_type": "http:0.0.0.0:8080" }
```
- Two ports: HTTP on N, control WebSocket on **N+1**, HTTP POST fallback on N.
- Documented in `README-websockets.md`, which is explicitly labelled legacy.
- This is the stack that uses `ws://` audio destinations (websocketpp sinks in
  `lib/op25_audio.cc`); the new stack ignores them and re-streams UDP instead.
- `terminal.py` also provides `terminal_type: "curses"` for a TUI.

`www/react-app-legacy/AGENTS.md` is the detailed (legacy) protocol reference and is
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

## Call capture, speech-to-text, Home Assistant

`apps/ha_bridge.py` (stdlib only — nothing new to install on a Pi) slices the
UDP audio into one clip per transmission and optionally pushes each one
through Home Assistant's speech-to-text API, matches keywords, and POSTs the
result to an HA webhook. Full reference: `README-home-assistant.md`.

- **Segmentation is the whole trick.** The decoder emits UDP audio only while
  a call is up, so a gap in packets is the voice-activity detector. Feeding a
  continuous stream to Whisper instead means transcribing mostly silence,
  which is where the hallucinated "Thank you for watching" output comes from.
- `CallRecorder.push()` is called from the UDP receiver thread and
  `CallRecorder.poll()` from the same `select()` loop (it wakes at least once
  a second, which is enough to close a call after its hang time).
- Clips are gated on `min_call_secs` and `min_peak`. The peak gate is what
  drops encrypted traffic, which decodes to near-silence — that is correct
  behaviour, not a bug to fix.
- **One `CallRecorder` per UDP port** (`CallCapture`). P25 only ever uses one
  port — `p25_frame_assembler_impl.h` holds a single `p25p2_tdma` and calls
  plain `send_audio()`. Slot B (`port + 1`) is DMR-only, via
  `rx_sync::output()` when `d_stereo` is set, and those two slots are
  *independent conversations*: one recorder for both would interleave two
  people into one clip.
- **Clips are loudness-normalised at finalize** (measured 24.4 dB → 6.1 dB RMS
  spread on live traffic). Gain targets speech RMS — `speech_rms()` averages
  only the louder half of frames, so pauses don't inflate the boost — then is
  clamped so peaks reach but never cross the ceiling, which means levelling
  cannot introduce clipping. `peak`/`rms` in clip metadata are **as received**,
  pre-normalisation, so they stay valid as an RF indicator.
- **`ChannelStatus.error` is `demod.get_freq_error()` in Hz** (multi_rx.py:551)
  — an AFC tuning figure, *not* a bit error rate. OP25 does not surface BER to
  Python (`rs_errs`/`gly_errs` exist in the C++ but only reach stderr at debug
  level). Don't build decode-quality gating on `error`.
- `voiced_ratio()` is the speech-likeness heuristic used instead; it is
  advisory and its gate (`min_voiced_ratio`) defaults to **off** so it cannot
  silently eat traffic.
- **Whisper hallucination filtering** is on by default. Unintelligible input
  yields confident boilerplate, not silence; rejected text is preserved in
  `discarded_transcript` (never keyword-matched) so over-filtering is visible.
- Metadata comes from the newest `channel_update` via
  `_note_channel_state()` / `_current_call_metadata()`. All channels share one
  audio capture, so with several channels active at once attribution is
  best-effort (first channel with a tgid wins). Single-channel is exact.
- `_merge_metadata()` never overwrites a field that is already set: a call can
  start before its tgid is known, but a *later* update may already describe
  the next call.
- HA's `/api/stt/<engine>` accepts only 16 kHz/16-bit/mono and passes the body
  to the provider as raw PCM chunks, so clips are upsampled and sent
  headerless (`stt_audio: "wav"` switches to a container if a provider needs
  one).
- **A mismatch in the `X-Speech-Content` header is an HTTP 415 that names
  nothing.** HA's `check_metadata()` compares all six declared fields against
  the provider's lists and returns a bare "Unsupported Media Type" on any
  miss. `HomeAssistantBridge.negotiate()` therefore `GET`s
  `/api/stt/<engine>` at thread start and reconciles language and sample rate;
  `_describe_mismatch()` does the same lookup on a 415 so the error says which
  field. The language tag is the usual offender — HA Cloud advertises `en-US`,
  Wyoming/Whisper advertises `en`, and the same config fails when moved
  between them.
- Endpoints: `/api/calls`, `/api/calls/{id}/audio.wav?rate=`, `/api/ha/status`
  (start troubleshooting here), and `/api/stream?rate=&format=`. The stream
  defaults are unchanged — 8 kHz WAV — so the React player is unaffected.
- **`transcript_pending` is stamped by `websocket_server._on_clip_complete`,
  not by `HomeAssistantBridge.submit()`.** The clip is broadcast to the UI
  before it is queued, and the worker thread can transcribe and re-broadcast
  it before that first message is even serialised — so the flag has to be set
  ahead of the broadcast, using `bridge.will_transcribe()` (the same predicate
  `submit()` applies, plus `stt_configured`). `_settle()` clears it on *every*
  terminal outcome including a clip shed from a full queue, so no row is left
  waiting forever. The field is omitted from `to_dict()` when false, which
  means the client cannot clear it by spreading the second message over the
  first — `op25Service` pins it explicitly.
- **Call History joins the call log to clips heuristically** (talkgroup +
  start time, `www/app/src/utils/callTranscripts.ts`). The two feeds share no
  id: `call_log` is written by the trunking layer at voice-grant time,
  `call_clip` by the UDP segmenter at end-of-transmission. Exact on a single
  channel, best-effort with several up. The `frequency_data` fallback path in
  that card has no usable timestamp (`last_activity` is preformatted text), so
  it never shows a transcript.
- **The config is served to the browser, so it must not hold secrets.**
  `/api/config` and the decoder's `get_full_config` both hand the loaded JSON
  to an unauthenticated client; `ha_bridge.redact_config()` masks
  `SECRET_KEYS` at both choke points (the REST handler and `_dispatch`). The
  token should come from `token_file` or `$OP25_HA_TOKEN` rather than the
  config in the first place — redaction is a backstop, not the mechanism.
- Clips live in a bounded in-memory ring (`ClipStore`, 60 clips / 24 MB).
  Nothing is written to disk *here* — but `media_upload` pushes each clip to
  HA's `/api/media_source/local_source/upload`, which inverts the transfer:
  HA never connects back, so `public_url` and this host's reachability stop
  mattering, and clips outlive the ring. The upload runs **before**
  `_post_webhook` so the payload can carry `media_path`; an automation cannot
  wait on an upload it did not start. That endpoint is `@require_admin`, so a
  merely-valid token gets a bare 401 — `_upload_media` adds that hint itself.
  Multipart is hand-rolled because this module stays stdlib-only.
- Tests: `tests/call_capture_spec.py` (116 tests), including HTTP round-trips
  against a stub HA. The stub uses `_FastHTTPServer` because
  `HTTPServer.server_bind()` calls `socket.getfqdn()`, which blocked for 35 s
  per run on this machine.

**The vocoder is the quality floor, not the sample rate.** Measured on live
clips: 0.1 % of energy above 3.4 kHz, 66 % in 300–1000 Hz. IMBE/AMBE+2 are
parametric — they resynthesize from pitch/voicing/envelope, so consonant cues
above 2 kHz are largely absent and upsampling recovers nothing. Don't propose
resampling, denoisers, or bandwidth extension as transcription fixes; the
levers that work are RF quality, a bigger Whisper model on a bigger host, and
`initial_prompt` vocabulary biasing. `README-home-assistant.md` §7 has the
numbers.

## Responsive UI

The React app is expected to work on a phone as well as a desktop.

- **Control sizing is a theme token, not a per-component prop.**
  `CONTROL_HEIGHT` (32px) in `themeService.tsx` is the height of every button,
  input, select and toggle, and `size="small"` is the default for all of them.
  Inputs carry no floating labels — `components/common/Field` puts the caption
  above the control instead, which is what lets the TGID box sit inline with
  Hold/Whitelist/Lockout. The shared primitives (`Field`, `InfoRow`,
  `ControlRow`, `SectionHeading`, `Hint`, `InsetPanel`, `SearchField`) are
  documented in `www/app/AGENTS.md`; reach for one before hand-rolling a flex
  row or an outlined `Box`.
- Below `md` the layout switches to tabs (Live / Audio / System / Signal) in
  `App.tsx`; at `md` and above it keeps the two-column dashboard. A phone
  cannot usefully show ten cards at once.
- `useIsPhone()` (`hooks/useIsPhone.ts`) is how the data tables drop
  lower-value columns below `sm` rather than letting the important ones
  squeeze into slivers. The Virtuoso tables use `tableLayout: fixed`, so the
  percentage widths in `fixedHeaderContent` must be kept in step with the
  cells actually rendered by `rowContent`.
- Theme follows `prefers-color-scheme` until the user toggles it, then
  persists in `localStorage`. `<meta name="theme-color">` is updated at
  runtime — dark mode uses `background.default`, not `primary.main`, because
  MUI does not render a dark AppBar in the primary colour.
- CSS grids that would otherwise force a sideways scroll use
  `minmax(min(Npx, 100%), 1fr)`.
- Verify with the CDP script pattern (see "Testing the running stack" below)
  and check `document.documentElement.scrollWidth > clientWidth` at 390 /
  820 / 1440 px — horizontal overflow is the failure that matters.

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
   — rebuild before testing UI changes. (`install.sh` / `install-mac.sh` now run
   `yarn build` when yarn is present.)
2. `call_log` is a **draining delta feed**: `tk_p25.get_call_log()` clears the
   buffer on every read, and `ws_terminal` polls once per second whether or not
   a client is attached. Clients must accumulate (the frontend does). The server
   keeps a 200-entry ring and replays it on connect, so a late-joining client is
   no longer blank — but calls from before the server started are still gone.
3. **SmartNet and Connect+/DMR parity is unverified on air.** The payloads and
   the Connect+ hold/skip/lockout/whitelist gating are covered by
   `tests/trunk_json_spec.py` against synthesized state only; there is no such
   system in range here. Two real bugs were fixed blind in `tk_trbo.py` (slot
   state aliasing, and `current_chan` never advancing during a CC hunt) — treat
   both as needing an on-air confirmation.
4. `set_full_config` still does nothing. It now returns an explicit error rather
   than a false `ok`, and the UI can display the config read-only. Writing the
   user's JSON from an unauthenticated browser is a deliberate non-goal.
5. Nothing here has been verified on the **Raspberry Pi 5**. The Linux audio
   path in particular is unchanged in its ALSA/PulseAudio ordering but has only
   been exercised through the fallback chain on macOS.
6. `add_default_config` (curses `t` key) is rx.py-only; under multi_rx it
   answers with an explicit "not supported" error, since systems come from the
   JSON config.

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

Python tests: `pytest` from `apps/` (specs are `tests/*_spec.py`), 213 tests,
in-process via FastAPI's `TestClient` — no network or dongle needed. Requires
`httpx`.

- `tests/websocket_server_spec.py` — static file serving, SPA fallback, path
  traversal, method handling, CORS (21).
- `tests/call_capture_spec.py` — PCM helpers, call segmentation, normalisation,
  speech heuristics, hallucination filtering, clip store, keyword matching, HA
  config, HA HTTP round-trips, REST endpoints, per-port capture (116).
- `tests/protocol_spec.py` — json_type routing, live SYSTEM_STATE, call-log
  ring, capture listing/download, upstream type validation (26).
- `tests/trunk_json_spec.py` — trunk_update payload shapes for P25 / SmartNet /
  Connect+, plus Connect+ grant handling and call filtering (28).
- `tests/audio_streams_spec.py` — endpoint discovery, per-port fan-out,
  `?channel=` / `?port=` selection (20).
- `tests/squelch_upstream_spec.py` — runs upstream's `squelch_core_test.py` and
  `squelch_gr_test.py`, which are standalone `main()` scripts rather than
  pytest modules, as subprocesses (2).

Note that `TestClient.stream()` hangs on `/api/stream` — it is an unbounded
generator. Drive `AudioStreamManager.generate()` directly under `asyncio`
instead (see `tests/audio_streams_spec.py`).

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
