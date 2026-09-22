"""Policy engine (CLAUDE.md rule 3/6: pure function, no I/O, no black-box
decisioning). `decide()` is the single place outcome/tier/limit/reason-codes
are produced; Phase 6's pipeline calls this after scorecard.compute_score()
and passes its result straight into decision_artifacts for the audit log.

Rule order (fixed; see backend/app/config/policy_v1.yaml for the numbers):
  1. Fraud severity HIGH -> DECLINE (hard floor -- nothing overrides this).
  2. Fraud severity MEDIUM -> caps at REFER.
  3. Identity check FAIL -> caps at REFER.
  4. Prompt-injection suspected on any document -> caps at REFER.
  5. Completeness/confidence gate fails -> caps at REFER (never DECLINE for
     thin data alone -- CLAUDE.md's explicit instruction).
  6. Score tiers (APPROVE/REFER/DECLINE thresholds from policy_v1.yaml).
  7. Two-signal rule: if a precedent_signal disagrees with the tier the score
     alone would produce, move to REFER (never used to make an outcome
     *worse* than REFER, and never invents an APPROVE/DECLINE the scorecard
     didn't already produce -- it only ever downgrades an APPROVE or
     upgrades a DECLINE, per the phase spec).
  8. Limit sizing (multiplier x verified_monthly_income_inr, capped, with a
     REFER starter-tier fraction applied afterward).
  9. RC10 (requested exceeds verified capacity) is appended if applicable,
     independent of the outcome the above rules produced.

Reason-code note: CLAUDE.md's canonical list (RC01-RC10) has no dedicated
code for "prompt-injection suspected" -- it is, at its core, a document-
integrity concern, so it is reported under RC07 (DOCUMENT_INTEGRITY_CONCERN),
the same code fraud findings and the authenticity_score scorecard factor use.
This is a documented, deliberate reuse (see docs/PROGRESS.md's Phase 5
section), not a gap.
"""

from __future__ import annotations

from functools import cache
from pathlib import Path
from typing import Any

import yaml

from app.schemas.scoring import Decision, PrecedentSignal, ScoreBreakdown

_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "policy_v1.yaml"

RC_FRAUD_OR_INJECTION = "RC07"
RC_IDENTITY_MISMATCH = "RC08"
RC_INCOMPLETE = "RC09"
RC_EXCEEDS_CAPACITY = "RC10"

_TIER_LABEL = {
    "APPROVE": "Standard approval",
    "REFER": "Tiered limit (refer for review)",
    "DECLINE": "Declined",
}


@cache
def load_policy(path: Path | None = None) -> dict[str, Any]:
    target = path or _CONFIG_PATH
    with target.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def clear_policy_cache() -> None:
    load_policy.cache_clear()


def _score_tier(score: int, cfg: dict[str, Any]) -> str:
    tiers = cfg["score_tiers"]
    if score >= tiers["approve_min"]:
        return "APPROVE"
    if score >= tiers["refer_min"]:
        return "REFER"
    return "DECLINE"


def _worse_of(a: str, b: str) -> str:
    """DECLINE is worse than REFER is worse than APPROVE. Hard rules only
    ever cap an outcome toward DECLINE, never improve it."""
    order = {"APPROVE": 0, "REFER": 1, "DECLINE": 2}
    return a if order[a] >= order[b] else b


def _apply_two_signal(
    outcome: str,
    precedent_signal: PrecedentSignal | None,
    cfg: dict[str, Any],
    rules_fired: list[str],
    *,
    fraud_severity: str = "NONE",
) -> tuple[str, str | None]:
    ts = cfg["two_signal"]
    if precedent_signal is None:
        rules_fired.append("two_signal: no precedent_signal provided, skipped")
        return outcome, None
    if precedent_signal.sample_size < ts["min_sample_size"]:
        rules_fired.append(
            f"two_signal: precedent sample_size={precedent_signal.sample_size} "
            f"< min_sample_size={ts['min_sample_size']}, skipped"
        )
        return outcome, None

    approve_ceiling = ts["max_acceptable_default_rate_for_approve"]
    if outcome == "APPROVE" and precedent_signal.ci_lower > approve_ceiling:
        rules_fired.append(
            "two_signal: TWO_SIGNAL_DOWNGRADE: APPROVE downgraded to REFER -- "
            f"peer default-rate CI lower bound {precedent_signal.ci_lower:.3f} "
            f"exceeds max_acceptable_default_rate_for_approve={approve_ceiling}"
        )
        return "REFER", "REFER"
    decline_floor = ts["min_acceptable_default_rate_for_decline"]
    if outcome == "DECLINE" and precedent_signal.ci_upper < decline_floor:
        if fraud_severity == "HIGH":
            rules_fired.append(
                f"two_signal: peer default-rate CI upper bound {precedent_signal.ci_upper:.3f} "
                f"is below min_acceptable_default_rate_for_decline={decline_floor}, "
                "but outcome is hard DECLINE due to HIGH fraud finding, which stands"
            )
            return outcome, None
        rules_fired.append(
            "two_signal: TWO_SIGNAL_UPGRADE: DECLINE upgraded to REFER -- "
            f"peer default-rate CI upper bound {precedent_signal.ci_upper:.3f} "
            f"is below min_acceptable_default_rate_for_decline={decline_floor}"
        )
        return "REFER", "REFER"
    rules_fired.append("two_signal: precedent signal agrees with the scorecard outcome")
    return outcome, None


