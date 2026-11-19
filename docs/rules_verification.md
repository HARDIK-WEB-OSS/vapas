# Rules verification (M0)

Every rule in `rules/rbi/` starts as `unverified`. Only rules you mark `verified` (with `verified_by` and `verified_on` in the YAML) may produce a claim shown to users. The schema rejects `verified` without both fields.

## How to verify

1. Open the official link in your browser (rbi.org.in may show a CAPTCHA; solve it yourself, never script around it). Download the PDF and check `(Get-FileHash .\file.pdf).Hash.ToLower()` against the `sha256` in the YAML (see `docs/product_policy.md` P4).
2. Compare the row below with the PDF, word by word: deadline, compensation, who is responsible, clause number.
3. If it matches, set `review: {status: verified, verified_by: <you>, verified_on: <date>}` in the YAML. If not, set `status: rejected` and tell me what differs.
4. Run `python rules/schema.py` to check the file still validates.

## A. Instruments and legal status (checked 19 Nov 2026)

| Instrument | Ref | Dates | Status | Check |
|---|---|---|---|---|
| TAT and compensation for failed transactions | RBI/2019-20/67, DPSS.CO.PD No.629/02.01.014/2019-20 | issued 20 Sep 2019, in force 15 Oct 2019 | `in_force_unconfirmed` | Confirm it is **not** in the 28 Nov 2025 repeal annex (that consolidation covered Department of Regulation circulars; this one is DPSS). Directions issued in 2024-25 (BBPS, Payment Aggregators, PPI) still cite it "as amended". [page](https://www.rbi.org.in/Scripts/NotificationUser.aspx?Id=11693&Mode=0), [PDF](https://rbidocs.rbi.org.in/rdocs/notification/PDFs/CIRCULAR677EC931A7A65E4D99AA957D8E85BC0A2A.PDF) sha256 `666fe280…f88f6` |
| Working-days relaxation 1 | RBI/2019-20/251, DPSS.CO.PD.No.1897/02.14.003/2019-20 | issued 4 Jun 2020; window 24 Mar 2020 to 31 Dec 2020 | `expired` | Annex SN 3. [page](https://www.rbi.org.in/Scripts/NotificationUser.aspx?Id=11910&Mode=0) |
| Working-days relaxation 2 | RBI/2021-22/41, CO.DPSS.POLC.No.S-106/02-14-003/2021-2022 | issued 21 May 2021; window "prospective" to 30 Sep 2021 | `expired` | Annexure SN 2; calendar days applied 1 Jan 2021 to 20 May 2021. [page](https://www.rbi.org.in/commonperson/english/scripts/Notification.aspx?Id=3307) |
| RB-IOS 2021 | CEPD.PRD.No.S873/13.01.001/2021-22 | 12 Nov 2021 to 30 Jun 2026 | `superseded` | Amended 5 Aug 2022 (S544) and 7 Oct 2025 (S684, in force 1 Nov 2025). [page](https://www.rbi.org.in/Scripts/NotificationUser.aspx?Id=12192&Mode=0) |
| **RB-IOS 2026** | Press release 2025-2026/1936; notification no. **not found yet** | issued 16 Jan 2026, in force **1 Jul 2026** | `in_force` | Fill in the notification number and clause numbers from the [scheme PDF](https://rbidocs.rbi.org.in/rdocs/content/pdfs/SCHEME16012026_A.pdf). |

The 2019 PDF hosted today cites "RB-IOS 2021 (as amended)" in para 6, so RBI changed the PDF after 2021. The sha256 lets us detect future silent edits.

## B. TAT rules (Annex to DPSS.CO.PD No.629, PDF pages 4-5)

Common to all rows: T = transaction date (calendar date, General Instruction 4). R = day the reversal is concluded (GI 5). Compensation = ₹100 × days of delay beyond the deadline, credited suo moto (para 5). Domestic transactions only (GI 7).

| # | Rule id | Annex | System / scenario | Responsible | Deadline | Compensation | VAPAS policy | Verified |
|---|---|---|---|---|---|---|---|---|
| 1 | `rbi.tat.atm_cash_not_dispensed` | 1(a) | ATM / micro-ATM: debited, cash not dispensed | issuer bank | T+5 | ₹100/day beyond T+5, to the account holder | claim on late reversal | ☐ |
| 2 | `rbi.tat.card_to_card` | 2(a) | Card-to-card: beneficiary card not credited | not stated | T+1 | ₹100/day beyond T+1 | claim on late reversal | ☐ |
| 3 | `rbi.tat.card_pos` | 2(b) | PoS card present incl. cash at PoS: no charge slip | not stated | T+5 | ₹100/day beyond T+5 | claim on late reversal | ☐ |
| 4 | `rbi.tat.card_cnp` | 2(c) | Card not present (e-commerce): no merchant confirmation | not stated | T+5 *(merged cell with 2b)* | ₹100/day beyond T+5 *(merged)* | claim on late reversal | ☐ |
| 5 | `rbi.tat.imps_not_credited` | 3(a) | IMPS: beneficiary not credited | **beneficiary bank** | T+1 | ₹100/day beyond T+1 | needs user input | ☐ |
| 6 | `rbi.tat.upi_p2p_not_credited` | 4(a) | UPI transfer: beneficiary not credited | **beneficiary bank** | T+1 | ₹100/day beyond T+1 | needs user input | ☐ |
| 7 | `rbi.tat.upi_merchant` | 4(b) | UPI merchant: no confirmation at merchant | not stated | T+5 | ₹100/day beyond T+5 | claim on late reversal | ☐ |
| 8 | `rbi.tat.aeps_merchant` | 5(a) | AePS: no confirmation at merchant | acquirer ("Credit Adjustment") | T+5 | ₹100/day beyond T+5 | claim on late reversal | ☐ |
| 9 | `rbi.tat.aeps_not_credited` | 5(b) | AePS: beneficiary not credited | acquirer *(merged cell with 5a)* | T+5 *(merged)* | ₹100/day beyond T+5 *(merged)* | needs user input | ☐ |
| 10 | `rbi.tat.apbs_credit_delay` | 6(a) | APBS: delay crediting beneficiary | beneficiary bank | T+1 | ₹100/day beyond T+1 | not detectable in v1 | ☐ |
| 11 | `rbi.tat.nach_credit_delay` | 7(a) | NACH: delay in credit or reversal | beneficiary bank | T+1 | ₹100/day beyond T+1 | not detectable in v1 | ☐ |
| 12 | `rbi.tat.nach_debit_after_revocation` | 7(b) | NACH: debited despite mandate revocation | customer's bank | T+1 ("resolution") | ₹100/day beyond T+1 *(compensation cell merged with 7a)* | needs user input | ☐ |
| 13 | `rbi.tat.ppi_off_us` | 8(a) | PPI off-us | rules of the underlying system | — | — | delegates | ☐ |
| 14 | `rbi.tat.ppi_on_us` | 8(b) | PPI on-us: not credited / no merchant confirmation | not stated | T+1 | ₹100/day beyond T+1 | not detectable in v1 (bank statements only) | ☐ |

*Merged cell*: in the PDF table one cell spans two rows, so the text extractor shows the lower row as empty. I rendered the pages and checked: the 2(b), 5(a) and 7(a) cells extend down over 2(c), 5(b) and 7(b). Please confirm this visually.

## C. Day-type overrides

| Rule id | Window | Effect | Verified |
|---|---|---|---|
| `rbi.tat_override.working_days_2020` | 24 Mar 2020 to 31 Dec 2020 | read "calendar days" as "working days" | ☐ |
| `rbi.tat_override.working_days_2021` | 21 May 2021 (assumed) to 30 Sep 2021 | same | ☐ |

## D. Ombudsman rules (RB-IOS 2026, in force 1 Jul 2026)

Text taken from RBI's FAQ on the scheme because the scheme PDF is behind a CAPTCHA. **Fill in the exact clause numbers from the scheme PDF.**

| Rule id | Rule | Days | Verified |
|---|---|---|---|
| `rbi.rbios26.prior_complaint` | complain to the bank first and keep proof | — | ☐ |
| `rbi.rbios26.wait` | wait 30 days (or longer if RBI/NPCI/card network guidelines set more) after the bank receives the complaint, unless it replied and the customer is dissatisfied | 30 | ☐ |
| `rbi.rbios26.deadline` | file with the Ombudsman within 90 days of the later of (wait period ends) and (last communication from the bank) | 90 | ☐ |
| `rbi.rbios26.limitation` | complaint to the bank within the Limitation Act, 1963 period (no number stored) | — | ☐ |
| `rbi.rbios26.filing_channels` | cms.rbi.org.in / crpc@rbi.org.in / CRPC Chandigarh | — | ☐ |
| `rbi.rbios26.appeal` | appeal an Award within 30 days (+30 at the Appellate Authority's discretion) | 30 | ☐ |
| `rbi.rbios26.transition` | complaints received before 1 Jul 2026 stay under RB-IOS 2021 | — | ☐ |
| `rbi.rbios21.deadline` | (history) 2021 scheme 10(2)(a)(ii): 1 year after reply, or 1 year + 30 days with no reply | — | ☐ |

## E. NACH mandate clauses on npci.org.in

No public NPCI clause on debits after mandate revocation was found. The NACH circular list shows "Circular No. 54 – Process Change in Mandate Cancellation", but its text is not publicly readable (the site serves no content to automated clients). The **RBI** annex does have a clause: row 7(b) above. See the open decision in the M0 summary.

## F. Ambiguous edge cases and conservative handling

| Case | Ambiguity | Conservative handling |
|---|---|---|
| Definition of T | T is the "calendar date" of the transaction, but statements show a txn date, a value date, or both, and late-night transactions can post the next day. | T = the **later** of txn date and value date (gives the bank the most time, so fewer false claims). If the two differ by more than 1 day, the finding is needs_review. |
| Definition of R | R is when funds return to the issuer; the circular says the customer's credit must happen the same day. The statement only shows the customer credit. | R = the date of the reversal credit on the statement. If the reversal is earlier than or equal to the deadline, no claim. |
| Delay formula | "₹100 per day of delay beyond T+n" | delay_days = R − (T + n), claim only if > 0; amount = 100 × delay_days. Example: ATM T=1 Mar, R=8 Mar, so delay = 8 − 6 = 2 days and ₹200 is owed. |
| Partial reversal | Reversal amount < debit | Not a claim. "Worth checking" with both amounts. |
| Reversal split across days | Several credits add up to the debit | Match only if the parts sum exactly to the debit; R = the date of the last part. Otherwise worth checking. |
| Compensation already paid | Bank may credit "TAT comp" or similar | Subtract any credit whose narration matches compensation patterns and whose date is after R; if unclear, show "may already be paid" and lower the confidence. |
| Working-day windows (2020, 2021) | Working days need a bank-holiday calendar we don't have from an allowed source | Transactions with T inside an override window → needs_review, no amount calculated. |
| 1 Jan to 20 May 2021 gap | Start of the 2021 "prospective" relaxation | Calendar days assumed, but marked needs_review. |
| Responsible party not stated (rows 2, 4b, 8b) | The annex does not say which bank pays | Letter addresses the customer's own bank (the bank holding the statement) and cites the row; the annex does not name a payer. |
| Credit-push payee (GI 1(a)) | GI 1(a) says the penalty for unreversed credit-push transfers is paid "to the beneficiary" | IMPS/UPI P2P rows stay needs_user_input as already decided; letters never state who receives compensation beyond the annex text. |
| Old transactions | Ombudsman requires the complaint to the bank within the Limitation Act period | No legal period stored. Product rule P2: only the last 12 months (configurable) can become claims; older findings are "historical, informational only". |
| NACH revocation date | The statement does not show when the mandate was revoked | Product rule P1: needs user input (revocation date + proof confirmed); the letter states the date was provided by the user. |
| International transactions | GI 7: domestic only | Excluded (already decided). |
