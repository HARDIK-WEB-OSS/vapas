# Architecture (as built)

This page describes what exists in the code. The full design with estimation, trade-offs and the scaling path is `docs/system_design.md`; decisions are in `docs/adr/` and `docs/decisions_log.md`.

## Deployment

```mermaid
flowchart LR
  user["User's phone or laptop"]
  subgraph vercel["Vercel bom1"]
    web["Next.js app<br/>app.&lt;domain&gt;"]
  end
  subgraph fly["Fly.io bom"]
    api["API process group<br/>FastAPI, 2 machines"]
    worker["Worker process group<br/>queue consumer + periodic jobs"]
  end
  pg[("Supabase Postgres ap-south-1<br/>RLS, partitioned transactions,<br/>jobs + outbox")]
  redis[("Redis<br/>rate limits, PDF password 15 min")]
  r2[("Cloudflare R2<br/>raw uploads, deleted within 1 h")]
  resend["Resend email"]
  sentry["Sentry (scrubbed)"]
  ollama["Local model (Ollama)<br/>optional, redacted prompts only"]

  user -->|HTTPS pages| web
  user -->|HTTPS JSON, Bearer + refresh cookie| api
  user -->|presigned PUT, size and type signed| r2
  api --> pg
  api --> redis
  api -->|HEAD at confirm| r2
  worker --> pg
  worker --> redis
  worker -->|GET then DELETE| r2
  worker --> resend
  worker -.->|llm_gateway only| ollama
  api -.-> sentry
  worker -.-> sentry
```

## Request path inside the API

```mermaid
flowchart TB
  req["HTTP request"] --> sec["SecurityHeadersMiddleware<br/>nosniff, DENY, CSP, HSTS in prod"]
  sec --> cors["CORS: only PUBLIC_APP_URL"]
  cors --> body["BodySizeLimitMiddleware<br/>64 KiB, 413"]
  body --> limit["API limits<br/>per IP 300/min, per user 60/min<br/>Redis, in-process fallback"]
  limit --> route["Route"]
  route --> dep["current_user: JWT check,<br/>RLS transaction as that user<br/>commits before the response"]
  dep --> db[("Postgres as vapas_app")]
```

## Statement processing

```mermaid
sequenceDiagram
  participant B as Browser
  participant A as API
  participant S as Object store
  participant P as Postgres
  participant W as Worker
  B->>A: POST /statements/presign (sha256, size, kind)
  A->>P: insert statement (awaiting_upload)
  A-->>B: presigned PUT URL (5 min, size and type signed)
  B->>S: PUT file
  B->>A: POST /statements/{id}/confirm
  A->>S: HEAD (size must match)
  A->>P: status queued + outbox event (one transaction)
  A-->>B: 202
  W->>P: relay outbox to jobs, claim with SKIP LOCKED (lease 5 min)
  W->>S: GET file
  W->>W: upload guard, parse in child process (90 s timeout), reconcile
  W->>P: encrypted transactions + status (one transaction)
  W->>S: DELETE raw file
  W->>P: detection job, findings pinned to rule version
  B->>A: GET /statements, /findings (polling while queued/parsing)
```

## Modules

| Module | Responsibility |
|---|---|
| `auth/` | Signup, verification, login, refresh rotation, logout, password reset; Argon2id; rate limits |
| `security/` | Envelope encryption, redaction, upload guard, private path guard, API limits, HTTP guards, client IP |
| `db/` | Tables, RLS session setup, repositories |
| `jobs/` | Queue, outbox relay, worker loop, parse/detect handlers, sweeper, case-work tick |
| `ingest/`, `classify/`, `detect/` | Parsing, reconciliation, channel rules, findings |
| `rules/`, `knowledge/` | Verified rule YAML loader, clause search |
| `cases/`, `letters/` | Case state machine, deadlines, template letters with guardrails, evidence PDF, reminders |
| `mail/`, `observability.py` | Email senders (local capture, Resend), Sentry with scrubbing |
| `frontend/` | Next.js app, English and Hindi, mobile-first |

## Built now vs designed only

Built: everything above, plus monthly partitions, RLS on every user-owned table, transactional outbox, dead-letter state, circuit breaker, per-user LLM budget, lifecycle backstop, CI (rules, audit, backend, frontend, full-stack e2e).

Designed only (`docs/system_design.md` section 9): separate worker pools per stage, read replica, Redis Streams or SQS broker, archiving, OpenTelemetry, pgvector, LightGBM channel model.
