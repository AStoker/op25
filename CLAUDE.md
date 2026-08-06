# CLAUDE.md — op25 modernization

Fork of boatbod/op25 (P25/DMR/SmartNet trunking SDR decoder). Working branch:
`feature/HA-app`. The React SPA + FastAPI/uvicorn rewrite is merged to `master`;
the goal of *this* branch is to package OP25 as a **Home Assistant OS add-on**
(Docker image, s6, ingress) while keeping the standalone install working on
**macOS (Apple Silicon)** and **Debian / Raspberry Pi 5 (GNURadio 3.10)**.

## Target platforms

| Platform | Install script | Python | Notes |
|---|---|---|---|
| macOS (Apple Silicon) | `./install-mac.sh` | venv at `op25/gr-op25_repeater/apps/.venv` seeded from Homebrew gnuradio's private venv | dev machine; no SDR attached any more |
| Home Assistant OS 18.2 (Intel N100, amd64) | the add-on, `addons/op25/` | `/usr/bin/python3` in the image | **where the dongle lives**; primary deployment target |
| Debian / Raspberry Pi 5 | `./install.sh` | system `/usr/bin/python3` | standalone install; must stay working |

`op25/gr-op25_repeater/apps/op25_python` is a one-line text file holding the
absolute path of the interpreter to use. It is gitignored and written by the
install script. **Always invoke apps with that interpreter**, e.g.

```bash
cd op25/gr-op25_repeater/apps
$(cat op25_python) multi_rx.py -c Palmetto800-single.json -v 1
```

## The UI stack

There is one web UI, selected by the `terminal` block of the JSON config. The
legacy stack was removed on this branch — see "What was removed" below.

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

`terminal.py` survives, but only for `terminal_type: "curses"` (a TUI) and a
bare UDP port number (headless, attach `./terminal.py <host> <port>` later —
that attach mode *is* the remote curses view). A config naming `http:` prints a
migration message and runs headless rather than tracebacking.

### What was removed (and why a grep will mislead you)

Deleted deliberately on this branch. Do not resurrect these when resolving an
upstream merge:

| Removed | Was |
|---|---|
| `apps/http_server.py`, `www/react-app-legacy/`, `www/www-static/`, `www/images/` | the two-port waitress GUI |
| `apps/rx.py`, `trunking.py`, `p25_decoder.py`, `audio.py`, `p25_demodulator.py`, `cfgtrunk.py` | the pre-`multi_rx` receiver and its trunking module |
| the `ws://` branch of `lib/op25_audio.cc` + `include/websocketpp/` + `include/asio*` | C++ websocketpp audio sinks (753 files, 7.5 MB) |
| the gnuplot subprocess in `gr_gnuplot.py` | PNG/x11 plot rendering |
| liquidsoap/Icecast-era scripts, `op25_stats.sh` | streaming helpers |

**Two survivors look dead to a grep and are not.** Both are loaded by *name*
from the JSON config via `importlib`, so nothing imports them statically:

- `sockaudio.py` — `"audio": {"module": "sockaudio.py"}`, local speaker output.
- `icemeta.py` — `"metadata": {"module": "icemeta.py"}`, Icecast metadata. Its
  only static importer was `rx.py`, so it went from one importer to zero while
  staying live.

Each carries a comment at the top saying so.

## Verified working (end-to-end smoke test, 2026-07-30, macOS + RTL-SDR V4)

Live against the real Palmetto 800 system with `Palmetto800-single.json`:
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

`sockaudio.py` is the single choke point for local speaker output; `multi_rx.py`
loads it as `audio.module` and goes through `socket_audio`. It has three backends
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
entry — but **only when `audio.module` is actually set**. `configure_audio()`
returns early on an empty module, so the instances list is inert and those
ports belong to the browser; excluding them anyway silenced any config with a
leftover audio block, which is exactly how the add-on runs by default.
To run both, give the channel a second destination and let discovery find
it (`destination` is comma-separated — `op25_audio.cc:143` tokenizes on `,`):

