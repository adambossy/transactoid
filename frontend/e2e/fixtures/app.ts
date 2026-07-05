/**
 * Shared E2E fixture: re-exports Playwright's test/expect against the app
 * booted by playwright.config.ts (backend in dev-principal mode + vite).
 *
 * The backend runs with PENNY_DEV_USER_ID / PENNY_DEV_HOUSEHOLD_ID pinned to
 * a seeded dev household, so every browser request is tenant-scoped without
 * real auth. Later phases extend this fixture rather than re-wiring servers.
 *
 * TODO(phase 2+): add signInWithClerkTestToken(page) here once real auth
 * lands; phase 1a deliberately ships the dev-principal path only.
 */
export { expect, test } from "@playwright/test";
