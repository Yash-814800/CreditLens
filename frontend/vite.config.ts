import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: {
      // Backend routes under /api/v1/* already carry that prefix (see
      // backend/app/main.py's router mounts) so it must be forwarded as-is.
      // /healthz and /readyz are mounted unprefixed, so only those two get
      // the /api stripped. Mirrors nginx.conf's split in prod -- a single
      // blanket `/api` rewrite here previously 404'd every /api/v1/* call
      // while looking fine for /api/healthz, which is why it went unnoticed
      // until this phase's first real API call.
      '/api/healthz': {
        target: 'http://localhost:8000',
        changeOrigin: true,
        rewrite: () => '/healthz',
      },
      '/api/readyz': {
        target: 'http://localhost:8000',
        changeOrigin: true,
        rewrite: () => '/readyz',
      },
      '/api/v1': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
    // e2e/ holds Playwright specs (a different test runner/API) -- Vitest's
    // default include glob would otherwise pick them up and fail trying to
    // run `test.describe.configure` from its own `test` global.
    exclude: ['e2e/**', 'node_modules/**'],
  },
})
