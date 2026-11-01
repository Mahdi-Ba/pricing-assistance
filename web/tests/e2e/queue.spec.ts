import { expect, test } from "@playwright/test";
import { USERS, reseed } from "./stack";

test.use({ storageState: USERS.expert.state });
test.beforeAll(() => reseed());

test("tier-A floor conflict is listed first", async ({ page }) => {
  await page.goto("/queue");
  const rows = page.getByRole("table", { name: "صف بررسی" }).locator("tbody tr");
  await expect(rows).toHaveCount(4);
  await expect(rows.first()).toContainText("تعارض با کف سود");
  await expect(rows.first()).toContainText("RTX 4060");
});

test("card drill-down shows exactly the more-expensive items", async ({ page }) => {
  await page.goto("/queue");
  const card = page.locator('[data-card="above_market"]');
  const count = (await card.locator("span").nth(1).innerText()).trim();
  await card.click();
  await expect(page).toHaveURL(/price_position=above_market/);
  const rows = page.getByRole("table", { name: "صف بررسی" }).locator("tbody tr");
  await expect(rows).toHaveCount(2);
  expect(count).toBe("۲");
  for (const row of await rows.all()) {
    await expect(row).toContainText(/کاهش قیمت|تعارض با کف سود/);
  }
});

test("filter by status is reflected in the URL", async ({ page }) => {
  await page.goto("/queue");
  await page.getByLabel("وضعیت", { exact: true }).selectOption("needs_review");
  await expect(page).toHaveURL(/status=needs_review/);
  const rows = page.getByRole("table", { name: "صف بررسی" }).locator("tbody tr");
  await expect(rows).toHaveCount(4);
  for (const row of await rows.all()) await expect(row).toContainText("نیازمند بررسی");
  await page.getByLabel("وضعیت", { exact: true }).selectOption("decided");
  await expect(page).toHaveURL(/status=decided/);
  await expect(rows).toHaveCount(0);
});

test("keyboard navigation and mixed-direction names", async ({ page }) => {
  await page.goto("/queue");
  const rows = page.getByRole("table", { name: "صف بررسی" }).locator("tbody tr");
  await rows.first().focus();
  await page.keyboard.press("ArrowDown");
  await expect(rows.nth(1)).toBeFocused();
  await expect(page.locator("bdi", { hasText: "Kingston DDR5 · 32GB / 5600" })).toHaveAttribute("dir", "ltr");
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/\/queue\/[0-9a-f-]{36}$/);
});
