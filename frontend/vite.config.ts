import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';
import path from 'path';

export default defineConfig({
  plugins: [react(), tailwindcss()],
  base: './',
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    port: 5174,
    strictPort: true,
    host: true,
    proxy: {
      // COS-195: dev-профиль проксирует /api на cosmo-api внутри cosmo-net
      // (VITE_API_PROXY); локальный host-dev — прежний 127.0.0.1:8100.
      '/api': process.env.VITE_API_PROXY || 'http://127.0.0.1:8100',
    },
  },
  test: {
    globals: true,
    environment: 'jsdom',
    include: ['src/**/*.test.{ts,tsx}'],
    setupFiles: ['./src/vitest.setup.ts'],
  },
});