/**
 * Phase 4 E2E — invite a new email; a second context joins the same household.
 *
 * (1) An existing member invites a brand-new email → it appears in the pending
 * list; a second browser context that signs up as that email lands in the
 * inviter's household (not a fresh solo one). (2) Inviting an already-active
 * email surfaces the 409 "start fresh" message instead of adding a pending row.
 *
 * Driven with Clerk testing tokens; requires a clerk-mode frontend+backend
 * (PENNY_E2E_CLERK), skipped otherwise so the dev-principal harness stays green.
 */
import { expect, test } from "@playwright/test";
import { signInAsTestUser, signUpNewUser, USER_A } from "./support/auth";

test.skip(
  !process.env.PENNY_E2E_CLERK,
  "set PENNY_E2E_CLERK=1 with Clerk test keys + a clerk-mode backend to run the invite e2e spec",
);

test("an invited new email joins the inviter's household", async ({ browser }) => {
  const invited = `invitee${Date.now()}+clerk_test@example.com`;

  // Context A: an existing member invites a brand-new email.
  const ctxA = await browser.newContext();
  const a = await ctxA.newPage();
  await signInAsTestUser(a, USER_A);
  const inviterHousehold = await a.getByTestId("household-name").innerText();

  await a.goto("/invites");
  await a.getByTestId("invite-email-input").fill(invited);
  await a.getByTestId("send-invite").click();
  await expect(a.getByTestId("pending-invite").filter({ hasText: invited })).toBeVisible();

  // Context B: the invited email signs up and lands in the SAME household.
  const ctxB = await browser.newContext();
  const b = await ctxB.newPage();
  await signUpNewUser(b, invited);
  await expect(b.getByTestId("household-name")).toHaveText(inviterHousehold);

  await ctxA.close();
  await ctxB.close();
});

test("inviting an already-active email shows the start-fresh 409 message", async ({
  page,
}) => {
  await signInAsTestUser(page, USER_A);
  await page.goto("/invites");

  // USER_B is an existing active account — inviting it is rejected with the
  // start-fresh copy rather than adding a pending row.
  const activeEmail = process.env.E2E_CLERK_USER_B_IDENTIFIER ?? "b@example.com";
  await page.getByTestId("invite-email-input").fill(activeEmail);
  await page.getByTestId("send-invite").click();

  await expect(page.getByTestId("invite-error")).toContainText(
    "sign up with a new account",
  );
  await expect(
    page.getByTestId("pending-invite").filter({ hasText: activeEmail }),
  ).toHaveCount(0);
});
