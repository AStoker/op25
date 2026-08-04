# OP25 React GUI — agent reference

Architecture and conventions for the **current** OP25 web UI. Read this before
changing anything here.

The full server/protocol reference is [`README-new-gui.md`](../../../../README-new-gui.md)
at the repo root; this document covers the frontend.

Do not confuse this app with `../react-app/`, the older GUI that targets
`http_server.py` and builds to `../www-static/`. Both stacks are present in the
tree and are selected by the `terminal` block of the multi_rx JSON config.

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
