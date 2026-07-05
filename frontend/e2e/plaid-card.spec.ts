import { expect, test } from "./fixtures/app";

/**
 * Phase 5 inline Plaid Link card E2E.
 *
 * Asserts the `connect_bank_account` tool output renders the inline card and
 * enables its "Connect a bank" button once the hosted `link_token` is present
 * (react-plaid-link `ready`). The Plaid popup itself is a manual sandbox step
 * (Task 8, Step 3), so the spec stops at button-enabled and never clicks through
 * the hosted Link flow.
 *
 * Needs a live model (to emit the tool call) + Plaid sandbox keys in hosted
 * mode, so it is gated behind PENNY_E2E_MODEL; skipped otherwise.
 */
test.skip(
  !process.env.PENNY_E2E_MODEL,
  "set PENNY_E2E_MODEL=1 (model API key + Plaid sandbox, hosted mode) to run",
);

test("inline Plaid card renders and enables the connect button", async ({
  page,
}) => {
  await page.goto("/");

  // Prompt the agent to connect a bank so it emits the tool part.
  const composer = page.getByRole("textbox");
  await composer.fill("I want to connect my bank account");
  await composer.press("Enter");

  const card = page.locator('[data-tool="connect_bank_account"]');
  await expect(card).toBeVisible({ timeout: 60_000 });
  await expect(card).toContainText(/connect a bank/i);

  // The button is enabled once the link token is present (Plaid ready === true).
  const button = card.getByRole("button", { name: /connect a bank/i });
  await expect(button).toBeEnabled();
});
