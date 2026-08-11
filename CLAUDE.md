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
- **`AudioStreamManager.generate()` primes a jitter buffer, for exactly the
  reason `portaudio_sound` does** (`_STREAM_PRIME_MS`, 120 ms, env
  `OP25_STREAM_PRIME_MS`). The decoder emits one 20 ms frame every 20 ms and the
  generator consumes one every 20 ms, so the steady-state cushion is zero and
  any late packet found an empty buffer — the old code spliced a 20 ms silence
  hole into the middle of a word and never got a chance to build a cushion, so a
  few percent of scheduling jitter was heard as continuous chopping,
  indistinguishable by ear from a bad RF decode. Running dry now *re-primes*
  rather than emitting a hole per late packet: one longer gap, then smooth.
  Fixing the *drift* (the absolute `next_send` deadline) was a separate,
  earlier bug — don't mistake one for the other.
- **Every listener gets its own queues (`_StreamSink`). A shared queue was silent
  corruption, not an inefficiency.** `_take_chunk` *deletes* what it returns, so
  two consumers on one manager received strictly **alternating** chunks — each
  hearing half the samples of every word. Measured: A got `[35,37,39]`, B got
  `[36,38,40]`, zero overlap. It sounds like heavy chopping with a comb-filter
  echo a few ms off, it is completely independent of RF quality, and nothing in
  the logs named it.
  - **`PlayerCard` opened two streams on every first Play**, so the ordinary
    single-user case hit this every time. `handlePlay` called `start()`, which
    synchronously set status `loading`; that flipped `playing` true, which is a
    dependency of the source-switch effect, whose `playedUrlRef` guard was still
    `null` — so it fired a *second* `start()` for the same URL. Measured over CDP
    against the real built bundle: one click → `opens +2, live: 2`. The fix is
    `handlePlay` claiming `playedUrlRef` before starting.
  - Two tabs, a phone beside a desktop, or an HA media player on the UI's port
    all did it too — and still would, which is why the fan-out is the real fix
    and the PlayerCard change alone would only have hidden it.
  - `useAudioStream` now supersedes sessions with a **monotonic token**, not a
    boolean. A boolean cannot express "this invocation was superseded": an older
    `start()` parked on `await fetch()` woke to find the flag set back to true by
    the newer call and carried on, leaving two reader loops and leaking an HTTP
    body that held a listener slot open server-side.
  - `_detach` hands the departing listener's newest audio back as the idle window
    (bounded to `_IDLE_KEEP_MS`) rather than discarding it — that is exactly what
    the window would have held had nobody been listening.
  - The `ws audio:` line prints `listeners=`. Its absence is what made this cost
    so much time: the only trace was `yielded` growing at N× `pushed`, which reads
    as a puzzle rather than as "two things are listening".
  - `drop_stale()` is gone. It had no callers — the idle-window bound replaced it.
- **Audio buffered while nobody is listening is history, not buffering.**
  `push_audio` bounds each source to `_IDLE_KEEP_MS` (120 ms) when
  `_consumers == 0` and to `_MAX_BUFFERED_BYTES` (4 s) when a `generate()` is
  attached. Without that an idle server filled to 4 s and a client attaching
  inherited that lag *for as long as it listened* — drained at real time,
  refilled at real time. Seen live as `buf=64000 pushed=181440 yielded=0
  dropped=117440`.
  - **The discriminator is who is attached, not how deep the buffer is.** A
    first attempt trimmed any backlog past a lag threshold, which broke
    `audio_udp_roundtrip_spec`: its producer is not real-time, bursts 2 s of
    tone, and got it discarded as "stale". A producer ahead of real time is
    normal — UDP coalescing does it too — and that audio is the start of a
    transmission. Trimming it clips the first word.
- **`ffplay http://host:8099/api/stream` is the first thing to try when live audio
  sounds bad.** It splits the problem in half in thirty seconds: clean in ffplay
  and choppy in the browser means the fault is in the browser player, and no
  amount of decoder work will touch it. That test is what finally located the
  two-listeners bug above, after a release aimed at the decoder changed nothing.
