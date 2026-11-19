# ADR 0004: Legal rules are versioned data, not code

Status: accepted (M0.5, 19 Nov 2026)

## Context
Every amount VAPAS shows must trace to a verified RBI instrument, clause and effective window. Rules change over time: RB-IOS 2026 replaced RB-IOS 2021, and there were day-type relaxations in 2020 and 2021. A finding must stay explainable after the rules change.

## Options
1. Hard-code TATs and amounts in detector code.
2. Rules in a database, edited through an admin UI.
3. Rules as YAML files in `rules/`, validated by `rules/schema.py`, reviewed in git, and loaded into read-only database tables at deploy with a content hash as the version.

## Decision
Option 3. `rules/loader.py` validates the YAML, computes `rules_sha256` (legal fields) and `policy_sha256` (product-policy fields and policy config), and activates a `rule_versions` row. Only rules with `review.status: verified` can produce a finding with an amount; the loader refuses to activate a set in which a claim-producing rule is unverified. The detector picks the rule whose effective window contains the transaction date T. Each finding stores `rule_id`, `rule_version_id` and `policy_version` and is never re-pointed to a newer version.

## Consequences
- Every rule change is a reviewed git diff with source URL, quote and verification record.
- Old findings remain explainable with the exact rule text that produced them.
- CI fails if any rule YAML is invalid (M1).
- Changing a rule needs a deploy. That is acceptable because every change also needs manual verification against the source.
