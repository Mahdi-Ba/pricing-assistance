/** Helpers to drive the backend stack used by the e2e tests. */
import { execFileSync } from "node:child_process";
import path from "node:path";
import type { Page } from "@playwright/test";

export const BACKEND_DIR = path.resolve(__dirname, "../../../backend");
export const E2E_ENV: Record<string, string> = {
  PA_ENVIRONMENT: "dev",
  PA_LOG_JSON: "true",
  PA_DATABASE_APP_URL: "postgresql+asyncpg://pa_app:pa_app_dev@localhost:55432/pricing_e2e",
  PA_DATABASE_OWNER_URL: "postgresql+psycopg://pa_owner:pa_owner_dev@localhost:55432/pricing_e2e",
  PA_DATABASE_MAINTENANCE_URL: "postgresql+asyncpg://pa_maintenance:pa_maintenance_dev@localhost:55432/pricing_e2e",
  PA_REDIS_URL: "redis://localhost:56390/14",
  PA_S3_BUCKET: "pricing-evidence-e2e",
};

function seed(...args: string[]): void {
  execFileSync("uv", ["run", "python", "-m", "tests.support.e2e_seed", ...args], {
    cwd: BACKEND_DIR,
    env: { ...process.env, ...E2E_ENV },
    stdio: "pipe",
    timeout: 120_000,
  });
}

/** Wipe and re-seed the e2e database (and the e2e Redis DB). */
export function reseed(): void {
  seed("reset");
}

/** Make a new recommendation version for the variant, as new market data would. */
export function supersede(sku: string): void {
  seed("supersede", sku);
}

export const USERS = {
  expert: { username: "pilot-expert", password: "dev-password-1", state: path.resolve(__dirname, ".auth/expert.json") },
  admin: { username: "pilot-admin", password: "dev-password-1", state: path.resolve(__dirname, ".auth/admin.json") },
};

/** Log in through Keycloak's own login page (the app never sees the password). */
export async function login(page: Page, username: string, password: string): Promise<void> {
  await page.goto("/signin?callbackUrl=/queue");
  await page.getByRole("button", { name: "ورود با حساب سازمانی" }).click();
  await page.locator("#username").fill(username);
  await page.locator("#password").fill(password);
  await page.locator("#kc-login").click();
  await page.waitForURL("**/queue");
}
