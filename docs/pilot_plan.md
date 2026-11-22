# Pilot plan (M10)

Status: ready to run once the deploy in `docs/needs_owner.md` is done. Nothing in this plan has been run yet; there are no pilot numbers.

## 1. Goal and the questions it answers

A closed beta with 20 to 50 people to learn, with measured numbers:

1. Does VAPAS read real statements? (% statements processed, % fully reconciled, per bank)
2. Are the findings right? (user-confirmed precision of "money owed" claims, with a 95% interval)
3. Is there money to find? (claims per active user, rupees found)
4. Does anyone get it back? (cases created, sent, escalated, expired; rupees recovered as reported by users)

Synthetic tests prove the code matches the generator, not that it is right on real banks. Only this pilot measures real precision.

## 2. Who

- 20 to 50 adults: friends, family, college contacts, each with an Indian savings account at a supported bank (SBI, HDFC, ICICI, Axis, Kotak first).
- Each person uses their own account and uploads their own statements. Nobody uploads a statement for someone else.
- No payment, no incentive (v1 is free, CLAUDE.md product limits).

## 3. Before the first invite (checklist)

- [ ] Deploy done, custom domain working, `/ready` green, uptime monitor and Sentry on (`docs/needs_owner.md`).
- [ ] `INVITE_ONLY=true` on the API and `NEXT_PUBLIC_INVITE_ONLY=1` on the frontend.
- [ ] Legal review of privacy policy and terms; native Hindi review; per-bank download steps (pending items 12 to 15 in `docs/pending_real_data.md`).
- [ ] Owner has run the whole flow on production with a synthetic statement.
- [ ] Invite codes created: `uv run python scripts/create_invites.py --count 50 --cohort pilot-1 --max-uses 1 --expires-days 30` (codes are printed once and stored hashed).
- [ ] A support channel that is not the app (a dedicated email address) for questions and "please delete my data" requests.

## 4. Invitation message (short consent message)

Send one code per person, personally (not in a group):

> Hi! I am testing VAPAS, a free tool I built that reads your bank statement and finds failed payments the bank refunded late. Under an RBI rule, banks owe Rs 100 for every day of such delay, and most people never claim it.
>
> What it does: you upload your statement; it shows items worth checking and drafts a complaint you can send yourself. It never connects to your bank, never touches money and never sends anything on your behalf. It is not legal advice.
>
> Your data: the statement file is deleted within an hour of reading; transaction details are encrypted; you can download or delete everything at any time in Settings. The full privacy notice is shown at signup.
>
> What I ask: try it with the last 12 months of statements and press "Looks right", "This is wrong" or "Not sure" on each finding. After a week I will ask you 5 short questions. You can stop at any time.
>
> Your invite code: XXXX-XXXX-XXXX-XXXX (single use, valid 30 days). Sign up at https://app.<domain>

Joining is voluntary; the in-app consent notice is the legal consent. Keep a private list (outside the repo) of who received which code only if needed to answer support requests; delete it at the end of the pilot.

## 5. Timeline

| Week | What |
|---|---|
| 0 | Checklist above; invite 10 people first (wave 1) |
| 1 | Watch Sentry and dead jobs daily; fix blockers; first weekly report |
| 2 | Wave 2: invite the rest if wave 1 had no wrong claim left unexplained |
| 3-6 | Follow cases: reminders, escalations, recoveries; weekly report every Monday |
| 7 | Questions round 2 (did the bank pay?); final report; decide next step |

## 6. Questions after one week

Ask by message or a short call. Record answers in a private sheet without statement details.

1. Could you download and upload your statement without help? Where did you get stuck?
2. Did any finding surprise you? Did you check one against your bank app?
3. Did you send a complaint to your bank? If not, why not?
4. Did anything make you worry about your data or money?
5. Would you tell a friend about VAPAS? Why or why not?

## 7. Numbers to track (weekly)

Run every Monday for the previous week:

```powershell
cd backend
uv run python scripts/impact_report.py --data-label "pilot" --out C:\vapas-reports\impact-<date>.md
```

The report (`backend/src/vapas/analytics/impact.py`) holds aggregates only: users, active users, statements processed, % reconciled, findings per active user, user-confirmed precision for claims and worth-checking items (Wilson 95% interval), cases created, escalated, expired, rupees found, rupees recovered. An example on synthetic data is in `docs/impact_report_synthetic.md`.

The run needs the owner database role to bypass RLS (`docs/needs_owner.md` section 2). Reports on pilot data are not committed; only final, aggregate numbers go into the README.

## 8. Stop rules

- Any "This is wrong" on a **money owed** claim: look at it within 48 hours (with the user's permission, using only what they choose to share), reproduce it as a synthetic case, fix, release. Until fixed, if the cause could affect others, turn the affected rule's claims into "worth checking" in the product policy and release.
- Claim precision below 90% with at least 10 judged claims: pause new invites until fixed.
- Any suspected data leak: stop the pilot and follow section 7 of `docs/privacy.md`.
- A case reaching `expired`: contact the user to learn why; consider earlier reminders.

## 9. Fix loop

Every "This is wrong" becomes a regression test:

1. Write the pattern in one sentence (for example "merchant refund treated as late reversal").
2. Build synthetic rows that reproduce it, with invented names, amounts and references. Never copy real narrations, names, UPI IDs or account numbers.
3. Add a `RegressionCase` to `backend/tests/regression/cases.py` with `case_id` `PILOT-<number>`, `source` "pilot feedback, <date>", the pattern, the rows and the expected result (`forbidden_levels`, or `expected` findings).
4. Run `uv run pytest tests/regression`: it must fail before the fix and pass after it.
5. Fix the classifier, detector or product policy (never a verified RBI rule without the owner re-verifying it), run the full suite, release.

The file already contains two template cases and a positive control.

## 10. End of pilot

- Final report with real numbers only; README updated (CLAUDE.md "README (final)" and "RESUME OUTPUT").
- Ask each participant whether they want to keep their account; delete on request (Settings, or the owner via the same deletion path).
- Delete the private code-to-person list.
