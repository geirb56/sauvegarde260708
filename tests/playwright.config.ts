import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './e2e',
  outputDir: './test-results',
  timeout: 60_000,
  retries: 1,
  workers: 1,
  reporter: [
    ['list'],
    ['json', { outputFile: './test-results/results.json' }],
  ],
  use: {
    baseURL: process.env.REACT_APP_BACKEND_URL || 'https://charge-load.preview.emergentagent.com',
    screenshot: 'on',
    trace: 'on-first-retry',
    headless: true,
    viewport: { width: 1920, height: 1080 },
    ignoreHTTPSErrors: true,
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
});
