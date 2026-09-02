import { defineConfig } from '@playwright/test';

/**
 * COS-064: Browser acceptance — notification surface.
 *
 * Runs against live stack:
 *   - vite dev server :5175 (e2e-dedicated port; 5174 occupied by external WSL relay)
 *   - FastAPI backend :8100 (must be running, PG :5432)
 *
 * Notification fixtures go through the production code path via
 * e2e/helpers/cosmo_notify_helper.py (record_event → POST /process).
 */
export default defineConfig({
  testDir: './e2e',
  timeout: 60_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  workers: 1,
  reporter: [['list']],
  use: {
    baseURL: 'http://localhost:5175',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'off',
  },
  webServer: {
    command: 'npm run dev -- --port 5175 --strictPort',
    url: 'http://localhost:5175',
    reuseExistingServer: true,
    timeout: 60_000,
  },
});
