# Capability gaps — fork vs. upstream boatbod/op25

Audit date: 2026-08-04. Branch `feature/updated-gui` @ `bf56b51b`.
**Closed 2026-08-05 at `3b7d4d49`** — see "Status" below.
Reference points: upstream `README.md` capability lists, `op25/gr-op25_repeater/apps/README*.md`,
the legacy control protocol table in
[www/react-app-legacy/AGENTS.md](https://github.com/AStoker/op25/blob/3b7d4d49d48b379495992dcbea5b57f5c3941d00/op25/gr-op25_repeater/www/react-app-legacy/AGENTS.md),
and `upstream/dev` (12 commits ahead of our merge-base `b2e04c3f`).

> **Links into the legacy tree are permalinks pinned to `3b7d4d49`.** That commit is the
> last one before `www/www-static/`, `www/react-app-legacy/` and `apps/http_server.py`
> were deleted. They no longer resolve in the working tree, and that is expected — this
> document is a closed audit, not a live map.

Scope: what upstream *advertises* (or ships) that this fork's new stack
(`websocket_server.py` + `www/app`) does not deliver, plus code paths that exist
on one side of the bridge with nothing hooked up on the other.

Legend: **[P1]** advertised capability unreachable · **[P2]** dead or half-wired
code · **[P3]** docs & housekeeping.

---

## Status — closed 2026-08-05

Worked through in six phases (commits `2ab54018`…`b2ef0cf6` plus the merge
`0f328a14`). 42 of 46 items closed; test count went 137 → 213 (277 by audit close).

**The audit is closed.** Of the four items that were still open on 2026-08-04:

- `meta_update` (§2) is the one real remaining gap, carried forward as a standing
  known limitation rather than closed.
- Two are upstream roadmap tracking (§10) and were never fork regressions.
- The upstream-PR-policy note (§10) is retired — see the strikethrough there.

This file is now a historical record. It is not maintained against the working tree,
and its links into the deleted legacy stack are pinned permalinks (see above).

Where the fix differs from what the item proposed, that is deliberate:

- **`SYSTEM_CONTROL` mute/unmute** — resolved by *removing* the client sends and
  narrowing the type, not by implementing server-side muting. The page stopping
  its pull of `/api/stream` is the entire mechanism; a server command would have
  been a second, redundant one.
- **`set_full_config`** — now answers with an explicit error, and the UI gained a
  read-only config viewer. Writing the user's JSON from an unauthenticated
  browser stays out of scope.
- **`rx_update`** — turned out to be the *http* terminal's gnuplot PNG list
  (`multi_rx.ui_plot_update`, gated on `terminal_type == "http"`), not symbol
  captures, so the ws terminal never receives one. Captures got their own
  `/api/captures` endpoints instead, fed by a new `capture_file` field.
- **`get_ws_instances`** — still not requested. Per-channel audio was solved with
  `/api/stream?channel=` + `/api/audio/channels` rather than the legacy `ws://`
  sinks, so the command has no consumer; §5 documents the divergence.
- **`ws://` audio destinations** — documented as legacy-only rather than
  implemented in the new stack (README-browser-audio.md now splits by stack).

Two bugs surfaced while implementing DMR parity, both fixed: `dmr_chan`
appended the `_grant_info` *class* twice so both time slots aliased one set of
attributes, and `tune_next_chan` never assigned `current_chan`, so the
control-channel hunt could only cycle between the first two LCNs. Neither has
been confirmed on air — see the note in §6.

Still open: Raspberry Pi 5 verification, the Icecast-metadata display, and the
two upstream roadmap items.

---

## 1. Control commands the decoder accepts but the new GUI never sends

The decoder's UI command surface is [multi_rx.py:851-947](op25/gr-op25_repeater/apps/multi_rx.py#L851-L947).
The new UI only ever sends `get_full_config`, `get_terminal_config`, `hold`,
`skip`, `lockout`, `whitelist`, `toggle_plot`
([op25Service.tsx:145-300](op25/gr-op25_repeater/www/app/src/services/op25Service.tsx#L145-L300)).

- [x] **[P1] `adj_tune` — fine tuning.** Advertised: "ability to adjust fine tuning in real time (,./<> keys)".
      Handler at [multi_rx.py:887](op25/gr-op25_repeater/apps/multi_rx.py#L887); curses binds it at
      [terminal.py:307-314](op25/gr-op25_repeater/apps/terminal.py#L307-L314); legacy web UI has it
      (`main.js` `adj_tune`, legacy `ChannelControls.tsx`). No control in `www/app`.
- [x] **[P1] `set_debug` — "Dynamically controllable log level".** Handler at
      [multi_rx.py:892](op25/gr-op25_repeater/apps/multi_rx.py#L892); legacy `SettingsDialog.tsx:342`
      exposes it. Nothing in the new UI.
- [x] **[P1] `capture` — "Dynamic demodulator symbol capture and replay (commanded through terminal)".**
      Handler at [multi_rx.py:922](op25/gr-op25_repeater/apps/multi_rx.py#L922). Not sendable from the
      new UI, and the resulting `rx_update` file list is also unhandled (see §2).
- [x] **[P1] `reload` — "TGID Blacklist, Whitelist with **dynamic reloading**".**
      Implemented per-receiver in [tk_p25.py:2375-2378](op25/gr-op25_repeater/apps/tk_p25.py#L2375-L2378)
      and [tk_smartnet.py:2133-2136](op25/gr-op25_repeater/apps/tk_smartnet.py#L2133-L2136). No UI path,
      so blacklist/whitelist file edits cannot be re-read without a restart.
- [x] **[P2] `dump_tgids` / `dump_buffer`.** Handlers at
      [multi_rx.py:919](op25/gr-op25_repeater/apps/multi_rx.py#L919) and
      [multi_rx.py:929](op25/gr-op25_repeater/apps/multi_rx.py#L929); both reachable from curses and the
      legacy web UI, neither from the new one.
- [x] **[P2] `lockout` / `whitelist` are wired in the service but no component calls them.**
      `lockoutTalkGroup` / `whitelistTalkGroup`
      ([op25Service.tsx:289-295](op25/gr-op25_repeater/www/app/src/services/op25Service.tsx#L289-L295))
      have zero call sites — `ChannelsCard` only offers hold/release. So blacklisting a talkgroup is
      unreachable from the browser even though the plumbing exists.
- [x] **[P2] No way to enter an arbitrary TGID.** Curses has `H` (hold/goto tgid), `W` (whitelist tgid),
      `B` (blacklist tgid) — [terminal.py:253-306](op25/gr-op25_repeater/apps/terminal.py#L253-L306).
      The new UI can only act on talkgroups already present in the table.
- [x] **[P3] `get_ws_instances`** ([multi_rx.py:912](op25/gr-op25_repeater/apps/multi_rx.py#L912)) is
      never requested. Related to the per-channel audio gap in §5.

## 2. Decoder → browser messages that arrive and are dropped

- [x] **[P1] `rx_update` is ignored.** Emitted at
      [multi_rx.py:987](op25/gr-op25_repeater/apps/multi_rx.py#L987) with the list of symbol-capture
      filenames. The bridge forwards it as a generic `SYSTEM_STATE`
      ([websocket_server.py:1202](op25/gr-op25_repeater/apps/websocket_server.py#L1202)) and the UI has
      no branch for it. There is also no HTTP endpoint that serves the capture files, so the legacy
      "download capture" affordance has no equivalent.
- [x] **[P2] `terminal_config` is requested and then discarded.** Requested at
      [op25Service.tsx:146](op25/gr-op25_repeater/www/app/src/services/op25Service.tsx#L146); no handler.
      Keys the legacy UI honours and the new one ignores
      ([main.js:276-300](https://github.com/AStoker/op25/blob/3b7d4d49d48b379495992dcbea5b57f5c3941d00/op25/gr-op25_repeater/www/www-static/main.js#L276-L300)):
      `smart_colors`, `tuning_step_small`, `tuning_step_large`, `default_channel`, `terminal_interface`.
- [ ] **[P2] `meta_update` is ignored.** *(Still open at audit close — the only one. It has a
      real route in `_JSON_TYPE_TO_MSG`, but no card displays Icecast stream state. Carried
      forward as a standing gap rather than closed; Icecast metadata is a niche path and
      `icemeta.py` remains a live `metadata.module`.)* Emitted by
      [tk_p25.py:54-69](op25/gr-op25_repeater/apps/tk_p25.py#L54-L69) for Icecast metadata
      ("support for streaming metadata updates" — README-metadata.md). Nothing surfaces stream metadata
      state in the new UI.
- [x] **[P2] `SDR_STATUS` is a declared channel that is never used.** `MSG_SDR_STATUS`,
      `broadcast_sdr_status()`, `broadcast_system_state()`, `broadcast_call_activity()`
      ([websocket_server.py:1044-1056](op25/gr-op25_repeater/apps/websocket_server.py#L1044-L1056))
      have no callers, and the `_JSON_TYPE_TO_MSG` table
      ([websocket_server.py:792-800](op25/gr-op25_repeater/apps/websocket_server.py#L792-L800)) keys on
      `chan_status` / `trunked_site_status` / `sys_info`, none of which any decoder module emits
      (the real json_types are `trunk_update`, `channel_update`, `call_log`, `rx_update`, `plot`,
      `meta_update`, `terminal_config`, `full_config`, `ws_instances`, `ok`). Either populate the
      table with real types or delete the fiction — right now the documented protocol in `CLAUDE.md`
      overstates what is on the wire.
- [x] **[P2] Initial `SYSTEM_STATE` snapshot is permanently `status: "stopped", uptime: 0`.**
      [websocket_server.py:93-105](op25/gr-op25_repeater/apps/websocket_server.py#L93-L105); sent once on
      connect ([:815-823](op25/gr-op25_repeater/apps/websocket_server.py#L815-L823)) and never refreshed.
      Its consumer hook `useSystemState()`
      ([useSystemState.ts:18](op25/gr-op25_repeater/www/app/src/hooks/useSystemState.ts#L18)) has no call
      sites. Either drive it from real decoder state or drop it.

## 3. Upstream → browser control that the server drops

- [x] **[P1] `SYSTEM_CONTROL` mute/unmute are sent and silently discarded.** `PlayerCard` sends
      `unmute`/`mute` on play/stop
      ([PlayerCard.tsx:51,56](op25/gr-op25_repeater/www/app/src/components/PlayerCard/PlayerCard.tsx#L51-L56)),
      but `handle_system_control` only implements `quit`
      ([websocket_server.py:1223-1233](op25/gr-op25_repeater/apps/websocket_server.py#L1223-L1233)).
      Playback happens to work because the client stops pulling `/api/stream`, so this is a no-op
      round-trip that looks wired.
- [x] **[P2] `start` / `stop` / `restart` / `volume` are declared in the protocol type and unimplemented**
      ([websocket.ts:76](op25/gr-op25_repeater/www/app/src/types/websocket.ts#L76)). Decide whether the
      server gains them or the type shrinks to `quit | mute | unmute`.

## 4. Backend commands with no implementation anywhere (both stacks)

- [x] **[P2] `set_full_config` is a stub.** [multi_rx.py:909-911](op25/gr-op25_repeater/apps/multi_rx.py#L909-L911)
      replies `ok` and does nothing, so the legacy `ConfigDialog.tsx` "save config" cannot work. Either
      implement config write-back or remove the command and the dialog claim.
- [x] **[P2] `dump_tracking` has no handler at all.** Sent by both legacy UIs
      ([main.js:1738](https://github.com/AStoker/op25/blob/3b7d4d49d48b379495992dcbea5b57f5c3941d00/op25/gr-op25_repeater/www/www-static/main.js#L1738),
      [react-app-legacy/src/App.tsx:600](https://github.com/AStoker/op25/blob/3b7d4d49d48b379495992dcbea5b57f5c3941d00/op25/gr-op25_repeater/www/react-app-legacy/src/App.tsx#L600)) and documented in
      [www/react-app-legacy/AGENTS.md:116](https://github.com/AStoker/op25/blob/3b7d4d49d48b379495992dcbea5b57f5c3941d00/op25/gr-op25_repeater/www/react-app-legacy/AGENTS.md#L116) as "Log tracking
      state". No matching branch in `multi_rx.py` or `rx.py`. Documented capability that never existed.
- [x] **[P3] `set_freq` and `add_default_config` are curses-only.** Bound at
      [terminal.py:216,234](op25/gr-op25_repeater/apps/terminal.py#L216-L234) but only handled by
      [rx.py:959,971](op25/gr-op25_repeater/apps/rx.py#L959-L971). Under `multi_rx.py` those keystrokes
      are silently ignored — worth either implementing or noting in the curses help line.
- [x] **[P1] DMR/Connect+ trunking ignores every UI command.**
      [tk_trbo.py:156-157](op25/gr-op25_repeater/apps/tk_trbo.py#L156-L157) is
      `def ui_command(self, msg): pass  # TODO`. So hold/skip/lockout/whitelist/reload do nothing on
      Connect+ systems, in both the old and new GUI.

## 5. Browser audio: divergence from upstream's advertised design

Upstream's browser audio ("Awesome new HTTP based terminal … **with websocket audio**", README-browser-audio.md)
uses a `ws://host:port` entry in the channel `destination`, served by the C++ sink
(`lib/op25_audio.cc` + bundled `websocketpp`), one WS port per channel, with a per-channel headphones
toggle and a "Mute Browser Audio at Startup" setting. Our stack re-streams UDP as one mixed
`/api/stream` instead.

- [x] **[P1] Per-channel audio selection is missing.** `_discover_audio_ports()`
      ([websocket_server.py:500-560](op25/gr-op25_repeater/apps/websocket_server.py#L500-L560)) collects
      every channel's UDP ports into a single stream; a multi-channel config plays all channels mixed
      with no way to pick one. Upstream's UI mutes/unmutes per channel.
- [x] **[P1] `ws://` destinations are ignored by the new stack.** A user who follows
      `README-browser-audio.md` (`"destination": "ws://0.0.0.0:9000"`) gets no browser audio unless they
      also add a `udp://` destination. Either consume `ws_instance`
      ([multi_rx.py:197](op25/gr-op25_repeater/apps/multi_rx.py#L197)) or state the difference in the docs.
- [x] **[P3] `/api/stream` `rate`/`format` query params are not exposed in the UI**
      ([PlayerCard.tsx:17](op25/gr-op25_repeater/www/app/src/components/PlayerCard/PlayerCard.tsx#L17)
      hardcodes `/api/stream`).

## 6. Non-P25 modes: advertised, but the new UI shows almost nothing

The UI never branches on `TrunkSystem.type`
([op25.ts:55](op25/gr-op25_repeater/www/app/src/types/op25.ts#L55)); every card is written against the
P25 payload shape.

- [x] **[P1] SmartNet/SmartZone.** `tk_smartnet`'s `to_json` emits only
      `type, system, top_line, nac, secondary, frequencies, frequency_data, patch_data, adjacent_data,
      last_tsbk` — no `syid/rfid/stid/sysid/rxchan/txchan/wacn/band_plan/wuid_data/tgid_tags`. So
      Site Information, Band Plan and Subscribers render blank/garbage on a SmartNet system even though
      "Motorola SmartZone Trunking" is a headline capability. Needs either UI branching or richer
      payload (README-smartnet.md is the reference).
- [x] **[P1] Connect+ / DMR.** [tk_trbo.py:85-95](op25/gr-op25_repeater/apps/tk_trbo.py#L85-L95) returns
      an essentially empty system dict (`system: "tk_trbo"`, empty freq/adjacent maps, `last_tsbk: 0`),
      so the whole System tab is empty for DMR. See also §4 (no UI commands).
- [x] **[P1] DMR slot is never displayed.** `call_log` carries `slot`
      ([op25.ts:113](op25/gr-op25_repeater/www/app/src/types/op25.ts#L113)) and slot B audio arrives on
      `port+1`, but no card shows which slot a call was on — for a two-slot DMR system the call history
      is ambiguous.
- [x] **[P2] TGID priority is not surfaced.** "TGID Priority with mid-call preemption" is advertised and
      `call_log.prio` is on the wire; nothing renders it, and there is no UI to change it.
- [x] **[P2] NBFM analog is a single chip.** `ChannelsCard` shows only `analog`/`digital`
      ([ChannelsCard.tsx:309](op25/gr-op25_repeater/www/app/src/components/ChannelsCard/ChannelsCard.tsx#L309)).
      No squelch state, deviation or squelch-mode display (README-analog.md).
- [x] **[P2] Encryption state is under-reported.** Decoder-side support exists for `crypt_keys` /
      `crypt_behavior` ([multi_rx.py:187-248](op25/gr-op25_repeater/apps/multi_rx.py#L187-L248)) and
      `tk_p25` publishes `encryption_algid`, `network_active` (failsoft) and `lra`
      ([tk_p25.py:1923-1925](op25/gr-op25_repeater/apps/tk_p25.py#L1923-L1925)) — none of which appear in
      `TrunkSystem` or any card. The UI shows only a per-channel `encrypted` boolean, so a user cannot
      see algid/keyid, whether a key matched, or whether the site is running failsoft.

## 7. Upstream code we have not merged (`upstream/dev`, since `b2e04c3f`)

`upstream/master` is fully merged; `upstream/dev` is 12 commits ahead and carries real features.

- [x] **[P1] NBFM noise & voice squelch (PA3FWM / DB1NV).** New `apps/squelch_core.py`,
      `apps/op25_squelch.py`, changes to `apps/op25_nbfm.py` + `apps/multi_rx.py`, tests
      (`squelch_core_test.py`, `squelch_gr_test.py`), and the expanded `README-analog.md` config keys:
      `nbfm_squelch_mode` (`power|noise|voice`), `nbfm_noise_squelch_db`, `nbfm_noise_squelch_hang`,
      `nbfm_noise_squelch_ref`. Ours still documents only `nbfm_squelch`.
- [x] **[P1] Gate LDU2 audio on newly received AlgId when skipping encrypted calls** —
      `lib/p25p1_fdma.cc` (+10). Fixes a burst of encrypted audio leaking through `crypt_behavior=2`.
- [x] **[P2] "Tolerate empty module names in audio/metadata/terminal config sections"** (`multi_rx.py`).
      Cheap robustness fix for configs with `"module": ""`.
- [x] **[P3] `field-test/` kit** (11 files: NBFM squelch field-test harness, config renderer, analyzers).
      Decide whether to carry it — it is upstream's calibration tooling for the squelch work above.
- [x] **[P3] Upstream README updates** — capability list now says "…HTTP based terminal … with websocket
      audio" plus a W1JPI squelch section. Our README has diverged (see §8).

## 8. Documentation that no longer matches the code

- [x] **[P1] `README.md` advertises the wrong protocol doc for this branch.** Our README's
      "HTTP / WebSocket Communication" section points at `README-websockets.md`, which documents the
      **legacy** stack (control WS on HTTP port+1, HTTP POST fallback, `http_server.py`/waitress).
      `websocket_server.py` is single-port, `/ws`, no POST fallback. A reader following that doc will
      configure the wrong thing.
- [x] **[P1] `README.md` does not advertise this fork's actual capabilities.** Nothing about the
      React/Vite SPA + FastAPI stack, macOS/Apple-Silicon support with the PortAudio backend, or
      `ha_bridge.py` call capture / speech-to-text / Home Assistant integration. Capability lists are
      still upstream's.
- [x] **[P2] `README-browser-audio.md` describes a mechanism the new UI does not implement** (ws://
      destinations, per-channel headphone toggle, "Mute Browser Audio at Startup"). Needs a "new stack"
      section or an explicit note.
- [x] **[P2] `www/app/AGENTS.md` is thin; the new protocol is documented only in `CLAUDE.md`.**
      The detailed reference
      ([www/react-app-legacy/AGENTS.md](https://github.com/AStoker/op25/blob/3b7d4d49d48b379495992dcbea5b57f5c3941d00/op25/gr-op25_repeater/www/react-app-legacy/AGENTS.md))
      describes the legacy stack and includes at least
      one command that does not exist (`dump_tracking`, §4).
- [x] **[P3] `apps/README.md` "HTTP Console" section covers only `rx.py -l http:…`.** No mention of
      `terminal_type: "ws:host:port"` or that the new GUI is `multi_rx.py`-only
      (`rx.py` hardcodes `from terminal import op25_terminal` at
      [rx.py:88](op25/gr-op25_repeater/apps/rx.py#L88) and special-cases `http:` at
      [rx.py:784,914](op25/gr-op25_repeater/apps/rx.py#L784)).

## 9. Housekeeping / smaller dead ends

- [x] **[P2] `/api/config` is never fetched.** Endpoint at
      [websocket_server.py:878](op25/gr-op25_repeater/apps/websocket_server.py#L878); comments in
      [op25Service.tsx:27](op25/gr-op25_repeater/www/app/src/services/op25Service.tsx#L27) and
      [multi_rx.py:665](op25/gr-op25_repeater/apps/multi_rx.py#L665) claim it is the config source, but
      the app uses `get_full_config` over the WebSocket. Fix the comments or use the endpoint.
- [x] **[P2] `/api/ha/status` has no UI surface.** It is documented as the place to start HA
      troubleshooting; the UI only renders clips/transcripts
      (`TranscriptsCard`), with no indication of whether STT is configured, reachable, or failing.
- [x] **[P3] Empty leftover component directories:** `www/app/src/components/FrequenciesCard/` and
      `www/app/src/components/TalkGroupsCard/` contain no files (that content now lives in
      `SiteInfoCard` and `ChannelsCard`). Delete them.
- [x] **[P3] No tuning/quality feedback in the UI.** `ChannelStatus` carries `ppm`, `error`
      (AFC freq error in Hz) and `capture`
      ([op25.ts:96-101](op25/gr-op25_repeater/www/app/src/types/op25.ts#L96-L101)); no card displays any
      of them, which is also why the missing `adj_tune` control (§1) would currently be flying blind.
- [x] **[P3] Carry-overs already known in `CLAUDE.md`** — restated here so they live in one checklist:
      `www/dist` is a committed build artifact that drifts; `call_log` is a draining delta feed so a
      late-connecting client loses history permanently; `gains` values must be integers
      ([multi_rx.py:150](op25/gr-op25_repeater/apps/multi_rx.py#L150)); nothing verified on Raspberry Pi 5.

## 10. Upstream roadmap items (tracking only — not fork regressions)

- [ ] Demodulator improvements to speed up channel lock-time.
- [ ] Additional encryption algorithms (today: ADP/RC4 `0xAA`, DES-OFB `0x81`, AES `0x84` —
      `lib/op25_crypt_{adp,des,aes}.cc`).
- [x] ~~Fork-specific PRs upstream go to boatbod's `dev` branch; keep the new-stack work reviewable
      separately from upstream syncs.~~ **Retired 2026-08-05.** No longer true: the fork
      deliberately deleted `rx.py`, `trunking.py`, `p25_decoder.py`, `http_server.py`, the `ws://`
      C++ audio transport and the vendored `websocketpp`/`asio` trees. The current merge policy
      and the remaining mergeable surface are documented in `CLAUDE.md`.
