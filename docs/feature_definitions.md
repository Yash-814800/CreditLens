# Feature definitions

Every canonical feature from CLAUDE.md's "Domain contracts" section, with its
exact formula. Source of truth is the code (`backend/app/services/scoring/features.py`
and `backend/app/services/ingestion/bank_parser.py`); this document must stay in
sync with it. A feature is `None` (never a fabricated value) whenever the
document it depends on is missing, or a required field inside it was
unreadable -- Phase 5's scorecard treats a missing factor as 0 points
(neutral), never as a penalty for data that simply isn't there.

## From the utility bill

**`utility_tenure_months`** = `(bill_date - connection_date).days / 30.44`.
`None` if either date is missing/unreadable or `bill_date < connection_date`.

**`utility_on_time_ratio`** = fraction of the **last <= 12** `payment_history`
rows whose `status == "On-time"`. Only the most recent 12 months are
considered so an old, resolved delinquency doesn't permanently cap an
applicant who has since paid on time for a year. `None` if there is no
payment history at all.

## From the gig-payout report

**`gig_active_days_per_week`** = mean of `active_days` across all reported
weeks. `None` if there are no weeks.

**`gig_weekly_earnings_cv`** = population coefficient of variation
(`pstdev(net_payout) / mean(net_payout)`) across all reported weeks, computed
on **net** payout (after platform deductions), not gross earnings. `None` if
fewer than 2 weeks are reported or the mean is 0.

**`gig_tenure_weeks`** = `(report_period_end - partner_since).days / 7`. `None`
if either date is missing/unreadable or `report_period_end < partner_since`.

## From the bank/UPI statement

**`avg_daily_balance_inr`**: the end-of-day balance is forward-filled over
**every calendar day** in `[period_from, period_to]` (not just days with a
transaction -- a day with no activity keeps the prior day's closing balance),
then averaged. This matches how a real cash-flow analytics product (e.g.
FinBox BankConnect) would compute it, and avoids understating balance
stability just because most days have no transaction.

**`low_balance_day_ratio`** = fraction of those same forward-filled daily
balances that fall below **₹500**.

**`weekly_inflow_cv`** = population CV of total **credit** amount per
calendar week (Monday-Sunday), counting **complete weeks only** (a week whose
Monday falls within the statement period AND whose Sunday also falls within
it). This is a general cash-inflow-stability signal computed from *every*
credit line in the statement, not just gig-platform ones -- deliberately
distinct from `gig_weekly_earnings_cv`, which measures volatility of the
*declared* gig income instead. `None` if fewer than 2 complete weeks exist.

**Running-balance verification** (not a scored feature, but computed
alongside these): replays `balance[i] = balance[i-1] + credit[i] - debit[i]`
for every row and reports any row where the statement's own stated balance
disagrees with that replay by more than a 1-paisa tolerance. Feeds Phase 4's
arithmetic-consistency fraud check.

## Cross-document features

**`income_reconciliation_ratio`** = `bank_platform_credits_inr / gig_total_net_payout_inr`,
capped at **1.5**. "Platform credits" are bank-statement credit rows whose
narration contains the gig platform's name with spaces/punctuation stripped
(both sides are normalised to bare uppercase alphanumerics before comparing,
because narrations render names like "ZIPRIDEPARTNER" with no spaces --
see `find_platform_credits()`). `None` unless **both** the bank statement and
the gig-payout report are present -- this is a cross-check, not a
single-document feature, so it has no meaning with only one side available.

**`verified_monthly_income_inr`**: a conservative monthly income estimate.
- Each present document produces its own independent monthly estimate:
  - Bank: `total_platform_credits_inr / period_days * 30.44`.
  - Gig payout: `total_net_payout_period / weeks_in_report * 4.345`
    (4.345 = 52/12, the standard weeks-per-month average).
- **Both present**: the estimate is the **minimum** of the two independent
  estimates (deliberately conservative -- an underwriter should not trust
  whichever single number is larger).
- **Only one present**: that document's estimate, discounted by a flat **30%
  haircut** for being single-sourced and unreconciled against the other
  document.
- **Neither present**: `None`.

**`authenticity_score`** is populated by the fraud/integrity layer (Phase 4),
not by this module -- it is `trust_score / 100` from `run_fraud_checks()`.

## What Phase 3 deliberately does NOT compute here

`data_completeness` (which documents are present/legible) and the score/
decision themselves are Phase 5 (`scoring/scorecard.py`, `scoring/decision.py`)
concerns, built on top of this feature dict -- this module's only job is
"given whatever documents exist, compute whatever numbers can honestly be
computed from them."
