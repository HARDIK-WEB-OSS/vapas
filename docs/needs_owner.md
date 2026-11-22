# Needs the owner

Steps only the owner can do (accounts, credentials, domains, payment, real people, machine resources). Everything around them is built with local stand-ins and env placeholders. Do them in order.

## 0. Run the k6 load test (machine resources)

Blocked locally: installing k6 was stopped because the machine ran out of memory (see `docs/blockers.md`). Steps, with other projects' containers and browser tabs closed:

```powershell
winget install --id GrafanaLabs.k6 -e
docker compose up -d postgres redis objectstore
cd backend
$env:MAIL_OUTBOX_DIR = "C:\vapas-load\outbox"; $env:CLIENT_IP_HEADER = "X-Load-Client-IP"
Start-Process -NoNewWindow uv -ArgumentList "run uvicorn --factory vapas.main:create_app --host 127.0.0.1 --port 8000"
Start-Process -NoNewWindow uv -ArgumentList "run python -m vapas.jobs.worker"
uv run python loadtest/prepare.py --out-dir C:\vapas-load\data --outbox C:\vapas-load\outbox --users 400
Start-Process -NoNewWindow uv -ArgumentList "run python loadtest/sample_queue.py --out C:\vapas-load\queue.csv --seconds 600"
k6 run -e LOAD_DIR=C:/vapas-load/data --summary-export C:\vapas-load\summary.json loadtest/upload_flow.js
```

Note: the worker started this way needs `DATABASE_URL` set to the `vapas_worker` role (see `frontend/tests/e2e-backend.mjs` for how it is derived from `.env`). Then give the numbers to the next session to write `docs/load_test.md` (before/after).

## 0b. Real email in local development (Gmail SMTP)

1. Turn on 2-Step Verification on the Gmail account, then create an app password (Google Account, Security, App passwords).
2. In your local `.env` (never committed): `MAIL_BACKEND=smtp`, `SMTP_USERNAME=<you>@gmail.com`, `SMTP_PASSWORD=<16-character app password>`, `EMAIL_FROM=VAPAS <<you>@gmail.com>`. `SMTP_HOST` and `SMTP_PORT` default to smtp.gmail.com and 587.
3. Restart the API and worker. Tests and Playwright still capture mail and never use these settings.
4. For local load tests with `@example.in` users, also set `EMAIL_MX_CHECK=false` (allowed only locally).
5. Revoke the app password when local testing ends.

## 1. Custom domain (needed before any production use)

Why: the refresh cookie is `SameSite=Strict`; the app and the API must share one registrable domain (`docs/frontend.md`). Default `*.vercel.app` / `*.fly.dev` names will not work for login.

1. Buy a domain (any registrar).
2. Plan two host names: `app.<domain>` (frontend) and `api.<domain>` (API).

## 2. Postgres: Supabase, region South Asia (Mumbai) `ap-south-1`

1. Create a Supabase project in Mumbai. Save the database password in a password manager.
2. Use the direct connection (port 5432) or the session pooler. Do not use the transaction pooler (port 6543): asyncpg prepared statements break there.
3. Create the roles once from your machine:
   ```powershell
   psql "postgresql://postgres:<password>@<host>:5432/postgres" -v app_password="<new strong>" -v worker_password="<new strong>" -f infra/postgres/roles.sql
   ```
4. Build three URLs (all `postgresql+asyncpg://`): `DATABASE_URL` (vapas_app), `WORKER_DATABASE_URL` (vapas_worker), `MIGRATION_DATABASE_URL` (postgres).
5. Turn on point-in-time recovery if the plan allows (`docs/runbook.md` section 1).
6. Check that the owner role bypasses RLS: `SELECT rolbypassrls FROM pg_roles WHERE rolname = current_user;` must return `t`. The SECURITY DEFINER functions (login lookup, case-work scan, invite redemption) and the impact report rely on it; locally the owner is a superuser. If it returns `f`, stop and record it in `docs/blockers.md`.

## 3. Redis: Upstash (or any TLS Redis)

Create a database in Mumbai if offered, otherwise Singapore. Copy the `rediss://` URL. Redis holds no durable data (`docs/system_design.md` section 6.1).

## 4. Object storage: Cloudflare R2

1. Create bucket `vapas-raw`. R2 has no India location; raw files live under 1 hour and are deleted by the sweeper (noted in `docs/decisions_log.md`).
2. Create an API token scoped to that bucket (Object Read & Write). Note the account ID, access key and secret.
3. After the API is configured (step 6), run once from your machine with the production env loaded: `uv run python scripts/configure_bucket.py` (sets browser-upload CORS for `PUBLIC_APP_URL` and the 1-day lifecycle backstop; it prints the lifecycle days).
4. Frontend env `NEXT_PUBLIC_UPLOAD_ORIGIN` = `https://<account-id>.r2.cloudflarestorage.com`.