- **A clip and the live stream are NOT comparable, and the difference is not a
  bug.** `CallRecorder.push` *concatenates* — nothing fills gaps — so a call that
  lost half its LDUs yields a clip half as long that sounds continuous. The live
  stream is paced at real time, so the same loss is rendered as silence and heard
  as chop. An earlier note here recommending that comparison as a way to isolate
  jitter from RF was wrong.
  - **But "the recording is clean and the live audio is choppy" does NOT imply
    lost frames**, which is what this said before and it sent the investigation
    into the decoder for a whole release. The recording is written from the UDP
    stream *before* the browser path exists, so anything wrong downstream of
    `push_audio` shows up in exactly the same way. Check `continuity` (≈1.0 means
    nothing was lost at the decoder) and ffplay before touching the decoder.
  - Measured against the real `AudioStreamManager` with a P25-shaped producer
    (9 packets per LDU burst, 180 ms apart, with LDUs dropped): `LOST BY
    PLAYER = 0` in every case. The stream plays every byte the decoder produced.
  - `clip.metadata['continuity']` is the number that makes this visible: audio
    duration ÷ wall-clock span, clamped to 1.0. 0.6 means 40 % of the
    transmission never decoded. Unlike `symbol_quality` it is a post-FEC figure —
    it counts frames that actually arrived.
  - **This is still true after the concealment work below, and deliberately so.**
    `conceal_lost_frames` emits at most three repeated 20 ms frames per gap and
    then stops rather than padding the rest with silence — padding would make a
    long dropout indistinguishable from clean audio in the clip's duration, which
    is the only thing `continuity` has to measure. So a lossy call still yields a
    short clip; it just no longer starts each hole with a hard cut.
- **`underruns` means "lost audio that was in flight"; idle silence is
  `silent_chunks`.** They used to be the same counter, which made it useless as
  a diagnostic because idle time dominated it. The 5 s `ws audio:` log line
  prints `voice`/`silent`/`underruns`: underruns climbing while `voice` is
  steady is jitter in this process, not RF.
- **Re-priming after a dropout is right for transport jitter and wrong for lost
  voice frames, and the discriminator is `producer_idle_ms()`.** Every underrun
  used to set `primed = False`, which charges a further `_STREAM_PRIME_MS`
  (120 ms) of silence on top of the gap. If packets are still arriving, an empty
  buffer means we outran them and the cushion *is* worth rebuilding — that is
  what the prime exists for. If the decoder has gone quiet the silence is lost
  LDUs, for as long as the RF is bad, and no cushion can help: a 180 ms loss was
  being rendered as a 300 ms hole, every time.
  - **The verdict has to be latched as a running maximum (`dry_idle`), because
    the packet that ends the gap destroys the evidence.** Read fresh each tick,
    the producer looks alive again the instant it resumes, so the gap re-primes
    anyway. A two-threshold latch (`_JITTER_IDLE_MS` down, `_DROPOUT_END_MS` up)
    was tried first and *oscillated* between the two verdicts on alternate ticks.
  - Past `_DROPOUT_END_MS` (750 ms) it is not a mid-call dropout any more, it is
    the end of the transmission, and the next one gets a full prime. Without that
    the no-reprime verdict sticks and every subsequent call chops on its first
    word. The value matches the decoder's own `CONCEAL_MAX_GAP_SYMBOLS`.
  - `dry_idle` starts at infinity, so a newly attached client always primes
    properly whatever the producer was doing before it arrived.
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

## Lost voice frames: recovery and concealment (P25 phase 1)

The audible chop on live P25 audio was mostly not a streaming fault. Two loss
mechanisms exist and only one of them was ever handled.

**Per-codeword damage was already correct and standards-compliant.**
`software_imbe_decoder::decode_fullrate` implements TIA-102.BABA-A §7.7 Frame
Repeat and §7.8 Frame Muting: `repeat_last()` reloads the previous frame's
`w0`/`L`/voicing/spectral amplitudes, `rpt_ctr` allows three repeats and mutes on
the fourth, and `ER` (a leaky estimate built from Golay/Hamming corrections) mutes
outright above 0.0875. A muted frame still pushes 160 zero samples, so the 20 ms
timeline survives. Do not "simplify" any of that.

**Whole-LDU loss was not handled at all, and that was the chop.** A failed NID
BCH check discarded the entire frame — nine independently-FEC-protected IMBE
codewords, 180 ms of audio — because 64 bits of *addressing* failed. The NID
carries NAC and DUID and not one bit of voice. Worse, `rx_sync` then called
`sync_reset()`, so `d_threshold` dropped to 0 and the receiver had to re-acquire
an exact 48-bit sync match on a signal that had just proved marginal — which is
how one bad frame cascaded into several.

- **A subscriber unit does not do that.** Once it has acquired the channel it
  knows the strict `HDU → LDU1 → LDU2 → LDU1 → …` alternation and the 20 ms frame
  clock, and keeps decoding voice straight through a bad NID. `p25_framer` now
  does the same: `set_voice_hint(duid)` supplies the predicted DUID and
  `load_nid()` falls back to it instead of returning 0.
