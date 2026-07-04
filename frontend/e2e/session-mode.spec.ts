import { expect, test } from "@playwright/test";
import { signInAsTestUser, USER_A } from "./support/auth";

// Requires a clerk-mode frontend+backend and Clerk test keys; skipped otherwise.
test.skip(
  !process.env.PENNY_E2E_CLERK,
  "set PENNY_E2E_CLERK=1 with Clerk test keys + a clerk-mode backend to run the auth e2e specs",
);

test("new-chat picker offers Individual and Joint", async ({ page }) => {
  await signInAsTestUser(page, USER_A);
  await page.getByRole("button", { name: /new chat/i }).click();
  await expect(page.getByRole("radio", { name: /individual/i })).toBeVisible();
  await expect(page.getByRole("radio", { name: /joint|household/i })).toBeVisible();
});

test("creating a joint conversation persists that mode", async ({ page }) => {
  await signInAsTestUser(page, USER_A);
  await page.getByRole("button", { name: /new chat/i }).click();
  await page.getByRole("radio", { name: /joint|household/i }).check();
  await page.getByRole("textbox", { name: /message/i }).fill("Household summary");
  await page.getByRole("button", { name: /send/i }).click();
  await expect(page.locator("[data-message-role='assistant']").last()).toBeVisible();

  // Mode is immutable server-side: reloading the conversation keeps it joint and
  // no longer offers the picker.
  await page.reload();
  await expect(page.getByText(/joint|household/i)).toBeVisible();
  await expect(page.getByRole("radio", { name: /individual/i })).toHaveCount(0);
});
