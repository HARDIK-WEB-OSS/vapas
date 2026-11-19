# ADR 0007: Complaint letters are templates filled with engine facts; a model may only polish wording

Status: accepted (M0.5, 19 Nov 2026)

## Context
Letters go to banks and, for escalation, into the RBI CMS portal. A wrong amount, a wrong rule or an invented clause damages the user's claim and trust. reversal_only letters must never contain an amount. NACH letters must state that the revocation date was provided by the customer. Bank letters must not cc RBI as a form of escalation (P6).

## Options
1. A model drafts the whole letter from the findings.
2. Templates only, no model at all.
3. Templates (English and Hindi) filled only with engine facts; an optional model polish via `llm_gateway` on redacted text; guardrails check the final text.

## Decision
Option 3. `letters/guardrails.py` extracts every amount, date and rule id from the final text. They must match the engine's facts and the verified rule ids exactly, and the required disclosures and the "not legal advice" notice must be present. Any mismatch, a missing disclosure, or an amount in a reversal_only letter rejects the polished version, and the unpolished template is used. The user must approve every letter.

## Consequences
- Letters are always correct, even if the model is down or misbehaves.
- Hindi and English templates must be written and maintained by hand.
- How much the wording can be polished is limited. That is acceptable for a formal complaint.
