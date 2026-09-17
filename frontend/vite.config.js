import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const proxyTarget = env.VITE_API_PROXY_TARGET || 'http://localhost:8000'

  return {
    plugins: [react()],
    server: {
      port: 5173,
      strictPort: true,
      // Same-origin API: the browser talks to /api on the Vite origin; Vite forwards to
      // Django. Cookies (refresh + csrftoken) are therefore first-party.
      // In production the frontend host must provide the same /api rewrite (see README).
      proxy: {
        '/api': {
          target: proxyTarget,
          changeOrigin: false, // keep Host = localhost:5173 so Django's origin check is same-origin
        },
      },
    },
  }
})
