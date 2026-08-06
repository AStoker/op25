import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import path from 'path';

export default defineConfig({
  plugins: [react()],
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