```json
"destination": "udp://127.0.0.1:23456, udp://127.0.0.1:23458"
```

`terminal.audio_ports` is an explicit override that wins outright.
`apps/Palmetto800-single.json` is a working example of this dual-audio setup,
and the tracked `p25_rtl_example.json` / `smartnet_example.json` now use it too.

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
- **`/media/<source>/<dir>` is not linkable.** `LocalMediaView` inherits
  `requires_auth = True`, so a notification tap 401s and a dashboard link is
  swallowed by the frontend router (no panel named `media`). `<config>/www` is
  registered as a *static* path at `/local` and bypasses auth entirely, so the
  fix is to upload there and set `media_url_base` — the upload target and the
  public URL stop agreeing at that point, which is the only reason that key
  exists. It buys linkability at the cost of the clips being unauthenticated.
- The media filename is the only metadata that travels with the audio (HA's
  library is bare files, no sidecar, no DB), hence
  `<date>_<time>_<tgid>_<slug>_<id>.wav` from `_media_filename()`. Underscores
  are stripped from the slug so `split('_')` always yields exactly five
  fields — one oddly-named talkgroup would otherwise break every consumer's
  parsing — and the leading timestamp makes a plain directory listing sort
  chronologically.
- Tests: `tests/call_capture_spec.py` (170 tests), including HTTP round-trips
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

## Talkgroup metadata and scan lists

- **`frequency_data` cannot tell you when a talkgroup was last heard.** It lists
  a tgid against a frequency only while the call is up — `TGID_EXPIRY_TIME` is
  **1.0 s** (tk_p25.py:1957-1964) — and `last_activity` is a per-*frequency*
  preformatted string. The GUI's Last column read that, so it could only ever
  show `"  Now"` or blank, and the Freq column had the same single root cause.
  Sorting was string-comparing `"  Now"` against `" 4.1s"`.
- The per-talkgroup numbers now travel in `tgid_tags`: `last_seen` (raw epoch,
  0 = never), `last_freq`, `count`. Same shape from `tk_p25` / `tk_smartnet` /
  `tk_trbo`. Formatting stays client-side (`www/app/src/utils/lastSeen.ts`) —
  the browser knows the viewer's clock, and a number sorts.
- **`last_freq` is a separate sticky key, not a reuse of `frequency`.**
  `expire_talkgroup` clears `['frequency']` to `None` to mean "no call up"
  (tk_p25.py:2667) and the trunking logic depends on that.
- **`encrypted` is P25-only in this payload.** SmartNet carries encryption in a
  tgid bit (`tgid & 0x8`) and never stores it per talkgroup;
  `talkgroups[tgid]['mode']` there is analog-vs-digital (tk_smartnet.py:2186), so
  reporting it as `encrypted` would flag every digital talkgroup on the system.
- **`apps/tg_metadata.py` is the fork's storage layer, deliberately not in the
  `tk_*` modules** — those are the files where an upstream cherry-pick is still
  realistic, so they only publish numbers they already had. The in-memory dict is
  the source of truth; SQLite is write-behind, flushed in one transaction every
  `FLUSH_INTERVAL` (30 s) and at shutdown. That database may be on an SD card on
  HA OS, so the batching is the point, not an optimisation.
  - `_note_trunk_update()` observes *and* merges: durable values are folded back
    into the outgoing payload, so the browser never learns persistence exists.
  - `last_seen` never regresses, and a reported `0` never erases a real stamp —
    two receivers report independently and a fresh decoder reports 0 for
    everything. `count` accumulates by **delta**, because the decoder's counter is
    per-process; a counter that drops is treated as a restart and rebased.
  - Path: `$OP25_METADATA_DB`, then `terminal.metadata_db`, then
    `op25_metadata.sqlite` in the cwd. Either may be empty to disable.
  - A bad path or corrupt file logs once and degrades to memory-only. This must
    never be able to fail the decoder.
  - `stats()` has no `talkgroups` key on purpose: `/api/talkgroups` spreads it
    beside its `talkgroups` list, and a same-named counter silently replaced the
    list with an integer. The tests caught that.
