import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './tests/e2e',
  timeout: 30_000,
  expect: { timeout: 10_000 },
  use: {
    baseURL: process.env.SOURCEBRIEF_WEB_URL ?? 'http://localhost:3105',
    // These smoke tests authenticate with local/CI admin credentials and seed a
    // browser session token. Do not retain Playwright traces by default; traces
    // can include request payloads and storage state.
    trace: 'off',
  },
  webServer: process.env.SOURCEBRIEF_SKIP_PLAYWRIGHT_WEBSERVER ? undefined : {
    command: 'npm run dev -- --hostname 0.0.0.0 --port 3105',
    url: 'http://localhost:3105/api/health',
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
    env: {
      NEXT_PUBLIC_API_BASE_URL: process.env.SOURCEBRIEF_API_URL ?? 'http://localhost:18000',
    },
  },
  projects: [
    { name: 'chromium', use: { ...devices['Desktop Chrome'] } },
  ],
});
