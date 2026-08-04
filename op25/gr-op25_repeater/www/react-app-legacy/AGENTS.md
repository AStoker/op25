# OP25 React GUI — Agent Reference (LEGACY)

> **This is the legacy GUI.** It builds to `../www-static/` and is served by
> `http_server.py` (waitress, two ports) when the config says
> `"module": "terminal.py", "terminal_type": "http:host:port"`.
>
> The **current** GUI is `../app/`, which builds to `../dist/` and is served by
> `websocket_server.py` on a single port. See `../app/AGENTS.md` and
> `README-new-gui.md` at the repo root.
>
> Kept because the `http:` terminal and the curses terminal still work and are
> still supported. Sections below describing `json_type` shapes remain the best
> reference for the underlying `multi_rx.py` messages, which both stacks share.

This document describes the full architecture, server protocol, and implementation conventions for the OP25 React GUI. Read this before making changes to avoid unnecessary exploration turns.

---

## Project Layout

```
react-app-legacy/               ← this directory
  src/
    App.tsx              ← root component; all state, polling, response dispatch
    main.tsx             ← ReactDOM.createRoot entry
    types.ts             ← ALL TypeScript interfaces (canonical source of truth)
    theme.ts             ← buildTheme(accentColor) → MUI dark theme
    hooks/
      useAudio.ts        ← WebSocket audio hook (PCM streaming)
    components/
      NavBar.tsx         ← AppBar: settings/config/about buttons, connection status
      MainDisplay.tsx    ← Current freq/system/talkgroup/encryption/audio button
      ChannelControls.tsx← Scan/Hold/Lockout/Whitelist/GoTo/Tune/Capture buttons
      TalkgroupPanel.tsx ← Preset buttons + recently-seen TG buttons
      FrequencyTable.tsx ← Per-NAC system info, freq table, band plan, adj sites, patches
      ChannelTable.tsx   ← Multi-channel list with status
      CallHistory.tsx    ← Filterable call log table, CSV export
      SubscriberTable.tsx← Sortable/filterable subscriber (radio) tracking table
      SettingsDialog.tsx ← All user settings including remote server URL
      ConfigDialog.tsx   ← Read-only full config viewer (from server)
      AboutDialog.tsx    ← About / GPLv3 info
  index.html             ← Vite dev-server entry (not the served file in production)
  vite.config.ts         ← Build config (see CRITICAL constraint below)
  package.json
  tsconfig.json / tsconfig.app.json / tsconfig.node.json
```

The Python server that serves the built files is at:
```
../../../apps/http_server.py   (relative to react-app-legacy/)
```

---

## Build

```bash
cd react-app-legacy/
yarn install     # first time
yarn build       # tsc -b && vite build → outputs to ../www-static/
yarn dev         # Vite dev server (proxies nothing; see remote server section)
```

### CRITICAL: Flat Output Constraint

`http_server.py` sanitises request paths with:
```python
filename = re.sub(r'[^a-zA-Z0-9_.\-]', '', environ['PATH_INFO'])
```
This **strips `/`**, so the server cannot serve files in subdirectories. Every built file must land flat in `www-static/`. The Vite config enforces this:

- `assetsDir: ''` — no `assets/` subfolder
- `entryFileNames: 'op25-react.js'`
- `chunkFileNames: 'op25-[name]-[hash].js'`
- `assetFileNames`: CSS → `op25-react.css`
- `manualChunks` names use **only** `[a-zA-Z0-9_.-]` characters (no slashes, no `@`, no colons)

**Never** add chunk names, import aliases, or asset paths that contain `/`, `@`, `:`, or other characters stripped by the regex.

---

## HTTP Communication Protocol

### Request

The GUI communicates with the server exclusively via a single `POST /` endpoint. All requests are JSON arrays of command objects:

```json
[
  { "command": "update",             "arg1": 0,    "arg2": 1 },
  { "command": "hold",               "arg1": 1234, "arg2": 1 },
  { "command": "get_terminal_config","arg1": 0,    "arg2": 0 }
]
```

`arg1` and `arg2` are always numbers. For commands targeting a channel, `arg2` is the channel index (from `channelList`).

### Response

The server replies with a JSON array of response objects. Each has a `json_type` discriminator field:

