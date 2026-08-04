import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import path from 'path';

// Vite config for OP25 React GUI
// Output goes to ../www-static/ with flat file names only (no subdirectories).
// The Python http_server.py strips '/' from request paths, so all served files
// must live directly in www-static/ with no directory component.
export default defineConfig({
  plugins: [react()],
  build: {
    outDir: path.resolve(__dirname, '../www-static'),
    emptyOutDir: false, // Preserve legacy UI files (legacy-index.html, etc.)
    assetsDir: '',      // No assets/ subdirectory – all output lands in www-static root
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
