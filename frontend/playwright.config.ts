import { defineConfig } from "@playwright/test";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

/**
 * E2E harness: boots the real backend on dedicated ports (backend :8100,
 * vite :5175) so it never collides with a developer's own servers. Runs in dev-principal mode with throwaway SQLite
 * finance + web DBs under test-results/, then drives
 * a headless chromium against the SPA. Phase 1a owns this bootstrap; later
 * phases only add feature specs on top of e2e/fixtures/app.ts.
 */

const BACKEND_DIR = path.resolve(__dirname, "../backend");
const E2E_DB_DIR = path.resolve(__dirname, "test-results");

// The same well-known dev principal the backend test suite uses.
const DEV_USER_ID = "11111111-1111-1111-1111-111111111111";
const DEV_HOUSEHOLD_ID = "22222222-2222-2222-2222-222222222222";

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  use: {
    baseURL: "http://127.0.0.1:5175",
  },
  projects: [{ name: "chromium", use: { browserName: "chromium" } }],
  webServer: [
    {
      command: `sh -c 'mkdir -p "${E2E_DB_DIR}" && uv run uvicorn penny.api.main:app --host 127.0.0.1 --port 8100'`,
      cwd: BACKEND_DIR,
      url: "http://127.0.0.1:8100/api/health",
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
      env: {
        DATABASE_URL: `sqlite:///${E2E_DB_DIR}/penny-e2e.db`,
        PENNY_WEB_DATABASE_URL: `sqlite:///${E2E_DB_DIR}/penny-e2e-web.db`,
        // The backend defaults to fail-closed clerk mode (phase 2); the default
        // harness runs dev-principal. Overridable so the gated Clerk auth specs
        // (PENNY_E2E_CLERK=1) can force clerk mode with real Clerk env.
        PENNY_AUTH_MODE: process.env.PENNY_AUTH_MODE ?? "dev",
        PENNY_DEV_USER_ID: DEV_USER_ID,
        PENNY_DEV_HOUSEHOLD_ID: DEV_HOUSEHOLD_ID,
        PENNY_DEV_SESSION_MODE: "individual",
        PENNY_LANGFUSE_ENABLED: "false",
      },
    },
    {
      command: "npm run dev -- --port 5175",
      url: "http://127.0.0.1:5175",
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
      env: {
        // Point the E2E vite proxy at the E2E backend (dev setups often
        // have their own server on :8000).
        BACKEND_URL: "http://127.0.0.1:8100",
        // CI has no ~/code/agent-ui checkout; resolve the published npm package
        // instead of the source alias (matches vite.config's AGENT_UI_USE_PUBLISHED).
        AGENT_UI_USE_PUBLISHED: process.env.CI
          ? "1"
          : (process.env.AGENT_UI_USE_PUBLISHED ?? "0"),
        // Clerk publishable key for the auth e2e specs. Empty in the default
        // dev-principal harness (the app then sends no bearer token); set it
        // (with PENNY_E2E_CLERK=1 + a clerk-mode backend) to run auth.spec.ts.
        VITE_CLERK_PUBLISHABLE_KEY: process.env.VITE_CLERK_PUBLISHABLE_KEY ?? "",
      },
    },
  ],
});
