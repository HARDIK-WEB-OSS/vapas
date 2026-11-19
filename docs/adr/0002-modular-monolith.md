# ADR 0002: Modular monolith with one API and one worker process type

Status: accepted (M0.5, 19 Nov 2026)

## Context
One developer builds and runs VAPAS. The load at 100k users fits one Postgres primary, a few API instances and up to 10 worker processes (system_design.md section 2). The idempotency design relies on single-database transactions (statement + outbox, findings + job state), and RLS works per database session.

## Options
1. Microservices (auth, ingest, detect, cases, notify), each with its own database.
2. A single process doing everything, including parsing inside HTTP requests.
3. A modular monolith: one codebase with strict module boundaries, deployed as two process types (API and worker) from the same image.

## Decision
Option 3. Module boundaries are enforced by convention and tests: only `llm_gateway` calls models, only `storage` calls object storage, only `db/repo.py` issues SQL, only `jobs` touches queue tables. In v1 the worker consumes all queues.

## Consequences
- Simple deploys, one CI pipeline, local runs with docker-compose.
- Cross-module calls are function calls, so transactions can span modules safely.
- API and worker scale independently because they are separate process types.
- A bad change in one module can affect the whole process. Tests per module limit this, and the queue keeps slow or crashing work away from the API.
- Splitting later is possible along the queue boundaries; separate worker pools per stage are already in the scaling path.
