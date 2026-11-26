import { defineConfig, devices } from '@playwright/test';

const baseURL = process.env.VNV_BASE_URL || 'http://127.0.0.1:5174';

export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  workers: 1,
  reporter: [
    ['list'],
    ['junit', { outputFile: '../docs/vnv/artifacts/playwright-junit.xml' }],
  ],
  use: {
    baseURL,
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
  },
  projects: [
    {
      name: 'chromium',
      use: {
        ...devices['Desktop Chrome'],
        // Prefer Playwright browser; fall back to system Chrome if download failed
        channel: process.env.PLAYWRIGHT_CHROME_CHANNEL || 'chrome',
      },
    },
  ],
  webServer: process.env.VNV_NO_WEBSERVER
    ? undefined
    : {
        command: 'npm run dev -- --port 5174 --strictPort',
        url: baseURL,
        reuseExistingServer: true,
        timeout: 120_000,
      },
});