- **`set_whitelist` / `set_blacklist` replace a list in one command.** Not a loop
  over single `whitelist` commands: `add_whitelist()` expires the current call
  whenever the tgid it is on falls outside the new list, so 50 entries applied one
  at a time tear the receiver down repeatedly. Validation is all-or-nothing.
  - These are the first commands whose argument does not fit a `gr.message`'s two
    floats. `handle_call_control` sends the whole payload as JSON when it carries
    any field beyond `command`/`arg1`/`arg2`; `multi_rx.process_qmsg` has always
    tried `json.loads()` before the bare-string form, so nothing regressed.
  - Applied to **every receiver of the system**, each with its own copy of the
    dict. With a whitelist file configured `load_bl_wl()` hands every receiver the
    *same* object (tk_p25.py:2276) while `add_whitelist()` un-shares it by
    assigning a fresh `{}` — the copy makes that aliasing irrelevant instead of
    load-bearing. Same bug class as the `tk_trbo` slot aliasing.
  - An empty whitelist becomes `None`, which means "scan everything". An empty
    *dict* would mean scan nothing, so the two are never interchangeable —
    including in `channel_update.whitelist`, which is `null` for unrestricted.
  - Timed blacklist entries survive a replacement: those are `TGID_SKIP_TIME`
    skips in flight, and `get_scan_lists()` omits them so the UI does not flicker.
- **Focus/pin and the scan list are separate, and the second is never implicit.**
  Pinning is `localStorage` (`hooks/useTalkgroupFocus.ts`) and only sorts/filters
  the table; the scan list stops other talkgroups being received at all, so it
  takes an explicit button in the Talkgroup Browser. Narrowing what you look at
  must not silently narrow what gets recorded and transcribed.
- `components/TalkgroupBrowser` **freezes its list while open** (`systems` is
  deliberately not a loader dependency). Chasing a row that re-sorts under you as
  traffic arrives is the problem it exists to solve.
- An invalid live regex shows *everything* and says why, rather than emptying the
  table — most keystrokes in a pattern are a syntax error in progress.

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
- **The header's `Config` and `About` are modals, not routes** (`ConfigDialog`,
  `AboutDialog`, both on `common/DialogShell`, full-screen below `sm`). Config
  holds the one decoder knob that is live at runtime — log level, i.e. `-v`,
  which `set_debug` applies to *every* channel and device, so it is not in the
  per-channel Tuning card — plus the browser's display preferences and the
  read-only loaded JSON (moved out of the dashboard, where nobody scans it).
  The AppBar gear menu is gone; its smart-colours switch is in Config →
  Interface, next to the accent-colour picker that `themeService` has always
  exposed and no UI ever reached.
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

The UI renders plots client-side from raw data. **gnuplot is not involved at
all** — the subprocess, the PNG writer and the x11 path were deleted with the
legacy stack, so `gr_gnuplot.py` is now a misnomer (kept, because renaming it
would churn six imports in `multi_rx.py` for no gain).
`wrap_gp.send_plot()` emits `json_type: "plot"` with
`{chan, mode, data: [[x,y],...], xrange, yrange, title}`, matching
`PlotPayload` in `www/app/src/types/op25.ts`. All six modes work: `fft`,
`constellation`, `symbol`, `eye`, `mixer`, `fll`.

Things to know:

- **Plots require the `ws` terminal.** `toggle_plot()` is a no-op elsewhere and
  says so on stderr. Nothing renders the traces under curses, so building them
  would be pure CPU burn.
- **The plot sinks only exist while a plot is on.** `toggle_plot` connects and
  disconnects them under `tb.lock()` (multi_rx.py:415-430), so with every plot
  off the cost is exactly zero. Any claim that plot work happens unconditionally
  at full stream rate is wrong on both counts.
