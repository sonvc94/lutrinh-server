/// <reference types="vitest/config" />
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// The Python server serves admin/dist at /admin (page 04 §F); in dev, /admin/api goes to it
// so the cookie and CSRF flow are the same as in production (page 04 §G).
const api = process.env.LUTRINH_API ?? 'http://127.0.0.1:8000'

export default defineConfig({
  base: '/admin/',
  plugins: [react()],
  build: { outDir: 'dist', emptyOutDir: true, chunkSizeWarningLimit: 1500 },
  server: {
    port: 5173,
    strictPort: true,
    proxy: { '/admin/api': { target: api, changeOrigin: false } },
    fs: { allow: ['..'] },
  },
  test: {
    environment: 'jsdom',
    include: ['src/**/*.test.{ts,tsx}', 'tests/**/*.test.{ts,tsx}'],
    setupFiles: ['tests/setup.ts'],
    css: { modules: { classNameStrategy: 'non-scoped' } },
  },
})
