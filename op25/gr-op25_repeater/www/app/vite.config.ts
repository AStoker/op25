import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import path from 'path';
import { createRequire } from 'module';

// Kept in step with addons/op25/config.yaml by scripts/bump-version.py, so the
// About dialog can name the version an install is running. Baked in at build
// time on purpose: the decoder does not know it, and asking the server would
// mean a new endpoint for a string that only changes when we release.
const { version } = createRequire(import.meta.url)('./package.json');

// Where `yarn dev` proxies /api and /ws.
//
// Defaults to a local websocket_server.py. Point it at the Home Assistant
// add-on's published port to develop the UI against the machine that actually
// has the dongle attached:
//
//     OP25_BACKEND=http://homeassistant.local:8099 yarn dev
//
// Everything the browser talks to is still http://localhost:5173, so this needs
// no CORS and no change to the Python side. Note the add-on's port 8099 is
// unauthenticated — ingress is the authenticated path — so treat this as a
// trusted-LAN convenience, not a way to expose OP25 to a hostile network.
const BACKEND = process.env.OP25_BACKEND ?? 'http://127.0.0.1:8080';
const WS_BACKEND = BACKEND.replace(/^http/, 'ws');

export default defineConfig({
  plugins: [react()],
  define: {
    __APP_VERSION__: JSON.stringify(version),
  },
  // Relative asset URLs so index.html works both at the server root
  // (http://host:8080/) and under a path prefix. Home Assistant serves add-ons
  // through ingress at /api/hassio_ingress/<session-token>/, where the
  // root-absolute "/op25-react.js" would 404. Runtime fetch/WebSocket URLs are
  // resolved against document.baseURI by src/utils/url.ts for the same reason.
  base: './',
  server: {
    // Proxy API and WebSocket requests to the Python backend during `yarn dev`.
    // Set OP25_BACKEND to develop against a remote decoder (see above).
    proxy: {
      '/api': {
        target: BACKEND,
        changeOrigin: true,
      },
      '/ws': {
        target: WS_BACKEND,
        ws: true,
      },
    },
  },
  build: {
    outDir: path.resolve(__dirname, '../dist'),
    emptyOutDir: true,
    // assetsDir: '',      // No assets/ subdirectory – all output lands in dist root
    rollupOptions: {
      output: {
        entryFileNames: 'op25-react.js',
        // Safe names only: alphanumeric + dash + dot. [hash] is hex-only = safe.
        chunkFileNames: 'op25-[name]-[hash].js',
        assetFileNames: (info) =>
          info.name?.endsWith('.css') ? 'op25-react.css' : 'op25-[name]-[hash][extname]',
        manualChunks: {
          // Group vendor deps into predictably-named chunks with safe filenames
          'vendor-react': ['react', 'react-dom'],
          'vendor-emotion': ['@emotion/react', '@emotion/styled'],
          'vendor-mui': ['@mui/material'],
          'vendor-icons': ['@mui/icons-material'],
        },
      },
    },
  },
});
