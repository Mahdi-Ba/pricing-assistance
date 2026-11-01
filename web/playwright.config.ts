import { defineConfig, devices } from "@playwright/test";

/**
 * End-to-end tests run the whole stack against the local services (`make up`): the API, a
 * scheduler and a worker on the `pricing_e2e` database (started by global-setup), and this app
 * in dev mode. Tests share one seeded database, so they run serially and re-seed as needed.
 */
export const BACKEND_PORT = 8100;
const baseURL = process.env.E2E_BASE_URL ?? "http://localhost:3000";

export default defineConfig({
  testDir: "./tests/e2e",
  globalSetup: "./tests/e2e/global-setup.ts",
  fullyParallel: false,
  workers: 1,
  timeout: 90_000,
  expect: { timeout: 15_000 },
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? "github" : "list",
  use: { baseURL, locale: "fa-IR", timezoneId: "Asia/Tehran", trace: "retain-on-failure" },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"], channel: process.env.E2E_BROWSER_CHANNEL },
    },
  ],
  webServer: process.env.E2E_BASE_URL
    ? undefined
    : {
        command: "npm run dev",
        url: baseURL,
        reuseExistingServer: false,
        timeout: 180_000,
        env: {
          BACKEND_API_URL: `http://localhost:${BACKEND_PORT}`,
          AUTH_SECRET: "e2e-only-auth-secret-0123456789abcdef0123456789",
          AUTH_KEYCLOAK_ID: "pricing-web",
          AUTH_KEYCLOAK_SECRET: "pricing-web-dev-secret",
          AUTH_KEYCLOAK_ISSUER: "http://localhost:58080/realms/tunoo",
          AUTH_TRUST_HOST: "true",
        },
      },
});