- **The gate is the frame sync, not optimism.** Recovery requires a voice hint
  *and* `sync_bit_errors(fs) <= RECOVERY_MAX_SYNC_ERRS` (4 of 48). The sync
  detector itself locks at ≤ 2; 4 is still far beyond what noise produces, and it
  is the only remaining evidence that a frame really starts here once the NID's
  own BCH has given up. Getting this wrong injects noise into the audio, so it is
  deliberately strict.
- **A recovered frame is voice-only.** `nid_recovered` means nac / nid_word /
  parity / bch_errors are stale, so `process_frame` decodes codewords and nothing
  else: no `process_duid` message to the trunking layer (that would assert a frame
  type that was *inferred*), no LCW, no ESS. It does reset `qtimer` — a frame
  genuinely arrived — and does `cycle_p25_mi()` on a recovered LDU2, the same
  fallback `process_LDU2` already uses when the ESS fails to decode, so a keyed
  encrypted call stays in step.
- Guessing LDU1 vs LDU2 wrong is harmless for clear traffic: `imbe_deinterleave`
  uses the same bit map for both. It only shifts the keystream offset for
  encrypted-and-keyed calls, which any lost frame already breaks.
- The hint is cleared by every non-voice DUID, by `call_end()`, and by the 1 s
  `check_timeout()`, so a stale hint cannot outlive its call for long.

**Frames that never arrived at all are concealed, bounded.**
`software_imbe_decoder::decode_erasure()` is the §7.7/§7.8 path with no codeword
to decode: repeat the previous frame's parameters, mute when the budget is spent,
always emit exactly 160 samples. `p25p1_fdma::conceal_gap()` measures the hole and
drives it.

- **Gap measurement needs a symbol clock that survives a resync**, which is why
  `rx_sync::d_symbols_total` exists alongside `d_symbol_count` — the latter is
  reset by `sync_reset()`, i.e. precisely by the event whose duration we need.
  It is passed into `p25p1_fdma::load_nid()`; P25 voice frames are contiguous, so
  any excess over `LDU_SYMBOLS` (864 = 180 ms) is lost audio rather than an
  inter-call pause. Callers that pass 0 get no concealment, which is how the
  deprecated `rx_sym` path stays inert.
- Bounded twice: at most `CONCEAL_FRAMES_DEFAULT` (3, `$OP25_CONCEAL_FRAMES`)
  frames per gap, and not at all past `CONCEAL_MAX_GAP_SYMBOLS` (720 ms) where the
  previous frame's parameters are too stale to repeat and muting is what a real
  radio does anyway.
  - **The env var is surfaced as the add-on's `conceal_frames` option**, exported
    by the s6 run script. It exists as a knob rather than a constant only so
    concealment can be switched off on real RF *without* also disabling the NID
    recovery it ships beside — that is the only way to attribute a change in what
    you hear to one or the other. A dev-only env var would have been useless on
    the one platform that has a dongle attached.
- **`d_voice_audio_flowing` gates it on the previous frame having actually put
  samples on the wire.** Encrypted traffic without a key, and traffic silenced by
  `crypt_behavior`, emit nothing — concealing there would repeat the last frame
  the vocoder *did* decode and bleed a previous clear call into one that is
  supposed to be silent.
- `ER` is deliberately **not** driven up by an erasure: it estimates the channel
  error rate from corrections actually counted, and there are none here. Loading
  it would keep muting good frames for several frames after the gap closed.
  `rpt_ctr` alone is the limiter, and the next good frame resets it.

Counters are in `get_fec_stats_json()` under `voice`: `frames`, `recovered`,
`lost`, `concealed`. `lost` climbing while `recovered` stays flat means sync is
being lost outright — an RF problem, not a decode one. Nothing calls
`control('fec_stats')` yet, so for now the visible signal is `-v 10`, which prints
both `voice recovered as duid=` and `conceal_gap: N voice frames lost`. Counting
those against clip `continuity` is how to tell the two mechanisms apart.

