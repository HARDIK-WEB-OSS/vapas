# ADR 0005: All model access goes through one llm_gateway with redaction inside it

Status: accepted (M0.5, 19 Nov 2026)

## Context
Statement text contains account numbers, names, UPI IDs and third-party data. The real-data rule forbids sending real statements to any hosted model. Models are still useful for unknown statement layouts and for letter wording. Hosted providers fail, get slow, and cost money per token.

## Options
1. Call model SDKs wherever they are needed.
2. Local model only, no hosted model at all.
3. One internal `llm_gateway` module that is the only code allowed to reach any model, with routing, redaction, a circuit breaker per provider and a per-user daily budget.

## Decision
Option 3. Routes:
- `local` (Ollama, qwen2.5:3b or similar): the only route allowed for statement text. It is used for layout mapping and page extraction. Output is strict Pydantic and must pass balance reconciliation, otherwise it is rejected.
- `hosted`: only for redacted text (letter wording polish). The gateway redacts account and card numbers, names, phone numbers, emails, PAN, UPI IDs and IFSC-plus-account patterns. It then scans the redacted text again and blocks the call if anything matching those patterns remains.

Circuit breakers: if the hosted model fails, the unpolished template is used; if the local model fails, the statement goes to needs_review. A CI test fails if any module other than `llm_gateway` imports a model client.

## Update (M3, 20 Nov 2026)
The gateway calls the local Ollama HTTP API directly with `httpx` instead of going through LiteLLM. One local endpoint does not justify a large extra dependency (and its supply-chain surface). The gateway interface does not change, so LiteLLM or a provider SDK can be added behind it in M7 if the hosted route needs it. The budget is passed to the gateway as a `charge` callback, so the gateway itself never touches the database. Redaction now applies to every prompt, local route included.

## Consequences
- There is one place to audit for data leaving the machine, and a test proves nothing reaches the hosted route unredacted (M3).
- Polishing is optional by design, so a provider outage never blocks a letter.
- Local GPU capacity becomes the cost driver for unknown layouts (system_design.md section 2.6), which pushes towards native parsers for common banks.
- Redaction can over-redact wording. That is acceptable because guardrails re-check every amount and rule id anyway (ADR 0007).
