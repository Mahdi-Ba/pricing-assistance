import { expect, test } from "@playwright/test";
import { USERS, reseed } from "./stack";

test.use({ storageState: USERS.admin.state });
test.beforeAll(() => reseed());

test("reports render measured values next to targets", async ({ page }) => {
  await page.goto("/reports");
  const pilot = page.getByRole("region", { name: "شاخص‌های آزمایشی" });
  await expect(pilot.locator('[data-kpi="پیشنهاد زیر کف سود"]')).toContainText("۰");
  await expect(pilot.locator('[data-kpi="کامل بودن شواهد"]')).toContainText("۱۰۰٪");
  await expect(pilot.locator('[data-kpi="دقت تطبیق"]')).toContainText("≥ ۹۸٪");
  const weekly = page.getByRole("region", { name: "گزارش هفتگی" });
  await expect(weekly.locator('[data-kpi="اطمینان مشاهده روی سایت در مهلت"]')).toContainText("هدف تعیین نشده");
  await expect(weekly.getByRole("table", { name: "منابع هفته" }).locator("tbody tr").first()).toBeVisible();
  await expect(page.getByRole("region", { name: "نمونه بررسی تطبیق" })).toBeVisible();
});