The C++ here has no automated coverage — `test_op25_repeater_sources` is empty and
these paths cannot be reached from `apps/tests`. Both were validated by throwaway
harnesses linking `p25_framer.cc`/`software_imbe_decoder.cc` directly (recovery
gating, the sync error threshold, frame sizing; and 160 samples per erasure, the
bounded repeat budget, re-arming on a good frame). Re-derive that if you change
them — do not assume the pytest suite covers it.

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
- **`talkgroup_scope` decides which calls are worth a round trip**: `all`,
  `focused` (the talkgroups pinned in the UI) or `list` (the explicit
  `talkgroups` array, which is what a bare `talkgroups` has always meant — hence
  that being the default when the key is absent but the list is not, rather than
  silently widening an upgraded install onto a metered STT engine).
  - `focused` reads `ui_state.focused_talkgroups` through a **callable**
    (`HomeAssistantBridge.focused_talkgroups`, supplied by
    `websocket_server._focused_talkgroups`), not a captured list. Two reasons:
    `ha_bridge` stays stdlib-only and ignorant of `ui_state`, and pinning a
    talkgroup has to take effect on the next call rather than the next restart.
    The scope itself is config and does need a restart; the pins do not.
  - **An empty selection means everything, not nothing** — same convention as an
    empty whitelist. A user who turns this on and then unpins their last
    talkgroup would otherwise get silence with nothing on screen to explain it.
    `/api/ha/status` reports `talkgroup_scope`, the resolved `talkgroup_filter`
    and `filtering` so the widened case is visible.
  - `filtered` is counted separately from `dropped` and only while enabled: a
    rising `filtered` beside a flat `submitted` is the answer to "why is nothing
    being transcribed", and a disabled bridge is off rather than filtering.
  - Excluded calls are still recorded, still in `/api/calls`, still in the UI.
    This gates what leaves the host, not what is captured.
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
- **`ChannelStatus.error` is `demod.get_freq_error()` in Hz** — an AFC tuning
  figure, *not* a bit error rate. OP25 does not surface BER to Python
  (`rs_errs`/`gly_errs` exist in the C++ but only reach stderr at debug level).
  Don't build decode-quality gating on `error`.
- **`symbol_quality` / `symbol_locked` are the nearest available stand-in.**
  `gardner_cc` runs the Yair Linn timing-lock detector (`gardner_cc_impl.cc:178`)
  averaged over the last 480 symbols and compared against a 0.28 threshold;
  `quality()` / `locked()` were already pybind-bound and wrapped in
  `p25_demodulator_dev.py`, but nothing read them. `error_tracking()` now
  publishes both in `channel_update` and `ReceiverCard` shows the number, which
  is what you watch while aiming an antenna. Both are `null` when the channel is
  idle **and** when the demodulator is not `cqpsk` — the `fsk4` chain uses a
  different clock recovery with no equivalent, hence the `getattr` guard. It is
  still not a BER: it measures eye opening, so it degrades with multipath and
  noise but says nothing about post-FEC frame errors.
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
  against a stub HA, plus per-call decode continuity. The stub uses `_FastHTTPServer` because
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
  Pinning lives on the receiver (`hooks/useTalkgroupFocus.ts` → `ui_state`) and
  only sorts/filters the table; the scan list stops other talkgroups being
  received at all, so it takes an explicit button in the Talkgroup Browser.
  Narrowing what you look at must not silently narrow what gets recorded and
  transcribed.
- `components/TalkgroupBrowser` **freezes its list while open** (`systems` is
  deliberately not a loader dependency). Chasing a row that re-sorts under you as
  traffic arrives is the problem it exists to solve.
- **The browser filters on a *set* of patterns, OR'd together.** One box could
  express one idea; the real question is a union — "W Cola 1, and everything
  starting RCHP, and 4501". Each pattern carries its own rule
  (`utils/talkgroupPatterns.ts`: contains / starts / exact / wildcard / regex),
  and the kind is guessed from what you type so `RCHP*` lands on Wildcard.
  Without that guess it would be read as a substring, match nothing — no tag
  contains a literal asterisk — and read as the filter being broken rather than
  the wrong rule being applied.
  - **Each chip shows how many talkgroups it accounts for**, counted against the
    rows currently in scope. A pattern that matches nothing is the commonest
    reason a search "does not work", and it is invisible in a union.
  - The half-typed pattern participates in the filter before it is added, so the
    table previews what Add would do.
  - A pattern that will not compile is reported, never silently dropped and never
    silently matched: in a union, a broken pattern that matched everything would
    quietly widen the result. That is also why an *invalid* pattern is shown as a
    red chip rather than emptying the table — most keystrokes in a regex are a
    syntax error in progress.
  - Patterns persist in `ui_state.talkgroup_filters`, like pins and for the same
    reason: retyping them on every visit, and again on the phone, is the
    navigation cost the browser exists to remove.
