import { expect, test } from "@playwright/test";

test("root redirects to English and shows the promise and the legal notice", async ({ page }) => {
  await page.goto("/");
  await expect(page).toHaveURL(/\/en$/);
  await expect(page).toHaveTitle("VAPAS");
  await expect(page.getByRole("heading", { level: 1 })).toContainText("₹100");
  await expect(page.getByText("We never connect to your bank and never touch your money.")).toBeVisible();
  await expect(page.getByText("This is not legal advice.")).toBeVisible();
});

test.describe("Hindi browser", () => {
  test.use({ locale: "hi-IN", extraHTTPHeaders: { "Accept-Language": "hi-IN,hi;q=0.9" } });

  test("lands on the Hindi page and can switch to English", async ({ page }) => {
    await page.goto("/");
    await expect(page).toHaveURL(/\/hi$/);
    await expect(page.locator("html")).toHaveAttribute("lang", "hi");
    await expect(page.getByText("यह कानूनी सलाह नहीं है।")).toBeVisible();
    await page.getByRole("link", { name: "English" }).click();
    await expect(page).toHaveURL(/\/en$/);
  });
});

test("email links without a language keep their token", async ({ page }) => {
  await page.goto("/reset-password#token=abcdefghijkl");
  await expect(page).toHaveURL(/\/en\/reset-password/);
  await expect(page.getByRole("heading", { name: "Choose a new password" })).toBeVisible();
});

for (const path of ["/en", "/hi", "/en/guide", "/en/signup", "/en/login", "/hi/privacy", "/en/terms"]) {
  test(`${path} fits a phone screen without horizontal scroll`, async ({ page }) => {
    await page.goto(path);
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    expect(overflow).toBeLessThanOrEqual(0);
  });
}

test("pages are served with security headers", async ({ request }) => {
  const response = await request.get("/en");
  const headers = response.headers();
  expect(headers["x-frame-options"]).toBe("DENY");
  expect(headers["x-content-type-options"]).toBe("nosniff");
  expect(headers["content-security-policy"]).toContain("frame-ancestors 'none'");
  expect(headers["content-security-policy"]).toContain("connect-src 'self' http://127.0.0.1:8000 http://127.0.0.1:8333");
});
