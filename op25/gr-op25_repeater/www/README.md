# `www/` — which directory is which

Two web UIs live here. They are selected by the `terminal` block of the
multi_rx JSON config, never at runtime, and they share no protocol.

| Directory | Role | Build | Served by |
|---|---|---|---|
| **`app/`** | **Current GUI source** — React 18 + MUI 6 + Vite | `yarn build` → `../dist` | `websocket_server.py` (FastAPI, **one port**) |
| **`dist/`** | Current GUI build output — **committed artifact** | — | `websocket_server.py` |
| `react-app-legacy/` | Legacy GUI source | `yarn build` → `../www-static` | `http_server.py` (waitress, **two ports**) |
| `www-static/` | Legacy GUI build output, plus the older hand-written `main.js` UI | — | `http_server.py` |
| `images/` | gnuplot PNGs written by the `http:` terminal (`http_plot_directory`) | — | `http_server.py` |

## Which one am I running?

```jsonc
// current stack
"terminal": { "module": "websocket_server.py", "terminal_type": "ws:0.0.0.0:8080" }

// legacy stack
"terminal": { "module": "terminal.py", "terminal_type": "http:0.0.0.0:8080" }
```

Against a running instance, one request settles it — the endpoint only exists on
the current stack:

```bash
curl -s localhost:8080/api/audio/channels    # JSON → current, 404 → legacy
```

## Gotcha

`dist/` and `www-static/` are **committed build artifacts** and can drift from
their sources. After changing anything under `app/`, run `yarn build` — otherwise
the server keeps serving the old bundle and you will draw wrong conclusions from
what the browser shows. `index.html` references content-hashed filenames, so a
hard reload (Cmd/Ctrl-Shift-R) is worth doing after a rebuild.

Docs: [`README-new-gui.md`](../../../README-new-gui.md) (current protocol and
endpoints), [`app/AGENTS.md`](app/AGENTS.md) (current frontend conventions),
[`README-websockets.md`](../../../README-websockets.md) (legacy protocol).
