import { expect, test } from "./fixtures/app";

test("app harness boots and serves the SPA", async ({ page }) => {
  await page.goto("/");
  await expect(page).toHaveTitle(/Penny/i);
  await expect(page.locator("#root")).toBeVisible();
});