- **Every column sorts, and the default is Calls descending.** "Which talkgroups
  actually carry traffic" is the question that decides what to select, and it is
  answered by `count` / `last_seen` — the two fields `tg_metadata` exists to
  persist. `Calls` survives on a phone where `Freq` does not, and a "Heard only"
  switch drops the never-heard entirely.
  - Selected rows are **not** floated to the top here, unlike the dashboard's
    table: ticking a checkbox would move the row out from under the pointer, and
    this dialog exists to be ticked through.

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
- **Every emitted frontend file is content-hashed, and `index.html` is
  `no-store`.** The entry chunk and CSS used to be the stable names
  `op25-react.js` / `op25-react.css`; a URL that serves different bytes after an
  update is one a browser can hold a stale copy of forever. What that actually
  produced was a blank panel after an add-on update, explained only by
  `'text/html' is not a valid JavaScript MIME type for module script` in the
  console: the cached `index.html` asked for the *previous* build's hashed vendor
  chunk, and `serve_spa` answered every unknown path with `index.html`. So
  `_ASSET_SUFFIXES` now 404s anything that looks like a build artifact — handing
  HTML to a script request is never right, and the 404 body says "reload" — while
  hashed files are `immutable, max-age=31536000`. `addons/op25/Dockerfile` also
  asserts at build time that every asset `index.html` references is relative
  (ingress) *and* actually shipped.
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
- **The base config is a shipped preset by default, not a file on disk.**
  `addons/op25/presets/*.json` are baked into the image at `/opt/op25/presets/`
  and chosen by the `preset` option (`palmetto800` default, `custom` to read
  `config_file` instead). This exists because a seeded file *cannot receive a
  fix*: `init-op25` writes one only when it is absent — overwriting the user's
  edits would be worse — so the 0.0.7 gain/rate corrections reached only fresh
  installs. A preset ships with the image, so it updates.
  - Per-install differences go in add-on options (`device_overrides`,
    `home_assistant`, `audio_output`, `extra_json`), *not* in a copied preset.
    Copying one to change a single value re-creates the staleness.
  - When a preset is selected and a `config_file` also exists, the run script
    warns loudly that the file is being ignored. Silence there costs someone an
    afternoon.
  - `#`-prefixed keys are documentation and are stripped recursively by `jq`
    `walk()` before the decoder sees them — `/api/config` serves the effective
    config to the browser and the UI renders it.
  - **The RF facts are stated twice** (preset and `apps/Palmetto800-single.json`)
    and drifted apart once already, which is what shipped `LNA:39` / `1000000`
    to every add-on install. `tests/addon_preset_spec.py` pins them together.
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

## Scanner state that outlives a restart

`apps/ui_state.py` is the third small persisted store, beside `tg_metadata`
(talkgroup history) and `config_store` (the config overlay). It holds pins,
holds, the selected channel — state that belongs to the *receiver*.

