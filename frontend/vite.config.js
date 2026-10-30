import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// The API in development. Deployed, one process serves this UI and the API
// together, so there is nothing to proxy and nothing to configure.
const API = process.env.VITE_DEV_API ?? 'http://127.0.0.1:8000'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    // Proxying rather than calling the backend's own origin means the browser
    // sees one origin in development too -- the same as deployed -- so CORS is
    // not involved either way, and the dev setup cannot pass while the
    // deployed one fails on a header nobody set.
    proxy: {
      '/libraries': { target: API, changeOrigin: true },
      '/docs': { target: API, changeOrigin: true },
      '/openapi.json': { target: API, changeOrigin: true },
    },
  },
})
