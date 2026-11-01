import { expect, test } from "@playwright/test";
import { USERS } from "./stack";

test.describe("signed out", () => {
  test("workspace pages redirect to sign-in", async ({ page }) => {
    await page.goto("/queue");
    await expect(page).toHaveURL(/\/signin\?callbackUrl=%2Fqueue/);
    await expect(page.locator("html")).toHaveAttribute("dir", "rtl");
  });

  test("the API proxy refuses calls without a session", async ({ request }) => {
    const response = await request.get("/api/backend/api/v1/queue");
    expect(response.status()).toBe(401);
  });
});

test.describe("expert", () => {
  test.use({ storageState: USERS.expert.state });

  test("cannot see or open admin pages", async ({ page }) => {
    await page.goto("/queue");
    const nav = page.getByRole("navigation", { name: "منوی اصلی" });
    await expect(nav.getByRole("link", { name: "صف بررسی" })).toBeVisible();
    await expect(nav.getByRole("link", { name: "منابع" })).toHaveCount(0);
    await expect(nav.getByRole("link", { name: "قواعد سود" })).toHaveCount(0);
    for (const path of ["/sources", "/rules", "/catalog/imports"]) {
      await page.goto(path);
      await expect(page.getByRole("heading", { name: "دسترسی ندارید" })).toBeVisible();
    }
  });

  test("no token is readable by browser JavaScript", async ({ page }) => {
    await page.goto("/queue");
    const cookies = await page.evaluate(() => document.cookie);
    expect(cookies).not.toMatch(/eyJ|access_token|refresh_token|authjs\.session-token/);
    const session = await page.evaluate(async () => (await fetch("/api/auth/session")).text());
    expect(session).toContain("pilot-expert");
    expect(session).not.toMatch(/eyJ|accessToken|refreshToken|access_token/);
    // the session cookie exists, but only as httpOnly
    const stored = await page.context().cookies();
    const sessionCookie = stored.find((c) => c.name.startsWith("authjs.session-token"));
    expect(sessionCookie?.httpOnly).toBe(true);
  });

  test("cross-origin writes through the proxy are refused", async ({ page }) => {
    await page.goto("/queue");
    // the context's request client carries the session cookie but lets us set Origin freely
    const forged = await page.request.post("/api/backend/api/v1/review-sessions", {
      headers: { origin: "https://evil.example" },
      data: {},
    });
    expect(forged.status()).toBe(403);
    const sameOrigin = await page.request.post("/api/backend/api/v1/review-sessions", {
      headers: { origin: "http://localhost:3000" },
      data: {},
    });
    expect(sameOrigin.status()).toBe(422); // reached the API, which validates the body
  });
});

test.describe("admin", () => {
  test.use({ storageState: USERS.admin.state });

  test("sees admin navigation", async ({ page }) => {
    await page.goto("/queue");
    const nav = page.getByRole("navigation", { name: "منوی اصلی" });
    await expect(nav.getByRole("link", { name: "منابع" })).toBeVisible();
    await page.goto("/sources");
    await expect(page.getByRole("heading", { name: "منابع داده" })).toBeVisible();
  });
});
