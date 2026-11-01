import { expect, test } from "@playwright/test";
import { USERS, reseed } from "./stack";

test.use({ storageState: USERS.expert.state });
test.beforeEach(() => reseed());

test("side-by-side compare highlights differing attributes", async ({ page }) => {
  await page.goto("/matches");
  const match = page.locator("[data-match]").first();
  await expect(match).toContainText("990 PRO");
  const capacity = match.locator('[data-attribute="capacity"]');
  await expect(capacity).toHaveAttribute("data-state", "different");
  await expect(capacity).toContainText("1TB");
  await expect(capacity).toContainText("2TB");
  await expect(match.locator('[data-attribute="brand"]')).toHaveAttribute("data-state", "equal");
});

test("reject a pending match with a reason", async ({ page }) => {
  await page.goto("/matches");
  const match = page.locator("[data-match]").first();
  await match.getByRole("button", { name: "رد", exact: true }).click();
  await match.getByLabel("دلیل", { exact: true }).fill("ظرفیت متفاوت");
  await match.getByRole("button", { name: "ثبت", exact: true }).click();
  await expect(page.getByRole("status")).toHaveText("تطبیق رد شد.");
  await expect(page.locator("[data-match]")).toHaveCount(0);
});

test("confirm a suggested URL", async ({ page }) => {
  await page.goto("/matches");
  const suggestion = page.locator("[data-suggested]").first();
  await expect(suggestion).toContainText("همان مدل، ظرفیت و فرکانس");
  await suggestion.getByRole("button", { name: "تأیید نشانی" }).click();
  await expect(page.getByRole("status")).toHaveText("نشانی تأیید شد و پایش آن زمان‌بندی شد.");
  await expect(page.locator("[data-suggested]")).toHaveCount(0);
});
