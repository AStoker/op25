# OP25 React GUI — agent reference

Architecture and conventions for the **current** OP25 web UI. Read this before
changing anything here.

The full server/protocol reference is [`README-new-gui.md`](../../../../README-new-gui.md)
at the repo root; this document covers the frontend.

This is the only web UI in the tree. The older `react-app-legacy/` +
`www-static/` GUI and its `http_server.py` waitress backend were removed.

---

## Layout

```
app/                        ← this directory
  src/
    App.tsx                 root layout: tabs below md, two columns at md+
    main.tsx                ReactDOM entry
    services/
      websocketService.tsx  the /ws connection, reconnect, subscribe()/send()
      op25Service.tsx       decoder state + every control action (the hub)
      themeService.tsx      light/dark, follows prefers-color-scheme then localStorage
    hooks/
      useAudioStream.ts     Web Audio playback of /api/stream
      useAudioSources.ts    /api/audio/channels — selectable streams
      useSystemState.ts     the SYSTEM_STATE health payload
      useIsPhone.ts         drop low-value table columns below sm
      useTalkgroupFocus.ts  pinned talkgroups (on the receiver, via useUiState)
      useTalkgroupFilters.ts  the browser's saved search patterns, likewise
      useConfigEditor.ts    the config REST client + flattened-path helpers
    components/<Name>Card/  one card per panel, all wrapped in CardShell
    components/ConfigDialog/  Config modal: the editor, runtime knobs, display prefs
      SettingsTab.tsx         schema-driven form; edits held local until Save
      TranscriptionTab.tsx    the transcription section + what the bridge is doing
      ConfigFieldInput.tsx    one control, rendered from a server field description
      AdvancedJsonTab.tsx     raw JSON, plus reset-to-preset and export
      HistoryTab.tsx          versions, field diffs, rollback
    components/AboutDialog/   About modal: what this fork is, how it differs upstream
    components/TalkgroupBrowser/  pick talkgroups from the full list: patterns + batch
    components/common/      the design-system primitives (see below)
    utils/systemKind.ts     P25 / SmartNet / Connect+ branching + safe formatters
    utils/lastSeen.ts       relative last-heard / frequency formatting
    utils/talkgroupPatterns.ts  contains/starts/exact/wildcard/regex matching
    types/op25.ts           decoder payload shapes
    types/websocket.ts      envelope + upstream/downstream unions
  vite.config.ts            builds to ../dist
```

## Build

```bash
cd app/
yarn install     # first time
yarn build       # tsc -b && vite build → ../dist
yarn dev         # Vite dev server, proxying /api and /ws to 127.0.0.1:8080

# …or against the decoder on whichever box has the dongle. The browser still only
# talks to localhost:5173, so this needs no CORS and no dev-only server code.
OP25_BACKEND=http://homeassistant.local:8099 yarn dev
```

That port is **unauthenticated** (the add-on's ingress is the authenticated path),
so it is a trusted-LAN convenience, not a way to expose OP25.

`../dist` is a **committed build artifact**. It can drift from `src/` — rebuild
before testing, or you will be looking at old code and drawing wrong
conclusions.

---

## Design system

Sizing lives in the **theme** (`services/themeService.tsx`), not in components.
A component that restates a size is a bug waiting to drift.

- `CONTROL_HEIGHT` (32px) is the height of every interactive control — button,
  input, select, toggle, and a small icon button holding a `fontSize="small"`
  icon. MUI's own `size="small"` disagrees with itself (a 40px outlined input
  against a 32px button), which is why the TGID and filter boxes used to sit a
  head taller than the buttons next to them. Change the token, not a component.
- `size="small"` is the **default** for Button, ButtonGroup, ToggleButton(Group),
  TextField, Select and Chip. Don't pass it.
- Buttons and toggles are sentence case (`textTransform: none`), so are Tabs.
- Chips are 22px — deliberately smaller than a control, because they are labels,
  not things you click. Chip icons are scaled by the theme; don't set
  `sx={{ fontSize }}` on them.
- Tooltips default to `arrow` with a 400ms delay.

**No floating input labels anywhere.** A label inside the box has to grow the
box, and it disagrees with the caption-above-value pattern every read-only field
already uses. Instead:

| Need | Use |
|---|---|
| Labelled control | `common/Field` — caption above, optional one-line `hint`/`error` below |
| Read-only labelled value | `common/InfoRow` — same shape, plus `tooltip` for radio jargon |
| A row of controls | `common/ControlRow` — one gap, one wrap rule, one alignment |
| Heading inside a card | `common/SectionHeading` — `title` + muted `meta` + right-aligned `action` |
| Note under a control | `common/Hint` (what `Field` renders internally) |
| Repeated outlined tile | `common/InsetPanel` — `highlight` for a keyword hit |
| Filter box in a heading | `common/SearchField` — magnifier, placeholder, clear button |
| A modal panel | `common/DialogShell` — the dialog's `CardShell`: title, close button, full-screen below `sm` |

