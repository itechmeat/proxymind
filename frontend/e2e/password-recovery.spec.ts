import { test } from "@playwright/test";

import {
  buildE2eUser,
  createVerifiedUser,
  expectInvalidSignIn,
  requestPasswordReset,
  resetPassword,
  signIn,
} from "./helpers/user-flows";

test("end users can recover access with password reset", async ({
  page,
}, testInfo) => {
  const user = buildE2eUser(testInfo, "reset");
  const nextPassword = "Cycle4Reset456!";

  await createVerifiedUser(page, user);
  await requestPasswordReset(page, user.email);
  await resetPassword(page, user, nextPassword);

  await page.getByRole("button", { name: "Back to sign in" }).click();
  await expectInvalidSignIn(page, user);

  await signIn(page, {
    ...user,
    password: nextPassword,
  });
});
