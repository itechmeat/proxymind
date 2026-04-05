import { execFileSync } from "node:child_process";
import path from "node:path";
import { setTimeout as delay } from "node:timers/promises";
import { fileURLToPath } from "node:url";

import {
  composeArgs,
  getIsolatedStackConfig,
  shouldResetIsolatedStack,
} from "./stack";

const repoRoot = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "../..",
);
const isolatedStack = getIsolatedStackConfig();
const backendReadyUrl = `${isolatedStack.backendUrl}/ready`;
const backendReadyTimeoutMs = 120_000;

function runDockerCompose(args: string[]) {
  return execFileSync("docker", composeArgs(args), {
    cwd: repoRoot,
    encoding: "utf8",
    stdio: ["ignore", "pipe", "pipe"],
  }).trim();
}

async function waitForBackendReady() {
  const deadline = Date.now() + backendReadyTimeoutMs;

  while (Date.now() < deadline) {
    try {
      const response = await fetch(backendReadyUrl);
      if (response.ok) {
        return;
      }
    } catch {
      // Ignore connection errors while the backend is still starting.
    }

    await delay(1_000);
  }

  throw new Error(
    `Backend did not become ready within ${backendReadyTimeoutMs}ms at ${backendReadyUrl}`,
  );
}

export default async function globalSetup() {
  const lifecycle = {
    ci: Boolean(process.env.CI),
    fresh: process.env.PLAYWRIGHT_E2E_FRESH === "1",
  };

  if (shouldResetIsolatedStack(lifecycle)) {
    runDockerCompose(["down", "-v", "--remove-orphans"]);
  }

  runDockerCompose(["up", "-d", "--build", isolatedStack.apiService]);
  await waitForBackendReady();

  const emailBackend = runDockerCompose([
    "exec",
    "-T",
    isolatedStack.apiService,
    "sh",
    "-lc",
    'printf %s "$EMAIL_BACKEND"',
  ]);

  if (emailBackend !== "console") {
    throw new Error(
      `Playwright auth e2e requires EMAIL_BACKEND=console, got ${emailBackend || "<empty>"}`,
    );
  }

  const emailOutboxDir = runDockerCompose([
    "exec",
    "-T",
    isolatedStack.apiService,
    "sh",
    "-lc",
    'printf %s "$EMAIL_OUTBOX_DIR"',
  ]);

  if (!emailOutboxDir) {
    throw new Error(
      "Playwright auth e2e requires EMAIL_OUTBOX_DIR to be configured for the isolated API stack.",
    );
  }

  runDockerCompose([
    "exec",
    "-T",
    isolatedStack.apiService,
    "sh",
    "-lc",
    'rm -rf "$EMAIL_OUTBOX_DIR" && mkdir -p "$EMAIL_OUTBOX_DIR"',
  ]);

  runDockerCompose([
    "exec",
    "-T",
    isolatedStack.apiService,
    "python",
    "-m",
    "app.scripts.seed_isolated_test_stack",
  ]);
}
