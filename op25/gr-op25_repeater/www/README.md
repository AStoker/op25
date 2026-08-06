# `www/` — which directory is which

One web UI lives here, selected by the `terminal` block of the multi_rx JSON
config:

```jsonc
"terminal": { "module": "websocket_server.py", "terminal_type": "ws:0.0.0.0:8080" }
```

| Directory | Role | Build | Served by |
|---|---|---|---|
| **`app/`** | **GUI source** — React 18 + MUI 6 + Vite | `yarn build` → `../dist` | `websocket_server.py` (FastAPI, one port) |
| **`dist/`** | GUI build output — **committed artifact** | — | `websocket_server.py` |

The older stack — `react-app-legacy/` + `www-static/` + `images/`, served by
`http_server.py` on waitress over two ports — was removed. A config that still
says `"terminal_type": "http:…"` now prints a migration message and runs
headless rather than starting a server.

## Gotcha

`dist/` is a **committed build artifact** and can drift from `app/`. After
changing anything under `app/`, run `yarn build` — otherwise the server keeps
serving the old bundle and you will draw wrong conclusions from what the browser
shows. `index.html` references content-hashed filenames, so a hard reload
(Cmd/Ctrl-Shift-R) is worth doing after a rebuild.

Docs: [`README-new-gui.md`](../../../README-new-gui.md) (protocol and
endpoints), [`app/AGENTS.md`](app/AGENTS.md) (frontend conventions).
