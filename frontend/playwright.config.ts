import path from "node:path";
import { fileURLToPath } from "node:url";
import { defineConfig } from "@playwright/test";

import { getIsolatedStackConfig } from "./e2e/stack";

const frontendRoot = path.dirname(fileURLToPath(import.meta.url));
const isolatedStack = getIsolatedStackConfig();

export default defineConfig({
  testDir: "./e2e",
  testMatch: "**/*.spec.ts",
  fullyParallel: true,
  timeout: 120_000,
  expect: {
    timeout: 10_000,
  },
  reporter: [["list"]],
  outputDir: "./test-results/playwright",
  retries: 0,
  use: {
    baseURL: isolatedStack.frontendUrl,
    headless: true,
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
    video: "retain-on-failure",
  },
  globalSetup: path.resolve(frontendRoot, "./e2e/global-setup.ts"),
  globalTeardown: path.resolve(frontendRoot, "./e2e/global-teardown.ts"),
  webServer: {
    command: "bun run dev -- --host 127.0.0.1 --port 4173 --strictPort",
    cwd: frontendRoot,
    env: {
      ...process.env,
      VITE_ADMIN_MODE: "true",
      VITE_API_URL: isolatedStack.backendUrl,
    },
    reuseExistingServer: process.env.PLAYWRIGHT_REUSE_SERVER === "1",
    timeout: 120_000,
    url: `${isolatedStack.frontendUrl}/auth/sign-in`,
  },
});
