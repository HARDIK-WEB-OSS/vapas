# Pending real data

These acceptance checks need real bank statements. They run only when real statements are available ("statements ready"). Until then, every milestone must still pass its synthetic tests before it is pushed.

Rules for running them:
- Real statements live only in `PRIVATE_FIXTURES_DIR`, outside the repo. Scripts refuse to run if that path is inside the repo.
- Statements from anyone other than the repo owner need that person's written consent first. The consent must name who will see transaction descriptions, including third-party names and UPI IDs. Consent records stay in `PRIVATE_FIXTURES_DIR\consent\`.
- Scripts print and commit aggregate numbers only: no rows, narrations or account numbers. Nothing from these statements is sent to a hosted model.
- Every rate is reported with a 95% confidence interval.

| # | Milestone | Check | Script | Status |
|---|---|---|---|---|
| 1 | M3 | % rows parsed and % statements fully reconciled on real statements, per bank | `backend/scripts/eval_private.py` | PENDING REAL DATA |
| 2 | M3 | Share of real statements that need the LLM fallback (feeds the [A: M3] fallback share in `system_design.md` section 2.6) | `backend/scripts/eval_private.py` | PENDING REAL DATA |
| 3 | M4 | Channel rule coverage and precision on a labelled sample of real narrations; decides whether `channel_model.py` (LightGBM) is built (threshold about 95% coverage). Steps: `uv run python scripts/measure_rule_coverage.py coverage`, then `sample` (writes `labels/channel_sample.csv` inside PRIVATE_FIXTURES_DIR), label `true_channel` and `true_kind` by hand, then `score`. Also check the reversal, refund, compensation and charge keywords against real wording | `backend/scripts/measure_rule_coverage.py` | PENDING REAL DATA |
| 4 | M5 | Detector on real statements: aggregate finding counts by detector and level; every claim and question reviewed manually in `labels/claims_review.csv` (one subfolder per person in PRIVATE_FIXTURES_DIR) | `backend/scripts/eval_private_detect.py` | PENDING REAL DATA |
| 5 | M5 | Demand: % of statements with at least one confirmed claim, total Rs owed, total reversals found (on time + late, as a parser sanity check), duplicates found. Replaces the [U] assumptions in `system_design.md` section 2.5 | `backend/scripts/eval_private_detect.py` | PENDING REAL DATA |
| 6 | M3 | Parser order: confirm which banks appear most in the real statements and reorder parser work if needed | manual | PENDING REAL DATA |
| 7 | M3 | Confirm each bank layout (SBI, HDFC, ICICI, Axis, Kotak): exact header labels, date format, Cr/Dr style, single-line vs two-line headers, whether wrapped narrations sit below or around the date line. Only header lines are needed, never rows. Then set `verified_against_real_statement: true` for that layout | manual + `backend/scripts/eval_private.py` | PENDING REAL DATA |
| 9 | M5 | Failure words per bank (P9): check which words each bank really uses on failed or pending debits, update `FAILURE_WORDS` in `backend/src/vapas/detect/unreversed.py`, and add the bank to `FAILURE_WORDS_VERIFIED_AGAINST_REAL_STATEMENTS` | manual review of real narrations | PENDING REAL DATA |
| 10 | M5 | Merchant vs person signals (P7): check the UPI and AePS patterns in `backend/src/vapas/classify/payee.py` against real narrations (merchant QR VPAs, P2M/P2P markers, Aadhaar Pay, fund transfer); measure how many questions each statement generates from `analytics_events`; then set `PATTERNS_VERIFIED_AGAINST_REAL_STATEMENTS` | manual review + analytics | PENDING REAL DATA |
| 11 | M6 | PENDING SOURCE PDFS (not statements): give the paths of the RBI PDFs downloaded by hand; record the SHA-256 of the RB-IOS 2026 (and 2021) scheme PDFs in their YAML after checking they are the files the rules were verified against; then run `scripts/ingest_rbi.py --pdf rbi.dpss_629_2019=PATH --pdf rbi.rbios_2026=PATH` and re-run `scripts/eval_knowledge.py --write` | `backend/scripts/ingest_rbi.py` | PENDING |
| 8 | M3 | Real PDF parse time per page (system_design.md section 2.7, assumed 0.4 s, synthetic 0.10 s) | `backend/scripts/eval_parsers.py` style timing on private files | PENDING REAL DATA |