Never use `helperText=" "` to reserve a line: that is what made the TGID field
taller than its buttons whether or not it had anything to say. Put the message
in a `Hint` under the whole row, where appearing and disappearing costs the row
nothing.

---

## How state flows

1. `websocketService` owns the single `/ws` connection and exposes
   `subscribe(cb)` / `send(msg)` / `status`.
2. `op25Service` subscribes once, routes frames by `type` and inner `json_type`,
   and holds all decoder state: `systems`, `channels`, `callLog`, `callClips`,
   `plots`, `config`, `terminalConfig`.
3. Components read state through `useOp25Service()`, `useSelectedChannel()` and
   `useSelectedSystem()`. They do not talk to the WebSocket directly.
4. Every control action is a method on the service (`holdTalkGroup`,
   `adjustTune`, `setLogLevel`, `toggleCapture`, `reloadLists`, …), which wraps
   `CALL_CONTROL`. Add new commands there, not in components.

`arg2` on a `CALL_CONTROL` command is the channel msgqid; the service resolves
it from the selected channel.

A command whose argument is a **list** cannot use `arg1`/`arg2` — a `gr.message`
carries two floats. `setScanList` therefore sends `{command, msgqid, tgids}` and
the server forwards the whole payload as JSON (see README-new-gui.md). Any
`CALL_CONTROL` field beyond `command`/`arg1`/`arg2` triggers that.

---

## Where a setting goes

The header's `Config` and `About` entries are modals, not routes — there is one
page here. `AppShell` owns which one is open.

- **Config → Decoder** is for anything global to the decoder. Log level lives
  here and not in `ReceiverCard` because `set_debug` fans out to every channel,
  device and trunking module (`multi_rx.py:616`); the rest of the tab is the
  read-only startup picture, since `multi_rx` reads its JSON once and takes only
  `-c` / `-v` / `-p` / `-d` on the command line, of which just `-v` is live.
- **Config → Interface** is for browser preferences (theme, accent colour, smart
  colours) — localStorage only, never sent to the decoder. This is where the
  AppBar gear menu went; the theme icon in the header stays as a shortcut.
- **Config → Running config** is the loaded JSON, read-only (`set_full_config`
  answers with an error, by design).
- **A dashboard card** is for anything you watch or act on per channel. If it is
  not worth a glance during normal operation, it belongs in a dialog.

## Things that will bite you

- **System types.** `tk_p25`, `tk_smartnet` and `tk_trbo` publish different
  fields, and each omits what does not apply. Reading `system.wacn.toString(16)`
  on a SmartNet snapshot throws. Branch with `systemKind()` and format with
  `hexOrDash` / `numOrDash` / `freqOrDash` from `utils/systemKind.ts`.
- **`call_log` is a draining delta feed.** Clients must accumulate. The server
  replays a 200-entry ring on connect (`replay: true`), which covers a late
  join but not calls from before the server started.
- **`ChannelStatus.error` is frequency error in Hz** (an AFC figure), not a bit
  error rate. Label it accordingly; OP25 does not surface BER to Python.
- **Virtuoso tables use `tableLayout: fixed`.** The percentage widths in
  `fixedHeaderContent` must be kept in step with the cells `rowContent`
  actually renders, including the phone/desktop branches.
- **Plot state lives in the decoder** and survives a page reload, so the service
  adopts any mode it sees data for. Without that, a reload leaves the toggle
  dark while data streams and the next click switches the decoder off.
- **Muting is client-side.** Stopping the Web Audio path stops pulling
  `/api/stream`; there is no mute command, and `SYSTEM_CONTROL` only accepts
  `quit`.
- **Last-heard comes from `tgid_tags`, never from `frequency_data`.** The latter
  lists a talkgroup against a frequency only while its call is up (one second), so
  a column fed from it can only ever say "Now" or nothing — which is exactly the
  bug that was there. `tgid_tags[tgid].last_seen` is a raw epoch (0 = never);
  format with `utils/lastSeen.ts` and sort on the number.
- **Pinning and the scan list are different things.** `useTalkgroupFocus` is
  receiver-side state that only sorts/filters the table. `setScanList` stops the
  decoder receiving anything else, so it must stay behind an explicit action —
  never wire it to a selection change.
- **The Talkgroup Browser freezes its list while open** on purpose (`systems` is
  not a loader dependency). Re-sorting it as traffic arrives is the problem it
  exists to solve.
