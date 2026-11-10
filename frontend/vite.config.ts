import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// The dev server proxies /api to Django so the session + CSRF cookies are same-origin.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': 'http://127.0.0.1:8000',
    },
  },
})
