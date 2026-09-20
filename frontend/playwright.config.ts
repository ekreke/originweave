import { defineConfig, devices } from '@playwright/test'

// Browser end-to-end for originweave (M1c-2b 2b-5). It drives the real built SPA
// (frontend/dist) served by scripts/e2e_server.py over a fake provider, so the run
// is deterministic and needs no network or credentials.
const PORT = Number(process.env.E2E_PORT ?? 8790)

export default defineConfig({
  testDir: './e2e',
  timeout: 30_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  workers: 1,
  reporter: 'list',
  use: {
    baseURL: `http://127.0.0.1:${PORT}`,
    trace: 'retain-on-failure',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: {
    command: 'bash ../scripts/run_e2e_server.sh',
    url: `http://127.0.0.1:${PORT}`,
    env: { PORT: String(PORT) },
    // Always start a fresh server: the scripted worker is a single-run queue, so a
    // reused process would have no replies left for a second run.
    reuseExistingServer: false,
    timeout: 60_000,
  },
})
