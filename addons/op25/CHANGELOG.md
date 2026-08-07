# Changelog

## 0.0.9

- **Palmetto 800 gain goes back up, to 40.** 0.0.8 lowered it to 30 on the
  theory that near-maximum gain overloads the tuner on 800 MHz. On air that was
  wrong: the log showed a receiver starved of signal, not overloaded — 44
  control-channel timeouts hunting all four frequencies, and voice frames with
  8–13 bit errors against a repair threshold of about 10. Overload and starvation
  produce the same symptom, so this is a per-site measurement rather than a
  setting with a right answer. Sweep it with the `device_overrides` option and
  watch the symbol-quality figure in Tuning & Diagnostics; no need to change any
  file to try a value.
- **Audio no longer plays several seconds late.** The decoder feeds the audio
  buffer whether or not anyone is listening, so an idle scanner accumulated four
  seconds of it — and opening the UI inherited that as a permanent delay, because
  the buffer was drained and refilled at the same rate. You would hear the reply
  before the call. With nobody listening the buffer now keeps only a fraction of
  a second, so opening the UI starts you live.

  Once you *are* listening nothing is discarded early, which matters: audio can
  legitimately arrive in bursts, and throwing that away clips the first word of a
  transmission.

## 0.0.8

**Fixes a blank OP25 panel after updating to 0.0.7.** If you are seeing one,
this release fixes it — and a hard reload (Ctrl/Cmd-Shift-R) fixes it on 0.0.7.

- **An update no longer breaks an open tab.** Every file the UI loads is named
  after a hash of its contents, so those names all change when the add-on
  updates. `index.html` is the one file whose address stays the same, it was
  being served without any cache instruction, and so a browser could keep an old
  copy — one that asks for files the new version does not have. The only clue was
  a MIME-type error in the browser console. `index.html` is now marked
  never-cache, and the files that *are* content-addressed are marked
  cache-forever, which is both correct and faster than before.
- **A missing file now says so.** Any address the server did not recognise
  returned the app's own HTML page, including requests for scripts. A browser
  asked for JavaScript, got HTML, and rendered nothing. Those requests now
  return a plain 404 that names the problem and says to reload.
- **Built-in system presets.** The new `preset` option selects a config that
  ships inside the add-on, and defaults to `palmetto800`. Nothing to place, no
  file to edit, and — the point — fixes to it reach you when the add-on updates.
  Set `preset: custom` to go back to editing your own `config_file`; that is
  still fully supported, and a first run copies the preset there to start from.

  This is the answer to "I updated and my config did not change." A config file
  is only ever written when it is absent, because overwriting your edits would
  be worse — which means a file seeded once could never receive a fix. The
  0.0.7 gain and sample-rate corrections, for instance, only reached people who
  installed fresh. With a preset they arrive on update.

  Per-install differences belong in add-on options rather than a copied file:
  `device_overrides` for the dongle serial, gain and ppm, plus
  `home_assistant`, `audio_output` and `extra_json`.
- The Palmetto 800 preset carries the 0.0.7 RF corrections that the old shipped
  sample missed: gain down from near-maximum, and a sample rate that divides
  evenly into the decoder's IF rate. A test now pins the preset and the
  standalone config together so they cannot drift apart again.
- Every field in a preset carries a note explaining why it is set that way.
  These are stripped before the decoder reads the config.

## 0.0.7

- **Browser audio no longer chops.** The audio stream had no jitter buffer: the
  decoder emits one 20 ms frame every 20 ms and the stream consumed one every
  20 ms, so the cushion was always empty. A packet arriving even slightly late
  became a 20 ms hole spliced into the middle of a word, and because the cushion
  could never build, a few percent of scheduling jitter was heard as *continuous*
  garbling — which sounds exactly like a bad radio signal but was not. The stream
  now holds 120 ms before playback and rebuilds that cushion when it runs dry.
  Tunable with `OP25_STREAM_PRIME_MS` if you want less delay or more safety.
