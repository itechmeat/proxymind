import { expect, test } from "@playwright/test";

import {
  buildE2eUser,
  createVerifiedUser,
  expectTwinProfileLoaded,
  sendChatMessage,
  signIn,
} from "./helpers/user-flows";

test("authenticated users can bootstrap chat, send a message, and restore it after reload", async ({
  page,
}, testInfo) => {
  test.slow();

  const user = buildE2eUser(testInfo, "chat");
  const prompt = "Reply with a short hello.";

  await createVerifiedUser(page, user);
  await signIn(page, user);
  await expectTwinProfileLoaded(page);

  await sendChatMessage(page, prompt);

  await page.reload({ waitUntil: "networkidle" });
  await expect(page.getByLabel("Ask ProxyMind something...")).toBeVisible();
  await expect(page.getByText(prompt)).toBeVisible();
  await expectTwinProfileLoaded(page);
});