- **The throttle sits after the FFT on purpose, and that is not the bug it looks
  like.** The exponential average has to be fed to stay converged. What *was*
  wrong is the rate: `FFT_FREQ` (20 Hz) and `MIX_FREQ` (50 Hz) suit a
  continuously-redrawing gnuplot window, not a browser fed at
  `http_plot_interval` (1 Hz). So `compute_interval()` reduces the transform rate
  to `AVGS_PER_PLOT` (8) per frame and `_averaging_alpha()` rescales the
  coefficient — `alpha' = 1 - (1-alpha)**(actual/nominal)` — which keeps the
  settling time identical. Verified exact in `tests/plot_rate_spec.py`. Do not
  "simplify" by moving the throttle above the FFT without that compensation:
  20 Hz → 1 Hz would stretch `FFT_AVG`'s ~1 s time constant to ~20 s.
  `compute_interval()` never goes *faster* than nominal, so a short
  `http_plot_interval` cannot make the DSP work harder than it used to.
- `eye` / `constellation` / `symbol` hold no state between frames, so `due()`
  gates them *before* any work. The historical `plot_count % 20` eye decimation
  therefore applies only when unthrottled — leaving it in both places meant 20
  plot intervals per eye frame, one every 20 seconds at the default.
- The averaging is vectorised (18x); measured 0.37 ms → 0.020 ms per call. A
  `sum_pwr` running total accumulated over every bin for mixer/fll and never read
  is gone, and the Blackman window is cached. Net at 1 Hz: ~35x less CPU on
  `fft`, ~120x on `mixer`/`fll`.
- **An enabled plot used to outlive the tab that enabled it.** The decoder owns
  plot state so it survives a reload, and `multi_rx`'s `watchdog` only closes
  plots when `update` goes quiet — which never happens, because `ws_terminal`
  polls at 1 Hz whether or not a client is attached (deliberately, to keep the
  call-log ring filling). `ws_terminal._reap_idle_plots()` now sends the new
  `close_plots` command after `PLOT_IDLE_GRACE` (5 s) at zero clients; the grace
  period is what stops a page reload costing the user their plots.
- `send_plot()` puts a bare **dict** on `ui_in_q`, while `multi_rx` puts a
  **list** — same message type `-4`. `curses_terminal.process_q_events()`
  normalises both. It did not use to, and iterating the dict yielded key
  strings, which `process_json()` then subscripted: a `TypeError` that the bare
  `except` in `run()` converted into a `quit`. Pressing 1–6 under curses killed
  the receiver. Keep that normalisation.
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

## Home Assistant add-on

`addons/op25/` plus a root `repository.yaml` make this repo an add-on store.
The image is built by CI and published to `ghcr.io/astoker/op25`; `config.yaml`
names it with `image:`, so Supervisor *pulls* rather than compiling GNU Radio on
the user's box.

- **Debian trixie base**, not bookworm. Trixie's librtlsdr is 2.0.2, which
  already supports the RTL-SDR Blog V4 — that deletes the whole
  `update-rtlsdr.sh` dpkg-build workstream. It also packages `python3-fastapi`
  and `python3-uvicorn`, so no pip and no PEP 668. GNU Radio there is 3.10.12.
- **The DVB driver question is platform-specific — check before assuming.**
  On **generic x86-64** (HA OS 18.2, kernel 6.18.39) `CONFIG_DVB_USB_RTL28XXU`
  is absent: it appears in exactly one fragment, `kernel-arm64-rockchip.config`,
  and the x86-64 board config has no DVB entries at all. So on an amd64 NUC
  nothing can claim the dongle and no blacklist is needed.
  On an **arm64 Rockchip** HA OS board the module *is* built (`=m`), so
  `dvb_usb_rtl28xxu` can bind the device first. That cannot be fixed from
  inside the add-on — HA OS ignores `/etc/modprobe.d` — so it is a host-side
  problem to document if anyone hits it. `blacklist-rtl.conf` remains for the
  standalone Debian path.
