import { existsSync, readdirSync, readFileSync } from "node:fs";
import path from "node:path";

import { expect, test, type Page } from "@playwright/test";

const OUTBOX = path.resolve(__dirname, "../test-results/mail-outbox");
const PASSWORD = "quiet-river-lantern-42";
const DAY_MS = 86_400_000;

type Mail = { to: string; body: string; kind: string };

function ddmmyyyy(date: Date): string {
  const pad = (value: number) => String(value).padStart(2, "0");
  return `${pad(date.getDate())}/${pad(date.getMonth() + 1)}/${date.getFullYear()}`;
}

function syntheticStatement(): Buffer {
  const start = new Date(Date.now() - 90 * DAY_MS);
  const later = (days: number) => new Date(start.getTime() + days * DAY_MS);
  const rows: [Date, string, number, number][] = [
    [start, "ATM WDL/412345678901/PUNE", 2000, 0],
    [later(12), "REV ATM WDL 412345678901 PUNE", 0, 2000],
    [later(20), "UPI/398765432109/RAMESH KUMAR/OKAXIS", 350, 0],
  ];
  let balance = 50000;
  const lines = ["State Bank of India", "Txn Date,Value Date,Description,Ref No./Cheque No.,Debit,Credit,Balance"];
  lines.push(`,,Opening Balance,,,,${balance.toFixed(2)}`);
  for (const [date, text, debit, credit] of rows) {
    balance += credit - debit;
    const stamp = ddmmyyyy(date);
    lines.push(`${stamp},${stamp},${text},,${debit ? debit.toFixed(2) : ""},${credit ? credit.toFixed(2) : ""},${balance.toFixed(2)}`);
  }
  return Buffer.from(lines.join("\n") + "\n");
}

async function verificationToken(email: string): Promise<string> {
  for (let attempt = 0; attempt < 40; attempt += 1) {
    if (existsSync(OUTBOX)) {
      const mails = readdirSync(OUTBOX)
        .sort()
        .map((name) => JSON.parse(readFileSync(path.join(OUTBOX, name), "utf-8")) as Mail)
        .filter((mail) => mail.to === email && mail.kind === "verify_email");
      const match = mails.length ? /#token=(\S+)/.exec(mails[mails.length - 1].body) : null;
      if (match) return match[1];
    }
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  throw new Error("verification email not found in the local outbox");
}

async function signUpAndVerify(page: Page, email: string) {
  await page.goto("/en/signup");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(PASSWORD);
  await expect(page.getByLabel("Privacy notice", { exact: true })).toBeVisible();
  await page.getByLabel(/I have read the privacy notice/).check();
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page.getByText("Check your email.")).toBeVisible();
  await page.goto(`/verify-email#token=${await verificationToken(email)}`);
  await expect(page.getByText("Your email is verified.")).toBeVisible();
  await expect(page).not.toHaveURL(/token=/);
}

test("signup, upload a synthetic statement, see the claim, create a complaint and approve the letter", async ({ page }) => {
  test.setTimeout(180_000);
  const email = `e2e-${Date.now()}@example.in`;
  await signUpAndVerify(page, email);

  await page.goto("/en/login");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Log in" }).click();
  await expect(page).toHaveURL(/\/en\/dashboard$/);
  await expect(page.getByTestId("impact")).toBeVisible();

  await page.getByRole("navigation").getByRole("link", { name: "Upload" }).click();
  await page.getByLabel(/Statement file/).setInputFiles({ name: "statement.csv", mimeType: "text/csv", buffer: syntheticStatement() });
  await page.getByRole("button", { name: "Upload and analyse" }).click();
  await expect(page).toHaveURL(/\/en\/statements/);
  await expect(page.getByTestId("statement-status").first()).toHaveText("Analysed", { timeout: 90_000 });

  await page.goto("/en/findings");
  await expect(page.getByRole("heading", { name: /Money owed/ })).toBeVisible({ timeout: 30_000 });
  await expect(page.getByTestId("amount-owed").first()).toHaveText("₹700");
  await page.getByRole("button", { name: "Looks right" }).first().click();
  await expect(page.getByText("You marked this as right.").first()).toBeVisible();
  await page.getByLabel("Add to complaint").first().check();
  await page.getByRole("button", { name: "Create complaint (1)" }).click();
  await expect(page).toHaveURL(/\/en\/cases\/[0-9a-f-]{36}$/);
  await expect(page.getByTestId("case-state")).toHaveText("Draft");

  await page.getByRole("button", { name: "Prepare the letter" }).click();
  const letter = page.getByTestId("letter-bank");
  await expect(letter).toContainText("DPSS.CO.PD No.629/02.01.014/2019-20");
  await expect(letter).toContainText("Rs 700");
  await expect(letter).toContainText("not legal advice");
  await page.getByLabel("Full name").fill("Asha Rao");
  await page.getByLabel("Last 4 digits of your account number").fill("1234");
  await page.getByLabel("Phone or email for the bank to reply").fill(email);
  await page.getByRole("button", { name: "Approve letter" }).click();
  await expect(letter).toContainText("Asha Rao");
  await expect(page.getByRole("button", { name: "Copy text" })).toBeVisible();

  await page.getByRole("button", { name: "I sent it" }).click();
  await expect(page.getByTestId("case-state")).toHaveText("Sent to bank");
  await expect(page.getByTestId("timeline")).toContainText("Letter approved");

  await page.goto("/en/dashboard");
  await expect(page.getByTestId("impact")).toContainText("₹700");
});
