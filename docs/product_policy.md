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

## P5. Transfers not credited to the beneficiary (credit-push)
- Rules: `rbi.tat.card_to_card` (2a), `rbi.tat.imps_not_credited` (3a), `rbi.tat.upi_p2p_not_credited` (4a), `rbi.tat.aeps_not_credited` (5b).
- Annex General Instruction 1(a): for credit-push transfers the penalty is paid **to the beneficiary**, so VAPAS cannot tell the payer they are owed it.
- Policy: **worth checking** only. No amount and no claim, even with user input. Letters may ask only for the reversal (`letter_scope: reversal_only`; the schema rejects any other scope for worth_checking rules).

## P6. RB-IOS 2026 maintainability (Clause 10)
- Bank complaint letters never cc or mark RBI as a form of escalation. Copying RBI is not a complaint to the Ombudsman (`rbi.rbios26.direct_to_ombudsman`, Clause 10(1)(a)).
- VAPAS never files a complaint for the user. The user files personally (`rbi.rbios26.who_may_file`, Clause 10(1)(b)).
- Before escalation, M7 asks: "Have you already filed this grievance with the RBI Ombudsman or any court, tribunal, arbitrator or other forum?" If the answer is yes, escalation is blocked (`rbi.rbios26.no_duplicate_grievance`, Clause 10(1)(h)-(k)).

## P4. RBI/NPCI source documents
- Download source PDFs manually in a browser. Never script around the bot check or CAPTCHA.
- Record the sha256 of the downloaded file in the YAML (`sha256`), e.g. `(Get-FileHash .\file.pdf).Hash.ToLower()`.
- `scripts/ingest_rbi.py` (M6) reads only manually downloaded files and refuses any file whose hash differs from the one in the YAML.
- Source PDFs are not committed (`*.pdf` is in `.gitignore`); the URL plus hash is the record.

## P7. UPI and AePS: merchant payment or transfer to a person (accepted 21 Nov 2026)
- Rows 4(b) and 5(a) (payment to a merchant) are claim rows; rows 4(a) and 5(b) (transfer to a person, credit-push) are not (P5).
- **Amended 21 Nov 2026:** VAPAS first classifies from the statement description, using structural signals only (never merchant names): a `P2M` marker, merchant QR VPA patterns (PhonePe `Q...@ybl`, `paytmqr...@paytm`, `bharatpe...`), a POS/ECOM code inside a UPI line, AePS "Aadhaar Pay" or "purchase" for merchants; a `P2P`/`P2A` marker or AePS "fund transfer"/`FT` for persons (`backend/src/vapas/classify/payee.py`). These patterns are not yet verified on real statements (PENDING REAL DATA).
- Only when there is no clear signal, or signals conflict, does VAPAS ask the user: "Was this a payment to a shop or business?". The user's answer always overrides the statement signal.
- Until classified, the finding is **needs user input** and shows no amount. Merchant makes it a claim under 4(b) / 5(a); person makes it informational under 4(a) / 5(b) (compensation goes to the receiver, Annex General Instruction 1(a)).
- Each finding records how the merchant classification was made (`merchant_source`: `customer` or `statement:<signal>`). The number of questions each statement generates is tracked in `analytics_events` (`statement_analysed`, no personal data) to see how often users must be asked.
- Every complaint letter for a UPI or AePS claim must state how the merchant classification was made: "confirmed by the customer" when the user answered, or "classified from the statement description" when a statement signal decided it. M7 letter guardrails must require the matching sentence.
- **Interpretation (recorded as such):** an AePS cash withdrawal at a business correspondent is classified under Annex row **1(a)**, because the annex wording for that row covers "ATMs including Micro-ATMs" with "cash not dispensed". It is detected from the AePS narration (CASH WITHDRAWAL, CASH WDL, CW) and needs no question. T + 5 days and Rs 100 per day apply either way, so the amount does not depend on this choice; only the cited row does.

## P8. Uncertain matches never become claims (accepted 21 Nov 2026)
- If a reversal carries no reference number shared with the debit and more than one debit could belong to it (same amount, channel and counterparty), the finding is **needs review** with no amount.
- Only transactions from statements whose running balance reconciled are used for detection. A statement that did not reconcile shows the user a plain-language reason (`analysis_note` on the statement) explaining that it was not analysed and what to try instead.
- Transactions with an international marker (INTL, FOREIGN, a foreign currency code) are skipped (Annex General Instruction 7: domestic only).

## P9. Debits that look failed but were never reversed (accepted 21 Nov 2026)
- Only debits whose description contains a failure word are flagged. The list is kept **per bank** (`FAILURE_WORDS` in `detect/unreversed.py`); every bank currently uses the default list (FAILED, FAIL, DECLINED, TIMEOUT, TIMED OUT, NOT DISPENSED, PENDING), and no list is verified against real statements yet (PENDING REAL DATA). Ordinary debits are never flagged.
- The user is asked "Did the payment fail?". Only after "yes", and only on a claim row, the finding becomes a claim whose compensation keeps growing (accruing) until the reversal arrives.

## P10. NACH mandates (accepted 21 Nov 2026, implements P1)
- NACH debits are grouped by counterparty. One question per group: "Did you cancel this mandate before any of these debits?"
- After the user enters the cancellation date and confirms proof, each debit after that date becomes a claim under 7(b): T = debit date, deadline T + 1, compensation accrues until a matching reversal arrives.
