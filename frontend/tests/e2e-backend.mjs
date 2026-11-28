import { spawn } from "node:child_process";
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const backendDir = path.resolve(here, "../../backend");
const outbox = path.resolve(here, "../test-results/mail-outbox");

function readEnvFile(file) {
  const values = {};
  for (const line of readFileSync(file, "utf-8").split(/\r?\n/)) {
    const match = /^([A-Z0-9_]+)=(.*)$/.exec(line.trim());
    if (match) values[match[1]] = match[2];
  }
  return values;
}

const env = readEnvFile(path.resolve(backendDir, "../.env"));
const appUrl = env.DATABASE_URL;
const workerUrl = appUrl.replace(`vapas_app:${env.APP_DB_PASSWORD}@`, `vapas_worker:${env.WORKER_DB_PASSWORD}@`);
if (workerUrl === appUrl) throw new Error("could not derive the worker database URL from .env");

const shared = { ...process.env, MAIL_BACKEND: "capture", EMAIL_MX_CHECK: "false", MAIL_OUTBOX_DIR: outbox, PUBLIC_APP_URL: "http://127.0.0.1:3000", PROXY_SHARED_SECRET: process.env.E2E_PROXY_SECRET, CLIENT_IP_HEADER: "X-Vapas-Client-IP", REFRESH_COOKIE_PATH: "/api/auth" };
if (!shared.PROXY_SHARED_SECRET) throw new Error("E2E_PROXY_SECRET is not set");
const children = [
  spawn("uv", ["run", "uvicorn", "--factory", "vapas.main:create_app", "--host", "127.0.0.1", "--port", "8000"], {
    cwd: backendDir,
    env: shared,
    stdio: "inherit",
  }),
  spawn("uv", ["run", "python", "-m", "vapas.jobs.worker"], {
    cwd: backendDir,
    env: { ...shared, DATABASE_URL: workerUrl },
    stdio: "inherit",
  }),
];

function stopAll() {
  for (const child of children) child.kill();
}

for (const child of children) {
  child.on("exit", (code) => {
    stopAll();
    process.exit(code ?? 1);
  });
}
process.on("SIGINT", stopAll);
process.on("SIGTERM", stopAll);
