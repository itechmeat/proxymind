import { execFileSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { composeArgs, shouldTearDownIsolatedStack } from "./stack";

const repoRoot = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "../..",
);

function runDockerCompose(args: string[]) {
  return execFileSync("docker", composeArgs(args), {
    cwd: repoRoot,
    encoding: "utf8",
    stdio: ["ignore", "pipe", "pipe"],
  }).trim();
}

export default async function globalTeardown() {
  if (
    !shouldTearDownIsolatedStack({
      ci: Boolean(process.env.CI),
      fresh: process.env.PLAYWRIGHT_E2E_FRESH === "1",
    })
  ) {
    return;
  }

  runDockerCompose(["down", "-v", "--remove-orphans"]);
}
