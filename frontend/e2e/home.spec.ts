import { expect, test } from "./fixtures/app";

/**
 * Guards the logged-out landing page via the dev-only /home preview route
 * (same pattern as /ui): it renders without Clerk, so the dev-principal
 * harness covers it. Clerk-mode signed-out behavior at `/` is auth.spec.ts.
 */
test("landing page renders hero with sign-up CTAs", async ({ page }) => {
  await page.goto("/home");

  await expect(page.getByRole("heading", { level: 1 })).toContainText(/Meet Penny/i);
  // Header CTAs route to the auth screens.
  await expect(page.getByRole("link", { name: "Meet Penny" })).toHaveAttribute("href", "/sign-up");
  await expect(page.getByRole("link", { name: "Sign in" })).toHaveAttribute("href", "/sign-in");
  // Hero input affordance is present.
  await expect(page.getByRole("button", { name: "Ask Penny" })).toBeVisible();
});
