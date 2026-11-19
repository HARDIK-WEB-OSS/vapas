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
| 3 | M4 | Channel rule coverage and precision on a labelled sample of real narrations; decides whether `channel_model.py` (LightGBM) is built (threshold about 95% coverage) | `backend/scripts/measure_rule_coverage.py` | PENDING REAL DATA |
| 4 | M5 | Detector on real statements: aggregate finding counts by kind; every claim reviewed manually | `backend/scripts/eval_private.py` | PENDING REAL DATA |
| 5 | M5 | Demand: % of statements with at least one confirmed claim, total Rs owed, total reversals found (on time + late, as a parser sanity check), duplicates found. Replaces the [U] assumptions in `system_design.md` section 2.5 | `backend/scripts/eval_private.py` | PENDING REAL DATA |
| 6 | M3 | Parser order: confirm which banks appear most in the real statements and reorder parser work if needed | manual | PENDING REAL DATA |
