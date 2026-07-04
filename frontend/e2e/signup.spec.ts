/**
 * Phase 4 E2E — self-serve signup lands in a solo household.
 *
 * A brand-new Clerk test user who signs up is auto-provisioned an isolated solo
 * household whose name (`<email-local-part>'s household`) renders in the header.
 * Driven with Clerk testing tokens so signup runs headless without a human
 * solving a bot check. Requires a clerk-mode frontend+backend against the same
 * Clerk test instance (PENNY_E2E_CLERK), skipped otherwise so the dev-principal
 * harness stays green.
 */
import { expect, test } from "@playwright/test";
import { signUpNewUser } from "./support/auth";

test.skip(
  !process.env.PENNY_E2E_CLERK,
  "set PENNY_E2E_CLERK=1 with Clerk test keys + a clerk-mode backend to run the signup e2e spec",
);

test("a brand-new signup lands in its own solo household", async ({ page }) => {
  // A `+clerk_test` local part keeps the local-part → household-name mapping
  // simple and lets Clerk test-mode verify without real email delivery.
  const local = `signup${Date.now()}+clerk_test`;
  const email = `${local}@example.com`;

  // Drive Clerk's <SignUp> for a brand-new email through test verification.
  await signUpNewUser(page, email);

  // The app resolves /api/me (first call triggers provisioning) and shows the
  // derived household name in the header.
  await expect(page.getByTestId("household-name")).toHaveText(`${local}'s household`);

  // /api/me itself resolves a household for this fresh identity.
  const me = await page.request.get("/api/me").then((r) => r.json());
  expect(me.household_name).toBe(`${local}'s household`);
  expect(me.email).toBe(email);
});
