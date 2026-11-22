import { expect, test, type Page, type Route } from "@playwright/test";

const VERIFY = "**/auth/verify-email";
const UNREACHABLE = "Can't reach the server. Your link is still valid; please try again.";

type Answer = "ok" | "network" | "server_error" | "used";

async function answerWith(page: Page, answers: Answer[]): Promise<() => number> {
  let calls = 0;
  await page.route(VERIFY, async (route: Route) => {
    const answer = answers[Math.min(calls, answers.length - 1)];
    calls += 1;
    if (answer === "network") return route.abort("connectionrefused");
    if (answer === "server_error") return route.fulfill({ status: 503, contentType: "application/json", body: '{"error":"temporarily_unavailable"}' });
    if (answer === "used") return route.fulfill({ status: 400, contentType: "application/json", body: '{"error":"invalid_token"}' });
    return route.fulfill({ status: 200, contentType: "application/json", body: '{"status":"verified"}' });
  });
  return () => calls;
}

async function settle(page: Page) {
  await page.waitForTimeout(1500);
}

test("the verify endpoint is called exactly once", async ({ page }) => {
  const calls = await answerWith(page, ["ok"]);
  await page.goto("/en/verify-email#token=abc123token");
  await expect(page.getByText("Your email is verified.")).toBeVisible();
  await settle(page);
  expect(calls()).toBe(1);
  await expect(page).not.toHaveURL(/token=/);
});

test("a network error says the server is unreachable, and retrying works", async ({ page }) => {
  const calls = await answerWith(page, ["network", "ok"]);
  await page.goto("/en/verify-email#token=abc123token");
  await expect(page.getByText(UNREACHABLE)).toBeVisible();
  await expect(page.getByText("This link has expired or was already used.")).toHaveCount(0);
  expect(calls()).toBe(1);
  await page.getByRole("button", { name: "Try again" }).click();
  await expect(page.getByText("Your email is verified.")).toBeVisible();
  expect(calls()).toBe(2);
});

test("a 5xx says the server is unreachable", async ({ page }) => {
  await answerWith(page, ["server_error"]);
  await page.goto("/en/verify-email#token=abc123token");
  await expect(page.getByText(UNREACHABLE)).toBeVisible();
});

test("a used or expired link still says so", async ({ page }) => {
  await answerWith(page, ["used"]);
  await page.goto("/en/verify-email#token=abc123token");
  await expect(page.getByText("This link has expired or was already used.")).toBeVisible();
});

test("a retry that finds the link used suggests logging in", async ({ page }) => {
  await answerWith(page, ["network", "used"]);
  await page.goto("/en/verify-email#token=abc123token");
  await page.getByRole("button", { name: "Try again" }).click();
  await expect(page.getByText(/your email is probably verified already/)).toBeVisible();
});

test("Hindi page shows the Hindi unreachable message", async ({ page }) => {
  await answerWith(page, ["network"]);
  await page.goto("/hi/verify-email#token=abc123token");
  await expect(page.getByText("सर्वर से संपर्क नहीं हो पा रहा है।", { exact: false })).toBeVisible();
});
