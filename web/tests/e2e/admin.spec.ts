import path from "node:path";
import { expect, test } from "@playwright/test";
import { USERS, reseed } from "./stack";

test.use({ storageState: USERS.admin.state });
test.beforeEach(() => reseed());

test("catalog import reports row errors", async ({ page }) => {
  await page.goto("/catalog/imports");
  await page.getByLabel("فایل (CSV یا XLSX)").setInputFiles(path.resolve(__dirname, "files/catalog-with-errors.csv"));
  await page.getByRole("button", { name: "بارگذاری" }).click();
  const report = page.getByRole("region", { name: "گزارش ورود" });
  await expect(report).toContainText("catalog-with-errors.csv");
  const errors = report.getByRole("table", { name: "خطاهای ردیف‌ها" }).locator("tbody tr");
  await expect(errors.first()).toBeVisible();
  await expect(report.getByRole("table", { name: "خطاهای ردیف‌ها" })).toContainText("سطح اهمیت باید A، B یا C باشد.");
  await expect(errors.filter({ hasText: "importance" }).first()).toContainText("۲"); // the second data row
  await expect(report).toContainText(/جدید ۱/);
});

test("a source gets a clearance and is approved", async ({ page }) => {
  await page.goto("/sources");
  await page.locator("tr", { hasText: "Candidate Shop" }).getByRole("button", { name: "مدیریت" }).click();
  const panel = page.getByRole("region", { name: "منبع Candidate Shop" });
  const status = panel.getByRole("form", { name: "تغییر وضعیت منبع" });
  await status.getByLabel("وضعیت جدید").selectOption("under_evaluation");
  await status.getByLabel("دلیل").fill("شروع ارزیابی");
  await status.getByRole("button", { name: "تغییر وضعیت" }).click();
  await expect(panel).toContainText("مجوز دسترسی این منبع ثبت نشده است");

  const clearance = panel.getByRole("form", { name: "ثبت مجوز" });
  await clearance.getByLabel("تأییدکننده").fill("مالک فروشگاه رقیب");
  await clearance.getByLabel("تاریخ تأیید").fill("2026-10-20");
  await clearance.getByLabel("دامنه مجوز").fill("صفحات عمومی محصول");
  await clearance.getByLabel("شماره سند").fill("LEGAL-77");
  await clearance.getByLabel("سقف درخواست در دقیقه").fill("30");
  await clearance.getByRole("button", { name: "ثبت مجوز" }).click();
  await expect(panel).toContainText("LEGAL-77");

  await status.getByLabel("وضعیت جدید").selectOption("under_evaluation");
  await status.getByLabel("دلیل").fill("مجوز ثبت شد");
  await status.getByRole("button", { name: "تغییر وضعیت" }).click();
  await expect(page.getByRole("heading", { name: "Candidate Shop — در حال ارزیابی" })).toBeVisible();
  await status.getByLabel("وضعیت جدید").selectOption("approved");
  await status.getByLabel("دلیل").fill("کیفیت کافی");
  await status.getByRole("button", { name: "تغییر وضعیت" }).click();
  await expect(page.getByRole("heading", { name: "Candidate Shop — تأییدشده" })).toBeVisible();
});

test("a proposed extraction rule is approved", async ({ page }) => {
  await page.goto("/sources");
  await page.locator("tr", { hasText: "Rule Shop" }).getByRole("button", { name: "مدیریت" }).click();
  const rule = page.locator("[data-rule]").first();
  await expect(rule).toContainText("پیشنهادی");
  await expect(rule).toContainText("موفق");
  await rule.getByLabel("دلیل بررسی").fill("روی نمونه‌ها درست است");
  await rule.getByRole("button", { name: "تأیید و فعال‌سازی" }).click();
  await expect(rule).toContainText("فعال");
});
