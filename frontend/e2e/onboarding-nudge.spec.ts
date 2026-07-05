import { expect, test } from "./fixtures/app";

/**
 * Phase 5 onboarding-nudge E2E.
 *
 * The signed-in dev-principal user starts with no linked banks, so the first
 * agent turn should nudge to connect one and render the inline
 * `connect_bank_account` card. The Plaid-hosted popup can't be driven headlessly
 * (that link-through is a manual sandbox step), so this spec stubs
 * `POST /api/plaid/exchange` and drives the card's success path via the
 * `window.__pennyPlaidExchange` test hook, then asserts the nudge stops.
 *
 * Needs a live model to produce the nudge + tool call, so it is gated behind
 * PENNY_E2E_MODEL (with the model API key + Plaid sandbox keys +
 * PENNY_PLAID_LINK_MODE=hosted in the env); skipped otherwise so the default
 * suite stays green.
 */
test.skip(
  !process.env.PENNY_E2E_MODEL,
  "set PENNY_E2E_MODEL=1 (model API key + Plaid sandbox, hosted mode) to run",
);

test("first turn nudges to connect a bank; card renders; nudge stops after link", async ({
  page,
}) => {
  await page.goto("/");

  // First message → the agent nudges to connect a bank.
  const composer = page.getByRole("textbox");
  await composer.fill("hi");
  await composer.press("Enter");

  const assistant = page.locator('[data-role="assistant"]').last();
  await expect(assistant).toBeVisible({ timeout: 60_000 });
  await expect(assistant).toContainText(/connect .*bank/i);

  // The inline connect card renders with its Connect-a-bank button.
  const card = page.locator('[data-tool="connect_bank_account"]');
  await expect(card).toBeVisible();
  await expect(
    card.getByRole("button", { name: /connect a bank/i }),
  ).toBeVisible();

  // Stub the server exchange and drive the card's success path without the
  // real Plaid popup.
  await page.route("**/api/plaid/exchange", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ item_id: "item-e2e", accounts: 2 }),
    }),
  );
  await page.evaluate(() => {
    (
      window as unknown as { __pennyPlaidExchange?: (pt?: string) => void }
    ).__pennyPlaidExchange?.("public-e2e");
  });
  await expect(page.getByTestId("plaid-card")).toContainText(/linked|syncing/i);

  // A follow-up turn confirms the link and does NOT re-nudge / re-render a card.
  await composer.fill("thanks");
  await composer.press("Enter");
  const confirm = page.locator('[data-role="assistant"]').last();
  await expect(confirm).toBeVisible({ timeout: 60_000 });
  await expect(confirm).toContainText(/linked|connected/i);
  await expect(page.locator('[data-tool="connect_bank_account"]')).toHaveCount(1);
});
