# Threat model (STRIDE, short)

Status: M2, 20 Nov 2026. Covers the API, worker, Postgres, Redis, object storage and the LLM gateway. Updated whenever a milestone adds a new trust boundary.

Assets: users' statements and transactions (including third-party names and UPI IDs), account credentials, per-user data keys, case documents, and the correctness of claimed amounts.

Trust boundaries: browser ↔ API; API/worker ↔ Postgres, Redis, object storage; worker ↔ local model; gateway ↔ hosted model (redacted text only); operator ↔ hosting accounts.

| Threat | Example | Mitigation (status) |
|---|---|---|
| **S**poofing | Credential stuffing, password guessing | Argon2id; per-account failure limit (5 per 15 min) and per-IP login limit; generic errors; dummy hash work for unknown emails (built M2) |
| Spoofing | Stolen refresh token | Opaque token stored hashed; rotation on every use; reuse revokes the whole session family; httpOnly, SameSite=Strict cookie scoped to `/auth`, Secure outside local (built M2) |
| Spoofing | Stolen access token | 15-minute lifetime; every request checks the session is still active, so logout and reuse detection take effect immediately (built M2) |
| Spoofing | Forged email links | 256-bit random tokens, stored hashed, single use, short expiry, sent in the URL fragment so they never reach server logs (built M2) |
| **T**ampering | User edits another user's rows through an app bug | Postgres RLS with FORCE on every user table; app role has no BYPASSRLS, cannot `SET ROLE` or turn row security off; tests prove it (built M2) |
| Tampering | Ciphertext swapped between users or fields | AES-GCM with associated data bound to user and field (built M2) |
| Tampering | Audit log rewritten | App and worker roles have INSERT and SELECT only (built M2) |
| Tampering | Malicious PDF or spreadsheet | Upload guard in the worker: magic bytes must match the declared type, size and page limits, no JavaScript, launch actions or embedded files, no macros, zip-bomb limits; parsing in a child process with a timeout (built M3) |
| Tampering | Client lies about the file hash or swaps the upload | Worker recomputes SHA-256 from the stored object and fails the statement on mismatch (built M3) |
| Tampering | Wrong amount in a letter | Template letters; guardrails check every amount and rule id (M7) |
| **R**epudiation | "I never deleted my account" / "I never approved that letter" | Append-only audit log for signup, login, failures, resets, export, consent changes, deletion, letter approvals (M2, M7) |
| **I**nformation disclosure | Cross-user read | RLS (built M2); ids are random UUIDs |
| Information disclosure | Account enumeration | Same response for existing and new emails on signup, reset and resend; same login error. Known residual: the per-account lockout (429) reveals that an account exists after 5 failures |
| Information disclosure | Secrets or statement text in logs | JSON logs with ids only; dependency errors log the error type only; Redis keys hashed; test that a failing probe does not log its message (built M2); redaction scanner on logs (M3) |
| Information disclosure | Statement text sent to an AI provider | Only `llm_gateway` may call models; every prompt is redacted and re-scanned, and the layout fallback sends only a masked sketch (built M3); a test proves names, UPI IDs, phone, PAN, account and card numbers never reach the model |
| Information disclosure | Database backup leak | Encrypted fields unreadable without the KEK; deleted users crypto-shredded |
| Information disclosure | Real statements committed to git | `PRIVATE_FIXTURES_DIR` must be outside the repo (startup check and tests); `*.pdf`, `*.csv`, `*.xls*` ignored (built M1) |
| **D**enial of service | Login or signup flooding | Per-IP token buckets; auth fails closed with 503 if Redis is down (built M2) |
| Denial of service | Upload flooding or parser bombs | Per-user upload bucket, size and page limits, per-stage queue with dead-letter (M3) |
| Denial of service | GPU exhaustion via unknown layouts | Per-user daily LLM budget (M3) |
| **E**levation of privilege | Lookup functions abused to read data | `SECURITY DEFINER` functions return only the fields needed for login, refresh and email links, with a fixed `search_path`; EXECUTE granted to the app role only (built M2) |
| Elevation of privilege | Migration role used by the app | API and worker connect as `vapas_app` / `vapas_worker`; only Alembic uses the owner (built M2) |

## Known gaps and accepted risks

- Two browser tabs refreshing with the same token at the same moment will look like token reuse and log the user out. Accepted: it is safe, and the frontend (M8) refreshes from one place only.
- The local-only email sender logs the link body in `APP_ENV=local`. Staging and production refuse to start until a real provider is configured (M9).
- Local Postgres runs the owner as a superuser; production uses a non-superuser owner with BYPASSRLS (runbook in M9).
- Client IP comes from the direct connection; behind a proxy in production, trusted-proxy configuration is required (M9) or per-IP limits would see the proxy's IP.
