# Changelog

## 0.0.19

**You can now search your captured calls — by what was said, or by who said
it.** There is a new search box at the top of the Call Audio & Transcripts card.

Type anything and the list narrows as you go. It looks in three places at once,
so you do not have to decide in advance which one you remember:

- the **transcript**, if the call has one
- the **talkgroup name**
- the **talkgroup number**

Type more than one word and *all* of them have to match — but they can match in
different places. So `cola fire` finds a call on a West Columbia talkgroup where
someone said "fire", which is usually what you actually want and is not something
a single search box normally lets you ask.

Small things that make it easier to use:

- **Matches are highlighted**, so you can see why each call is in the results.
  Search matches are shaded plainly and your configured alert keywords keep their
  orange marker — a search hit is not an alert, and the two never look alike.
- **The talkgroup number now appears on each call** next to its name, so a call
  found by number shows you the number it matched.
- The count reads "3 of 40 captured" while you are searching, so a search that
  finds nothing is obvious rather than looking like nothing was ever recorded.
- It combines with the existing **Keyword hits only** switch.
- Searching for `10-33` or a stray bracket does what you would expect. This is a
  plain text search, not a pattern — unlike the talkgroup browser's filter, where
  `RCHP*` means a wildcard. Radio traffic is full of characters that would
  otherwise be read as pattern syntax and quietly match nothing.

Worth knowing:

- **Calls with no transcript are still findable by talkgroup.** If you have not
  set up speech-to-text, the search still works — it just has names and numbers
  to go on, and it tells you so when a search comes up empty.
- **It searches the calls that are still in the list**, which is the most recent
  60. Older calls are gone from the server's memory and cannot be searched. If
  you want a permanent archive, turn on `media_upload` so clips are saved into
  Home Assistant's media library.
- The search box clears itself on reload. It filters a live list, so a search
  restored later would hide calls that arrived since you typed it.

Nothing to configure, and nothing else changed in this release.

## 0.0.18

**Live audio is now levelled the same way the recordings are. That difference —
recordings sounding better than the same call heard live — was distortion, and it
was measurable.**

The web player used to apply one fixed volume boost to everything and then run it
through what was labelled a limiter. Two things were wrong with that:

- **The "limiter" was actually a hard clipper.** Because of how it was wired, any
  sound above about a quarter of full volume came out squared off flat rather than
  gently compressed. On loud talkgroups that was over 6% of the audio being
  distorted. It is the gritty, harsh edge you hear on live speech but never on the
  recording of the same call.
- **One fixed boost cannot suit the traffic.** Talkgroups arrive around 28 dB
  apart in loudness, so a single setting was simultaneously far too loud for
  normal calls — around 8 to 12 dB hotter than the recording of the same audio —
  and still too quiet for the faintest ones.

Recordings never had this problem because they are levelled per call, with the
volume backed off far enough that peaks cannot clip. The live player now uses the
same targets, applied continuously as audio arrives:

- Loudness now lands within about 1 to 3 dB of the recording of the same call,
  instead of 8 to 12 dB over it.
- The spread between the quietest and loudest traffic drops from 25 dB to under
  5 dB, so you should stop reaching for the volume control between talkgroups.
- **Nothing clips.** Zero flat-topped samples at any input level tested.
- Loud sounds are held back quickly (30 ms) so a sudden shout cannot distort,
  while quiet passages are brought up gently (400 ms) so the level does not pump
  audibly between words.

There is nothing to configure; it adapts on its own. Expect the first half-second
of the first transmission after you press Play to settle in level.

Also in this release: the levelling has an automated check that runs on every
build, driving the real playback code over test tones at five different loudnesses
and failing if anything clips or the levels drift apart again. The previous
version's limiter carried a comment confidently describing behaviour it did not
have, and nothing would have caught that.

## 0.0.17

**This is the one that fixes choppy audio in the browser. It was a bug, not a
limitation of listening over the web — and not the radio's fault at all.**