- **Ingress strips the prefix before proxying**, so the Python side needs no
  path awareness: it still sees `/api/config` and `/ws`. Only the browser
  needed fixing — `vite base: './'` plus `www/app/src/utils/url.ts`, which
  resolves every fetch/WS URL against `document.baseURI`. Some of those strings
  are *server*-generated and root-absolute (`/api/stream?port=N` from
  `/api/audio/channels`, `audio_url` on a clip), which is why `apiUrl()` strips
  a leading slash rather than assuming a relative input.
- **Never point a Home Assistant media player at an ingress URL.** Those carry
  a rotating per-session token only an authenticated browser holds. That is
  what the published port 8099 is for.
- **Port 8099 is unauthenticated.** `allow_origins=["*"]`, no token: anyone on
  the LAN can hold a talkgroup, apply a scan list, quit the decoder or listen.
  Ingress is the authenticated path. That is also what `OP25_BACKEND` points a
  local `yarn dev` at, so treat it as a trusted-LAN convenience. A tunnel is not
  an alternative — unpublishing the port hides it from the HA host too, so there
  would be nothing to forward to; the real fix would be auth on the server.
- **The run script renders the config, it does not edit the user's file.**
  `rootfs/.../op25/run` merges add-on options over the user's JSON with `jq` and
  pipes the result to `multi_rx.py -c -`. That forces
  `terminal.module`/`terminal_type`, keeps the HA token out of the JSON that
  `/api/config` serves (it goes via `$OP25_HA_TOKEN`), and leaves their file
  untouched. **The Home Assistant injection is confined to one commented block
  there** so the pending transcription/alerts schema split is a one-place edit.
- **`usb: true` + `udev: true` is sufficient.** `usb: true` bind-mounts
  `/dev/bus/usb` *and* adds the USB device-cgroup rules, which is all libusb
  needs; RTL-SDR has no `/dev` node, so no `devices:` entry, and `full_access`
  would actually void `usb`/`udev`.
- **s6 `finish` halts the supervision tree** rather than letting s6 restart in
  place, so a flowgraph that cannot start surfaces to Supervisor instead of
  silently looping. `down-signal` is SIGINT because `multi_rx`'s non-interactive
  path blocks in `tb.wait()` (C++, no bytecode) where a Python SIGTERM handler
  cannot run; `timeout-kill` backstops it.
- **CPU budget.** The target is an Intel N100: four Alder Lake-N E-cores, ~6 W,
  sharing the box with Home Assistant. Single-channel P25 is comfortable;
  multi-channel plus a local Whisper model is not, so point transcription at
  HA Cloud or an off-box Wyoming instance. `USE_SIMD` stays at its CMake
  default (SSE2 on x86_64) — never set `AVX`, which is `-march=native` and
  would bake the CI runner's ISA into an image that has to run on the N100.
- Two non-obvious build inputs, both found by dry-running the builder stage's
  COPY list through cmake: `op25/gr-op25_repeater/cmake/Modules` (installed by
  its `CMakeLists.txt`) and `docs/doxygen/pydoc_macros.h`, which GNU Radio's
  `GrPybind.cmake` `configure_file()`s for every pybind target. `.dockerignore`
  excludes `docs/` but re-includes that one header.

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
6. `add_default_config` (curses `t` key) answers with an explicit "not
   supported" error — systems come from the JSON config. It was only ever
   implemented in `rx.py`, which is gone.
7. **On-air decode is unverified since the `ws://` C++ removal**, because the
   dongle now lives on the Home Assistant NUC. The *audio transport* is
   covered: `tests/audio_udp_roundtrip_spec.py` drives the real compiled
   `analog_udp` block and asserts non-silent PCM comes out of `/api/stream`.
   What is still untested here is RF → demod → vocoder, which needs hardware.

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

# Frontend against the decoder on the Home Assistant box (which has the dongle).
# Vite proxies /api and /ws, so the browser only ever talks to localhost:5173 --
# no CORS, no dev-only code path on the Python side.
OP25_BACKEND=http://homeassistant.local:8099 yarn dev

