import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";
import { USERS, reseed } from "./stack";

test.use({ storageState: USERS.expert.state });
test.beforeAll(() => reseed());

async function seriousViolations(page: import("@playwright/test").Page) {
  const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]).analyze();
  return results.violations
    .filter((v) => v.impact === "serious" || v.impact === "critical")
    .map((v) => ({ id: v.id, impact: v.impact, nodes: v.nodes.map((n) => n.target.join(" ")) }));
}

test("queue page has no serious or critical accessibility violations", async ({ page }) => {
  await page.goto("/queue");
  await expect(page.getByRole("table", { name: "صف بررسی" }).locator("tbody tr").first()).toBeVisible();
  expect(await seriousViolations(page)).toEqual([]);
});

test("detail page has no serious or critical accessibility violations", async ({ page }) => {
  await page.goto("/queue");
  await page.getByRole("table", { name: "صف بررسی" }).locator("tbody tr").first().getByRole("link", { name: "بررسی" }).click();
  await expect(page.getByRole("table", { name: "شواهد بازار" })).toBeVisible();
  expect(await seriousViolations(page)).toEqual([]);
});
