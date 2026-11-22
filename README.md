# VAPAS

Verified Automated Payment Audit System ("vapas" is Hindi for "money back").

VAPAS reads a person's bank statements, finds failed payments the bank reversed late, and calculates the compensation the RBI requires the bank to pay for the delay, citing the exact rule. It also flags duplicate debits and other items worth checking, and walks the user through claiming: a complaint to the bank, tracking the waiting period, and escalation to the RBI Ombudsman inside the filing deadline.

VAPAS never connects to a bank, never moves money and never files anything for the user. It drafts; the user reviews and sends. It is not legal advice. It is free.

## The problem

RBI's circular "Harmonisation of Turn Around Time (TAT) and customer compensation for failed transactions using authorised Payment Systems" (RBI/2019-20/67, DPSS.CO.PD No.629/02.01.014/2019-20, 20 September 2019, in force from 15 October 2019) sets a deadline for reversing each kind of failed transaction and requires compensation of Rs 100 per day of delay, paid by the bank on its own (suo moto). In practice most customers never receive it and do not know it exists.

The complaint path is also unfamiliar. Under the Reserve Bank - Integrated Ombudsman Scheme, 2026 (in force 1 July 2026), the customer first complains to the bank, may escalate after the waiting period (30 days, or a longer period where RBI, NPCI or card-network rules set one) or after an unsatisfactory reply, and must file with the Ombudsman within 90 days. Missing that window loses the claim.

Existing tools draft complaint letters from what a person describes. VAPAS starts from the statement itself: it finds the late reversals, works out the amount from the verified rule, and keeps the deadlines.

Demand is **not yet validated**: no real statements have been analysed and no pilot has run (see "Status").

## How it works

1. The user downloads a statement (PDF, CSV or Excel) from their bank and uploads it. The file goes straight to object storage through a short-lived presigned URL bound to its size and type; it is deleted within an hour of being read.
2. A worker parses the statement (bank layouts for SBI, HDFC, ICICI, Axis, Kotak; an optional local-model fallback for unknown layouts that only ever sees redacted text) and checks the running balance row by row.
3. Rules classify each transaction (UPI, IMPS, NEFT, ATM, card, NACH, AePS, charges, merchant refunds) and extract UTR/RRN references.
4. The detector pairs debits with reversals (reference first, then amount, time window and counterparty, as an optimal assignment so no reversal is used twice), and applies the verified rule for the transaction's date:
   - **Money owed** (claims) only for the annex rows where the customer is owed compensation and both dates are on the statement: ATM cash not dispensed 1(a), card PoS 2(b), card e-commerce 2(c), UPI to merchant 4(b), AePS to merchant 5(a). Amount = Rs 100 x days beyond the deadline, minus any compensation already credited.
   - **Worth checking**: unreversed debits that may have failed, partial reversals, duplicates, credit-push transfers (where the annex pays the beneficiary, so VAPAS never shows the payer an amount).
   - **Needs your input**: questions such as "was this payee a merchant?" or a NACH mandate revocation date.
   Merchant refunds, wrong-recipient transfers and international transactions are never claims. Only the last 12 months can become claims.
5. The user turns findings into a case. Letters are built from templates filled only with engine facts; guardrails reject any amount or rule id that the engine did not produce. The case tracks the bank's reply, the escalation date and a countdown to the Ombudsman deadline, with reminder emails and in-app banners.

Every rule is stored as data with the instrument name, number, date, clause, URL, effective dates and verification status (`rules/rbi/`), and was verified word for word against the RBI source by the owner. Product choices that interpret the rules are kept separately in `docs/product_policy.md`.

## Demo (steps for recording)

1. Open the app on a phone-sized window; switch between English and Hindi.
2. Sign up, read the consent notice, verify the email.
3. Upload a synthetic statement (`backend/scripts/gen_synthetic_statements.py`); watch it go from "Queued" to "Analysed".
4. Findings: "Money owed Rs 700" for an ATM reversal 7 days late, with the rule citation; press "Looks right".
5. Create a complaint, review and approve the letter, download the evidence PDF, press "I sent it".
6. Case timeline and Ombudsman countdown; dashboard impact counter.

## Architecture

A modular monolith (FastAPI) plus one worker process, PostgreSQL 16 with Row Level Security, Redis, S3-compatible storage, and a Next.js frontend. Diagrams: [docs/architecture.md](docs/architecture.md). Full design: [docs/system_design.md](docs/system_design.md).

Design estimates for 100,000 users (from `docs/system_design.md`, section 2): month-start peak about 0.77 uploads per second, about 50 API requests per second, about 310 transaction rows inserted per second, about 10 worker processes, about 2.8 GB of raw files resident at peak.

Key trade-offs, each with an ADR in [docs/adr/](docs/adr/):

| Decision | Why |
|---|---|
| Postgres queue with a transactional outbox (0001) | No second system to run; a statement row and its job can never disagree |
| Modular monolith, not microservices (0002) | One team, one deploy; module boundaries kept in code |
| Presigned uploads (0003) | Statements never pass through the API |
| Rules as versioned data (0004), separate from product policy (0009) | Every finding is pinned to the rule version that produced it |
| One LLM gateway with redaction (0005) | Statement text never reaches a hosted model |
| Monthly partitions for transactions (0006) | Cheap retention (13 months) by dropping partitions |
| Template letters, not generated ones (0007) | Amounts and citations cannot be invented |
| Full-text search before vectors (0008) | recall@5 0.933 on the clause eval without pgvector |

