import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import path from "node:path";

// Frontend dev server proxies /api/* to the Python backend so the browser
// talks to a single origin (no CORS) and cookies/streaming pass through.
const BACKEND_URL = process.env.BACKEND_URL ?? "http://localhost:8000";

// Resolve @adambossy/agent-ui to the local source checkout so edits in
// ~/code/agent-ui hot-reload into Penny. Mirrors the alias the playground
// uses internally. Set AGENT_UI_USE_VENDOR=1 to fall back to the vendored
// tarball under node_modules (useful for CI / production builds).
const AGENT_UI_SRC = path.resolve(
  process.env.AGENT_UI_PATH ?? path.resolve(import.meta.dirname, "../../../../../agent-ui/packages/agent-ui"),
  "src",
);
const useVendor = process.env.AGENT_UI_USE_VENDOR === "1";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: useVendor
      ? []
      : [
          {
            find: "@adambossy/agent-ui/styles.css",
            replacement: path.join(AGENT_UI_SRC, "styles.css"),
          },
          { find: "@adambossy/agent-ui", replacement: path.join(AGENT_UI_SRC, "index.ts") },
        ],
  },
  server: {
    port: 5173,
    host: true,
    proxy: {
      "/api": {
        target: BACKEND_URL,
        changeOrigin: true,
        ws: false,
      },
    },
  },
});
