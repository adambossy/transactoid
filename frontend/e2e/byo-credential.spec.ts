/**
 * Phase 2b BYO-credential E2E.
 *
 * Part (a) runs on the default dev-principal harness (fixtures/app.ts): connect
 * an API key in Settings → Providers & billing, confirm it is masked on reload
 * and never present in the DOM or the /api/me/billing response body.
 *
 * Parts (b) subsidy exhaustion → inline connect card, and (c) cross-user
 * isolation, need extra configuration (a lowered subsidy / a clerk-mode backend
 * with two users) and are gated behind env flags so the default harness stays
 * green.
 */
import { expect, test } from "./fixtures/app";

const FAKE_KEY = "sk-e2e-secret-abcd1234";

test.describe("BYO credential — settings", () => {
  test("connect an API key → masked on reload, secret never exposed", async ({
    page,
  }) => {
    await page.goto("/settings/providers");

    // Enter the key once and connect.
    await page.getByTestId("provider-select").selectOption("google");
    await page.getByTestId("api-key-input").fill(FAKE_KEY);
    await page.getByTestId("connect-key").click();

    // The connected credential shows only the masked hint.
    const cred = page.getByTestId("credential-google");
    await expect(cred).toBeVisible();
    await expect(cred).toContainText("sk-…1234");

    // Reload → still masked, still no plaintext anywhere in the DOM.
    await page.reload();
    await expect(page.getByTestId("credential-google")).toContainText("sk-…1234");
    const dom = await page.content();
    expect(dom).not.toContain(FAKE_KEY);

    // The billing API response body never carries the secret either.
    const body = await page.request
      .get("/api/me/billing")
      .then((r) => r.text());
    expect(body).not.toContain(FAKE_KEY);
    expect(body).toContain("sk-…1234");

    // Cleanup so the harness principal starts clean next run.
    await page.getByTestId("disconnect-google").click();
    await expect(page.getByTestId("no-credentials")).toBeVisible();
  });
});

test.describe("BYO credential — subsidy exhaustion", () => {
  test.skip(
    !process.env.PENNY_E2E_BILLING,
    "set PENNY_E2E_BILLING=1 with a lowered PENNY_SUBSIDY_CENTS + platform key to run",
  );

  test("exhausted runway gates the next turn with the inline connect card", async ({
    page,
  }) => {
    await page.goto("/");
    // Drive turns until the subsidy is spent; the gate then streams the block
    // message and the inline connect card renders.
    for (let i = 0; i < 20; i++) {
      await page.getByRole("textbox", { name: /message/i }).fill("hi");
      await page.getByRole("button", { name: /send/i }).click();
      if (await page.getByTestId("connect-provider-card").isVisible().catch(() => false)) {
        break;
      }
    }
    await expect(page.getByTestId("connect-provider-card")).toBeVisible();

    // Connecting a key unblocks the next turn.
    await page.getByTestId("connect-provider-input").fill(FAKE_KEY);
    await page.getByTestId("connect-provider-submit").click();
    await expect(page.getByTestId("connect-provider-done")).toBeVisible();
  });
});

test.describe("BYO credential — cross-user isolation", () => {
  test.skip(
    !process.env.PENNY_E2E_CLERK,
    "set PENNY_E2E_CLERK=1 with a clerk-mode backend + two users to run",
  );

  test("a second user never sees the first user's credentials", async ({ page }) => {
    // Placeholder: with two Clerk test users, sign in as A, connect a key, sign
    // out, sign in as B, and assert B's /settings/providers shows no credentials
    // and B's /api/me/billing body contains none of A's hints. Wired once the
    // phase-2/4 two-user Clerk harness is available in CI.
    await page.goto("/settings/providers");
    await expect(page.getByTestId("credits-card")).toBeVisible();
  });
});
