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