Playing the same stream outside the browser was clean, which is what finally
gave it away. If it sounds clean in VLC and choppy in the web UI, the audio
already arrived intact and something in the page is mangling it. That was
exactly the case here.

- **The web UI was opening two audio streams and letting them fight over the
  audio.** Pressing Play started one stream, and a second one started itself
  immediately afterwards. The server handed each connection *alternate* pieces of
  the audio instead of giving both the whole thing — so the page was playing
  roughly every other fragment of every word, with the two streams a few
  milliseconds apart.

  That is the chop, and the faint echo or doubling underneath it. It had nothing
  to do with signal strength, which is why it never tracked reception quality and
  why last release's decoder work made no difference to it.
- **Several listeners now work properly.** Each connection gets its own copy of
  the audio. Two browser tabs, a phone next to a desktop, or a Home Assistant
  media player pointed at port 8099 while you also have the UI open — all of
  those used to break each other's sound in the same way, and now they don't.
- **The player no longer leaves an abandoned connection behind** when you switch
  audio source or press Play twice quickly. Those kept a listener slot open on the
  scanner for nothing.
- The add-on log now reports `listeners=` alongside the other audio counters. It
  is there because not having it is what made this take so long to find: the only
  hint was a throughput number that looked odd, rather than anything saying "two
  things are listening to this."

Worth knowing: **0.0.16's decoder work is still in place and still worth
having** — it recovers voice from frames that used to be discarded outright. It
simply was not the cause of the browser chop. If you turned `conceal_frames`
down while testing, it is safe to put it back to 3.

If audio still sounds wrong after this, the useful comparison is the same one:
play `http://<your-ha-host>:8099/api/stream` in VLC. Clean there and bad in the
browser means there is still something in the page; bad in both means it is worth
looking at reception.

## 0.0.16

**Live audio should be noticeably less choppy. The decoder was throwing away
audio it could have decoded.**

- **A corrupt frame header no longer costs you the audio in that frame.** Each
  180 ms of P25 voice arrives wrapped in a small header that says who is talking
  and what kind of frame it is — and nothing else. It carries no voice at all.
  Until now, if that header failed its error check, OP25 discarded the whole
  frame: nine chunks of speech, each with its own independent error correction,
  each perfectly decodable, thrown out because 64 bits of *addressing* were
  damaged.

  Worse, dropping the frame also lost the receiver's place in the stream, so it
  had to re-lock onto a signal that had just proved marginal — which is how one
  bad frame turned into several in a row.

  A real P25 radio does not do this. Once it has locked onto a channel it knows
  the frame pattern and keeps decoding speech straight through a bad header. OP25
  now does the same. This is the change that should be audible.
- **Short gaps are smoothed instead of cut.** When audio genuinely is lost, the
  decoder now does what a real radio does: it holds the last fragment of speech
  briefly instead of cutting to silence instantly. That is why a P25 radio in a
  marginal spot sounds warbly or underwater rather than chopped — holding the
  pitch renders the loss as a smeared vowel instead of a hole.

  This is deliberately brief — up to 60 ms — and then the gap goes quiet. It
  softens the edges of a dropout; it cannot invent speech that never arrived.
- **The browser stream stopped adding its own silence on top of the loss.**
  After any interruption the player rebuilt its safety buffer before resuming,
  which costs an extra 120 ms of quiet. That is the right thing to do when the
  network hiccuped, and the wrong thing when the radio signal simply went away —
  there is nothing to buffer, so the wait was pure added silence, on every single
  dropout. A 180 ms loss was being played back as a 300 ms hole. The stream now
  tells the two cases apart and resumes immediately when the gap was the radio's.
- **Recordings still show you when a call was lossy.** A call that lost half its
  audio still produces a shorter clip, and the decode-quality figure on it still
  reflects that. Smoothing the gaps was not allowed to hide them.

Notes for testing this on air:

- All of the above is in the decoder, so it takes effect when the add-on
  restarts after the update. Nothing to configure.
