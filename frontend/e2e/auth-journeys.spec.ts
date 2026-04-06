import { expect, test } from "@playwright/test";

import {
  buildE2eUser,
  createVerifiedUser,
  expectOnSignInPage,
  signIn,
} from "./helpers/user-flows";

test.describe.configure({ mode: "parallel" });

test("anonymous visitors are redirected to sign-in", async ({ page }) => {
  await page.goto("/");
  await expectOnSignInPage(page);
});

test("end users can register, verify email, sign in, and sign out", async ({
  page,
}, testInfo) => {
  const user = buildE2eUser(testInfo, "register");

  await page.goto("/");
  await expectOnSignInPage(page);

  await createVerifiedUser(page, user);
  await signIn(page, user);
  const firstSessionId = await page.evaluate(() =>
    localStorage.getItem("proxymind_session_id"),
  );

  await page.getByRole("button", { name: "Sign out" }).click();
  await expectOnSignInPage(page);
  await expect
    .poll(async () =>
      page.evaluate(() => localStorage.getItem("proxymind_session_id")),
    )
    .toBeNull();

  await signIn(page, user);
  const secondSessionId = await page.evaluate(() =>
    localStorage.getItem("proxymind_session_id"),
  );

  expect(firstSessionId).toBeTruthy();
  expect(secondSessionId).toBeTruthy();
  expect(secondSessionId).not.toBe(firstSessionId);
});
