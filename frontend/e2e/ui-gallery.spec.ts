import { expect, test } from "./fixtures/app";

/**
 * Guards the @penny/ui design system end to end: the dev-only /ui route renders
 * the Gallery, so this asserts (a) every primitive renders, and (b) a screen is
 * wrapped in AppShell with the palette applied — the AppShell root's computed
 * background resolves to the --paper token (rgb(250, 244, 231)), proving tokens
 * reached the DOM and the screen uses the shell.
 */

// Every primitive the Gallery mounts, by data-testid. AppShell itself is the
// #root child whose background is asserted below (its "render" proof).
const PRIMITIVES = [
  "ui-header",
  "ui-footer",
  "ui-eyebrowpill",
  "ui-logo-emblem",
  "ui-logo-flat",
  "ui-button-filled",
  "ui-button-outlined",
  "ui-chip",
  "ui-input",
  "ui-card",
  "ui-navlink",
  "ui-accent-underline",
];

test("gallery renders every primitive inside an AppShell with tokens applied", async ({ page }) => {
  await page.goto("/ui");

  for (const id of PRIMITIVES) {
    await expect(page.getByTestId(id)).toBeVisible();
  }

  // AppShell root = the single child of #root. bg-paper -> var(--color-paper).
  const appShellRoot = page.locator("#root > div");
  await expect(appShellRoot).toHaveCSS("background-color", "rgb(250, 244, 231)");
});
