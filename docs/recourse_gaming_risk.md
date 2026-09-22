# Recourse gaming risk

`backend/app/services/scoring/recourse.py` tells a REFER/DECLINE applicant
exactly which numeric thresholds to cross to reach a better outcome tier.
That transparency is the point (CLAUDE.md rule 3: no black-box decisioning),
but it is also, honestly, a map of exactly how to game the scorecard if the
underlying behaviour isn't real. This is a known, accepted trade-off of
transparent scorecards generally (not unique to this system), and it is worth
naming plainly rather than pretending it doesn't exist.

## The concrete risk

The clearest example is `avg_daily_balance_inr`: the recourse text says
"maintain an average daily balance of at least Rs X for about 30 days." A
bad-faith applicant could borrow or transfer a lump sum into their account
right before re-submitting a bank statement, hold it for the minimum window,
withdraw it immediately after, and walk away with a scorecard-visible balance
that does not reflect their real financial cushion.

Similar, smaller-magnitude versions exist for the other actionable factors:
- `gig_active_days_per_week`: working unsustainably hard for one short
  reporting window right before reapplying, then reverting.
- `income_reconciliation_ratio`: a one-time manual transfer that happens to
  match a declared payout figure, without an ongoing real reconciliation
  habit.
- `utility_on_time_ratio` / `utility_tenure_months`: comparatively low risk,
  since these require sustained behaviour over real calendar time and a
  real utility relationship, which is much harder to fake cheaply.

## Why this system ships the transparency anyway

CLAUDE.md rule 3 requires transparent, explainable decisioning; hiding the
scorecard's thresholds to make gaming harder would trade away exactly the
auditability and fairness the project exists to demonstrate. A black-box
score without recourse is not a safer alternative -- it is worse for
legitimate applicants and does not actually stop a determined bad actor from
probing the system's boundary through trial and error anyway.

## How production monitoring would counter it (not implemented in this demo)

1. **Sustained-window verification, not a single snapshot.** `avg_daily_balance_inr`
   should ultimately be computed from a consent-based, ongoing feed (Account
   Aggregator / bank API, per this repo's README "production path" section)
   rather than a single uploaded CSV, so a balance spike-and-drop around the
   exact statement window is visible as an anomaly rather than invisible
   between two snapshots.
2. **Re-verification at disbursal, not just at scoring.** A short
   cooling-off/re-check before funds are released catches a balance that
   reverted immediately after the statement was pulled.
3. **Trend and spike detection**, flagging a single unexplained large credit
   followed by an equally large debit within days as its own fraud finding
   (a natural extension of Phase 4's semantic/arithmetic checks, which
   already flag single-transaction spikes) -- this app's fraud layer already
   has `check_credit_spike`-style logic conceptually in scope; the specific
   "spike then reversal around a recourse deadline" pattern is a reasonable
   addition to Phase 4's fraud_policy_v1.yaml if this went to production.
4. **Recourse re-application cooldown.** Rate-limit how soon a declined/
   referred applicant can re-submit and be re-scored, so gaming requires
   sustaining the (expensive, or genuinely behaviour-changing) action for
   real, rather than a quick single-cycle patch.

None of the above is implemented in this hackathon build -- `data/synth/`
data and `data/demo_pack/` personas are static, single-snapshot files, so
there is no "before/after" re-verification window to monitor yet. This note
exists so the risk is documented rather than silently assumed away.