```json
[
  { "json_type": "channel_update", ... },
  { "json_type": "trunk_update",   ... }
]
```

### Polling

`App.tsx` sends one `update` command per second via `setInterval`. On startup it also sends `get_terminal_config`, `get_full_config`, and `get_ws_instances`.

### Command Reference

| Command | arg1 | arg2 | Effect |
|---|---|---|---|
| `update` | 0 | channel index | Triggers server to flush pending responses |
| `get_terminal_config` | 0 | 0 | Returns `terminal_config` response |
| `get_full_config` | 0 | 0 | Returns `full_config` response |
| `get_ws_instances` | 0 | 0 | Returns `ws_instances` response |
| `hold` | tgid | channel | Hold on talkgroup (0 = release) |
| `whitelist` | tgid | channel | Add tgid to whitelist |
| `skip` | 0 | channel | Skip (scan past) current talkgroup |
| `lockout` | tgid | channel | Lockout (blacklist) talkgroup |
| `adj_tune` | Hz offset | channel | Adjust frequency offset |
| `capture` | 0 | channel | Toggle IQ capture |
| `dump_tgids` | 0 | channel | Log talkgroups, patches, wuids and rids to server console |
| `dump_buffer` | -1 | channel | Force buffer dump |
| `set_debug` | level (0–10) | channel | Set log verbosity |
| `toggle_plot` | plot type (cast as number) | channel | Toggle gnuplot |
| `reload` | 0 | channel | Re-read blacklist/whitelist files |
| `set_freq` | Hz | channel | Retune the channel (`rx.py`, and `multi_rx.py` as of this fork) |

**Not a command:** earlier revisions of this table listed `dump_tracking`, and
both legacy UIs sent it. Neither `rx.py` nor `multi_rx.py` has ever had a
handler for it, so it was always a no-op; the sends have been removed.

"Hold on talkgroup" requires sending `whitelist` first then `hold` — see `holdTalkgroup()` in `App.tsx`.

---

## Response Types

All TypeScript interfaces are in `src/types.ts`. Key ones:

### `terminal_config`
```typescript
{ smart_colors, terminal_interface, tuning_step_large, tuning_step_small, default_channel }
```
Contains keyword→colour mappings for smart colour highlighting.

### `channel_update`
```typescript
{ channels: ChannelData[] }
```
Array of all receiver channels with current tgid, frequency, tag, mode, hold/capture state, error offset.

### `trunk_update`
```typescript
{ nac?, srcaddr?, grpaddr?, encrypted?, emergency?, [nacKey: string]: NacData }
```
Top-level fields are current active call info. All numeric-keyed fields are `NacData` objects, one per NAC being tracked. `NacData` contains:
- `system`, `type` (`'p25'`|`'smartnet'`), `callsign`, `sysid`, `wacn`, `nac`, `rfid`, `stid`
- `frequency_data`: `Record<freqHz, FrequencyEntry>` — per-frequency activity
- `band_plan`: P25 band plan entries
- `adjacent_data`: Adjacent site list
- `patch_data`: Talkgroup patches
- `wuid_data`: Subscriber (radio) affiliations

`FrequencyEntry` has `tgids[2]`, `tags[2]`, `srctags[2]`, `srcaddrs[2]` for TDMA slot 0 and slot 1. For FDMA only slot 0 is populated.

### `change_freq`
```typescript
{ freq, system, tgid, tag, stream_url, nac? }
```
Sent when the active channel tunes to a new frequency/talkgroup. `stream_url` is the Icecast/Liquidsoap stream URL if configured.

### `rx_update`
```typescript
{ files, error?, fine_tune? }
```
Incremental receiver status (frequency error in Hz).

### `ws_instances`
```typescript
{ json_type: 'ws_instances', [channelKey: string]: string | null }
```
Maps channel keys to WebSocket audio endpoint URLs. Keys are arbitrary strings matching channel identifiers.

### `call_log`
```typescript
{ log: CallLogEntry[] }
```
Voice grant log entries used when `callHistorySource === 'voice'`.

### `full_config`
```typescript
{ json_type: 'full_config', trunking?: { chans: [...] }, ...rest }
```
Full trunking config including presets and site aliases.

---

## WebSocket Audio

