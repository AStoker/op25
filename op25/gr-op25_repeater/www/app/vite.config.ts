import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import path from 'path';

export default defineConfig({
  plugins: [react()],
  build: {
    outDir: path.resolve(__dirname, '../dist'),
    emptyOutDir: true,
    // assetsDir: '',      // No assets/ subdirectory – all output lands in www-static root
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
