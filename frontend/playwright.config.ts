import { defineConfig, devices } from "@playwright/test";

const fullStack = process.env.E2E_FULL === "1";
const devServer = process.env.E2E_DEV === "1";
const port = fullStack ? 3000 : devServer ? 3200 : 3100;
const serverScript = devServer ? "dev" : "start";

const E2E_PROXY_SECRET = "e2e-only-proxy-secret-0123456789abcdef";
const proxyEnv: Record<string, string> = { VAPAS_API_ORIGIN: "http://127.0.0.1:8000", VAPAS_PROXY_SECRET: E2E_PROXY_SECRET };
const noEnv: Record<string, string> = {};

const frontend = {
  command: `npm run ${serverScript} -- --hostname 127.0.0.1 --port ${port}`,
  env: fullStack ? proxyEnv : noEnv,
  url: `http://127.0.0.1:${port}`,
  reuseExistingServer: !process.env.CI,
  timeout: 120_000,
};

const backend = {
  command: "node tests/e2e-backend.mjs",
  env: { E2E_PROXY_SECRET },
  url: "http://127.0.0.1:8000/ready",
  reuseExistingServer: false,
  timeout: 180_000,
};

export default defineConfig({
  testDir: "./tests",
  testIgnore: fullStack ? [] : ["**/flow.spec.ts"],
  testMatch: devServer ? ["**/verify-email.spec.ts"] : undefined,
  timeout: devServer ? 120_000 : undefined,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 1 : 0,
  workers: fullStack ? 1 : undefined,
  reporter: process.env.CI ? "github" : "list",
  use: {
    baseURL: `http://127.0.0.1:${port}`,
  },
  projects: [{ name: "mobile-chromium", use: { ...devices["Pixel 7"] } }],
  webServer: fullStack ? [backend, frontend] : [frontend],
});