# Run
cd op25/gr-op25_repeater/apps
$(cat op25_python) multi_rx.py -c Palmetto800-single.json -v 1 2> stderr.2
# then open http://localhost:8080
```

Python tests: `pytest` from `apps/` (specs are `tests/*_spec.py`), 366 tests,
mostly in-process via FastAPI's `TestClient` — no network or dongle needed.
Requires `httpx`.

Without GNU Radio installed the `trunk_json_spec` (via `tk_trbo`/`tk_smartnet`),
`plot_rate_spec` (via `gr_gnuplot`) and `audio_udp_roundtrip_spec` cases
`importorskip` out. Everything else is GR-free because `websocket_server` guards
its `from gnuradio import gr`.

- `tests/websocket_server_spec.py` — static file serving, SPA fallback, path
  traversal, method handling, CORS (21).
- `tests/call_capture_spec.py` — PCM helpers, call segmentation, normalisation,
  speech heuristics, hallucination filtering, clip store, keyword matching, HA
  config, HA HTTP round-trips, media upload, REST endpoints, per-port
  capture (170).
- `tests/protocol_spec.py` — json_type routing, live SYSTEM_STATE, call-log
  ring, capture listing/download, idle-plot reaping, upstream type
  validation (32).
- `tests/trunk_json_spec.py` — trunk_update payload shapes for P25 / SmartNet /
  Connect+, talkgroup activity fields, batch scan lists (including the
  per-receiver dict copy), plus Connect+ grant handling and call filtering (51).
- `tests/tg_metadata_spec.py` — durable talkgroup store: db path resolution,
  merge rules (last_seen never regresses, count by delta), sqlite round-trip and
  batching, degradation to memory-only, trunk_update wiring,
  `/api/talkgroups` (36).
- `tests/plot_rate_spec.py` — plot payload shape for all six modes, compute-rate
  reduction, exponential-average compensation, stateless-mode skipping,
  decimation, dead-source guard (20).
- `tests/audio_streams_spec.py` — endpoint discovery, per-port fan-out,
  `?channel=` / `?port=` selection (31).
- `tests/audio_udp_roundtrip_spec.py` — drives the compiled `analog_udp` block
  and asserts non-silent PCM out of `/api/stream` (3).
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

`op25_metadata.sqlite` is written into the cwd (the work dir) by `tg_metadata.py`
on first run. It is a cache of talkgroup last-heard history, safe to delete, and
gitignored.

- `Palmetto800-single.json` — one RTL-SDR, Palmetto 800 (SC) P25 trunked
  system. This is the primary smoke test. (Tracked, unusually — `apps/.gitignore`
  re-includes `Palmetto800*`.)
- `Palmetto800-multi.json` — three-dongle version.
- `palmetto_tgs.tsv` — talkgroup tags. **Not tracked**, so a clean checkout
  cannot load it.
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
- **This is a hard fork, no longer tracking upstream.** It began as
  [boatbod/op25](https://github.com/boatbod/op25) and diverged at merge-base
  `b2e04c3f`; the `upstream` git remote has been removed deliberately, so
  `git merge upstream/...` is not part of the workflow any more.

  The divergence is not incidental — `rx.py`, `trunking.py`, `p25_decoder.py`,
  `http_server.py`, the whole legacy web UI and the `ws://` C++ audio transport
  are deleted (see "What was removed"), the config schema has changed, and the
  frontend is a different application. A merge would conflict in most of that
  and resolving it would mean resurrecting code this fork exists to be rid of.

  If a specific upstream fix is worth having, cherry-pick it deliberately.
  The files where that is still realistic are the decoder internals:
  `lib/` (except `op25_audio.*`), `apps/multi_rx.py`, `apps/tk_*.py`,
  `apps/p25_demodulator_dev.py`, `apps/sockaudio.py`, `apps/helper_funcs.py`,
  `apps/squelch*` and `include/gnuradio/`. Everything else is fork-only.

    git fetch https://github.com/boatbod/op25.git dev
    git cherry-pick <sha>