def _limit_sizing(
    *,
    outcome: str,
    requested_line_inr: float,
    verified_monthly_income_inr: float | None,
    cfg: dict[str, Any],
    rules_fired: list[str],
) -> float:
    ls = cfg["limit_sizing"]
    if outcome == "DECLINE":
        rules_fired.append("limit_sizing: outcome=DECLINE, eligible_line_inr=0")
        return 0.0

    if verified_monthly_income_inr is None:
        floor = ls["no_income_signal_floor_inr"] if outcome == "REFER" else 0.0
        rules_fired.append(
            f"limit_sizing: verified_monthly_income_inr is None, using fixed floor={floor}"
        )
        return float(floor)

    multiplier = ls["multiplier_by_outcome"][outcome]
    raw_limit = min(
        requested_line_inr, multiplier * verified_monthly_income_inr, ls["absolute_cap_inr"]
    )
    rules_fired.append(
        f"limit_sizing: raw_limit = min(requested={requested_line_inr}, "
        f"{multiplier}*income={multiplier * verified_monthly_income_inr:.2f}, "
        f"cap={ls['absolute_cap_inr']}) = {raw_limit:.2f}"
    )
    if outcome == "REFER":
        starter = raw_limit * ls["starter_tier_fraction_for_refer"]
        rules_fired.append(
            f"limit_sizing: REFER starter-tier fraction "
            f"{ls['starter_tier_fraction_for_refer']} applied -> {starter:.2f}"
        )
        return round(starter, 2)
    return round(raw_limit, 2)


def _principal_reason_codes(
    hard_codes: list[str], score_breakdown: ScoreBreakdown, cfg: dict[str, Any]
) -> list[str]:
    """Up to `principal_reasons_max` codes: hard-rule codes first (they are
    the actual deciding factors when present), then the scorecard factors
    with the largest shortfall vs. their own best bin (FCRA/ECOA-style "key
    factors"), skipping duplicates and factors that already earned their
    max_up (no shortfall)."""
    max_reasons = cfg["principal_reasons_max"]
    codes: list[str] = list(dict.fromkeys(hard_codes))  # dedupe, preserve order

    shortfalls = sorted(
        (f for f in score_breakdown.factors if f.value is not None and f.points < f.max_up),
        key=lambda f: f.max_up - f.points,
        reverse=True,
    )
    for f in shortfalls:
        if len(codes) >= max_reasons:
            break
        if f.reason_code not in codes:
            codes.append(f.reason_code)
    return codes[:max_reasons]


