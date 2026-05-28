import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// Frontend dev server proxies /api/* to the Python backend so the browser
// talks to a single origin (no CORS) and cookies/streaming pass through.
const BACKEND_URL = process.env.BACKEND_URL ?? "http://localhost:8000";

export default defineConfig({
  plugins: [react(), tailwindcss()],
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
