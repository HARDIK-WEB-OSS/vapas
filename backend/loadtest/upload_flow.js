import http from "k6/http";
import { check, sleep } from "k6";
import crypto from "k6/crypto";
import exec from "k6/execution";
import { Counter, Rate, Trend } from "k6/metrics";

const API = __ENV.API_URL || "http://127.0.0.1:8000";
const DATA_DIR = __ENV.LOAD_DIR;
const PEAK_RATE = Number(__ENV.PEAK_UPLOADS_PER_SECOND || "1");
const PEAK_MINUTES = Number(__ENV.PEAK_MINUTES || "5");
const BROWSE_RATE = Number(__ENV.BROWSE_ITERATIONS_PER_SECOND || "10");
const BROWSE_USERS = 60;
const POLL_SECONDS = 2;
const PROCESSING_LIMIT_SECONDS = 300;
const BUSY = new Set(["awaiting_upload", "queued", "parsing"]);

const manifest = JSON.parse(open(`${DATA_DIR}/manifest.json`));
const files = manifest.statements.map((name) => {
  const bytes = open(`${DATA_DIR}/${name}`, "b");
  return { bytes, sha256: crypto.sha256(bytes, "hex") };
});

const uploadAck = new Trend("upload_ack_ms", true);
const processing = new Trend("processing_ms", true);
const processedOk = new Rate("processed_ok");
const timedOut = new Counter("processing_timeouts");

export const options = {
  scenarios: {
    upload_spike: {
      executor: "ramping-arrival-rate",
      exec: "upload",
      startRate: 0,
      timeUnit: "1s",
      preAllocatedVUs: 40,
      maxVUs: 400,
      stages: [
        { target: PEAK_RATE / 10, duration: "1m" },
        { target: PEAK_RATE, duration: "30s" },
        { target: PEAK_RATE, duration: `${PEAK_MINUTES}m` },
        { target: 0, duration: "30s" },
      ],
    },
    browse: {
      executor: "constant-arrival-rate",
      exec: "browse",
      rate: BROWSE_RATE,
      timeUnit: "1s",
      duration: `${PEAK_MINUTES + 2}m`,
      preAllocatedVUs: 20,
      maxVUs: 100,
    },
  },
  thresholds: {
    "http_req_duration{name:confirm}": ["p(95)<300"],
    processing_ms: ["p(95)<120000"],
    processed_ok: ["rate>0.99"],
    "http_req_failed{scenario:browse}": ["rate<0.01"],
  },
};

function clientHeaders(index, token) {
  const headers = { "Content-Type": "application/json" };
  headers[manifest.ip_header] = `10.${(index >> 16) & 255}.${(index >> 8) & 255}.${index & 255}`;
  if (token) headers.Authorization = `Bearer ${token}`;
  return headers;
}

const uploaders = manifest.emails.length - BROWSE_USERS;

function login(index) {
  const email = manifest.emails[index];
  const response = http.post(
    `${API}/auth/login`,
    JSON.stringify({ email, password: manifest.password }),
    { headers: clientHeaders(index), tags: { name: "login" } },
  );
  check(response, { "login 200": (r) => r.status === 200 });
  return response.status === 200 ? response.json("access_token") : null;
}

export function setup() {
  const tokens = [];
  for (let index = 0; index < BROWSE_USERS; index += 1) tokens.push(login(manifest.emails.length - 1 - index));
  return { tokens };
}

export function upload() {
  const iteration = exec.scenario.iterationInTest;
  const index = iteration % uploaders;
  const token = login(index);
  if (!token) return;
  const headers = clientHeaders(index, token);
  const file = files[(iteration + Math.floor(iteration / uploaders)) % files.length];
  const started = Date.now();
  const presign = http.post(
    `${API}/statements/presign`,
    JSON.stringify({ sha256: file.sha256, size_bytes: file.bytes.byteLength, file_kind: "pdf" }),
    { headers, tags: { name: "presign" } },
  );
  if (!check(presign, { "presign 200": (r) => r.status === 200 })) return;
  const out = presign.json();
  if (out.upload_url) {
    const put = http.put(out.upload_url, file.bytes, { headers: { "Content-Type": out.content_type }, tags: { name: "put" } });
    if (!check(put, { "put 200": (r) => r.status === 200 })) return;
  }
  const confirm = http.post(`${API}/statements/${out.statement_id}/confirm`, "{}", { headers, tags: { name: "confirm" } });
  if (!check(confirm, { "confirm 200": (r) => r.status === 200 })) return;
  const acked = Date.now();
  uploadAck.add(acked - started);
  let status = confirm.json("status");
  while (BUSY.has(status) && Date.now() - acked < PROCESSING_LIMIT_SECONDS * 1000) {
    sleep(POLL_SECONDS);
    const poll = http.get(`${API}/statements/${out.statement_id}`, { headers, tags: { name: "poll" } });
    status = poll.status === 200 ? poll.json("status") : status;
  }
  if (BUSY.has(status)) {
    timedOut.add(1);
    processedOk.add(false);
    return;
  }
  processing.add(Date.now() - acked);
  processedOk.add(status === "parsed");
  http.get(`${API}/findings`, { headers, tags: { name: "findings" } });
}

export function browse(data) {
  const slot = exec.scenario.iterationInTest % data.tokens.length;
  const token = data.tokens[slot];
  if (!token) return;
  const headers = clientHeaders(manifest.emails.length - 1 - slot, token);
  for (const path of ["/account/me", "/statements", "/notifications", "/cases"]) {
    const response = http.get(`${API}${path}`, { headers, tags: { name: path } });
    check(response, { "browse 200": (r) => r.status === 200 });
  }
}