`useAudio(wsEndpoints, muteAtStartup, serverUrl)` in `src/hooks/useAudio.ts`:

- Endpoints come from the `ws_instances` server response
- Audio is raw **Int16 PCM at 8000 Hz**, mono, little-endian
- One `WebSocket` per channel; binary frames are PCM chunks
- JSON text frames: `{ "cmd": "audio_drain" }` or `{ "cmd": "audio_drop" }` flush the buffer
- `AudioContext` must be created on a user gesture — call `initAudioCtx()` before the first `toggleAudio()`. `MainDisplay` handles this on the audio toggle button click.
- Reconnects automatically after 3 s on `ws.onclose`

### URL Rewriting

WebSocket URLs from the server may contain `0.0.0.0` or `127.0.0.1`. The hook rewrites:
- If `serverUrl` is configured: replaces hostname and port with those from `serverUrl`
- Otherwise: replaces `0.0.0.0`/`127.0.0.1` with `window.location.hostname`

---

## Remote Server Support

`settings.serverUrl` (stored in `localStorage` as part of `op25-react-settings`) sets the base URL of the OP25 HTTP server. When empty the same origin is used.

- **HTTP**: `processQueue` in `App.tsx` builds the endpoint as `serverUrl.replace(/\/+$/, '') + '/'`
- **WebSocket**: `useAudio` rewrites WS hostname/port to match `serverUrl`
- **CORS**: `http_server.py` includes `CORS_HEADERS` on all responses and handles `OPTIONS` preflight with `204 No Content`. To restrict to a specific origin, change `'*'` in `CORS_HEADERS` in `http_server.py`.

---

## State Management Patterns

### Stale Closure Prevention

The polling `setInterval` runs with an empty dep array (`[]`) so it never re-registers. To avoid stale closures, all mutable values it needs are accessed through refs that are updated every render:

```typescript
const channelListRef = useRef([]);
channelListRef.current = channelList;  // updated each render

const sendCommandRef = useRef(sendCommand);
sendCommandRef.current = sendCommand;  // updated each render

const serverUrlRef = useRef(settings.serverUrl);
serverUrlRef.current = settings.serverUrl;  // updated each render
```

`processQueue` reads `serverUrlRef.current` (not `settings.serverUrl` directly) for the same reason — it has an empty dep array.

### TG Tag Cache

`tgTagCacheRef` is a `useRef<Record<sysHex, Record<tgid, TgCacheEntry>>>` — a non-reactive cache of talkgroup names accumulated across all `trunk_update` responses. It is read directly (not via state) to avoid triggering unnecessary re-renders. The `TalkgroupPanel` component receives it as a prop snapshot.

### Call History Deduplication

`callHistorySeenRef` tracks `sysHex|freq|tgid|src` → `epochMs` for the last 5 seconds (`MAX_HISTORY_SECONDS`). Entries seen within that window are not duplicated in the call history table.

### Settings Persistence

All settings are stored in `localStorage` under the key `op25-react-settings` as a JSON object. `loadSettings()` merges from `DEFAULT_SETTINGS` so new fields added to `Settings` always have a fallback value.

---

## Adding New Server Commands

1. Add the command string to the table above and call `sendCommand(cmd, arg1, arg2)` — the queue and HTTP transport are handled automatically.
2. If it generates a new response type: add the interface to `types.ts`, add it to the `ServerResponse` union, add a `case` in the response dispatcher switch in `App.tsx`, and write a handler.

## Adding New Settings

1. Add the field to the `Settings` interface in `types.ts`.
2. Add a default value in `DEFAULT_SETTINGS` in `App.tsx`.
3. Add a UI control in `SettingsDialog.tsx` — use `onUpdate('fieldName', value)`.
4. No migration needed: `loadSettings()` merges over defaults.

## Adding New Components

- Props flow down from `App.tsx`; no context API or global store is used.
- Callbacks (e.g. `onHold`, `onLockout`) are stable `useCallback` functions from `App.tsx`.
- Smart colour helpers exist in each component locally — they are simple keyword-match loops on the `smartColors` array.
- Use MUI `Tooltip` on every interactive element; include descriptive state in the tooltip text.
- All tables use MUI `size="small"` with `stickyHeader` for scrollable sections.
