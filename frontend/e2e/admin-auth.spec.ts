import { expect, test } from "@playwright/test";

import { getAdminApiKey } from "./helpers/user-flows";

test.describe.configure({ mode: "parallel" });

test("admin sign-in rejects invalid API keys", async ({ page }) => {
  await page.goto("/admin/sign-in");
  await page.getByLabel("Admin API key").fill("invalid-key");
  await page.getByRole("button", { name: "Sign in" }).click();

  await expect(page.getByText("Invalid or missing API key")).toBeVisible();
  await expect(page).toHaveURL(/\/admin\/sign-in$/);
});

test("admin sign-in accepts the configured API key and opens the control surface", async ({
  page,
}) => {
  await page.goto("/admin/sign-in");
  await page.getByLabel("Admin API key").fill(getAdminApiKey());
  await page.getByRole("button", { name: "Sign in" }).click();

  await expect(page).toHaveURL(/\/admin\/sources$/);
  await expect(page.getByText("ProxyMind Admin")).toBeVisible();
  await expect(page.getByRole("link", { name: "Chat" })).toBeVisible();

  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page).toHaveURL(/\/admin\/sign-in$/);

  await page.goto("/admin/sources");
  await expect(page).toHaveURL(/\/admin\/sign-in$/);
});
