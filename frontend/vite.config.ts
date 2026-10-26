import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Built assets are served by the FastAPI app: dist/index.html at "/" and
// dist/assets mounted at "/assets". In development, /api is proxied to the
// backend started with `python -m hunt serve --port 8010`.
export default defineConfig({
  plugins: [react()],
  base: '/',
  build: {
    outDir: 'dist',
    assetsDir: 'assets',
    emptyOutDir: true,
  },
  server: {
    port: 5173,
    proxy: {
      '/api': { target: 'http://127.0.0.1:8010', changeOrigin: true },
    },
  },
})
