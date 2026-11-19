# ADR 0003: Uploads go directly to object storage through presigned URLs

Status: accepted (M0.5, 19 Nov 2026)

## Context
Statements are up to a few MB and very sensitive. Upload acknowledgement must be p95 < 300 ms, and raw files must be deleted within 1 hour. API instances should stay stateless and cheap.

## Options
1. Upload through the API (multipart to FastAPI, then to storage or disk).
2. Store files in Postgres (bytea).
3. Presigned PUT URL from the API; the client uploads directly to S3-compatible storage (SeaweedFS locally, Cloudflare R2 in production); the API then confirms.

## Decision
Option 3. Presigned URLs expire in 5 minutes and are bound to the object key `raw/{user_id}/{statement_id}` and a size range. The bucket is private with no listing and no download URLs; only the worker reads raw files. The client sends the file's sha256 for early duplicate detection; the worker recomputes it and rejects a mismatch. A sweeper deletes raw objects older than 50 minutes. The bucket lifecycle rule works in whole days, so it is only a backstop.

## Consequences
- The API never holds file bytes, so the confirm call is a small database transaction and meets the 300 ms target.
- File validation (upload_guard) must run in the worker, after the upload, not before it.
- Object storage becomes a dependency for uploads (failure mode in system_design.md section 7).
- Local object storage is SeaweedFS, not MinIO: from late 2025 MinIO no longer publishes free container images (pulls from Docker Hub and quay.io are refused). SeaweedFS is Apache-2.0 and S3-compatible; the code only uses the S3 API through boto3, so the choice affects docker-compose only.
- Password-protected PDFs need their password to reach the worker separately (system_design.md section 4 and section 11, item 2).
