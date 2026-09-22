"""Hand-crafted demo personas P01-P08.

Distinct from the bulk fraud-eval corpus (documents.py generators driven by
identity.py's throwaway Faker identities): each persona here targets specific
*signals* so a later phase's pipeline produces a predictable, demoable
outcome. Phase 5 calibrates the scorecard against these archetypes (its
"persona feature fixtures produce their expected tiers" DONE WHEN check), so
the exact tier a persona lands in is that phase's responsibility -- what this
module guarantees is a clear, well-separated STRONG / MODERATE / WEAK /
INTEGRITY-FLAGGED / COLLISION / MISMATCH / THIN-FILE archetype for each.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class PersonaSpec:
    persona_id: str
    docs: list[str]
    kyc_name: str
    kyc_phone: str
    kyc_pan: str
    kyc_aadhaar: str
    kyc_address: str
    kyc_vocation: str
    requested_line_inr: float
    platform_key: str = "ride"
    gig_active_days_mean: float = 5.5
    gig_earnings_cv: float = 0.15
    gig_tenure_weeks: int = 52
    utility_tenure_months: int = 14
    utility_on_time_ratio: float = 0.9
    bank_avg_daily_spend: float = 220.0
    bank_platform_credit_weekly_mean: float = 5500.0
    bank_opening_balance: float = 6500.0
    document_name_override: str | None = None  # if set, docs show THIS name instead of kyc_name
    account_last4_mismatch: bool = False
    tamper_gig: str | None = None
    tamper_utility: str | None = None
    reuse_utility_bill_of: str | None = None  # persona_id to copy the utility bill IMAGE from
    injection_utility: str | None = None  # "visible" | "low_contrast" | "in_field"
    injection_gig: str | None = None
    rng_key: str | None = None
    prevent_overdraft: bool = False
    bimodal_gig: bool = False
    cashflow_profile: str = "standard"
    expected_outcome: str = "APPROVE"
    expected_notes: str = ""


PERSONAS: list[PersonaSpec] = [
    PersonaSpec(
        persona_id="P01",
        docs=["GIG_PAYOUT", "UTILITY_BILL", "BANK_STATEMENT"],
        kyc_name="Aarav Mehta",
        kyc_phone="9812345601",
        kyc_pan="AAAPM1234A",
        kyc_aadhaar="234567890101",
        kyc_address="14, Whitefield, Bengaluru - 560066",
        kyc_vocation="ride-hailing driver",
        requested_line_inr=25000,
        gig_active_days_mean=6.2,
        gig_earnings_cv=0.12,
        gig_tenure_weeks=60,
        utility_tenure_months=18,
        utility_on_time_ratio=0.97,
        bank_avg_daily_spend=180.0,
        bank_platform_credit_weekly_mean=6800.0,
        bank_opening_balance=9500.0,
        expected_outcome="APPROVE",
        expected_notes="Strong, stable profile across all three documents; clean fraud checks.",
    ),
    PersonaSpec(
        persona_id="P02",
        docs=["GIG_PAYOUT", "UTILITY_BILL", "BANK_STATEMENT"],
        kyc_name="Priya Nair",
        kyc_phone="9812345602",
        kyc_pan="BBBPN2345B",
        kyc_aadhaar="234567890102",
        kyc_address="7B, Kothrud, Pune - 411038",
        kyc_vocation="food delivery partner",
        requested_line_inr=20000,
        platform_key="food",
        gig_active_days_mean=4.3,
        gig_earnings_cv=0.38,
        gig_tenure_weeks=30,
        utility_tenure_months=7,
        utility_on_time_ratio=0.82,
        bank_avg_daily_spend=260.0,
        bank_platform_credit_weekly_mean=4200.0,
        bank_opening_balance=4200.0,
        expected_outcome="REFER",
        expected_notes="Moderate volatility, only 7-month utility tenure -> tiered-limit REFER, not APPROVE/DECLINE.",
    ),
    PersonaSpec(
        persona_id="P03",
        docs=["GIG_PAYOUT", "UTILITY_BILL", "BANK_STATEMENT"],
        kyc_name="Deepak Yadav",
        kyc_phone="9812345603",
        kyc_pan="CCCPY3456C",
        kyc_aadhaar="234567890103",
        kyc_address="Sector 62, Noida - 201309",
        kyc_vocation="auto-rickshaw driver",
        requested_line_inr=30000,
        gig_active_days_mean=2.6,
        gig_earnings_cv=0.7,
        gig_tenure_weeks=9,
        utility_tenure_months=2,
        utility_on_time_ratio=0.42,
        bank_avg_daily_spend=180.0,
        bank_platform_credit_weekly_mean=1800.0,
        bank_opening_balance=650.0,
        expected_outcome="DECLINE",
        expected_notes="High volatility, low balance, 2-month tenure, frequent late payments -> DECLINE + recourse.",
    ),
    PersonaSpec(
        persona_id="P04",
        docs=["GIG_PAYOUT", "UTILITY_BILL", "BANK_STATEMENT"],
        kyc_name="Sanjay Kulkarni",
        kyc_phone="9812345604",
        kyc_pan="DDDPK4567D",
        kyc_aadhaar="234567890104",
        kyc_address="Velachery, Chennai - 600042",
        kyc_vocation="ride-hailing driver",
        requested_line_inr=22000,
        gig_active_days_mean=5.8,
        gig_earnings_cv=0.16,
        gig_tenure_weeks=48,
        utility_tenure_months=15,
        utility_on_time_ratio=0.93,
        bank_avg_daily_spend=200.0,
        bank_platform_credit_weekly_mean=6000.0,
        bank_opening_balance=7000.0,
        tamper_gig="amount_edit",
        expected_outcome="REFER_OR_DECLINE",
        expected_notes="Otherwise strong profile, but the gig-payout screenshot has an edited amount plus simulated "
        "editor metadata -> document-integrity fraud finding caps the outcome regardless of score.",
    ),
    PersonaSpec(
        persona_id="P05",
        docs=["GIG_PAYOUT", "UTILITY_BILL", "BANK_STATEMENT"],
        kyc_name="Farhan Sheikh",
        kyc_phone="9812345605",
        kyc_pan="EEEPS5678E",
        kyc_aadhaar="234567890105",
        kyc_address="Banjara Hills, Hyderabad - 500034",
        kyc_vocation="food delivery partner",
        requested_line_inr=18000,
        platform_key="food",
        gig_active_days_mean=5.1,
        gig_earnings_cv=0.2,
        gig_tenure_weeks=44,
        utility_tenure_months=13,
        utility_on_time_ratio=0.9,
        bank_avg_daily_spend=210.0,
        bank_platform_credit_weekly_mean=4800.0,
        bank_opening_balance=5200.0,
        expected_outcome="APPROVE",
        expected_notes="Clean applicant. Its utility bill image is the ORIGINAL that P06 later re-submits under a "
        "different identity -- this is the syndicate pHash-collision demo.",
    ),
    PersonaSpec(
        persona_id="P06",
        docs=["GIG_PAYOUT", "UTILITY_BILL", "BANK_STATEMENT"],
        kyc_name="Vikram Chauhan",
        kyc_phone="9812345606",
        kyc_pan="FFFPC6789F",
        kyc_aadhaar="234567890106",
        kyc_address="Salt Lake, Kolkata - 700091",
        kyc_vocation="ride-hailing driver",
        requested_line_inr=20000,
        gig_active_days_mean=5.4,
        gig_earnings_cv=0.18,
        gig_tenure_weeks=50,
        bank_avg_daily_spend=190.0,
        bank_platform_credit_weekly_mean=5200.0,
        bank_opening_balance=6000.0,
        reuse_utility_bill_of="P05",
        expected_outcome="DECLINE",
        expected_notes="Submits a resized/re-encoded COPY of P05's utility bill under a different identity. The bill "
        "still reads P05's consumer name/number -> pHash near-duplicate corroborated by mismatched identity -> HIGH "
        "fraud severity -> DECLINE regardless of score. THE syndicate collision demo (submit P05 then P06).",
    ),
    PersonaSpec(
        persona_id="P07",
        docs=["GIG_PAYOUT", "UTILITY_BILL", "BANK_STATEMENT"],
        kyc_name="Rohit Verma",
        kyc_phone="9812345607",
        kyc_pan="GGGPV7890G",
        kyc_aadhaar="234567890107",
        kyc_address="Andheri East, Mumbai - 400069",
        kyc_vocation="cab driver",
        requested_line_inr=20000,
        gig_active_days_mean=5.0,
        gig_earnings_cv=0.22,
        gig_tenure_weeks=40,
        utility_tenure_months=12,
        utility_on_time_ratio=0.88,
        bank_avg_daily_spend=200.0,
        bank_platform_credit_weekly_mean=5000.0,
        bank_opening_balance=5500.0,
        document_name_override="Suresh Kumar",  # bill/bank show a different name than the KYC name above
        account_last4_mismatch=True,
        expected_outcome="REFER",
        expected_notes="Bill/bank holder name does not match KYC name, AND the gig payout's declared payout account "
        "last-4 does not match the bank statement's account last-4 -> identity mismatch (RC08) -> REFER.",
    ),
    PersonaSpec(
        persona_id="P08",
        docs=["BANK_STATEMENT"],
        kyc_name="Meena Iyer",
        kyc_phone="9812345608",
        kyc_pan="HHHPI8901H",
        kyc_aadhaar="234567890108",
        kyc_address="Sector 62, Noida - 201309",
        kyc_vocation="grocery delivery partner",
        requested_line_inr=15000,
        bank_avg_daily_spend=190.0,
        bank_platform_credit_weekly_mean=3800.0,
        bank_opening_balance=3000.0,
        expected_outcome="REFER",
        expected_notes="Thin file: only the bank CSV was submitted (no gig payout, no utility bill) -> incomplete "
        "application caps at REFER (RC09), never DECLINE for missing data alone.",
    ),
    PersonaSpec(
        persona_id="P09",
        docs=["GIG_PAYOUT", "UTILITY_BILL", "BANK_STATEMENT"],
        kyc_name="Kavita Sharma",
        kyc_phone="9812345609",
        kyc_pan="IIIKS9012I",
        kyc_aadhaar="234567890109",
        kyc_address="12, 4th Cross, Malleshwaram, Bengaluru - 560003",
        kyc_vocation="food delivery partner",
        requested_line_inr=20000,
        platform_key="food",
        gig_active_days_mean=5.0,
        gig_earnings_cv=0.18,
        gig_tenure_weeks=36,
        utility_tenure_months=10,
        utility_on_time_ratio=0.85,
        bank_avg_daily_spend=210.0,
        bank_platform_credit_weekly_mean=4800.0,
        bank_opening_balance=5000.0,
        injection_utility="visible",
        expected_outcome="REFER",
        expected_notes=(
            "Adversarial prompt injection attempt inside utility bill -> injection gate "
            "caps outcome at REFER (RC07), scorecard factors remain identical to clean twin."
        ),
    ),
    PersonaSpec(
        persona_id="P10",
        docs=["GIG_PAYOUT", "UTILITY_BILL", "BANK_STATEMENT"],
        kyc_name="Vikram Joshi",
        kyc_phone="9812345610",
        kyc_pan="JJJPV0123J",
        kyc_aadhaar="234567890110",
        kyc_address="42, Koramangala 4th Block, Bengaluru - 560034",
        kyc_vocation="cab driver",
        requested_line_inr=25000,
        platform_key="ride",
        gig_active_days_mean=6.0,
        gig_earnings_cv=0.40,
        gig_tenure_weeks=5,
        utility_tenure_months=18,
        utility_on_time_ratio=0.95,
        bank_avg_daily_spend=2000.0,
        bank_platform_credit_weekly_mean=5500.0,
        bank_opening_balance=200.0,
        rng_key="P10_s1",
        prevent_overdraft=True,
        bimodal_gig=True,
        cashflow_profile="blind_spot",
        expected_outcome="REFER",
        expected_notes=(
            "Blind-spot cohort borrower: scorecard alone rates profile as APPROVE (high utility tenure, "
            "strong on-time ratio, good income), but embedding reveals brittle cashflow (short gig "
            "tenure of 5 weeks, volatile earnings CV 0.67, frequent low balances). Precedents show peer "
            "default rate CI lower bound > 0.15 -> TWO_SIGNAL_DOWNGRADE to REFER."
        ),
    ),
    PersonaSpec(
        persona_id="P11",
        docs=["GIG_PAYOUT", "UTILITY_BILL", "BANK_STATEMENT"],
        kyc_name="Ananya Sen",
        kyc_phone="9812345611",
        kyc_pan="KKKPA1234K",
        kyc_aadhaar="234567890111",
        kyc_address="18, Salt Lake Sector 1, Kolkata - 700064",
        kyc_vocation="ride-hailing driver",
        requested_line_inr=15000,
        platform_key="ride",
        gig_active_days_mean=4.2,
        gig_earnings_cv=0.12,
        gig_tenure_weeks=75,
        utility_tenure_months=4,
        utility_on_time_ratio=0.45,
        bank_avg_daily_spend=650.0,
        bank_platform_credit_weekly_mean=2150.0,
        bank_opening_balance=1200.0,
        rng_key="P11_s2",
        prevent_overdraft=True,
        cashflow_profile="resilient",
        expected_outcome="REFER",
        expected_notes=(
            "Resilient thin-file borrower: scorecard alone rates profile as DECLINE (short 4-month utility "
            "history, modest bank balance), but embedding reveals steady career stability (75-week gig tenure, "
            "stable weekly earnings CV 0.12, near-zero low balance days). Precedents show peer default rate "
            "CI upper bound < 0.15 -> TWO_SIGNAL_UPGRADE to REFER."
        ),
    ),
]
