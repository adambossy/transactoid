import { expect, test } from "@playwright/test";
import { signInAsTestUser, USER_A, USER_B } from "./support/auth";

// Requires a clerk-mode frontend+backend and Clerk test keys; skipped otherwise.
test.skip(
  !process.env.PENNY_E2E_CLERK,
  "set PENNY_E2E_CLERK=1 with Clerk test keys + a clerk-mode backend to run the auth e2e specs",
);

test("user B cannot open user A's individual conversation URL", async ({ browser }) => {
  // Context A: create an individual conversation, capture its id/URL.
  const ctxA = await browser.newContext();
  const pageA = await ctxA.newPage();
  await signInAsTestUser(pageA, USER_A);
  await pageA.getByRole("textbox", { name: /message/i }).fill("Private note");
  await pageA.getByRole("button", { name: /send/i }).click();
  await expect(pageA.locator("[data-message-role='assistant']").last()).toBeVisible();
  const privateUrl = pageA.url(); // /c/<conversation-id>

  // Context B: a different signed-in user cannot open A's individual thread.
  const ctxB = await browser.newContext();
  const pageB = await ctxB.newPage();
  await signInAsTestUser(pageB, USER_B);
  await pageB.goto(privateUrl);
  await expect(pageB.getByText(/not found|no access|404/i)).toBeVisible();
  await expect(pageB.locator("[data-message-role='assistant']")).toHaveCount(0);

  await ctxA.close();
  await ctxB.close();
});
