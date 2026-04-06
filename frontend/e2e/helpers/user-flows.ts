import { execFileSync } from "node:child_process";
import { randomUUID } from "node:crypto";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { expect, type Page, type TestInfo } from "@playwright/test";

import { composeArgs, getIsolatedStackConfig } from "../stack";

const repoRoot = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "../../..",
);
const isolatedStack = getIsolatedStackConfig();
const tokenWaitTimeoutMs = 20_000;

export interface E2eUser {
  displayName: string;
  email: string;
  password: string;
}

interface EmailOutboxEntry {
  html_body: string;
  links: Array<{
    route_path: string;
    token: string;
  }>;
  subject: string;
  to: string;
}

let cachedAdminApiKey: string | null = null;

function getE2ePassword(): string {
  const password = process.env.E2E_TEST_PASSWORD?.trim();
  if (!password) {
    throw new Error(
      "E2E_TEST_PASSWORD must be set before running Playwright auth flows.",
    );
  }
  return password;
}

function runDockerCompose(args: string[]) {
  return execFileSync("docker", composeArgs(args), {
    cwd: repoRoot,
    encoding: "utf8",
    stdio: ["ignore", "pipe", "pipe"],
  }).trim();
}

function sleep(milliseconds: number) {
  return new Promise((resolve) => {
    setTimeout(resolve, milliseconds);
  });
}

function slugify(value: string) {
  return value
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 24);
}

export function buildE2eUser(testInfo: TestInfo, scope: string): E2eUser {
  const id = `${slugify(scope)}-${testInfo.workerIndex}-${randomUUID().slice(0, 8)}`;

  return {
    displayName: `E2E ${scope}`,
    email: `${id}@example.com`,
    password: getE2ePassword(),
  };
}

export async function expectOnSignInPage(page: Page) {
  await expect(page).toHaveURL(/\/auth\/sign-in$/);
  await expect(
    page.getByRole("heading", {
      name: "Return to your private twin workspace.",
    }),
  ).toBeVisible();
}

export async function registerUser(page: Page, user: E2eUser) {
  await page.goto("/auth/register");
  await page.getByLabel("Display name").fill(user.displayName);
  await page.getByLabel("Email").fill(user.email);
  await page.getByLabel("Password", { exact: true }).fill(user.password);
  await page.getByLabel("Confirm password").fill(user.password);
  await page.getByRole("button", { name: "Create account" }).click();

  await expect(
    page.getByText("Check your email to verify your account."),
  ).toBeVisible();
}

function readEmailOutboxEntries(): EmailOutboxEntry[] {
  const raw = runDockerCompose([
    "exec",
    "-T",
    isolatedStack.apiService,
    "python",
    "-c",
    [
      "import os, pathlib",
      'outbox = os.environ.get("EMAIL_OUTBOX_DIR")',
      "path = pathlib.Path(outbox) if outbox else None",
      "entries = sorted(path.glob('*.json')) if path and path.exists() else []",
      "for entry in entries:",
      "    print(entry.read_text())",
    ].join("\n"),
  ]);

  if (!raw) {
    return [];
  }

  return raw
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => JSON.parse(line) as EmailOutboxEntry);
}

async function waitForToken(email: string, routePath: string) {
  const deadline = Date.now() + tokenWaitTimeoutMs;

  while (Date.now() < deadline) {
    const entry = readEmailOutboxEntries()
      .reverse()
      .find((candidate) => candidate.to === email);
    const link = entry?.links.find(
      (candidate) => candidate.route_path === routePath,
    );

    if (link?.token) {
      return link.token;
    }

    await sleep(1_000);
  }

  throw new Error(
    `Token for ${routePath} and ${email} was not found in the email outbox.`,
  );
}

export async function verifyUserEmail(page: Page, user: E2eUser) {
  const token = await waitForToken(user.email, "/auth/verify-email");
  await page.goto(`/auth/verify-email?token=${token}`);

  await expect(page.getByText("Email verified successfully.")).toBeVisible();
}

export async function signIn(page: Page, user: E2eUser) {
  await page.goto("/auth/sign-in");
  await page.getByLabel("Email").fill(user.email);
  await page.getByLabel("Password").fill(user.password);
  await page.getByRole("button", { name: "Sign in" }).click();

  await expect(page).toHaveURL(/\/$/);
  await expect(page.getByLabel("Ask ProxyMind something...")).toBeVisible();
  await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();
}

export async function expectInvalidSignIn(page: Page, user: E2eUser) {
  await page.goto("/auth/sign-in");
  await page.getByLabel("Email").fill(user.email);
  await page.getByLabel("Password").fill(user.password);
  await page.getByRole("button", { name: "Sign in" }).click();

  await expect(page.getByText("Invalid email or password")).toBeVisible();
}

export async function requestPasswordReset(page: Page, email: string) {
  await page.goto("/auth/forgot-password");
  await page.getByLabel("Email").fill(email);
  await page.getByRole("button", { name: "Send reset link" }).click();

  await expect(
    page.getByText("If the account exists, reset instructions have been sent."),
  ).toBeVisible();
}

export async function resetPassword(
  page: Page,
  user: E2eUser,
  nextPassword: string,
) {
  const token = await waitForToken(user.email, "/auth/reset-password");
  await page.goto(`/auth/reset-password?token=${token}`);
  await page.getByLabel("New password").fill(nextPassword);
  await page.getByLabel("Confirm password").fill(nextPassword);
  await page.getByRole("button", { name: "Reset password" }).click();

  await expect(page.getByText("Password reset successfully.")).toBeVisible();
}

export async function createVerifiedUser(page: Page, user: E2eUser) {
  await registerUser(page, user);
  await verifyUserEmail(page, user);
}

export async function sendChatMessage(page: Page, message: string) {
  const userMessages = page.locator('article[data-role="user"]');
  const assistantMessages = page.locator('article[data-role="assistant"]');
  const beforeUserCount = await userMessages.count();
  const beforeAssistantCount = await assistantMessages.count();

  await page.getByLabel("Ask ProxyMind something...").fill(message);
  await page.getByRole("button", { name: "Send" }).click();

  await expect(userMessages).toHaveCount(beforeUserCount + 1);
  await expect(userMessages.nth(beforeUserCount)).toContainText(message);

  await expect
    .poll(async () => assistantMessages.count(), {
      timeout: 60_000,
    })
    .toBeGreaterThan(beforeAssistantCount);

  await expect(assistantMessages.nth(beforeAssistantCount)).not.toHaveAttribute(
    "data-state",
    "failed",
  );
}

export async function expectTwinProfileLoaded(page: Page) {
  const twinName = page.locator(".chat-header__name");
  await expect(page.getByText("Live chat")).toBeVisible();
  await expect(twinName).toBeVisible();
  await expect(twinName).not.toHaveText("");
  await expect(page.locator(".chat-header__avatar")).toBeVisible();
}

export function getAdminApiKey() {
  if (cachedAdminApiKey) {
    return cachedAdminApiKey;
  }

  const key = runDockerCompose([
    "exec",
    "-T",
    isolatedStack.apiService,
    "sh",
    "-lc",
    'printf %s "$ADMIN_API_KEY"',
  ]);

  if (!key) {
    throw new Error(
      "ADMIN_API_KEY is not configured in the running API container.",
    );
  }

  cachedAdminApiKey = key;
  return key;
}
