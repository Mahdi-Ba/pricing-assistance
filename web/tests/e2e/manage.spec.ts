import { expect, test } from "@playwright/test";
import { USERS, reseed } from "./stack";

test.beforeEach(() => reseed());

test.describe("admin", () => {
  test.use({ storageState: USERS.admin.state });

  test("a new source can be edited and deleted", async ({ page }) => {
    await page.goto("/sources");
    const create = page.getByRole("form", { name: "منبع جدید" });
    await create.getByLabel("نام").fill("Typo Shop");
    await create.getByLabel("دامنه").fill("typo.pricing-demo.test");
    await create.getByRole("button", { name: "افزودن منبع" }).click();
    const row = page.getByRole("table", { name: "منابع" }).locator("tr", { hasText: "Typo Shop" });
    await expect(row).toBeVisible();

    await row.getByRole("button", { name: "مدیریت" }).click();
    const panel = page.getByRole("region", { name: "منبع Typo Shop" });
    const edit = panel.getByRole("form", { name: "ویرایش منبع" });
    await edit.getByLabel("نام").fill("Fixed Shop");
    await edit.getByLabel("روش دریافت").selectOption("rendered_page");
    await edit.getByLabel("واحد پول قیمت‌های منبع").selectOption("RIAL");
    await edit.getByLabel("سهمیه در دقیقه").fill("15");
    await edit.getByRole("button", { name: "ذخیره تغییرات" }).click();
    const fixed = page.getByRole("table", { name: "منابع" }).locator("tr", { hasText: "Fixed Shop" });
    await expect(fixed).toBeVisible();
    await expect(page.getByRole("table", { name: "منابع" }).locator("tr", { hasText: "Typo Shop" })).toHaveCount(0);

    const renamed = page.getByRole("region", { name: "منبع Fixed Shop" });
    await renamed.getByRole("button", { name: "حذف منبع" }).click();
    const remove = renamed.getByRole("form", { name: "حذف منبع" });
    await remove.getByLabel("دلیل حذف").fill("ثبت اشتباه");
    await remove.getByRole("button", { name: "حذف قطعی" }).click();
    await expect(fixed).toHaveCount(0);
  });

  test("a source with history cannot be deleted, only rejected or suspended", async ({ page }) => {
    await page.goto("/sources");
    await page.locator("tr", { hasText: "Meghdad" }).getByRole("button", { name: "مدیریت" }).click();
    const panel = page.getByRole("region", { name: "منبع Meghdad" });
    await expect(panel.getByRole("button", { name: "حذف منبع" })).toHaveCount(0);
    await expect(panel).toContainText("فقط منبع «نامزد» که هنوز استفاده نشده قابل حذف است");
    // a collecting source keeps its collection settings
    await expect(panel.getByRole("form", { name: "ویرایش منبع" }).getByLabel("روش دریافت")).toBeDisabled();
    // its clearance can be revoked, which suspends it
    const revoke = panel.getByRole("form", { name: "لغو مجوز" });
    await revoke.getByLabel("دلیل لغو مجوز").fill("پایان قرارداد");
    await revoke.getByRole("button", { name: "لغو مجوز" }).click();
    await expect(page.getByRole("table", { name: "منابع" }).locator("tr", { hasText: "Meghdad" })).toContainText("معلق");
  });

  test("fixed cost components are added and deactivated", async ({ page }) => {
    await page.goto("/catalog/imports");
    const add = page.getByRole("form", { name: "افزودن جزء هزینه" });
    await add.getByLabel("نام هزینه").fill("حمل");
    await add.getByLabel("مبلغ هر عدد (تومان)").fill("۵۰٬۰۰۰");
    await add.getByRole("button", { name: "افزودن جزء" }).click();
    const table = page.getByRole("table", { name: "اجزای فعال بهای تمام‌شده" });
    const row = table.locator("tr", { hasText: "حمل" });
    await expect(row).toContainText("۵۰٬۰۰۰ تومان");
    await expect(row).toContainText("همه کالاها");
    await row.getByRole("button", { name: "غیرفعال کردن" }).click();
    await row.getByLabel("دلیل غیرفعال کردن").fill("قرارداد حمل تغییر کرد");
    await row.getByRole("button", { name: "غیرفعال شود" }).click();
    await expect(page.getByText("جزء فعالی ثبت نشده است")).toBeVisible();
  });

  test("settings are saved", async ({ page }) => {
    await page.goto("/settings");
    await page.getByLabel("مهلت مشاهده قیمت روی سایت (دقیقه)").fill("90");
    await page.getByLabel("پوشش کالاهای اهمیت الف (٪)").fill("95");
    await page.getByRole("button", { name: "ذخیره تنظیمات" }).click();
    await expect(page.getByRole("status").filter({ hasText: "تنظیمات ذخیره شد" })).toBeVisible();
    await page.reload();
    await expect(page.getByLabel("مهلت مشاهده قیمت روی سایت (دقیقه)")).toHaveValue("90");
    await expect(page.getByLabel("پوشش کالاهای اهمیت الف (٪)")).toHaveValue("95");
  });
});