- **Its filter is a list of patterns OR'd together**, each with its own rule
  (`utils/talkgroupPatterns.ts`). `guessKind` preselects the rule from what was
  typed, because `RCHP*` read as a substring matches nothing and looks like a
  broken filter rather than the wrong rule. Chips carry a match count — a
  pattern matching nothing is invisible inside a union — and a pattern that will
  not compile is shown as a red chip, never silently dropped and never silently
  matched. Saved in `ui_state.talkgroup_filters`.
- **An invalid pattern must show everything else**, not nothing: most keystrokes
  in a regex are a syntax error in progress.
- **Sortable columns default to Calls descending there**, because the question
  that decides a selection is which talkgroups carry traffic. Selected rows are
  deliberately *not* floated to the top as they are on the dashboard — the row
  would move out from under the pointer that is ticking it.
- **Responsive.** Below `md` the layout is tabs (Live / Audio / System /
  Signal); at `md`+ it is the two-column dashboard. Verify with CDP at
  390 / 820 / 1440 px and check
  `document.documentElement.scrollWidth > clientWidth` — horizontal overflow is
  the failure that matters. Use real `asyncio.sleep()` waits, never
  `--virtual-time-budget`, which outruns the WebSocket handshake and shows a
  frozen "connecting" state.


---

## The config editor

`ConfigDialog`'s Settings / Transcription / Advanced JSON / History tabs render
from `/api/config/schema` — **no field is named in this codebase**. Adding a
protocol is a matter of describing its fields in `apps/config_schema.py`, which
is what makes this a scanner UI rather than a P25 UI.

- **One `useConfigEditor` instance is shared by every editing tab** (created in
  `ConfigDialog`). Several copies would each re-fetch and then disagree about
  what was saved.
- It is **not** part of `op25Service`. That service is live decoder state
  arriving at 1 Hz; folding a REST resource into it would re-render the app every
  second for a panel nobody has open. The hook only loads while the dialog is on
  a tab that needs it.
- **Edits are held in local draft state until Save**, so a half-typed frequency
  is never sent and the recorded version is one deliberate change set rather than
  one per keystroke.
- **Field status is icons, not text chips**, with `FieldLegend` naming them once
  at the top. Every field carries at least one badge, so "restart" repeated down
  a column of twenty fields buries the labels it is attached to.
- **Overridden fields get a per-field reset**, whose tooltip names the preset
  value it would restore. It needs no server support: writing the preset value
  back is enough, because `prune_overlay` drops anything equal to the base. When
  the preset has no such key, `undefined` removes it from the submitted JSON,
  which has the same effect.
- **`overridden` is computed against the saved overlay, not the draft.** An
  unsaved edit is already covered by the dirty count; flagging it as an override
  would claim something is stored that is not.
- **An unset field shows the schema's `default`, not blank/off.** A switch
  reading "off" for something that is on (`call_recording`) invites the user to
  turn it on and store an override that changes nothing. The default is
  displayed, never submitted — the overridden badge still says whether a value is
  actually stored.
- **Which sections get their own tab is the server's call**, not this file's:
  `schema.standalone_sections` lists them and `SettingsTab`'s `only` prop renders
  them. `TranscriptionTab` is that form plus a *Running now* panel from
  `/api/ha/status`, because between a save and a restart the config and the
  running bridge disagree — and the pinned-talkgroup scope is live while the
  scope setting itself is not, which needs saying on screen.
- **Fields with a `group` get a sub-heading inside their section.** A section big
  enough to need it (transcription) otherwise reads as one undifferentiated grid.
- **Floats are trimmed to the schema's `precision`.** `adj_tune` works in
  fractional ppm and produces `2.3749999999999996`; at 859 MHz the smallest
  tuning step is ~0.116 ppm, so the extra digits are below what the hardware can
  act on. Rounding happens on save (server, `config_schema.round_floats`), at
  input (`trimFloat`), and in the drift report — the last because an overlay
  written before rounding existed still holds the long value.
- **Every field shows `live` or `restart`**, from the schema. Being optimistic
  there is the dangerous direction — the user would trust a value the decoder is
  not running — so the server classifies each save and the banner reports
  `needs_restart` with a Restart add-on button.
- `readPath` / `writePath` / `splitPath` handle the server's flattened paths
  (`devices[sdr0].gains`). **`splitPath` ignores dots inside brackets** because a
  device may be called `base.station`; the Python side has the same rule for the
  same reason.
- The raw editor is a plain `TextField multiline`, not CodeMirror or Monaco:
  ~300 kB of bundle for syntax colouring on a UI that loads over ingress on a
  phone, when the thing that actually catches mistakes is the server's
  validation, which runs either way.
- `PersistTuningButton` (in `ReceiverCard`) is why fine tuning now survives a
  restart. `adj_tune` moves ppm in the running decoder and nothing wrote it back,
  so every restart reverted to the config value. The button does the whole
  read-modify-write against `/api/config` because the server does not know the
  live ppm — it arrives in `channel_update`, which only the browser sees.