- **Signal quality you can aim an antenna by.** Tuning & Diagnostics now shows a
  symbol-quality figure from the demodulator's timing-recovery lock detector,
  which was computed all along and never displayed. Higher is a cleaner signal
  and it responds as you move an antenna, unlike the frequency-error number next
  to it. It is not a bit error rate — the decoder does not expose one — and it is
  blank while a channel is idle or when the demodulator is not `cqpsk`.
- The audio diagnostics in the log distinguish real dropouts from idle silence,
  so a rising underrun count now means something.
- The bundled Palmetto 800 sample config drops its gain from near-maximum (which
  overloads the tuner on 800 MHz and sounds like garbling) and moves to a sample
  rate that divides evenly into the decoder's IF rate, removing a resampling
  stage and widening the tuned window so fewer calls force the radio to retune.

## 0.0.6

- Persistance of metadata in `op25_metadata.sqlite` across restarts.
- Talk groups fixed
- Plots improved
- Remote GUI hooks

## 0.0.5

First image since 0.0.2: **0.0.3 and 0.0.4 never published one.** 0.0.3's build
was cancelled part-way by a GitHub Actions outage, and 0.0.4 was tagged without
bumping `config.yaml`, which the release workflow refuses by design. Everything
listed under 0.0.3 below therefore arrives here for the first time.

- **The header's Config and About entries do something.** Both were placeholders
  that swallowed the click.
- **Config → Decoder** holds the log level, which is the `-v` command-line
  option, alongside a read-only view of how the decoder was started (terminal,
  trunking module, plot interval, local speaker output, audio ports, the
  speech-to-text engine). Log level moved out of Tuning & Diagnostics: it is
  applied to every channel and device at once, so presenting it as a per-channel
  control was misleading.
- **Config → Interface** collects the browser's own preferences — theme, accent
  colour, talkgroup smart colours. The accent-colour picker is new; the theme
  service had always supported it with nothing in the UI to reach it. This
  replaces the gear menu in the header, which held a single switch.
- **Config → Running config** is the loaded JSON, moved out of the dashboard.
  It answers a question you ask while setting a system up, not one you scan.
- **About** says what this build is and how it differs from boatbod/op25, and
  now shows the add-on version — the answer to "what am I actually running".
- One version number across `config.yaml`, this changelog and the web UI, kept
  in step by `scripts/bump-version.py` and checked in CI.

## 0.0.3

- **Seeds a working config on first run** instead of refusing to start. Getting
  a file into an add-on's config directory is the most awkward step of a Home
  Assistant OS install -- there is no host shell -- so the add-on now writes
  the sample itself and starts. Edit it in place afterwards.
- The sample is now the **Palmetto 800** (South Carolina) single-SDR P25
  system, which is a real, heavily-used system rather than a placeholder.
  Sanitised: no serial number, no LAN addresses, and no `webhook_id` (that is
  a bearer secret -- anyone holding it can POST into your Home Assistant).
- DOCS explains the three ways to reach the config directory on HAOS, and the
  `/share` fallback for when none of them is convenient.
- Device args default to `rtl` rather than a specific serial: with one dongle
  that just works, and another machine's serial is actively wrong.

## 0.0.2

First image published to GHCR. Same content as 0.0.1, which never built: its
tag disagreed with the manifest version and the manifest tripped the add-on
linter.

## 0.0.1

Initial release. Experimental — not yet verified on real hardware.

- OP25 multi_rx with the React web UI, served through Home Assistant ingress
  and on port 8099.
- RTL-SDR via `usb: true`; Debian trixie's librtlsdr 2.0.2 supports the
  RTL-SDR Blog V4 without a patched build.
- Config comes from a JSON file in the add-on's config directory; add-on
  options cover only the things that change with hardware or credentials.
- Speech-to-text can use the Supervisor proxy, so no long-lived token.
