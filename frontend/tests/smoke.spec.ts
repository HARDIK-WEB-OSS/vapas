import { expect, test } from "@playwright/test";

test("home page shows the product promise and the legal notice", async ({ page }) => {
  await page.goto("/");
  await expect(page).toHaveTitle("VAPAS");
  await expect(page.getByRole("heading", { level: 1, name: "VAPAS" })).toBeVisible();
  await expect(page.getByText("We never connect to your bank and never touch your money.")).toBeVisible();
  await expect(page.getByText("This is not legal advice.")).toBeVisible();
});

test("home page fits a phone screen without horizontal scroll", async ({ page }) => {
  await page.goto("/");
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow).toBeLessThanOrEqual(0);
});
