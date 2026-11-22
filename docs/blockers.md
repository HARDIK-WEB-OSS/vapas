# Blockers

Problems not fixed after 3 serious attempts, or stopped by the environment. Each entry: what, what was tried, current state.

## B1. k6 load test not run (M9), 22 Nov 2026

- What: the month-start spike test needs k6. Installing it with winget was stopped by Claude Code because the machine was critically low on memory (other projects' containers, browsers and WSL use most of the 16 GB). The session rule is not to restart a job stopped for memory without the owner asking.
- Done instead: the full kit is written and partly validated: `backend/loadtest/prepare.py` (seeds verified users through the real API and writes five 400-row synthetic PDFs; validated with 3 users), `backend/loadtest/upload_flow.js` (spike scenario + browse traffic, thresholds from the SLOs), `backend/loadtest/sample_queue.py` (queue depth and oldest queued job every 2 s).
- Not done: no k6 numbers, so no measured bottleneck and no before/after comparison. No number is reported or estimated in their place.
- Owner step: `docs/needs_owner.md` section 0.

## B2. Production image not rebuilt locally after the M9 Dockerfile changes, 22 Nov 2026

- What: `docker compose build api` was stopped by Claude Code because the machine was critically low on memory. Not restarted, per the same rule as B1.
- Changes it would check: uvicorn flags `--no-server-header --timeout-graceful-shutdown 25`, the new `.dockerignore` entries, `sentry-sdk` in the lock file, `scripts/configure_bucket.py` as the compose `bucket-init` command.
- Coverage meanwhile: every code path runs from source in the unit, integration and e2e suites; the CI `backend` and `e2e` jobs build this image with `docker compose up --build`, so the first push verifies it.
- Owner step: with other containers stopped, run `docker compose build api` then `docker compose up -d --wait` and `Invoke-RestMethod http://127.0.0.1:8000/ready` (or rely on the CI result).
