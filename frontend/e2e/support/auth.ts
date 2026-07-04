/**
 * Clerk test-mode sign-in helper for the auth e2e specs (reused by phases 4/5).
 *
 * Uses @clerk/testing's Playwright utilities to mint a testing token and
 * establish a Clerk test-mode session for a seeded user — no interactive Google
 * OAuth. The test users map to the backend's seeded `users` rows (A and B in
 * household H1), so conversation scoping is exercised end-to-end.
 *
 * Requires a clerk-mode frontend+backend (VITE_CLERK_PUBLISHABLE_KEY set, the
 * backend in PENNY_AUTH_MODE=clerk against the same Clerk test instance) and
 * Clerk test keys in the environment. The specs skip when PENNY_E2E_CLERK is
 * unset, so this module is only exercised in that configuration.
 */
import { clerk, setupClerkTestingToken } from "@clerk/testing/playwright";
import type { Page } from "@playwright/test";

export interface TestUser {
  identifier: string;
  password: string;
}

export const USER_A: TestUser = {
  identifier: process.env.E2E_CLERK_USER_A_IDENTIFIER ?? "a@example.com",
  password: process.env.E2E_CLERK_USER_A_PASSWORD ?? "",
};

export const USER_B: TestUser = {
  identifier: process.env.E2E_CLERK_USER_B_IDENTIFIER ?? "b@example.com",
  password: process.env.E2E_CLERK_USER_B_PASSWORD ?? "",
};

/** Sign `user` in via a Clerk testing token, then wait for the chat shell. */
export async function signInAsTestUser(page: Page, user: TestUser): Promise<void> {
  await setupClerkTestingToken({ page });
  await page.goto("/");
  await clerk.signIn({
    page,
    signInParams: {
      strategy: "password",
      identifier: user.identifier,
      password: user.password,
    },
  });
  await page.goto("/");
  await page.getByRole("textbox", { name: /message/i }).waitFor();
}

// Clerk test-mode fixtures: a `+clerk_test` email skips real delivery and the
// fixed OTP 424242 always verifies. See Clerk's "Test emails and phones" docs.
const CLERK_TEST_OTP = "424242";

/** The password used for brand-new e2e signups (override via env if needed). */
export const NEW_USER_PASSWORD =
  process.env.E2E_CLERK_NEW_USER_PASSWORD ?? "Sup3r-Secret-Pw!";

/**
 * Drive Clerk's hosted <SignUp> form for a brand-new email through email-code
 * verification, using a Clerk testing token so no human bot-check is needed.
 * The `<SignUp>` component is the one AuthGate renders at /sign-up. Returns once
 * the app has navigated back to the authenticated shell.
 */
export async function signUpNewUser(page: Page, email: string): Promise<void> {
  await setupClerkTestingToken({ page });
  await page.goto("/sign-up");

  // Clerk's SignUp renders standard input names; fill email + password, submit.
  await page.locator('input[name="emailAddress"]').fill(email);
  await page.locator('input[name="password"]').fill(NEW_USER_PASSWORD);
  await page
    .getByRole("button", { name: /continue|sign up/i })
    .first()
    .click();

  // Email-code verification screen: the test OTP verifies immediately.
  const otp = page.locator(
    'input[name="code"], input[autocomplete="one-time-code"]',
  );
  await otp.first().waitFor();
  await otp.first().fill(CLERK_TEST_OTP);

  await page.goto("/");
}
