# ADR 0009: RBI rules and VAPAS product policy are recorded and versioned separately

Status: accepted (M0.5, 19 Nov 2026)

## Context
Some behaviour comes from RBI text: the TAT of T+5, Rs 100 per day, the RB-IOS 2026 90-day window. Other behaviour is a VAPAS choice: the 12-month claim lookback, credit-push rows being only worth_checking, NACH needing user input, the Clause 10 hard blocks. Mixing the two would make a product choice look like a legal requirement, or let a product change silently alter a verified rule.

## Options
1. One combined rule definition with no distinction.
2. Fully separate files for legal rules and for policy.
3. Legal facts in `rules/rbi/` with quotes and verification. Product decisions are documented in `docs/product_policy.md` (P1 to P6) and expressed as a small, named set of policy fields (`finding_policy`, `letter_scope`, `user_inputs`, `letter_disclosure`) and config (`CLAIM_LOOKBACK_MONTHS`), versioned with their own hash.

## Decision
Option 3. Legal fields carry source, clause, quote and verification, and changing them requires manual re-verification. Policy fields make no legal claim and point to a P-number. The loader computes `rules_sha256` over the legal fields and `policy_sha256` over the policy fields plus policy config, and findings store both versions. Letters cite only legal rules; the UI presents policy choices as VAPAS choices, never as RBI requirements.

## Consequences
- A policy change (for example a different lookback) never touches a verified rule and never needs re-verification, but it does create a new policy version that shows on new findings.
- Reviewers can see exactly which part of a finding is law and which is a product choice.
- Policy fields sit next to the rule they apply to, so they are easy to find. The schema must therefore keep the legal and policy field sets clearly named and validated, which `rules/schema.py` already does for `finding_policy` and `letter_scope`.
