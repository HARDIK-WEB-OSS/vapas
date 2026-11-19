# ADR 0001: Postgres job queue with a transactional outbox

Status: accepted (M0.5, 19 Nov 2026)

## Context
Statement processing is asynchronous: the API must acknowledge an upload in under 300 ms (p95), while parsing and detection take seconds to minutes. At 100k users the peak is about 0.77 uploads per second (system_design.md section 2.1). A job must never be lost or created without its statement row, and must never run twice with different results.

## Options
1. Redis queue (RQ, Celery with Redis): fast, but the job and the database write live in two systems, so a crash between them loses a job or creates an orphan. Redis also runs without persistence in this design.
2. Managed broker (SQS, Redis Streams): durable, but an extra service and cost, and the same dual-write problem without an outbox.
3. Postgres table as the queue (`SELECT ... FOR UPDATE SKIP LOCKED`) with per-stage queues, leases, retries with backoff and a dead-letter state, fed by a transactional outbox.

## Decision
Option 3. The API writes the statement row and an outbox event in one transaction. An outbox relay (running inside the worker process) turns outbox events into jobs with a unique idempotency key. Workers claim jobs with `SKIP LOCKED` and a lease. Each stage commits its output, its job state and its next outbox event in one transaction. After `max_attempts` (3) a job goes to `dead`.

## Consequences
- No dual write: a statement exists if and only if its event exists.
- One less service to run; the queue is covered by Postgres backups.
- The throughput ceiling is far above the need (hundreds of jobs per second vs under 1 per second at peak).
- The outbox is an extra hop today, because jobs could be inserted in the same transaction directly. It is kept because it decouples producers from the queue: at 1M users the relay can publish to Redis Streams or SQS without changing the API, and one event can fan out to jobs, notifications and analytics.
- Queue polling adds some load to Postgres. This is kept small with a partial index on queued jobs and short backoff sleeps; LISTEN/NOTIFY can be added if needed.
