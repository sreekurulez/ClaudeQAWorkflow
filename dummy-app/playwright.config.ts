import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./tests/e2e",
  // server.js holds all app state (items) in one shared in-memory store with a global
  // /api/__test__/reset endpoint. Two truly concurrent tests can still corrupt each other's
  // state even with per-test reset (one test's reset/writes landing mid another's run) — this
  // app was never built to be multi-tenant. Forcing serial execution is cheap insurance against
  // that, independent of whatever specific bug concurrent workers might otherwise mask or cause.
  workers: 1,
  reporter: [["json", { outputFile: "test-results/results.json" }]],
  use: {
    baseURL: "http://localhost:4000",
  },
  webServer: {
    command: "node server.js",
    port: 4000,
    reuseExistingServer: !process.env.CI,
  },
});
