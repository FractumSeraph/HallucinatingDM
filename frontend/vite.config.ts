import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// In dev, API/WS calls proxy to the backend (default localhost:8080; the
// docker dev compose sets VITE_API_PROXY=http://app:8080).
const target = process.env.VITE_API_PROXY ?? 'http://localhost:8080'

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': { target, changeOrigin: true },
      '/ws': { target, ws: true, changeOrigin: true },
    },
  },
})
