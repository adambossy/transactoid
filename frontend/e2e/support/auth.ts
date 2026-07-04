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
