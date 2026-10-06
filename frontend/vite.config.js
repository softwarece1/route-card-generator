import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { fileURLToPath } from 'url';

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    port: 5174,
    strictPort: false,
    // Same-origin proxy — avoids CORS / Network Error on LAN IPs
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8008',
        changeOrigin: true,
        // Analyze + local VLM can exceed default ~2 min proxy idle timeout
        timeout: 1_200_000,
        proxyTimeout: 1_200_000,
      },
    },
  },
});
