import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

export default defineConfig({
  plugins: [react()],
  resolve: { alias: { '@': path.resolve(__dirname, './src') } },
  server: {
    port: Number(process.env.FLD_WEB_PORT ?? 5173),
    strictPort: true,
    // FLD-OS-Backend (uvicorn :8031, anderes Ziel per FLD_API_URL): /fld-api/<pfad> → /api/v1/<pfad>
    proxy: {
      '/fld-api': { target: process.env.FLD_API_URL ?? 'http://127.0.0.1:8031', changeOrigin: true, rewrite: (p) => p.replace(/^\/fld-api/, '/api/v1') },
    },
  },
})