- **Pins used to be `localStorage`, and that lost them two ways.** It is per
  *origin*, so the same scanner reached through ingress and through port 8099
  kept two separate sets; and it is per browser, so a phone never agreed with a
  desktop. The original rationale (two people shouldn't fight over one setting)
  was real but cost more than it bought.
- **Display preferences stay in `localStorage` deliberately** — theme, accent,
  card collapse are per *device*. A phone wants dark and a desk monitor may not.
- **Not folded into the config overlay.** That is decoder configuration, so a pin
  toggle there would appear in the editor's diff and version history — pinning a
  talkgroup would read as reconfiguring the receiver.
- **`KNOWN_KEYS` is an allow-list, not a free-for-all**, because the endpoint is
  unauthenticated and must not become a place to park arbitrary data on someone's
  SD card. Values are coerced on the way in: `bool` is excluded from the tgid
  list (it is an `int` subclass and would become tgid 1), and a `0` hold is
  dropped rather than stored — 0 is the decoder's own "release", so storing it
  would re-apply a hold the user let go. Talkgroup-browser patterns are
  capped in both count and length, deduped, and an unrecognised `kind` degrades
  to `contains` rather than being dropped — the text is what the user typed, and
  `contains` is the one rule that cannot fail to compile.
- **Holds are keyed by channel *name*, not msgq id.** Ids are positional, so
  adding a device ahead of a channel would silently move a stored hold onto a
  different channel.
- **`/api/ui-state` is not behind the ingress write gate.** Holding a talkgroup
  and applying a scan list have always been accepted unauthenticated over the
  WebSocket, so gating the *record* of a hold while leaving the hold itself open
  buys nothing. Re-pointing the receiver is a different kind of act, and only
  that is gated.
- **`_restore_holds` fires on the first `channel_update`, not at startup** — the
  decoder cannot be told before it has channels — and only once per decoder
  (`_holds_applied`), because `channel_update` arrives every second and
  re-sending would fight a user who just released the hold. A channel that
  already holds the wanted tgid is left alone.
- `useUiState` is a **module-level singleton**: two components calling it would
  otherwise each fetch, each hold a copy, and drift apart on the first write.
  `localStorage` is still written, but only as a first-paint cache and a fallback
  for a server too old to have the endpoint; the server wins whenever it answers.

## Editable configuration

`apps/config_store.py` + `apps/config_schema.py` are the fork's config-editing
layer. The design exists because two wants are in tension: a config shipped in
the add-on image keeps receiving fixes on update, and a config the user owns does
not. The effective config is therefore **composed, never stored**:

    preset (read-only, in the image)  +  overlay (only what the user changed)

- **The overlay holds deltas only**, which is what makes the three operations the
  user asked for fall out for free: roll back to preset = discard the overlay;
  adopt preset changes = nothing to do, because unoverridden fields already track
  it (`preset_drift()` reports the short list where an override now masks a
  *moved* preset value); export = compose and write a standalone file for
  `preset: custom`.
- **`deep_merge` merges lists of dicts element-wise by `name`** (or `sysname` /
  `instance_name`), unlike the add-on run script's `jq *`, which replaces arrays.
  Replacement would force an overlay to restate a whole device to change one
  field of it — and then a preset fix to a *different* field could never arrive,
  which is the staleness the module exists to prevent.
- **`dict(base)` is a shallow copy and that was a real bug.** `effective()`
  handed out references into the preset, so a caller editing the returned config
  rewrote the base; the overlay then looked empty and the diff looked empty,
  because the "before" had already moved. `deep_merge` deep-copies untouched
  subtrees.
- **`prune_overlay` drops anything equal to the base**, so a field set back to
  the preset value stops being an override instead of silently pinning itself.
- **A masked secret means "unchanged".** `/api/config*` redacts
  `ha_bridge.SECRET_KEYS`, so a read-modify-write from the browser would persist
  the literal `***redacted***` as the token and surface much later as an HA 401.
  `unredact()` substitutes the live value; `ha_bridge.REDACTED` is a named
  constant precisely because it is recognised on the way back in.
- **`config_schema` is what makes this multi-protocol.** The editor renders from
  field metadata, so adding a protocol is field descriptions rather than another
  React form. `applies_to` hides fields that mean nothing for the loaded trunking
  module (`nac` is P25-only, `bandplan` SmartNet-only).
- **`live` vs restart-required is the load-bearing flag.** Almost nothing is live:
  device and channel parameters are read in `multi_rx`'s constructors. Being
  optimistic here is the dangerous direction — the UI would report success while
  the decoder ran the old value. `classify()` splits a diff and the API returns
  `needs_restart` honestly.
- **Gain and ppm *are* live, and that is new.** `osmosdr` passes `set_gain()` /
  `set_freq_corr()` straight to the tuner, so `set_device_gains` /
  `set_device_ppm` (multi_rx `RX_DEVICE_COMMANDS`) apply without a rebuild. This
  matters because gain is the parameter most worth sweeping — overload and
  starvation produce identical symptoms — and a restart per value makes that
  impractical. `set_device_ppm` re-derives every affected channel's relative
  frequency, or the correction is applied twice (once by the tuner, once by a
  stale `freq_xlat` offset).
- **Writes are gated to the ingress path.** Port 8099 is unauthenticated, so
  config *writes* there would let anyone on the LAN re-point the receiver.
  `_write_policy()` is `ingress` when `$SUPERVISOR_TOKEN` is set (the add-on) and
  `open` otherwise — a standalone install has no ingress to require, and
  defaulting to `ingress` there would make the editor permanently unreachable
  rather than secure. Reads stay open so `yarn dev` still works.
- `stats()` is spread **before** the computed keys in `/api/config/state`: it
  carries its own `editable` (meaning only "an overlay path exists") and
  spreading it last silently replaced the policy-aware value. Same trap as
  `tg_metadata.stats()` vs `/api/talkgroups`.
- Paths: `$OP25_CONFIG_OVERLAY` / `terminal.config_overlay` /
  `op25_config_overlay.json` in the cwd; history likewise via
  `$OP25_CONFIG_HISTORY_DB`. A corrupt overlay is **ignored, not fatal** — the
  preset alone is a working scanner — and a missing history db never blocks a
  save, because losing the audit trail must not stop a config being written.
- **The overlay is applied at startup by the add-on run script, not by the web
  server.** `config_store.py --apply-overlay` sits in the render pipeline between
  the add-on options and the forced terminal settings. Without that step the
  overlay was written and read *only* by `websocket_server`, so
  `/api/config/state` reported the user's override while `multi_rx` ran the preset
  value — a saved gain looked saved and reverted on every restart.
  - **Not done in `jq`.** `jq`'s `*` replaces arrays, so an overlay of
    `{"devices":[{"name":"sdr0","gains":"LNA:39"}]}` would replace the whole
    device and lose `args`, `rate` and `frequency`. `deep_merge` merges by name,
    and reusing the function the editor previews with is the only thing that
    guarantees the decoder runs what the UI called effective —
    `test_what_the_editor_previews_is_what_startup_produces` pins that.
  - Order is **preset → add-on options → overlay → `extra_json` → forced
    terminal**. The overlay is after the options because it is the layer the user
    is actively driving; before the forced terminal so it can never lock them out
    of the UI that produced it.
- **Never add a method to `rx_block` without grepping for the name first.** A
  second `find_device` was added for the live gain commands and shadowed the
  existing `find_device(chan)`, which resolves a *channel config dict* to a
  device. Python keeps the later definition, so `configure_channels` compared
  `dev.name` against a dict, matched nothing, and dropped every channel with
  `not attached to any device - ignoring!` — RF fine, decoder running, zero calls.
  The by-name lookup is `find_device_by_name`. `tests/multi_rx_api_spec.py` parses
  the source (it cannot import `multi_rx` without GNU Radio) and fails on any
  duplicate method in any class there.
- **`config_schema` also owns float precision.** `round_floats()` is applied on
  save, so `2.3749999999999996` from `adj_tune` never reaches the overlay
  whichever client sent it, and `_trim_drift()` rounds the drift report because an
  overlay written before that existed still holds the long value. Only paths with
  a declared `precision` are touched — a frequency in Hz is left exactly as given
  — and `bool` is excluded explicitly, since it is an `int` subclass and would
  otherwise round to 1.
- **The UI names no config field.** `ConfigDialog`'s Settings tab renders from
  `/api/config/schema`; `www/app/AGENTS.md` has the frontend detail. The three
  tabs share one `useConfigEditor`, which lives outside `op25Service` because
  that service re-renders at 1 Hz from the WebSocket and this is a REST resource
  that only changes when someone edits it.
- **It names no config *tab* either.** `schema.standalone_sections` (currently
  just `transcription`) is what moves a section out of Settings and onto its own
  tab; `SettingsTab` renders whichever sections it is given, so Transcription is
  the same form and inherits the dirty tracking, preset badges, write gate and
  restart banner rather than reimplementing five of them. A client that has not
  heard of the tab still shows the fields under Settings.
  - `TranscriptionTab` adds only what the config cannot say: what the *running*
    bridge is doing, from `/api/ha/status`. Those two disagree between a save and
    a restart, which is the state most likely to be read as a bug.
  - `group` splits a long section into sub-headings. Twenty controls in one grid
    hides which of them decide *what gets sent* and which decide *what comes
    back*.
- **`default` in the schema is displayed, never stored.** A switch for a field
  that defaults to on (`call_recording`, `filter_hallucinations`, `normalize`)
  read as off while the key was absent, which invites the user to "fix" it by
  storing an override that changes nothing. `ConfigFieldInput` shows the default
  when the value is unset; the overridden badge still distinguishes stored from
  defaulted.
- **`POST /api/restart` asks Supervisor to restart the add-on**, which is how a
  restart-required field actually takes effect. It needs `hassio_api` +
  `hassio_role: manager` (the narrowest role that permits
  `/addons/self/restart`), and is gated to ingress exactly like a write — a
  stranger on the LAN restarting the scanner is the thing that gate is for. A
  dropped connection mid-request is treated as **success**: the container going
  away is the restart working.
- **Fine tuning now survives a restart.** `adj_tune` moves `device.ppm` in the
  running decoder and nothing ever wrote it back, so every restart reverted to
  the config value — usually 0.0. `ppm` was always a config key; what was missing
  was a path from the live value into it. `PersistTuningButton` does the
  read-modify-write from the browser, because the server does not know the live
  ppm (it arrives in `channel_update`).

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
4. `set_full_config` (the decoder's own upstream command) still does nothing and
   returns an explicit error. It is **superseded, not pending**: config editing
   goes through the REST layer in "Editable configuration" above, which writes an
   overlay rather than the user's JSON and is gated to the ingress path. The old
   objection — writing config from an unauthenticated browser — is what that gate
   answers. The remaining work there is the React editor, not the backend.
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
8. **NID-failure voice recovery and gap concealment are unverified on air** for
   the same reason — see "Lost voice frames" above. The decision logic was
   validated directly in C++, but only real marginal RF can say whether the
   `RECOVERY_MAX_SYNC_ERRS` gate is tight enough in practice. The symptom of it
   being too loose is bursts of noise where there used to be silence; back it off,
   or set the add-on's `conceal_frames` to 0 (`$OP25_CONCEAL_FRAMES`) to isolate
   concealment from recovery. Shipped in 0.0.16.

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

## Cutting a release

**Never hand-edit the version. Run `scripts/bump-version.py <X.Y.Z>`.** Three
files carry it and two of them are read by machines that fail unhelpfully when
they disagree:

| File | Read by |
|---|---|
| `addons/op25/config.yaml` | Supervisor, to pick the image tag. `addon.yml`'s `version-check` job refuses to publish unless it equals the release tag |
| `addons/op25/CHANGELOG.md` | the add-on store, as the release notes the user sees |
| `www/app/package.json` | baked into the bundle at build time, shown in the About dialog — how you tell what a running install actually is |

`scripts/bump-version.py --check` runs in the `Tests` workflow and fails the push
on any mismatch. That check is the only thing standing between a hand-edited bump
and a release that reports the *previous* version in its own UI, which is exactly
what happened on the first attempt at 0.0.16.

Then, in order:

```bash
scripts/bump-version.py 0.0.17          # all three files; stubs the changelog
# write the changelog section — --check fails while the stub is there
cd op25/gr-op25_repeater/www/app && yarn build   # www/dist carries the version too
git commit -am 'chore(addon): bump to 0.0.17' && git push
git tag -a v0.0.17 -m '...' && git push origin v0.0.17
gh release create v0.0.17 --verify-tag --notes-file <notes>
```

- **Publishing the release is the build trigger.** A tag alone builds nothing, and
  *editing* an existing release does not re-fire the workflow — so a release cut
  against a bad commit cannot be repaired in place. Either move the tag (delete
  the release with `--cleanup-tag`, re-tag, re-create) or burn the version and go
  to the next one. Moving it is only defensible while no image has published; once
  Supervisor can pull `ghcr.io/astoker/op25:X.Y.Z`, that tag is spent.
- The changelog is written for a scanner user, not for this file: what they will
  hear differently, and what to do if it is worse. Compare 0.0.16's entry against
  the commit message for the same change — deliberately two different documents.
- `www/dist` is committed, so a version-only rebuild still moves the entry chunk's
  content hash. Vendor chunks keeping theirs is the signal that nothing else
  changed.

Python tests: `pytest` from `apps/` (specs are `tests/*_spec.py`), 640 tests,
mostly in-process via FastAPI's `TestClient` — no network or dongle needed.
Requires `httpx`.

Without GNU Radio installed the `trunk_json_spec` (via `tk_trbo`/`tk_smartnet`),
`plot_rate_spec` (via `gr_gnuplot`) and `audio_udp_roundtrip_spec` cases
`importorskip` out. Everything else is GR-free because `websocket_server` guards
its `from gnuradio import gr`.

- `tests/websocket_server_spec.py` — static file serving, SPA fallback, path
  traversal, method handling, CORS, stale-asset 404s and cache headers (35).
- `tests/call_capture_spec.py` — PCM helpers, call segmentation, normalisation,
  speech heuristics, hallucination filtering, clip store, keyword matching, HA
  config, HA HTTP round-trips, media upload, REST endpoints, per-port
  capture, and the talkgroup scope that gates transcription (188).
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
  `?channel=` / `?port=` selection, jitter-buffer priming and re-priming, the
  idle-vs-attached buffer bound, the jitter-vs-decoder-loss discrimination that
  decides whether a dropout re-primes at all, and the per-listener fan-out that
  stops two consumers eating each other's chunks (55).
- `tests/multi_rx_api_spec.py` — parses `multi_rx.py` (it cannot be imported
  without GNU Radio) to reject shadowed methods and pin the two device-lookup
  names apart (8).
- `tests/ui_state_spec.py` — the persisted scanner state: value coercion and the
  key allow-list, merge-not-replace, degradation to memory-only, the REST
  round-trip, hold record/restore incl. once-per-decoder, and the pinned list
  the transcription scope reads, and the browser's saved search patterns (37).
- `tests/config_store_spec.py` — merge/prune/diff primitives, overlay deltas,
  preset drift, rollback replaying intent onto a moved preset, redaction
  round-trip, path resolution, schema live-vs-restart classification, and the
  startup overlay application incl. editor/startup agreement, float
  precision and reset-to-preset semantics (84).
- `tests/config_api_spec.py` — the write gate (ingress/open/off), config state,
  schema filtering, validation, history, rollback, reset, export containment,
  the restart endpoint's gating and error mapping, and float precision
  over the API, and the transcription section's own schema (60).
- `tests/addon_preset_spec.py` — the built-in add-on presets: loadable, RF
  fields pinned to `Palmetto800-single.json`, and container-appropriate (no
  pinned serial, no local speaker output, no secrets) (29).
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