Production hardening: security headers and CSP, a 64 KiB body cap, per-user and per-IP token-bucket limits with an in-process fallback when Redis is down, trusted client IP header, signed upload size, a 1-day storage lifecycle backstop, Sentry with PII scrubbing, dependency audits in CI. Deploy target: Fly.io Mumbai (API and worker), Supabase Mumbai (Postgres), Vercel Mumbai functions (frontend), Cloudflare R2. Operations: [docs/runbook.md](docs/runbook.md).

## Privacy

VAPAS is a Data Fiduciary under the DPDP Act 2023 and DPDP Rules 2025. Details: [docs/privacy.md](docs/privacy.md), threat model: [docs/threat_model.md](docs/threat_model.md).

- Versioned consent notice; consent can be withdrawn and given again.
- Row Level Security on every user-owned table, tested with raw queries as the app role.
- Envelope encryption with a data key per user for narrations, references, finding snapshots and letters.
- Raw statement files deleted within 1 hour; transactions after 13 months.
- Full JSON export (including findings, snapshots, cases and letters) and account deletion that erases object storage too.
- Logs and error reports carry no personal data.

## Metrics

### Synthetic (prove the code matches the generator, not real banks)

| What | Result | Source |
|---|---|---|
| Parser: rows parsed exactly, statements reconciled (5 banks x 4 formats, 10 statements each) | 100% / 100% | [docs/parser_eval.md](docs/parser_eval.md) |
| Channel rules: coverage on 2,300 synthetic narrations | 93.5% (kind and reference 100%) | [docs/channel_eval.md](docs/channel_eval.md) |
| Detector on 200 synthetic users with injected cases | claim precision 1.000 (0 false positives), recall 0.894 | [docs/detector_eval.md](docs/detector_eval.md) |
| Clause search, 30 questions | recall@5 0.933 | [docs/knowledge_eval.md](docs/knowledge_eval.md) |
| Lighthouse mobile, public pages (median of 3) | performance 82-90, accessibility 100 | [docs/frontend.md](docs/frontend.md) |

### Real statements

**Pending.** Parser, channel and detector numbers on real statements run only on the owner's machine with consent, and are reported as aggregates. See [docs/pending_real_data.md](docs/pending_real_data.md).

### Load test

**Pending.** The k6 month-start spike kit is in `backend/loadtest/`; the run is blocked on this machine's memory ([docs/blockers.md](docs/blockers.md)). No load numbers are claimed.

### Pilot

**Pending.** Plan: [docs/pilot_plan.md](docs/pilot_plan.md) (invite-only, per-finding feedback, weekly impact report). An example report on synthetic data: [docs/impact_report_synthetic.md](docs/impact_report_synthetic.md).

## Limitations

- Bank layouts follow assumptions until checked against real statements; unknown layouts go to review.
- Real precision is unknown until the pilot; synthetic precision does not transfer.
- Credit-push failures (IMPS, UPI P2P, card-to-card, AePS fund transfer) never get an amount: the annex pays the beneficiary.
- Statements do not show APBS, NACH credit delays or PPI on-us events, so those rows cannot be detected.
- Finding explanations are English only; Hindi texts await native review; the privacy policy and terms await legal review.
- No Account Aggregator, no automatic filing, no payments, by design.

## Status

M0-M10 are built and tested locally ([docs/progress.md](docs/progress.md), [docs/final_report.md](docs/final_report.md)). Not done yet: the production deploy and the pilot (owner steps in [docs/needs_owner.md](docs/needs_owner.md)), the real-statement checks and the load test.

## Run locally (Windows PowerShell)

Requirements: Docker Desktop, [uv](https://docs.astral.sh/uv/), Node.js 24. Use `127.0.0.1`, not `localhost`, in the browser (the refresh cookie is same-site).

```powershell
Copy-Item .env.example .env
docker compose up -d --build --wait
Invoke-RestMethod http://127.0.0.1:8000/ready
```

Backend checks:

```powershell
cd backend
uv sync --locked
uv run ruff check
uv run ruff format --check
uv run mypy
uv run pytest
docker compose stop worker
uv run pytest -m integration
docker compose start worker
cd ..
uv run --project backend python rules/schema.py
```

Frontend:

```powershell
cd frontend
npm ci
npm run lint
npm run typecheck
npm run build
npx playwright test
$env:E2E_FULL = "1"; npx playwright test; Remove-Item Env:E2E_FULL
```

The full-stack Playwright run starts the API and worker from `backend/` itself; stop the compose `api` and `worker` containers first.

Local services: API on 127.0.0.1:8000, Postgres on 127.0.0.1:55433, Redis on 127.0.0.1:6379, S3-compatible storage (SeaweedFS) on 127.0.0.1:8333.

## Real statements

Real statements never enter this repository. They live in the folder named by `PRIVATE_FIXTURES_DIR`, and the app refuses to start if that folder is inside the repository. Committed tests use synthetic statements only.
