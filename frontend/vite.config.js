import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// The API port is configurable so a second stack can run alongside a developer's
// own — the test runner starts its own backend and dev server on ports of their
// own, and would otherwise proxy straight into whatever was already on :8000.
const API = process.env.RAILSETU_API_URL
  || `http://127.0.0.1:${process.env.RAILSETU_API_PORT || 8000}`

export default defineConfig({
  plugins: [react()],
  server: {
    port: Number(process.env.RAILSETU_WEB_PORT || 5173),
    proxy: {
      '/api': API,
    },
  },
})
