# Changelog

## 0.0.13

**Why the live audio is choppy when the recording of the same call is clear** —
and a number that tells you how bad it is.

- **Call recordings now show how much of the transmission actually decoded.** A
  clip below 90% gets a "% decoded" badge in Call Audio & Transcripts.

  This answers a genuinely confusing thing. A recording is built by joining
  together the audio that arrived, and nothing fills the gaps — so a call that
  lost half its frames produces a recording half as long that still sounds
  smooth and clear. Live audio cannot do that: it plays in real time, so those
  same missing frames are heard as silence, and that is exactly what "choppy"
  is.

  So a clear recording alongside choppy live audio does **not** mean the
  streaming is broken. It means frames are being lost off the air, and the
  recording is hiding it by omission. The new badge makes the loss visible: 60%
  decoded means 40% of that transmission never arrived.

- Nothing about the live audio path changed, because measurement showed it is
  not losing anything. Driven against a decoder-shaped source — nine packets per
  voice frame group, 180 ms apart, with groups deliberately dropped — the player
  played back every byte it was given, in every case. The silence you hear is
  the gap, faithfully rendered.

- If you see low percentages, that is the antenna and gain work, not a setting.
  Watch the badge while you sweep gain: it is a more direct measure of decode
  quality than the symbol-quality figure, because it counts frames that actually
  survived rather than how open the signal's eye looked.

## 0.0.12

Config editor polish.

- **Reset a single setting to its preset value.** Any setting you have changed
  gets a small reset button, and its tooltip names the value it would put back —
  so you can see what the preset says without clearing anything to find out.
  Resetting one setting leaves your other changes alone.
- **Frequency correction is no longer a sixteen-digit number.** Fine tuning works
  in fractions of a ppm and was landing on values like `2.3749999999999996`.
  Those digits are far below anything the radio can act on — at 859 MHz the
  smallest tuning step is about a tenth of a ppm — so they are now trimmed to
  three decimals. Existing saved values are shown trimmed and get tidied on the
  next save.
- **The status labels on each setting are icons now,** with a legend at the top
  of the Settings tab. Every setting carries at least one, and the words
  "restart, restart, restart" down a column of twenty was drowning out the labels
  they belonged to. Hovering any icon still spells it out.

## 0.0.11

**Fixes two bugs introduced in 0.0.10. If you are on 0.0.10, update — it does not
receive calls.**

- **0.0.10 stopped decoding entirely.** Adding the live gain controls introduced a
  second method with the same name as an existing one, and the new one silently
  replaced it. The replaced method was the one that matches a channel to its
  radio, so every channel was discarded at startup with *"not attached to any
  device - ignoring!"* in the log. The radio tuned, the decoder ran, the web UI
  loaded — and there was no receiver behind any of it.

  A test now parses the decoder source and fails on any duplicated method, in any
  class. It was verified to fail on this exact bug before being kept.
- **Saved settings were ignored at startup.** Changes made in the UI were stored
  correctly and the editor showed them, but the decoder was started from the
  preset alone — so a saved gain applied immediately and then reverted on the next
  restart. The startup path now applies your saved changes, in a defined order:
  preset, then add-on options, then your UI changes, so what the editor shows as
  effective is what actually runs.

  Your existing saved changes are picked up automatically; nothing to redo.

## 0.0.10

**Configuration is editable from the UI.** Config → Settings, Advanced JSON and
History.

- **Settings** is a form with every field explained, and each one marked *live*
  or *restart*. Almost nothing about a radio can change while it is running, so
  that distinction is shown rather than glossed over — a value the scanner is not
  actually using is worse than one you know you have to restart for.
- **Gain and frequency correction are live.** They apply the moment you save, so
  a gain sweep is now something you do while watching the symbol-quality figure,
  instead of a restart per value.
- **Fine tuning survives a restart.** This was the bug behind "I keep having to
  set ppm again": the fine-tune buttons moved it in the running decoder and
  nothing ever wrote it down, so every restart went back to the config value.
  There is now a **Save tuning** button next to them in Tuning & Diagnostics.
- **Only what you change is stored.** Everything you leave alone keeps tracking
  add-on updates, so a preset fix still reaches you. If one of your overrides is
  masking a newer preset value, the editor says so and shows both.
- **History** lists every change with the fields it touched, and restores any of
  them. Restoring replays *your* changes onto the current preset rather than
  reinstating an old one wholesale — so a rollback cannot quietly undo an add-on
  fix you never chose to undo. Resets and restores are themselves recorded, so
  they can be undone too.
- **Advanced JSON** edits the config directly, for anything the form does not
  cover — adding a device or a second system. It also holds **Reset to preset**
  and **Export**, which writes a complete standalone file for when you want to
  stop tracking the preset and own the config outright.
- **Restart from the UI.** A change that needs one gets a Restart add-on button.
  This is why the add-on now asks for Supervisor access; it is used for nothing
  else.
- **Editing requires the sidebar.** The published port (8099) is unauthenticated,
  so config changes are refused there — anyone on your network could otherwise
  re-point the scanner or change where it sends recordings. Reading stays open.
  Set the `config_write` option to `open` if you would rather allow it.

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
