# Product policy decisions

These are VAPAS product rules, not legal rules and not legal advice. They sit on top of the verified rules in `rules/rbi/`. Decided after the M0 review on 19 Nov 2026.

## P1. NACH debit after mandate revocation
- Rule: `rbi.tat.nach_debit_after_revocation` (Annex 7(b)).
- A finding starts as **needs user input**. It becomes a claim only after the user enters the revocation date **and** confirms they have proof of the revocation.
- T = the debit date. The debit must be after the revocation date the user entered.
- Every letter must include the rule's `letter_disclosure`: the revocation date was provided by the customer and is not shown on the statement.
- Encoded as `user_inputs` and `letter_disclosure` in the YAML. The schema rejects user inputs without a disclosure.

## P2. Old-transaction cutoff
- Only transactions dated within the last **12 months** can become claims. The window is configurable (`CLAIM_LOOKBACK_MONTHS`, added to `.env.example` in M1).
- Older findings are shown as **"historical, informational only"**: no claim, no letter, no amount presented as owed.
- This is a product choice to keep claims fresh and easy to evidence. It is not an interpretation of the Limitation Act.

## P3. Ombudsman wait and 90-day window (RB-IOS 2026)
- Wait before escalation = max(30 days, the TAT rule's `escalation_wait_days`). The 30 days come from `rbi.rbios26.wait` (`longer_system_wait_applies: true`). `escalation_wait_days` is set per TAT rule only when a longer RBI, NPCI or card network period is found on an allowed source and verified; until then it stays null.
- Filing deadline = 90 days from the later of (the wait period ends) and (the bank's last communication), per `rbi.rbios26.deadline`.
- M7 reminders and the M8 case page must show a visible countdown to this deadline. The bank's last communication date is entered by the user.

## P4. RBI/NPCI source documents
- Download source PDFs manually in a browser. Never script around the bot check or CAPTCHA.
- Record the sha256 of the downloaded file in the YAML (`sha256`), e.g. `(Get-FileHash .\file.pdf).Hash.ToLower()`.
- `scripts/ingest_rbi.py` (M6) reads only manually downloaded files and refuses any file whose hash differs from the one in the YAML.
- Source PDFs are not committed (`*.pdf` is in `.gitignore`); the URL plus hash is the record.
