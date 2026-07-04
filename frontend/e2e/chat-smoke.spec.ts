import { expect, test } from "./fixtures/app";

/**
 * Proves the phase-1a tenancy layer left the loading → sending → streaming
 * flow intact through the real UI. Needs a live model (the backend streams a
 * real agent response), so it is gated: set PENNY_E2E_MODEL=1 (with the
 * model API key exported) to run it; skipped otherwise.
 */
test("user sends a chat message and an assistant response streams in", async ({ page }) => {
  test.skip(
    !process.env.PENNY_E2E_MODEL,
    "set PENNY_E2E_MODEL=1 (with a model API key in the env) to run the chat smoke test",
  );
  await page.goto("/");
  const composer = page.getByRole("textbox");
  await composer.fill("Hello Penny, are you there?");
  await composer.press("Enter");

  // user message shows immediately
  await expect(page.getByText("Hello Penny, are you there?")).toBeVisible();

  // an assistant message streams in and ends up non-empty
  const assistant = page.locator('[data-role="assistant"]').last();
  await expect(assistant).toBeVisible({ timeout: 60_000 });
  await expect(assistant).not.toBeEmpty();
});