## 5. Email: Resend

1. Create a Resend account, add and verify `<domain>` (SPF, DKIM records at your DNS).
2. Create an API key with "sending access" only.
3. `EMAIL_FROM` = `VAPAS <no-reply@<domain>>`.

## 6. Backend: Fly.io, region Mumbai `bom`

1. Install flyctl, `fly auth login`, add a payment method.
2. From the repo root: `fly launch --no-deploy --copy-config --name <your-app-name> --region bom` (keeps `fly.toml`; update `app =` if the name differs). If Fly reports no capacity in `bom`, use `sin` and note it in `docs/decisions_log.md`.
3. Generate secrets: `python -c "import secrets; print(secrets.token_urlsafe(48))"` for `JWT_SECRET`; `python -c "import os, base64; print(base64.b64encode(os.urandom(32)).decode())"` for the KEK. Keep an offline copy of the KEK (`docs/runbook.md`).
4. Set secrets (one command, values from steps 2-5; template in `deploy/production.env.example`):
   ```powershell
   fly secrets set PUBLIC_APP_URL=https://app.<domain> DATABASE_URL=... WORKER_DATABASE_URL=... MIGRATION_DATABASE_URL=... REDIS_URL=... S3_ENDPOINT_URL=https://<account-id>.r2.cloudflarestorage.com S3_ACCESS_KEY_ID=... S3_SECRET_ACCESS_KEY=... JWT_SECRET=... KEK_KEYS='{"1":"<base64 key>"}' KEK_ACTIVE_VERSION=1 RESEND_API_KEY=... EMAIL_FROM="VAPAS <no-reply@<domain>>" SENTRY_DSN=...
   ```
5. `fly deploy`. The release command runs migrations and loads rule quotes.
6. `fly scale count api=2 worker=1` (2 API machines for availability, `docs/system_design.md`).
7. `fly certs add api.<domain>` and create the DNS records it prints.
8. Verify the client IP header: `curl.exe -H "Fly-Client-IP: 1.2.3.4" https://api.<domain>/health` must not let a client choose its IP. Check with `fly logs` that the audit IP hash differs from a request without the header; if Fly passes a client-set value through, set `CLIENT_IP_HEADER=` (empty) and record it.
9. Load the RBI clause PDFs once (pending item 11 in `docs/pending_real_data.md`).

## 7. Frontend: Vercel, function region Mumbai `bom1`

1. Import the GitHub repo, root directory `frontend`. `frontend/vercel.json` sets `bom1`.
2. Environment variables (Production): `NEXT_PUBLIC_API_URL=https://api.<domain>`, `NEXT_PUBLIC_UPLOAD_ORIGIN=https://<account-id>.r2.cloudflarestorage.com`, `NEXT_PUBLIC_INVITE_ONLY=1` (the API already has `INVITE_ONLY=true` in `fly.toml`).
3. Add domain `app.<domain>`, create the DNS record Vercel shows.

## 8. Sentry and uptime

1. Sentry: create a Python project, copy the DSN into `SENTRY_DSN` (step 6.4). Events are scrubbed before sending (`backend/src/vapas/observability.py`).
2. Uptime: a free monitor (for example Better Stack or UptimeRobot) on `https://api.<domain>/ready` every 1-5 minutes and on `https://app.<domain>/en`. Alert by email.

## 8b. Disposable-domain list

- The `blocklist-refresh` workflow runs every Monday and is read-only: it compares the latest public list with `rules/email/disposable_domains.txt` (count and sha256). If they differ, it opens or updates one issue, "Blocklist update available", with the counts and whether the new list passes the safety checks. It never creates branches, pull requests or commits.
- To apply an update: `cd backend; uv run python scripts/refresh_disposable_domains.py`, review the diff, run `uv run pytest tests/unit/test_email_domains.py tests/unit/test_refresh_disposable.py`, commit `rules/email/disposable_domains.txt` and `rules/email/disposable_source.yaml`, push to `main`, close the issue. Add `--force` only after checking a large size change.
- If the source is unreachable the run fails and GitHub emails you; the app keeps the committed list.
- False positive (for example a college domain): add it to `rules/email/allowlist_extra.txt`, one lowercase domain per line, then deploy. Extra blocks go to `rules/email/blocklist_extra.txt`.

## 9. Run the pilot

Follow `docs/pilot_plan.md`: checklist, invite codes (`scripts/create_invites.py`), invitation message, weekly `scripts/impact_report.py`, questions after one week, stop rules and the fix loop.

## 10. Before inviting anyone

- Legal review of privacy policy and terms; native Hindi review; per-bank download steps (pending items 12-15).
- Run the end-to-end flow on production with a synthetic statement (`frontend/tests/flow.spec.ts` steps by hand).
