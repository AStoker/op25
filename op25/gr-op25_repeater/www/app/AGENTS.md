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
    components/<Name>Card/  one card per panel, all wrapped in CardShell
    components/common/      the design-system primitives (see below)
    utils/systemKind.ts     P25 / SmartNet / Connect+ branching + safe formatters
    types/op25.ts           decoder payload shapes
    types/websocket.ts      envelope + upstream/downstream unions
  vite.config.ts            builds to ../dist
```

## Build

```bash
cd app/
yarn install     # first time
yarn build       # tsc -b && vite build → ../dist
yarn dev         # Vite dev server
```

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

---

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
- **Responsive.** Below `md` the layout is tabs (Live / Audio / System /
  Signal); at `md`+ it is the two-column dashboard. Verify with CDP at
  390 / 820 / 1440 px and check
  `document.documentElement.scrollWidth > clientWidth` — horizontal overflow is
  the failure that matters. Use real `asyncio.sleep()` waits, never
  `--virtual-time-budget`, which outruns the WebSocket handshake and shows a
  frozen "connecting" state.
