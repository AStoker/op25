# OP25 React GUI — Agent Reference

This document describes the full architecture, server protocol, and implementation conventions for the OP25 React GUI. Read this before making changes to avoid unnecessary exploration turns.

---

## Project Layout

```
app/               ← this directory
  src/
    App.tsx              ← root component; all state, polling, response dispatch
    main.tsx             ← ReactDOM.createRoot entry
  index.html             ← Vite dev-server entry (not the served file in production)
  vite.config.ts         ← Build config (see CRITICAL constraint below)
  package.json
  tsconfig.json / tsconfig.app.json / tsconfig.node.json
```

The Python server that serves the built files is at:
```
../../../apps/http_server.py   (relative to app/)
```

---

## Build

```bash
cd app/
yarn install     # first time
yarn build       # tsc -b && vite build → outputs to ../www-static/
yarn dev         # Vite dev server (proxies nothing; see remote server section)
```
---

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
| `dump_tgids` | 0 | channel | Log talkgroup IDs to server console |
| `dump_tracking` | 0 | channel | Log tracking state |
| `dump_buffer` | -1 | channel | Force buffer dump |
| `set_debug` | level (0–10) | channel | Set log verbosity |
| `toggle_plot` | plot type (cast as number) | channel | Toggle gnuplot |

"Hold on talkgroup" requires sending `whitelist` first then `hold` — see `holdTalkgroup()` in `App.tsx`.

---