def decide(
    *,
    score_breakdown: ScoreBreakdown,
    fraud_severity: str,
    identity_check_status: str,
    suspected_instruction_text: bool,
    requested_line_inr: float,
    verified_monthly_income_inr: float | None,
    min_extraction_confidence: float | None = None,
    precedent_signal: PrecedentSignal | None = None,
    policy: dict[str, Any] | None = None,
) -> Decision:
    cfg = policy or load_policy()
    rules_fired: list[str] = []
    hard_codes: list[str] = []

    score_tier_outcome = _score_tier(score_breakdown.total, cfg)
    rules_fired.append(f"score_tier: score={score_breakdown.total} -> {score_tier_outcome}")
    outcome = score_tier_outcome

    if fraud_severity == "HIGH":
        outcome = cfg["fraud_gate"]["high_severity_outcome"]
        hard_codes.append(RC_FRAUD_OR_INJECTION)
        rules_fired.append("fraud_gate: severity=HIGH -> hard DECLINE (overrides score tier)")
    elif fraud_severity == "MEDIUM":
        capped = _worse_of(outcome, cfg["fraud_gate"]["medium_severity_cap"])
        if capped != outcome:
            rules_fired.append(
                f"fraud_gate: severity=MEDIUM caps outcome at "
                f"{cfg['fraud_gate']['medium_severity_cap']} (was {outcome})"
            )
        outcome = capped
        hard_codes.append(RC_FRAUD_OR_INJECTION)
    else:
        rules_fired.append(f"fraud_gate: severity={fraud_severity}, no override")

    if identity_check_status == "FAIL":
        capped = _worse_of(outcome, cfg["identity_gate"]["fail_cap"])
        if capped != outcome:
            rules_fired.append(
                f"identity_gate: FAIL caps outcome at {cfg['identity_gate']['fail_cap']} "
                f"(was {outcome})"
            )
        outcome = capped
        hard_codes.append(RC_IDENTITY_MISMATCH)
    else:
        rules_fired.append(f"identity_gate: status={identity_check_status}, no override")

    if suspected_instruction_text:
        capped = _worse_of(outcome, cfg["injection_gate"]["suspected_cap"])
        if capped != outcome:
            rules_fired.append(
                f"injection_gate: suspected instruction text caps outcome at "
                f"{cfg['injection_gate']['suspected_cap']} (was {outcome})"
            )
        outcome = capped
        hard_codes.append(RC_FRAUD_OR_INJECTION)
    else:
        rules_fired.append("injection_gate: no suspected instruction text")

    completeness_cfg = cfg["completeness_gate"]
    if score_breakdown.data_completeness < completeness_cfg["min_data_completeness"]:
        if outcome == "DECLINE" and fraud_severity == "HIGH":
            # A real HIGH-fraud DECLINE stands -- "never DECLINE for thin data
            # ALONE" means incompleteness itself can't cause a decline, not
            # that it undoes an unrelated, already-justified fraud decline.
            rules_fired.append(
                f"completeness_gate: data_completeness={score_breakdown.data_completeness} "
                f"< min={completeness_cfg['min_data_completeness']}, but outcome is already "
                "DECLINE due to a HIGH fraud finding, which stands"
            )
        elif outcome != "REFER":
            rules_fired.append(
                f"completeness_gate: data_completeness={score_breakdown.data_completeness} "
                f"< min={completeness_cfg['min_data_completeness']}, capped at REFER "
                f"(never DECLINE for thin data alone; was {outcome})"
            )
            outcome = "REFER"
            hard_codes.append(RC_INCOMPLETE)
        else:
            hard_codes.append(RC_INCOMPLETE)
    else:
        rules_fired.append(
            f"completeness_gate: data_completeness={score_breakdown.data_completeness} "
            f">= min={completeness_cfg['min_data_completeness']}, no cap"
        )

    if (
        min_extraction_confidence is not None
        and min_extraction_confidence < completeness_cfg["min_extraction_confidence"]
    ):
        if outcome == "DECLINE" and fraud_severity == "HIGH":
            rules_fired.append(
                f"confidence_gate: min_extraction_confidence={min_extraction_confidence} "
                f"< threshold={completeness_cfg['min_extraction_confidence']}, but outcome is "
                "already DECLINE due to a HIGH fraud finding, which stands"
            )
        elif outcome != "REFER":
            rules_fired.append(
                f"confidence_gate: min_extraction_confidence={min_extraction_confidence} "
                f"< threshold={completeness_cfg['min_extraction_confidence']}, capped at REFER "
                f"(low-confidence extraction is treated the same as missing data; was {outcome})"
            )
            outcome = "REFER"
            hard_codes.append(RC_INCOMPLETE)
        else:
            hard_codes.append(RC_INCOMPLETE)
    else:
        rules_fired.append(
            f"confidence_gate: min_extraction_confidence={min_extraction_confidence}, no cap"
        )

    outcome, precedent_outcome = _apply_two_signal(
        outcome, precedent_signal, cfg, rules_fired, fraud_severity=fraud_severity
    )

    eligible_line = _limit_sizing(
        outcome=outcome,
        requested_line_inr=requested_line_inr,
        verified_monthly_income_inr=verified_monthly_income_inr,
        cfg=cfg,
        rules_fired=rules_fired,
    )

    if (
        verified_monthly_income_inr is not None
        and outcome != "DECLINE"
        and eligible_line < requested_line_inr
    ):
        hard_codes.append(RC_EXCEEDS_CAPACITY)
        rules_fired.append(
            f"capacity_check: eligible_line_inr={eligible_line} < "
            f"requested_line_inr={requested_line_inr}, RC10 added"
        )

    reason_codes = _principal_reason_codes(hard_codes, score_breakdown, cfg)

    return Decision(
        outcome=outcome,
        tier=_TIER_LABEL[outcome],
        eligible_line_inr=eligible_line,
        reason_codes=reason_codes,
        rules_fired=rules_fired,
        score=score_breakdown.total,
        fraud_severity=fraud_severity,
        data_completeness=score_breakdown.data_completeness,
        scorecard_outcome=score_tier_outcome,
        precedent_outcome=precedent_outcome,
        final_outcome=outcome,
        precedent_peer_count=precedent_signal.sample_size if precedent_signal else None,
        precedent_default_rate=precedent_signal.peer_default_rate if precedent_signal else None,
        precedent_wilson_ci=(
            (precedent_signal.ci_lower, precedent_signal.ci_upper) if precedent_signal else None
        ),
    )
