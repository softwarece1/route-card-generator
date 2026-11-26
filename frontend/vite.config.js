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
    host: true, // listen on 0.0.0.0 — clients open http://<server-ip>:5174
    port: 5174,
    strictPort: false,
    // Same-origin proxy — browser Origin stays on the Vite host; API is /api/*
    proxy: {
      '/api': {
        // Must match uvicorn --port (this box runs 8003). Override: VITE_API_PROXY_TARGET=http://127.0.0.1:8002
        target: process.env.VITE_API_PROXY_TARGET || 'http://127.0.0.1:8003',
        // Keep the browser Host (e.g. 172.16.x.x:5174). changeOrigin:true rewrites Host to
        // 127.0.0.1:8003 and CSRF same-host checks then fail for LAN IP clients.
        changeOrigin: false,
        // If a future proxy must rewrite Host, X-Forwarded-Host still feeds CSRF/CORS.
        xfwd: true,
        ws: true,
        // Analyze + local VLM can exceed default ~2 min proxy idle timeout
        timeout: 1_200_000,
        proxyTimeout: 1_200_000,
      },
    },
  },
  preview: {
    host: true,
    port: 5174,
  },
});
