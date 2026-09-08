import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Vite config for the dummy-app React frontend.
// The built output goes to dist/ — served by Express (server.js) as static files.
// Note: in local dev you can run `npm run dev` (port 5173, proxies /api/* → 4000).
// For Playwright runs, `npm start` does `vite build && node server.js` so everything
// goes through Express on :4000 — matching the playwright.config.ts webServer block.
export default defineConfig({
  plugins: [react()],
  build: {
    outDir: "dist",
  },
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://localhost:4000",
        changeOrigin: true,
      },
    },
  },
});
