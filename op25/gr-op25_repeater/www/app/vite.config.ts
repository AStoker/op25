import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import path from 'path';
import { createRequire } from 'module';

// Kept in step with addons/op25/config.yaml by scripts/bump-version.py, so the
// About dialog can name the version an install is running. Baked in at build
// time on purpose: the decoder does not know it, and asking the server would
// mean a new endpoint for a string that only changes when we release.
const { version } = createRequire(import.meta.url)('./package.json');

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
    // Change the target port if you start websocket_server.py on a different port.
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8080',
        changeOrigin: true,
      },
      '/ws': {
        target: 'ws://127.0.0.1:8080',
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
