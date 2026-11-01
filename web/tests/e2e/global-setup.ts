import { spawn, type ChildProcess } from "node:child_process";
import { chromium, type FullConfig } from "@playwright/test";
import { BACKEND_DIR, E2E_ENV, USERS, login, reseed } from "./stack";

const BACKEND_URL = "http://localhost:8100";

function start(args: string[]): ChildProcess {
  const child = spawn("uv", ["run", ...args], {
    cwd: BACKEND_DIR,
    env: { ...process.env, ...E2E_ENV },
    stdio: process.env.E2E_BACKEND_LOGS ? "inherit" : "ignore",
  });
  return child;
}

async function waitFor(url: string, timeoutMs = 60_000): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      if ((await fetch(url)).ok) return;
    } catch {
      // not up yet
    }
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
  throw new Error(`${url} did not become ready`);
}

export default async function globalSetup(config: FullConfig): Promise<() => Promise<void>> {
  reseed();
  const processes = [
    start(["uvicorn", "--factory", "pricing_assistant.app:create_app", "--port", "8100"]),
    start(["python", "-m", "pricing_assistant.scheduler"]),
    start(["dramatiq", "pricing_assistant.workers", "--queues", "process", "--processes", "1", "--threads", "2"]),
  ];
  await waitFor(`${BACKEND_URL}/readyz`);

  const baseURL = config.projects[0]?.use.baseURL ?? "http://localhost:3000";
  const browser = await chromium.launch({ channel: process.env.E2E_BROWSER_CHANNEL });
  for (const user of Object.values(USERS)) {
    const context = await browser.newContext({ baseURL, locale: "fa-IR" });
    const page = await context.newPage();
    await login(page, user.username, user.password);
    // tests drive the pages directly; tours open only where a test starts one
    await page.evaluate(() => localStorage.setItem("pa-tours:autostart", "off"));
    await context.storageState({ path: user.state });
    await context.close();
  }
  await browser.close();

  return async () => {
    for (const child of processes) child.kill("SIGTERM");
  };
}
