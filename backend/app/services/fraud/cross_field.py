"""Cross-field consistency checks (CLAUDE.md Phase 4 check #5): does the same
person's identity and story line up across the KYC record and the three
independently-submitted documents? Each function is a pure comparison over
already-extracted values -- no I/O, no LLM. rapidfuzz absorbs harmless
surface differences (initials, word order, punctuation) that would otherwise
make an honest applicant's own paperwork look like a mismatch.
"""

from __future__ import annotations

from rapidfuzz import fuzz

from app.schemas.fraud import Finding


def name_similarity_finding(
    *, label: str, name_a: str | None, name_b: str | None, policy: dict
) -> Finding | None:
    """Compares two holder-name strings (e.g. KYC name vs. a document's own
    extracted holder name) with rapidfuzz token_sort_ratio, which ignores word
    order (`"Kumar Suresh"` vs `"Suresh Kumar"`) and is tolerant of minor
    spelling/OCR noise -- CLAUDE.md's example band widths (>=85 pass,
    70-84 warn, <70 fail)."""
    if not name_a or not name_b:
        return None
    score = fuzz.token_sort_ratio(name_a, name_b)
    thresholds = policy["cross_field"]["name_similarity"]
    penalties = policy["penalties"]
    if score >= thresholds["pass_min"]:
        return None
    if score >= thresholds["warn_min"]:
        return Finding(
            check_name="cross_field_name",
            severity="LOW",
            penalty_points=penalties["cross_field_name_warn"],
            message=f"{label}: name similarity is borderline ({score:.0f}/100); worth a look.",
            evidence={"label": label, "name_a": name_a, "name_b": name_b, "score": score},
        )
    return Finding(
        check_name="cross_field_name",
        severity="MEDIUM",
        penalty_points=penalties["cross_field_name_fail"],
        message=f"{label}: names do not match closely enough ({score:.0f}/100).",
        evidence={"label": label, "name_a": name_a, "name_b": name_b, "score": score},
    )


def address_similarity_finding(
    *, declared_address: str | None, document_address: str | None, policy: dict
) -> Finding | None:
    if not declared_address or not document_address:
        return None
    score = fuzz.token_set_ratio(declared_address, document_address)
    pass_min = policy["cross_field"]["address_similarity"]["pass_min"]
    if score >= pass_min:
        return None
    return Finding(
        check_name="cross_field_address",
        severity="LOW",
        penalty_points=policy["penalties"]["cross_field_address_fail"],
        message=(
            f"Declared address does not closely match the document's service "
            f"address ({score:.0f}/100)."
        ),
        evidence={
            "declared_address": declared_address,
            "document_address": document_address,
            "score": score,
        },
    )


def vocation_platform_finding(
    *, stated_vocation: str | None, platform_names: list[str], policy: dict
) -> Finding | None:
    """`stated_vocation` (free text at intake) is compared against the
    platform name(s) the applicant's OWN gig-payout document(s) actually show.
    Never used to score -- CLAUDE.md rule 7 keeps stated_vocation itself out of
    scoring entirely; this only checks internal consistency of the story."""
    if not stated_vocation or not platform_names:
        return None
    vocation_map: dict[str, list[str]] = policy["cross_field"]["vocation_platform_map"]
    expected_platforms = vocation_map.get(stated_vocation.strip().lower())
    if expected_platforms is None:
        return None  # an unmapped free-text vocation is not itself a finding
    if any(p in expected_platforms for p in platform_names):
        return None
    return Finding(
        check_name="cross_field_vocation",
        severity="LOW",
        penalty_points=policy["penalties"]["cross_field_vocation_mismatch"],
        message=(
            f"Stated vocation {stated_vocation!r} does not match the gig-payout "
            f"document's platform ({', '.join(platform_names)})."
        ),
        evidence={"stated_vocation": stated_vocation, "platform_names": platform_names},
    )


def payout_account_mismatch_finding(
    *, payout_account_last4: str | None, bank_account_last4: str | None, policy: dict
) -> Finding | None:
    """The gig platform's declared payout account (last 4 digits) should be
    the same account the bank statement is for -- CLAUDE.md's ★ addition.
    A mismatch means either the applicant isn't the account holder receiving
    their own gig income, or the two documents belong to different people."""
    if not payout_account_last4 or not bank_account_last4:
        return None
    if payout_account_last4 == bank_account_last4:
        return None
    return Finding(
        check_name="cross_field_payout_account",
        severity="MEDIUM",
        penalty_points=policy["penalties"]["cross_field_payout_account_mismatch"],
        message=(
            f"Gig-payout account (...{payout_account_last4}) does not match the "
            f"bank statement account (...{bank_account_last4})."
        ),
        evidence={
            "payout_account_last4": payout_account_last4,
            "bank_account_last4": bank_account_last4,
        },
    )


def income_reconciliation_finding(
    *, income_reconciliation_ratio: float | None, policy: dict
) -> Finding | None:
    """A very low ratio of bank-verified platform credits to the payout
    report's own declared total is a fraud/consistency signal in its own
    right (not just a scoring input) -- CLAUDE.md's ★ cross-document income
    reconciliation. The scorecard (Phase 5) also uses this feature directly;
    this finding is the fraud layer's independent flag on the same number."""
    if income_reconciliation_ratio is None:
        return None
    threshold = policy["income_reconciliation"]["low_ratio_threshold"]
    if income_reconciliation_ratio >= threshold:
        return None
    return Finding(
        check_name="income_reconciliation",
        severity="LOW",
        penalty_points=policy["penalties"]["income_reconciliation_low"],
        message=(
            f"Only {income_reconciliation_ratio:.0%} of the declared gig payouts are "
            "traceable to bank credits over the same period."
        ),
        evidence={
            "income_reconciliation_ratio": income_reconciliation_ratio,
            "threshold": threshold,
        },
    )
