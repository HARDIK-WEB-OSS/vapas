# Progress

Test results per milestone, recorded when the milestone passed. All numbers are from real runs on the local machine (Windows 11, Python 3.11 via uv, Node 24) unless marked CI. Synthetic data only.

M0 to M7 were pushed before this log started; their results are in their commits and in `docs/parser_eval.md`, `docs/channel_eval.md`, `docs/detector_eval.md`, `docs/knowledge_eval.md`.

## M8 - Frontend (21 Nov 2026)

| Check | Command | Result |
|---|---|---|
| Backend lint | `uv run ruff check .` / `uv run ruff format --check .` | clean / 163 files formatted |
| Backend types | `uv run mypy` | no issues, 161 source files |
| Backend unit | `uv run pytest` | 341 passed, 1 skipped (symlink test needs Developer Mode on Windows; runs in CI on Linux) |
| Backend integration (worker stopped) | `uv run pytest -m integration` | 66 passed |
| New integration tests | `tests/integration/test_account_and_recovery.py` | locale, consent again after withdrawal, recovered amount (state and date rules, other user 404), CORS allow/deny: 4 passed |
| Frontend lint / types / build | `npm run lint`, `npm run typecheck`, `npm run build` | clean / clean / built |
| Playwright smoke + full flow | `E2E_FULL=1 npx playwright test` | 11 passed; 8 full-suite runs after the commit-scope fix: 7 green, 1 cold-start `toBeVisible` timeout that did not reproduce in the next 5 runs |
| Lighthouse mobile | see `docs/frontend.md` | performance 82-90, accessibility 100, best practices 96-100, SEO 100 (median of 3) |

Bug fixed during M8: `POST /statements/{id}/confirm` returned before its transaction committed (FastAPI default `yield` dependency scope). See `docs/frontend.md` and `docs/decisions_log.md`.

## M9 - Production hardening (21-22 Nov 2026)

