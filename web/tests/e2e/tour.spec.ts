import { expect, test } from "@playwright/test";
import { USERS, reseed } from "./stack";

test.use({ storageState: USERS.expert.state });
test.beforeAll(() => reseed());

test("queue tour walks through the page and can be reopened", async ({ page }) => {
  await page.goto("/queue");
  await expect(page.getByRole("table", { name: "صف بررسی" }).locator("tbody tr").first()).toBeVisible();
  await page.getByRole("button", { name: "راهنمای این صفحه" }).click();

  const dialog = page.getByRole("dialog");
  await expect(dialog).toContainText("به دستیار قیمت‌گذاری خوش آمدید");
  await expect(dialog).toContainText("۱ از ۷");
  await expect(dialog).toBeFocused();

  await dialog.getByRole("button", { name: "بعدی" }).click();
  await expect(dialog.getByRole("heading")).toHaveText("منوی اصلی");
  await page.keyboard.press("ArrowLeft"); // RTL: left is forward
  await expect(dialog.getByRole("heading")).toHaveText("کارت‌های خلاصه");
  await expect(dialog).toContainText("پشت صحنه چه اتفاقی می‌افتد");
  await dialog.getByRole("button", { name: "قبلی" }).click();
  await expect(dialog.getByRole("heading")).toHaveText("منوی اصلی");

  await page.keyboard.press("Escape");
  await expect(dialog).toHaveCount(0);
  await expect(page.getByRole("button", { name: "راهنمای این صفحه" })).toBeFocused();
});

test("first visit starts the page tour once", async ({ page }) => {
  await page.goto("/matches");
  await page.evaluate(() => {
    localStorage.removeItem("pa-tours:autostart");
    localStorage.removeItem("pa-tour-seen:matches:v1");
  });
  await page.reload();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toContainText("تطبیق یعنی چه؟");
  await dialog.getByRole("button", { name: "بستن راهنما" }).click();
  await page.reload();
  await expect(page.getByRole("heading", { name: "تأیید تطبیق‌ها" })).toBeVisible();
  await page.waitForTimeout(1_000);
  await expect(dialog).toHaveCount(0);
});

test("help page explains concepts and starts a page tour", async ({ page }) => {
  await page.goto("/help");
  await expect(page.getByRole("heading", { name: "واژه‌نامه" })).toBeVisible();
  await expect(page.getByText("کف سود", { exact: true })).toBeVisible();
  // experts do not see admin-only tours
  await expect(page.getByRole("heading", { name: "قواعد سود" })).toHaveCount(0);
  await page.getByRole("listitem").filter({ hasText: "گزارش‌ها" }).getByRole("button", { name: "شروع راهنما" }).click();
  await expect(page).toHaveURL(/\/reports$/);
  await expect(page.getByRole("dialog")).toContainText("بازه گزارش");
});
