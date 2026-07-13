import { expect, test } from "@playwright/test";
import { signInAsTestUser, USER_A } from "./support/auth";

// Requires a clerk-mode frontend+backend and Clerk test keys; skipped otherwise
// so the dev-principal harness (harness.spec.ts, chat-smoke.spec.ts) stays green.
test.skip(
  !process.env.PENNY_E2E_CLERK,
  "set PENNY_E2E_CLERK=1 with Clerk test keys + a clerk-mode backend to run the auth e2e specs",
);

test("a signed-out visitor sees the landing page and can reach sign-in", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1 })).toContainText(/Meet Penny/i);
  await expect(page.getByRole("textbox", { name: /message/i })).toHaveCount(0);

  await page.getByRole("link", { name: "Sign in" }).click();
  await expect(page.getByRole("heading", { name: /sign in/i })).toBeVisible();
});

test("sign in, send a message, get a response, sign out", async ({ page }) => {
  await signInAsTestUser(page, USER_A);
  await expect(page.getByRole("textbox", { name: /message/i })).toBeVisible();

  await page.getByRole("textbox", { name: /message/i }).fill("How much did I spend?");
  await page.getByRole("button", { name: /send/i }).click();
  await expect(page.locator("[data-message-role='assistant']").last()).toBeVisible();

  await page.getByRole("button", { name: /account|user menu/i }).click();
  await page.getByRole("menuitem", { name: /sign out/i }).click();
  await expect(page.getByRole("heading", { level: 1 })).toContainText(/Meet Penny/i);
});

test("a protected request while signed-out is rejected (no chat access)", async ({ page }) => {
  const res = await page.request.post("/api/chat", {
    data: { messages: [], sessionMode: "individual" },
  });
  expect([401, 403]).toContain(res.status());
});