test.describe("expert", () => {
  test.use({ storageState: USERS.expert.state });

  async function openItem(page: import("@playwright/test").Page) {
    await page.goto("/queue");
    await page.getByRole("table", { name: "صف بررسی" }).locator("tbody tr", { hasText: "990 PRO" }).getByRole("link", { name: "بررسی" }).click();
    await expect(page.getByRole("table", { name: "شواهد بازار" })).toBeVisible();
  }

  test("an offer address is registered for an item", async ({ page }) => {
    await openItem(page);
    const form = page.getByRole("form", { name: "افزودن نشانی آگهی" });
    await form.getByRole("combobox", { name: "منبع", exact: true }).selectOption({ label: "Lion (shop.pricing-demo.test)" });
    await form.getByLabel("نشانی صفحه کالا در منبع").fill("https://shop.pricing-demo.test/p/990-pro-new");
    await form.getByRole("button", { name: "افزودن نشانی" }).click();
    const offers = page.getByRole("table", { name: "آگهی‌های پایش‌شده" });
    await expect(offers.locator("tr", { hasText: "990-pro-new" })).toContainText("در حال پایش");
    // experts cannot pause offers or register own-store listings
    await expect(form.getByLabel("نوع آگهی")).toHaveCount(0);
    await expect(offers.getByRole("button", { name: "توقف پایش" })).toHaveCount(0);

    await form.getByRole("combobox", { name: "منبع", exact: true }).selectOption({ label: "Lion (shop.pricing-demo.test)" });
    await form.getByLabel("نشانی صفحه کالا در منبع").fill("https://elsewhere.example/p/1");
    await form.getByRole("button", { name: "افزودن نشانی" }).click();
    await expect(form.getByRole("alert")).toContainText("نشانی باید در دامنه");
  });

  test("a decision is corrected by a new decision", async ({ page }) => {
    await openItem(page);
    await page.getByLabel("یادداشت تصمیم").fill("هم‌راستا با بازار");
    await page.getByRole("button", { name: "ثبت تصمیم" }).click();
    const current = page.getByRole("region", { name: "تصمیم فعلی" });
    await expect(current).toContainText("پذیرش");
    await current.getByRole("button", { name: "اصلاح تصمیم" }).click();
    const correction = current.getByRole("form", { name: "اصلاح تصمیم" });
    await correction.getByLabel("تعویق").check();
    await correction.getByLabel("یادداشت تصمیم").fill("منتظر موجودی انبار");
    await correction.getByRole("button", { name: "ثبت تصمیم اصلاحی" }).click();
    await expect(page.getByRole("region", { name: "تصمیم فعلی" })).toContainText("تعویق");
    const history = page.getByRole("list", { name: "تاریخچه" });
    await expect(history).toContainText("هم‌راستا با بازار");
    await expect(history).toContainText("منتظر موجودی انبار");
    await expect(history).toContainText("اصلاح‌شده با تصمیم بعدی");
  });
});
