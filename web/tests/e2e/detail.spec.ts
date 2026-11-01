import { expect, test, type Browser, type Page } from "@playwright/test";
import { USERS, reseed, supersede } from "./stack";

test.use({ storageState: USERS.expert.state });
test.beforeEach(() => reseed());

async function openItem(page: Page, sku: string): Promise<void> {
  await page.goto("/queue");
  const row = page.getByRole("table", { name: "صف بررسی" }).locator("tbody tr", { hasText: sku === "SSD-990-1TB" ? "990 PRO" : sku });
  await row.first().getByRole("link", { name: "بررسی" }).click();
  await expect(page.getByRole("table", { name: "شواهد بازار" })).toBeVisible();
}

function evidenceRow(page: Page, price: string) {
  return page.getByRole("table", { name: "شواهد بازار" }).locator("tbody tr", { hasText: price });
}

test("evidence row content", async ({ page }) => {
  await openItem(page, "SSD-990-1TB");
  const rows = page.getByRole("table", { name: "شواهد بازار" }).locator("tbody tr");
  await expect(rows).toHaveCount(4);
  const lion = evidenceRow(page, "۸٬۶۰۰٬۰۰۰ تومان");
  await expect(lion).toContainText("موجود");
  await expect(lion).toContainText(/[۰-۹]+ دقیقه پیش/);
  await expect(lion).toContainText("تأییدشده");
  await expect(lion).toContainText("مرجع بازار");
  await expect(lion.getByRole("link", { name: "Lion" })).toHaveAttribute("href", /^https:\/\/shop\.pricing-demo\.test\//);
  const outlier = evidenceRow(page, "۶٬۰۰۰٬۰۰۰ تومان");
  await expect(outlier).toContainText("قیمت پرت");
});

test("notice after decision", async ({ page }) => {
  await openItem(page, "SSD-990-1TB");
  await page.getByLabel("یادداشت تصمیم").fill("هم‌راستا با بازار");
  await page.getByRole("button", { name: "ثبت تصمیم" }).click();
  await expect(page.getByRole("status").filter({ hasText: "تصمیم ثبت شد؛ هیچ قیمتی در فروشگاه تغییر نکرد." })).toBeVisible();
  await expect(page.getByRole("region", { name: "تصمیم فعلی" })).toContainText("پذیرش");
});

test("decision without reason is refused", async ({ page }) => {
  await openItem(page, "SSD-990-1TB");
  await page.getByRole("button", { name: "ثبت تصمیم" }).click();
  await expect(page.getByRole("alert").filter({ hasText: "یادداشت تصمیم" })).toHaveText(
    "برای ثبت، یادداشت تصمیم را وارد کنید.",
  );
});

async function asAdmin(browser: Browser, url: string): Promise<Page> {
  const context = await browser.newContext({ storageState: USERS.admin.state, locale: "fa-IR" });
  const page = await context.newPage();
  await page.goto(url);
  return page;
}

test("notice for pending override, then admin approval", async ({ page, browser }) => {
  await openItem(page, "SSD-990-1TB");
  await page.getByLabel("پذیرش با تغییر").check();
  await page.getByLabel("قیمتی که در فروشگاه اعمال کردید (تومان)").fill("۸٬۳۰۰٬۰۰۰");
  await page.locator('textarea[name="override_reason"]').fill("فروش ویژه پایان فصل");
  await page.getByLabel("یادداشت تصمیم").fill("رقابت با فروشنده اصلی");
  await page.getByRole("button", { name: "ثبت تصمیم" }).click();
  await expect(page.getByRole("status").filter({ hasText: "نیازمند تأیید مدیر" })).toContainText(
    "تا تأیید مدیر، قیمت فروشگاه را تغییر ندهید",
  );
  await expect(page.getByRole("button", { name: "قیمت را در فروشگاه تغییر دادم" })).toBeVisible();
  await page.getByRole("button", { name: "قیمت را در فروشگاه تغییر دادم" }).click();
  await expect(page.getByRole("alert").filter({ hasText: "کف" })).toHaveText("قیمت زیر کف نیازمند تأیید مدیر است.");

  const admin = await asAdmin(browser, page.url());
  await admin.getByRole("button", { name: "تأیید قیمت زیر کف" }).click();
  await admin.getByLabel("دلیل تصمیم مدیر").fill("کمپین تأییدشده");
  await admin.getByRole("button", { name: "ثبت", exact: true }).click();
  await expect(admin.getByTestId("override-state").first()).toContainText("تأیید مدیر");
  await admin.context().close();

  await page.reload();
  await page.getByRole("button", { name: "قیمت را در فروشگاه تغییر دادم" }).click();
  await expect(page.getByRole("region", { name: "تصمیم فعلی" })).toContainText("در انتظار مشاهده روی سایت");
});

test("stale submission (409) shows the new version", async ({ page }) => {
  await openItem(page, "SSD-990-1TB");
  await page.getByLabel("یادداشت تصمیم").fill("هم‌راستا با بازار");
  supersede("SSD-990-1TB");
  await page.getByRole("button", { name: "ثبت تصمیم" }).click();
  await expect(page.getByRole("status").filter({ hasText: "نسخه جدید نمایش داده شد" })).toBeVisible();
  // the new version is displayed (its floor reflects the new cost) and can be decided on
  await expect(page.getByRole("region", { name: "پیشنهاد", exact: true })).toContainText("۸٬۳۴۰٬۰۰۰ تومان");
  await page.getByLabel("یادداشت تصمیم").fill("بررسی نسخه جدید");
  await page.getByRole("button", { name: "ثبت تصمیم" }).click();
  await expect(page.getByRole("status").filter({ hasText: "هیچ قیمتی در فروشگاه تغییر نکرد" })).toBeVisible();
});

test("reject from evidence recomputes the recommendation", async ({ page }) => {
  await openItem(page, "SSD-990-1TB");
  await expect(page.getByRole("region", { name: "پیشنهاد", exact: true })).toContainText("۸٬۵۵۰٬۰۰۰ تومان");
  const lion = evidenceRow(page, "۸٬۶۰۰٬۰۰۰ تومان");
  await lion.getByRole("button", { name: "رد تطبیق" }).click();
  await lion.getByLabel("دلیل رد").fill("گارانتی متفاوت");
  await lion.getByRole("button", { name: "ثبت", exact: true }).click();
  // with two offers left, 6,000,000 is no longer an outlier (that needs two other offers): it
  // becomes the market reference, below the floor, so the new outcome is a floor conflict
  const proposal = page.getByRole("region", { name: "پیشنهاد", exact: true });
  await expect(proposal).toContainText("تعارض با کف سود", { timeout: 60_000 });
  await expect(proposal).toContainText("مرجع بازار۶٬۰۰۰٬۰۰۰ تومان");
  await expect(evidenceRow(page, "۸٬۶۰۰٬۰۰۰ تومان")).toHaveCount(0); // the rejected offer is gone
});

test("confirm outlier from evidence recomputes the recommendation", async ({ page }) => {
  await openItem(page, "SSD-990-1TB");
  const outlier = evidenceRow(page, "۶٬۰۰۰٬۰۰۰ تومان");
  await outlier.getByRole("button", { name: "تأیید قیمت پرت" }).click();
  await outlier.getByLabel("دلیل تأیید قیمت").fill("حراج واقعی");
  await outlier.getByRole("button", { name: "ثبت", exact: true }).click();
  // 6,000,000 now qualifies and is below the floor: floor conflict
  await expect(page.getByRole("region", { name: "پیشنهاد", exact: true })).toContainText("تعارض با کف سود", { timeout: 60_000 });
});
