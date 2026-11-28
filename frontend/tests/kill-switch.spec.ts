import { expect, test, type Page } from "@playwright/test";
import en from "../messages/en.json" with { type: "json" };
import hi from "../messages/hi.json" with { type: "json" };

const NOTICE = { version: "test-1", text_en: "Synthetic notice.", text_hi: "Synthetic notice." };

async function pauseSignup(page: Page): Promise<void> {
  await page.route("**/consent/notice", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(NOTICE) }),
  );
  await page.route("**/auth/signup", (route) =>
    route.fulfill({
      status: 503,
      contentType: "application/json",
      body: '{"error":"service_paused","message":"New signups and uploads are paused."}',
    }),
  );
}

for (const [lang, messages] of [
  ["en", en],
  ["hi", hi],
] as const) {
  test(`signup while paused shows the ${lang} kill-switch message`, async ({ page }) => {
    await pauseSignup(page);
    await page.goto(`/${lang}/signup`);
    await page.getByLabel(messages.auth.email, { exact: true }).fill("asha@example.in");
    await page.getByLabel(messages.auth.password, { exact: true }).fill("a-long-synthetic-password");
    const invite = page.getByLabel(messages.auth.inviteCode);
    if (await invite.count()) await invite.fill("ABCD-EFGH-JKMN-PQRS");
    await page.getByLabel(messages.auth.consentLabel).check();
    await page.getByRole("button", { name: messages.auth.signupButton }).click();
    await expect(page.getByText(messages.errors.service_paused)).toBeVisible();
  });
}
