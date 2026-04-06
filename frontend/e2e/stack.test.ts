import { describe, expect, it } from "vitest";

import {
  composeArgs,
  getIsolatedStackConfig,
  shouldResetIsolatedStack,
  shouldTearDownIsolatedStack,
} from "./stack";

describe("isolated E2E stack config", () => {
  it("builds docker compose args with a dedicated isolated namespace", () => {
    expect(composeArgs(["up", "-d", "api-e2e"])).toEqual([
      "compose",
      "-p",
      "proxymind-e2e",
      "-f",
      "docker-compose.yml",
      "-f",
      "docker-compose.e2e.yml",
      "up",
      "-d",
      "api-e2e",
    ]);
  });

  it("uses the isolated backend service names and urls", () => {
    expect(getIsolatedStackConfig()).toMatchObject({
      apiService: "api-e2e",
      backendTestService: "backend-test-e2e",
      backendUrl: "http://127.0.0.1:18001",
      frontendUrl: "http://127.0.0.1:4173",
      projectName: "proxymind-e2e",
    });
  });

  it("reuses the stack locally by default", () => {
    expect(shouldResetIsolatedStack({ ci: false })).toBe(false);
    expect(shouldTearDownIsolatedStack({ ci: false })).toBe(false);
  });

  it("forces a fresh stack lifecycle in CI", () => {
    expect(shouldResetIsolatedStack({ ci: true })).toBe(true);
    expect(shouldTearDownIsolatedStack({ ci: true })).toBe(true);
  });

  it("allows local callers to opt into a fresh stack", () => {
    expect(shouldResetIsolatedStack({ ci: false, fresh: true })).toBe(true);
    expect(shouldTearDownIsolatedStack({ ci: false, fresh: true })).toBe(false);
  });
});
