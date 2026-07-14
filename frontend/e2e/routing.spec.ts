import { expect, test } from "./fixtures/app";

/**
 * URL routing (fly-wz0): the URL is the source of truth for what's on screen.
 *
 * Runs ungated in the dev-principal harness: the backend persists the
 * conversation and the user message before streaming the assistant turn, so
 * conversation URLs, deep links, and history navigation are all assertable
 * without a live model (the assistant turn itself errors without a key, which
 * these specs never assert on).
 */

const UUID_RE = /\/c\/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;

async function sendMessage(page: import("@playwright/test").Page, text: string) {
  await page.getByRole("textbox", { name: /chat input/i }).fill(text);
  await page.getByRole("button", { name: /send/i }).click();
}

test("first send replaces / with the conversation URL, without a page load", async ({
  page,
}) => {
  await page.goto("/");
  await expect(page.getByText(/what can i help with/i)).toBeVisible();

  // Tag the window: a full page (re)load would lose this marker.
  await page.evaluate(() => {
    (window as unknown as { __penny_no_reload: boolean }).__penny_no_reload = true;
  });

  await sendMessage(page, "Routing check: first send");
  await expect(page).toHaveURL(UUID_RE);
  await expect(page.locator("[data-message-role='user']")).toContainText(
    "Routing check: first send",
  );
  const marker = await page.evaluate(
    () => (window as unknown as { __penny_no_reload?: boolean }).__penny_no_reload,
  );
  expect(marker).toBe(true);
});

test("a conversation URL is deep-linkable: a fresh load hydrates its history", async ({
  page,
}) => {
  await page.goto("/");
  await sendMessage(page, "Routing check: deep link");
  await expect(page).toHaveURL(UUID_RE);
  const conversationUrl = page.url();

  // A brand-new load of the captured URL (fresh history, no client state).
  await page.goto("about:blank");
  await page.goto(conversationUrl);
  await expect(page.locator("[data-message-role='user']")).toContainText(
    "Routing check: deep link",
  );
});

test("browser back/forward walk between conversations", async ({ page }) => {
  // Conversation A.
  await page.goto("/");
  await sendMessage(page, "Routing check: conversation A");
  await expect(page).toHaveURL(UUID_RE);
  const urlA = page.url();

  // New chat via the drawer link, then conversation B. Wait for the draft
  // screen's empty state before typing — the fill must not race the route
  // swap and land in conversation A's composer.
  await page.getByRole("button", { name: /open chat history/i }).click();
  await page.getByRole("link", { name: /new chat/i }).click();
  await expect(page).toHaveURL(/\/$/);
  await expect(page.getByText(/what can i help with/i)).toBeVisible();
  await sendMessage(page, "Routing check: conversation B");
  await expect(page).toHaveURL(UUID_RE);
  const urlB = page.url();
  expect(urlB).not.toBe(urlA);

  // Back: the / entry was replaced by /c/<b>, so back lands on conversation A.
  await page.goBack();
  await expect(page).toHaveURL(urlA);
  await expect(page.locator("[data-message-role='user']")).toContainText(
    "Routing check: conversation A",
  );

  await page.goForward();
  await expect(page).toHaveURL(urlB);
  await expect(page.locator("[data-message-role='user']")).toContainText(
    "Routing check: conversation B",
  );
});

test("an unknown conversation id shows the not-found state, not an empty chat", async ({
  page,
}) => {
  await page.goto("/c/00000000-0000-4000-8000-000000000000");
  await expect(page.getByText(/conversation not found/i)).toBeVisible();
  // No composer to message a nonexistent conversation into.
  await expect(page.getByRole("textbox", { name: /chat input/i })).toHaveCount(0);
  // The way out is a new chat.
  await page.getByRole("link", { name: /start a new chat/i }).click();
  await expect(page.getByText(/what can i help with/i)).toBeVisible();
});

test("unknown paths land on the new-chat screen", async ({ page }) => {
  await page.goto("/no/such/page");
  await expect(page).toHaveURL(/\/$/);
  await expect(page.getByText(/what can i help with/i)).toBeVisible();
});
