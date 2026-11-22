# Frontend (M8)

Next.js 16 (App Router) + TypeScript + Tailwind 4, mobile-first, English and Hindi.

## Pages

All pages live under `frontend/app/[lang]/` with `lang` = `en` or `hi`. `frontend/proxy.ts` redirects any path without a language to `/en/...` or `/hi/...` (saved `vapas_locale` cookie first, then the browser's `Accept-Language`). Signed-in users also have their language saved on the server (`POST /account/locale`) so reminder emails use the same language.

| Path | Purpose |
|---|---|
| `/` | Landing: the promise, how it works, "we never touch your money or contact your bank", privacy promise, not-legal-advice notice |
| `/signup`, `/login`, `/verify-email`, `/forgot-password`, `/reset-password` | Auth. Signup shows the full consent notice and needs an explicit tick |
| `/consent` | Consent notice; also used to give consent again after withdrawal (`POST /account/consent`) |
| `/guide` | How to download a statement, general steps + supported bank list |
| `/upload` | File + optional PDF password, hashing in the browser, presigned PUT, confirm |
| `/statements` | Processing status, polled while a statement is `queued` or `parsing` |
| `/findings` | Split into "Money owed", "Worth checking", "Needs your input" with amount, why, rule citation, confidence, confirm/deny buttons and the NACH revocation-date form |
| `/cases`, `/cases/[id]` | Case tracker, timeline, countdown to the Ombudsman filing deadline, letter review and approval, copy text, evidence PDF, "I sent it", reply received, escalation with the clause 10 questions, recovered amount |
| `/dashboard` | Impact counter: found, claimed, recovered (recovered is entered by the user) |
| `/settings` | Language, export my data (JSON), withdraw consent, delete account |
| `/privacy`, `/terms` | Privacy policy and terms (drafts, see pending items) |

## Same-site app and API (production needs a custom domain)

The access token lives only in memory. The refresh token is an `HttpOnly`, `Secure`, `SameSite=Strict` cookie scoped to `/auth` on the API origin, and the browser sends it with `fetch(..., { credentials: "include" })`.

A `SameSite=Strict` cookie is sent only when the page and the API are on the same *site* (same registrable domain). Locally this holds because both use `127.0.0.1` (ports do not count). This is also why the browser must use `127.0.0.1`, not `localhost`.

In production the default host names do not work: `*.vercel.app` and `*.onrender.com` are on the Public Suffix List, so `vapas-xyz.vercel.app` and `vapas-api.onrender.com` are different sites and the refresh cookie would never be sent. Production therefore needs one custom domain, for example `app.<domain>` for the frontend and `api.<domain>` for the API. Steps are in `docs/needs_owner.md`.

CORS on the API allows only `PUBLIC_APP_URL`, with credentials, for `GET`/`POST`/`DELETE` and the `Authorization` and `Content-Type` headers. The object store bucket allows browser `PUT` only from the same origin (`allow_browser_uploads`).

Anonymous visitors do not call `/auth/refresh`: after login the browser keeps a non-secret hint (`vapas-signed-in` in `localStorage`); without it the app starts signed out. If storage is blocked the app tries a refresh anyway.

## Tests

- `npm run lint`, `npm run typecheck`, `npm run build`.
- Smoke (`npx playwright test`, no backend): landing in English and Hindi, language switch, email links keep their token, no horizontal scroll at phone width on 7 pages.
- Full flow (`E2E_FULL=1 npx playwright test`): starts the API and worker from `backend/` with `MAIL_OUTBOX_DIR` (local and test only), then signup -> verify email from the local outbox -> login -> upload a synthetic SBI CSV -> statement analysed -> "Money owed" shows Rs 700 -> create complaint -> prepare and approve the letter (citation, amount and not-legal-advice line checked) -> "I sent it" -> timeline -> dashboard shows Rs 700.
- CI job `e2e` runs the same flow on compose infra (`.github/workflows/ci.yml`).

### Bug found by the full flow

The flow failed intermittently with the statement stuck at "Waiting for upload". FastAPI ends `yield` dependencies with the default scope *after* the response is sent, so `POST /statements/{id}/confirm` answered before its transaction committed; the next `GET /statements` could read the old state, and since `awaiting_upload` is not a polling state the page never refreshed. Fix: the per-request user transaction is now `Depends(current_user, scope="function")`, which commits before the response leaves. Regression test: `backend/tests/unit/test_request_transaction.py`. After the fix the full suite passed 8 times in a row except one cold-start run with a `toBeVisible` timeout that did not reproduce (logged in `docs/progress.md`).

## Lighthouse (mobile)

Measured 21 Nov 2026 with Lighthouse 12.8.2, default mobile preset (simulated throttling: 150 ms RTT, 1.6 Mbps, 4x CPU slowdown, Moto G Power class screen), headless Chromium 1255, against `next start` (production build) on `127.0.0.1:3100`. Median of 3 runs per page. The machine was under memory pressure (other projects' containers), benchmark index 1222; numbers on a quieter machine or CI will differ.

| Page | Performance | Accessibility | Best practices | SEO | FCP | LCP | TBT | CLS |
|---|---|---|---|---|---|---|---|---|
| /en | 88 | 100 | 100 | 100 | 0.9 s | 2.5 s | 396 ms | 0.000 |
| /hi | 82 | 100 | 100 | 100 | 0.8 s | 2.5 s | 618 ms | 0.000 |
| /en/guide | 90 | 100 | 100 | 100 | 0.8 s | 2.3 s | 337 ms | 0.000 |
| /en/signup | 85 | 100 | 96 | 100 | 0.8 s | 2.9 s | 512 ms | 0.000 |
| /en/login | 84 | 100 | 100 | 100 | 0.8 s | 2.5 s | 522 ms | 0.000 |
| /en/privacy | 87 | 100 | 100 | 100 | 0.8 s | 2.3 s | 451 ms | 0.000 |

- `/en/signup` best practices 96: the only failing audit is a console network error because the API was deliberately not running during the measurement (signup loads the consent notice from the API). Not a product issue.
- Before the signed-in hint fix, the first measurement (single run) was /en 80, /hi 70, and every page lost best-practices points for the failed `/auth/refresh` call.
- Remaining cost is JavaScript start-up (TBT): the framework chunk (about 225 KB uncompressed, 180 KB total transfer). Signed-in pages were not measured because Lighthouse runs without a session.

## Pending items (before the pilot)

| Item | Why | Where |
|---|---|---|
| Legal review of the privacy policy and terms | Drafted by the developer; VAPAS is a Data Fiduciary under the DPDP Act 2023 and DPDP Rules 2025 | `frontend/messages/*.json` (`privacy`, `terms`), `docs/privacy.md` |
| Native-speaker Hindi review | All Hindi UI text, letters, reminders and the consent notice | `frontend/messages/hi.json`, pending item 12 in `docs/pending_real_data.md` |
| Per-bank download steps | The guide gives general steps only. Menu names per bank must come from the owner checking each bank's own site or app, not from blogs | `frontend/messages/*.json` (`guide`) |
| Engine explanations are English only | Finding "why" texts and rule citations come from the backend in English; the Hindi UI shows them in English. Translating them needs the same native review | `backend/src/vapas/detect/late_reversal.py`, `unreversed.py`, `duplicates.py`, `mandates.py` |