| Check | Result |
|---|---|
| New unit tests | `test_http_hardening.py` (in-process limiter refill, Redis fallback, 429 with Retry-After, headers, HSTS only on HTTPS, 413 for declared and chunked bodies), `test_client_ip.py`, `test_email_provider.py`, `test_observability.py` (scrubber removes body, headers, cookies, query, user, local variables, breadcrumb data), docs hidden outside local |
| New integration tests | `test_hardening.py`: per-user limit with real Redis (refill-aware), headers on real routes, 413, presigned PUT rejects a bigger body than declared (SeaweedFS answers 403), lifecycle rule = 1 day |
| Chaos checks (`test_chaos.py`) | all pass: worker process killed with SIGKILL while parsing a 400-row PDF (no rows committed, lease expiry, redo parsed, narrations equal the generator's ground truth, attempts 2, state done); Redis down (login 503 `temporarily_unavailable`, authenticated reads 200 via in-process limits, `/ready` 503 with redis false); object store down (confirm 503, statement stays `awaiting_upload`, confirm works after recovery); LLM provider failing (3 calls then circuit open, all 4 unknown layouts `needs_review`); email down (banner at once, attempts counted, error log at 24 attempts, sent after recovery); poison statement (parse timeout every time, job `dead` after 3 attempts, statement `failed`); Postgres down (503 JSON, `/ready` 503, `/health` 200) |
| Failure-modes fixes found by chaos tests | confirm with object store down returned 500, now 503; Postgres connection failures returned 500, now 503 |
| Integration suite | 77 passed in 4 min 56 s (a first run under severe memory pressure took 64 min with 2 failures that passed on their own in 10 s; the re-run was clean) |
| Unit suite | 363 passed, 1 skipped |
| e2e with CSP and API limits | 12 passed (new smoke test checks frontend security headers) |
| pip-audit (runtime + dev, locked) | no known vulnerabilities |
| npm audit | 0 vulnerabilities |
| Backup and restore drill | `backup_restore_check.py`: 24 tables, 0 mismatched (database nearly empty because integration tests truncate it) |
| k6 load test | NOT RUN: blocked (`docs/blockers.md` B1). Kit written; seeding validated with 3 users |
| Deploy | NOT DONE: owner steps in `docs/needs_owner.md` |

## M10 - Pilot readiness without real users (22 Nov 2026)

| Check | Result |
|---|---|
| Migration 0010 | upgrade, downgrade, upgrade: OK |
| `test_pilot.py` (integration) | 5 passed: invite-only signup (missing, wrong, expired, used-up codes refused; code typed in lower case with spaces accepted; cohort recorded; single use counted), open signup ignores codes, app role cannot read `invite_codes`, per-finding feedback (validation, upsert, listed with findings, other user 404, RLS), export format 2 with findings, decrypted snapshots, feedback and case data, deletion removes feedback, impact report on synthetic data (exact counts, Rs 700 recovered, precision counts, no names or emails in the report) |
| `test_pilot_units.py` | 6 passed: code format and alphabet, typing variants hash the same, Wilson interval for 19/20 = 76.4% to 99.1%, no judgements = unknown |
| Fix-loop harness (`tests/regression/`) | 4 passed: two template cases (merchant refund, successful UPI transfer) never claims, positive control finds the Rs 700 ATM claim |
| e2e | 12 passed twice, flow now presses "Looks right" on the claim |
| Impact report on local synthetic data | `docs/impact_report_synthetic.md` |
| Gap fixed | data export did not contain findings, snapshots, cases or letters (required since M2); now included |

## Final verification (22 Nov 2026)

| Check | Result |
|---|---|
| Rule YAML (`rules/schema.py`) | valid; `rules/rbi/` not changed in M8-M10 |
| Backend lint / format / types | ruff clean, 187 files formatted, mypy strict clean (185 files) |
| Backend unit + golden + regression | 373 passed, 1 skipped (Windows symlink test) |
| Backend integration (82 tests) | 81 passed, 1 failed: `test_export_contains_my_data_and_no_secrets` asserted export format 1; the format is now 2 (findings and cases added). Test updated to format 2 and to require the new sections; `test_auth_flow.py` re-run: 18 passed. The run took 36 min under memory pressure |
| Frontend lint / types / build | clean / clean / built |
| Playwright smoke + full flow | 12 passed |
| Production image build | NOT RUN: stopped for low memory (`docs/blockers.md` B2); built by CI on push |

## After completion: email, signup and verify fixes (22 Nov 2026)

| Check | Result |
|---|---|
| Lint / format / types | ruff clean, 195 files formatted, mypy strict clean (193 files) |
| Unit + golden + regression | 414 passed, 1 skipped |
| New unit tests | `test_smtp_sender.py` (STARTTLS before login with certificate checks, never sends without TLS, password never in errors or logs, chosen by env), config guards (capture refused in staging and production, also by the factory; SMTP and Resend need credentials), `test_email_domains.py` 27 tests (disposable and subdomains blocked, no-MX blocked, gmail / `.ac.in` / company / custom domains allowed, DNS failure allows, both override files, override validation, tampered list refused, CRLF checkout accepted, MX outcomes incl. null MX and timeouts), `test_refresh_disposable.py` 6 tests (unreachable source fails loudly and keeps the last good list, major-provider and allowlisted clashes refused, size change needs `--force`, good refresh loads, unchanged list leaves files alone) |
| New integration tests (run on their own) | `test_signup_email_checks.py` 5 passed (disposable 400, no-MX 400, gmail and college accepted, DNS failure accepted, no user row for refused signups); `test_unverified_sweep.py` 3 passed (deleted after 48 h with consents, keys, tokens and sessions gone, audit row without email; verified at 47 h and unverified at 47.9 h kept; TTL configurable); `test_auth_flow.py` 18 passed |
| Full integration suite | NOT COMPLETED: stopped by Claude Code for low memory after 27 of 90 tests, with one failure inside `test_auth_flow.py`; that file then passed 18/18 on its own. Needs one full run on a machine with free memory |
| Playwright | 18 passed full stack (flow + smoke + 6 verify-page tests); verify-page tests 6 passed again under `next dev` (React Strict Mode); mutation check: with the single-flight disabled the "exactly once" test fails with 2 calls |
| Disposable list | 10,455 domains, CC0, fetched 22 Nov 2026, refresh re-run reports "unchanged" |
| Migration 0011 | upgrade, downgrade, upgrade: OK |

Follow-up (22 Nov 2026): the failure seen at test 13 of the stopped run was `test_login_is_rate_limited_per_ip` (login bucket refilled during slow Argon2 checks), not the signup limit; the test is now refill-aware and `test_auth_flow.py` passes 18/18. The weekly refresh now opens a pull request instead of committing to `main`. Full integration suite still NOT RUN, on hold by the owner until the other project's eval finishes.

Follow-up 2 (22 Nov 2026): weekly workflow made read-only (`--check` mode, single issue on a difference). Unit tests for the domain list and refresh script: 37 passed (4 new check-mode tests: unchanged, changed with nothing written, would-be-refused list reported, unreachable fails). Full integration suite still on hold.

Follow-up 3 (22 Nov 2026): `test_login_is_rate_limited_per_ip` is deterministic (frozen-refill limit in the test, exactly 20 x 401 then 429). `test_auth_flow.py` 18 passed; the same test with a 1.6 s delay per login passed in 37 s. Full integration suite still on hold.
