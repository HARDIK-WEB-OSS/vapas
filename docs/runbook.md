# Operations runbook

Commands are PowerShell from the repo root unless stated. Production values come from the host's secret store, never from files in the repo.

## 1. Backups

### What protects the data

| Layer | Mechanism | Owner action |
|---|---|---|
| Managed Postgres (Supabase, ap-south-1) | Provider daily backups; point-in-time recovery on paid plans | Turn on PITR before the pilot if the budget allows (see `docs/needs_owner.md`) |
| Logical dump | `pg_dump --format=custom` weekly and before every migration | Keep dumps outside the repo, encrypted at rest (for example a BitLocker or VeraCrypt volume); delete dumps older than 35 days |
| Object storage | Not backed up on purpose: raw statements are deleted within 1 hour (sweeper) with a 1-day lifecycle rule as backstop | None |
| Redis | Not backed up: cache, rate-limit buckets and 15-minute PDF passwords only | None |
| Envelope keys (`KEK_KEYS`) | Stored only in the host secret store and one offline copy | Without the KEK, every encrypted narration and reference in a backup is unreadable. Keep the offline copy separate from the dumps |

A dump contains encrypted narrations and references, emails in clear text (needed for login and reminders) and the audit log. Treat it as personal data under the DPDP Act: same access rules as production.

### Restore drill (tested)

`backend/scripts/backup_restore_check.py` dumps the database, restores it into a scratch database `vapas_restore_check` on the same server, compares the row count of every table, then drops the scratch database. It refuses an output folder inside the repo.

Local (compose Postgres):

```powershell
cd backend
uv run python scripts/backup_restore_check.py --out-dir C:\vapas-backups
```

Expected last line: `tables: N, rows: M, mismatched tables: 0` and exit code 0. Results are recorded in `docs/progress.md`.

Production (from the owner's machine, pg_dump 16 client installed):

```powershell
$env:PGPASSWORD = "<owner password from the secret store>"
pg_dump --host <supabase host> --port 5432 --username postgres --dbname postgres --format=custom --no-owner --no-privileges --schema=public --file C:\vapas-backups\vapas-prod-$(Get-Date -Format yyyyMMddTHHmm).dump
Remove-Item Env:PGPASSWORD
```

Restore into a new, empty database (never over production):

```powershell
pg_restore --host <host> --username postgres --dbname <new empty database> --no-owner --no-privileges --exit-on-error C:\vapas-backups\<file>.dump
```

Then run `infra/postgres/roles.sql` against the restored server if the roles do not exist, point a staging API at it and check `/ready`, login and one case page.

## 2. Migrations

- Migrations live in `backend/migrations/versions/`, run by Alembic as the owner role (`MIGRATION_DATABASE_URL`). The app and worker roles cannot change the schema.
- Production runs them automatically as Fly's `release_command` (`fly.toml`) before new machines start. A failed migration aborts the deploy and the old version keeps running.

Rules for every migration:

1. Expand, then contract. Add columns as nullable or with a default; deploy code that writes both; drop old columns in a later release. Old and new API machines run side by side during a rolling deploy.
2. No long locks on `transactions` (partitioned by month): add indexes per partition or with `CREATE INDEX CONCURRENTLY` in a separate migration with `transaction_per_migration` off for that file.
3. Every new user-owned table gets RLS in the same migration (`docs/system_design.md` section 5); the RLS isolation tests must cover it.
4. Take a logical dump right before a migration that drops or rewrites data.
5. `downgrade()` must exist and is tested locally (`uv run alembic downgrade -1` then `upgrade head`), but production rollback is "deploy the previous image"; data-destroying downgrades are not run in production.

Checking locally:

```powershell
cd backend
uv run alembic upgrade head
uv run alembic downgrade -1
uv run alembic upgrade head
uv run pytest -m integration
```

## 3. Rule and knowledge base updates

- `fly.toml` release command also runs `python scripts/ingest_rbi.py --rules`, loading rule YAML quotes. A rule change still needs the owner's word-for-word verification first (CLAUDE.md, M0 rules).
- Clause text from the source PDFs is loaded once per environment from the owner's machine: `uv run python scripts/ingest_rbi.py --pdf rbi.dpss_629_2019=PATH --pdf rbi.rbios_2026=PATH --pdf rbi.rbios_2021=PATH` with `MIGRATION_DATABASE_URL` pointing at that environment (pending item 11).

## 4. Deploys and rollback

- Backend: `fly deploy` from the repo root (see `docs/needs_owner.md` for first-time setup). Rolling strategy; `/ready` gates traffic.
- Rollback: `fly releases` then `fly deploy --image <previous image ref>`. Schema stays (expand/contract makes the old code compatible).
- Frontend: Vercel keeps every deployment; "Promote to production" on the previous one rolls back instantly.

## 5. Incidents

| Signal | First check | Action |
|---|---|---|
| Uptime check on `/ready` fails | `fly status`, `fly logs` | `/ready` JSON says which dependency is down; follow the failure modes table in `docs/system_design.md` section 7 |
| Sentry: `database unavailable` | Supabase status page | API answers 503 `temporarily_unavailable`; nothing to do in the app; wait or fail over per provider guidance |
| Sentry: `reminder email still unsent` | Resend dashboard | Reminders keep retrying hourly and the in-app banner is already shown; if the outage lasts more than a day, switch provider (Brevo) by changing the sender in `backend/src/vapas/mail/sender.py` and redeploying; pending reminders are sent on the next hourly tick |
| Sentry: `auth email not sent` | Resend dashboard | Users can press "resend verification" later |
| Dead jobs growing | `SELECT queue, last_error_code, count(*) FROM jobs WHERE state = 'dead' GROUP BY 1, 2` | Reproduce with a synthetic statement, add a regression test, fix |
| Suspected data breach | Stop: follow section 7 "Breach-notification process" in `docs/privacy.md` | |