- There is a new `conceal_frames` option, default 3. Setting it to `0` turns the
  gap smoothing off while leaving the header recovery on, which is how to tell
  which of the two is responsible for a change in what you hear.
- If something sounds *worse* — bursts of noise where there used to be silence —
  that points at the header recovery being too willing, and the honest fix is to
  roll back to 0.0.15 and say so. The decision logic was tested directly, but
  only real marginal RF can confirm the threshold, and there is no radio on the
  development machine to try it with.
- With `verbosity` at 10 the log names both effects: `voice recovered as duid=`
  is a frame rescued from a bad header, `conceal_gap: N voice frames lost` is
  audio that never arrived. If the first dominates, this release is working; if
  the second dominates, the signal itself is too weak and antenna or gain is the
  next thing to look at.

## 0.0.15

**Finding the talkgroups worth listening to, and deciding which of them get
transcribed.**

- **The Talkgroup Browser searches on several patterns at once.** One box could
  only ask one question; what you actually want is a union — "West Columbia 1,
  and everything starting RCHP, and 4501". Add as many patterns as you like and
  a talkgroup shows if it matches *any* of them.

  Each pattern has its own rule: contains, starts with, exact, wildcard
  (`RCHP*`) or a full regular expression. The rule is guessed from what you
  type, so `RCHP*` is treated as a wildcard rather than searched for literally,
  and you can override it. Every chip shows how many talkgroups it accounts for,
  so a pattern that finds nothing says so instead of hiding inside the union.

  Your patterns are saved on the receiver, alongside your pins — so they are
  still there tomorrow, and the same on your phone.
- **Every column in the browser sorts, and it opens on Calls, highest first.**
  Which talkgroups actually carry traffic is the question that decides what to
  select, and now it is the first thing on screen. There is also a "Heard only"
  switch to drop everything that has never been heard, and the header counts
  them for you.
- **Config has a Transcription tab**, holding everything about speech-to-text in
  one place: what gets sent, which engine, what comes back, and the recording
  gates that decide whether a call is worth transcribing at all. It shows what
  the running scanner is doing beside what the settings say, which is the
  difference you cannot otherwise see between saving a change and restarting
  into it.
- **You can now transcribe only the talkgroups you have pinned.** Transcription
  is the expensive step — a cloud engine bills for it, a local one competes with
  Home Assistant for CPU — so `Transcribe` offers *all traffic*, *only pinned
  talkgroups*, or *only a list you type*. Pinning is read live: pin a talkgroup
  and its next call is transcribed, no restart.

  Unpinning everything widens transcription back to all traffic rather than
  silently stopping it, and the tab says so when that happens.
- **Errors that used to vanish now say something.** A setting that would not
  save, or a command the decoder rejected, previously just undid itself a moment
  later, which looks like a broken screen rather than a message. Those now raise
  a notification that stays until you dismiss it.
- Settings that are on unless you say otherwise (call recording, hallucination
  filtering, clip levelling) no longer show as "off" in the config form when you
  have never touched them.

## 0.0.14

**Pinned talkgroups and holds now live with the scanner, so they survive a
restart — and follow you between devices.**

- **Pinned talkgroups are saved on the receiver.** They were kept in the
  browser, which loses them in two ways that look like a bug: browser storage is
  per *web address*, so opening OP25 from the Home Assistant sidebar and opening
  it directly on port 8099 kept two completely separate sets of pins — and a
  phone never agreed with a desktop. Now there is one set, and it is the
  scanner's.
- **Holds survive a restart.** A hold lived only in the decoder's memory, so
  restarting dropped it — which is most annoying precisely when the restart was
  to apply a setting you just changed. Holds are now remembered and re-applied
  once the decoder comes back up.

  If you released the hold yourself, or set a different one in the meantime,
  nothing is put back over the top of it.
- Theme, accent colour and which cards are collapsed stay per browser on
  purpose. Those are genuinely per device — a phone wants dark mode when a desk
  monitor may not.

Your existing pins are read from the browser once and adopted; nothing to redo.

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
