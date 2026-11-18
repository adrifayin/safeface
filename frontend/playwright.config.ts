import { defineConfig } from "@playwright/test";

// Runs against the full Compose stack (https://localhost:8443) with demo users
// created by `python scripts/init_secrets.py --demo`.
export default defineConfig({
  testDir: "./e2e",
  timeout: 6 * 60_000,
  expect: { timeout: 30_000 },
  workers: 1,
  reporter: [["list"]],
  use: {
    baseURL: process.env.SAFEFACE_URL ?? "https://localhost:8443",
    ignoreHTTPSErrors: true, // dev internal CA; production browsers trust the police CA
    trace: "retain-on-failure",
    acceptDownloads: true,
  },
});
