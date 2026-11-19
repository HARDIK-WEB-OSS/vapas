# Competitors (checked 19 Nov 2026)

## nyaykar.in (checked directly)

- **Input:** what the user types or says (11 Indian languages), plus company, date and amount. Nothing on the page says it reads bank statements or documents.
- **Output:** works out which regulator applies (RBI, IRDAI, TRAI, RERA, e-Jagriti), gives a 0-100 "case readiness" score, and drafts complaint letters (CPA 2019 format, English only). It shows filing steps, drafts escalation letters after 21 days without a reply (Pro), and also covers RTI and Section 138 cheque-bounce notices.
- **Pricing:** free check (letter preview only); ₹49 for 2 letters; ₹199 for a 30-day Pro pass.
- **Failed transactions / TAT:** not mentioned. It does not calculate ₹100/day compensation.
- **Submission:** it does not file for the user (portals need OTP/Aadhaar). VAPAS works the same way.

## Others

A web search for apps that read statements and detect late refunds or RBI compensation found none. It returned only bank and fintech blogs (Paytm, PhonePe) and news articles explaining the rule; these give no automated detection and sometimes contradict the circular. Example: some say compensation must be claimed, but para 5 says it is paid suo moto.

## How VAPAS differs

| | nyaykar.in | VAPAS |
|---|---|---|
| Finds the problem | user must already know | reads the statement and detects late reversals, duplicates and charges |
| Amount | user supplies | calculated from a verified rule: ₹100 × days beyond T+n, minus anything already paid |
| Citation | regulator routing | exact instrument, Annex row, effective dates, and a hash of the source PDF |
| Scope | broad (telecom, insurance, RERA, RTI…) | narrow: bank-statement money owed |
| Escalation timing | 21-day generic nudge | RB-IOS 2026: day 30 eligibility, then 90-day deadline tracking |
| Price | paid letters | free in v1 (decided) |

Our moat is detection and calculation, not letter writing. Letter drafting is a commodity, so VAPAS should not compete on it.
