"""Unit tests for EXTRACTION_SELF_CONSISTENCY feature flag:
dual extraction with permuted prompt/field orderings, disagreement detection on
critical numeric fields, fraud findings, and confidence gate integration.
"""

import io
import uuid
from typing import Any

import pytest
from PIL import Image
from pydantic import BaseModel

from app.schemas.extraction import (
    ExtractedDate,
    ExtractedFloat,
    ExtractedInt,
    ExtractedStr,
    GigPayoutExtraction,
    GigPayoutExtractionPermuted,
    GigPayoutWeek,
    UtilityBillExtraction,
    UtilityBillExtractionPermuted,
    UtilityLineItem,
    UtilityPaymentHistoryRow,
)
from app.services.extraction.cache import ExtractionCache
from app.services.extraction.guardrails import GuardrailFinding, _numbers_disagree
from app.services.extraction.llm_client import ExtractionCallResult
from app.services.extraction.service import ExtractionService
from app.services.fraud.policy import load_fraud_policy
from app.services.fraud.service import _guardrail_to_finding
from app.services.scoring.decision import decide, load_policy
from app.services.scoring.scorecard import compute_score, load_scorecard

pytestmark = pytest.mark.unit


class FakeLLMClient:
    """Mock LLM client that returns configurable responses for pass 1 and pass 2."""

    def __init__(self, responses: list[BaseModel]) -> None:
        self._responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    async def extract(
        self,
        *,
        doc_type: str,
        image_bytes: bytes | None,
        prompt_version: str,
        prompt_text: str,
        truth_fields: dict | None,
        schema: type[BaseModel] | None = None,
    ) -> ExtractionCallResult:
        self.calls.append(
            {
                "doc_type": doc_type,
                "prompt_version": prompt_version,
                "prompt_text": prompt_text,
                "schema": schema,
            }
        )
        if not self._responses:
            raise RuntimeError("FakeLLMClient ran out of mocked responses")
        parsed = self._responses.pop(0)
        return ExtractionCallResult(
            parsed=parsed,
            model="fake-llm",
            prompt_version=prompt_version,
            sampling_params={"temperature": 0},
            input_tokens=100,
            output_tokens=50,
            latency_ms=10.0,
            source="fake",
        )


def _valid_image_bytes() -> bytes:
    buf = io.BytesIO()
    im = Image.new("RGB", (10, 10), color="white")
    im.save(buf, format="PNG")
    return buf.getvalue()


def _make_sample_gig_payout(
    total_net: float = 15000.0,
    week1_net: float = 7500.0,
) -> GigPayoutExtraction:
    return GigPayoutExtraction(
        platform_name=ExtractedStr(value="ZipRide Partner", confidence=1.0, legible=True),
        partner_name=ExtractedStr(value="Ramesh Kumar", confidence=1.0, legible=True),
        partner_id=ExtractedStr(value="ZIP-12345", confidence=1.0, legible=True),
        partner_since=ExtractedDate(value="2023-01-15", confidence=1.0, legible=True),
        report_period_start=ExtractedDate(value="2024-01-01", confidence=1.0, legible=True),
        report_period_end=ExtractedDate(value="2024-01-14", confidence=1.0, legible=True),
        weeks=[
            GigPayoutWeek(
                week_start="2024-01-01",
                week_end="2024-01-07",
                active_days=6,
                trips_or_orders=45,
                gross_earnings=8500.0,
                incentives=500.0,
                deductions=1500.0,
                net_payout=week1_net,
            ),
            GigPayoutWeek(
                week_start="2024-01-08",
                week_end="2024-01-14",
                active_days=6,
                trips_or_orders=42,
                gross_earnings=8500.0,
                incentives=500.0,
                deductions=1500.0,
                net_payout=total_net - week1_net,
            ),
        ],
        total_net_payout_period=ExtractedFloat(value=total_net, confidence=1.0, legible=True),
        payout_account_last4=ExtractedStr(value="4321", confidence=1.0, legible=True),
        suspected_instruction_text=False,
    )


def _make_sample_utility_bill(total_due: float = 1250.0, units: int = 120) -> UtilityBillExtraction:
    return UtilityBillExtraction(
        utility_name=ExtractedStr(value="MahaVitaran Electricity", confidence=1.0, legible=True),
        consumer_name=ExtractedStr(value="Ramesh Kumar", confidence=1.0, legible=True),
        consumer_number=ExtractedStr(value="987654321012", confidence=1.0, legible=True),
        service_address=ExtractedStr(value="Flat 101, Pune", confidence=1.0, legible=True),
        connection_date=ExtractedDate(value="2021-06-01", confidence=1.0, legible=True),
        meter_number=ExtractedStr(value="MTR-9988", confidence=1.0, legible=True),
        bill_date=ExtractedDate(value="2024-02-05", confidence=1.0, legible=True),
        due_date=ExtractedDate(value="2024-02-20", confidence=1.0, legible=True),
        billing_period_start=ExtractedDate(value="2024-01-01", confidence=1.0, legible=True),
        billing_period_end=ExtractedDate(value="2024-01-31", confidence=1.0, legible=True),
        units_consumed=ExtractedInt(value=units, confidence=1.0, legible=True),
        line_items=[UtilityLineItem(label="Energy Charges", amount=total_due)],
        total_amount_due=ExtractedFloat(value=total_due, confidence=1.0, legible=True),
        payment_history=[
            UtilityPaymentHistoryRow(
                month="2024-01",
                amount=1200.0,
                due_date="2024-01-20",
                paid_date="2024-01-18",
                status="On-time",
            )
        ],
        suspected_instruction_text=False,
    )


def test_numbers_disagree_tolerance_logic():
    # Identical values
    assert not _numbers_disagree(100.0, 100.0)
    assert not _numbers_disagree(0.0, 0.0)
    assert not _numbers_disagree(None, None)

    # Within 1% tolerance
    assert not _numbers_disagree(100.0, 100.5)  # 0.5% diff
    assert not _numbers_disagree(100.0, 99.5)

    # Beyond 1% tolerance
    assert _numbers_disagree(100.0, 102.0)  # 2% diff
    assert _numbers_disagree(100.0, 95.0)

    # None vs value
    assert _numbers_disagree(100.0, None)
    assert _numbers_disagree(None, 100.0)


def test_self_consistency_flag_disabled_only_runs_one_pass(tmp_path):
    p1 = _make_sample_gig_payout(15000.0)
    fake_client = FakeLLMClient([p1])
    cache = ExtractionCache(tmp_path)

    service = ExtractionService(
        llm_client=fake_client,
        cache=cache,
        mock_llm=False,
        model_name="test-model",
        self_consistency=False,
    )

    import asyncio

    outcome = asyncio.run(
        service.extract_document(
            doc_type="GIG_PAYOUT",
            file_bytes=_valid_image_bytes(),
            mime="image/png",
            sha256="abc123sha",
        )
    )

    assert len(fake_client.calls) == 1
    assert fake_client.calls[0]["prompt_version"] == "gig_payout_extraction.v2"
    assert not any(f.check_name == "self_consistency_disagreement" for f in outcome.findings)
    assert outcome.extraction_confidence == 1.0


def test_self_consistency_agreement_case_preserves_high_confidence(tmp_path):
    p1 = _make_sample_gig_payout(15000.0)
    p2 = GigPayoutExtractionPermuted.model_validate(_make_sample_gig_payout(15000.0).model_dump())
    fake_client = FakeLLMClient([p1, p2])
    cache = ExtractionCache(tmp_path)

    service = ExtractionService(
        llm_client=fake_client,
        cache=cache,
        mock_llm=False,
        model_name="test-model",
        self_consistency=True,
    )

    import asyncio

    outcome = asyncio.run(
        service.extract_document(
            doc_type="GIG_PAYOUT",
            file_bytes=_valid_image_bytes(),
            mime="image/png",
            sha256="abc123sha",
        )
    )

    assert len(fake_client.calls) == 2
    assert fake_client.calls[0]["prompt_version"] == "gig_payout_extraction.v2"
    assert fake_client.calls[1]["prompt_version"] == "gig_payout_extraction.v2_permuted"
    assert not any(f.check_name == "self_consistency_disagreement" for f in outcome.findings)
    assert outcome.extraction_confidence == 1.0


def test_self_consistency_disagreement_lowers_confidence_and_adds_finding(tmp_path):
    # Pass 1 reads 15000.0, Pass 2 reads 25000.0
    p1 = _make_sample_gig_payout(total_net=15000.0)
    p2 = GigPayoutExtractionPermuted.model_validate(
        _make_sample_gig_payout(total_net=25000.0).model_dump()
    )
    fake_client = FakeLLMClient([p1, p2])
    cache = ExtractionCache(tmp_path)

    service = ExtractionService(
        llm_client=fake_client,
        cache=cache,
        mock_llm=False,
        model_name="test-model",
        self_consistency=True,
    )

    import asyncio

    outcome = asyncio.run(
        service.extract_document(
            doc_type="GIG_PAYOUT",
            file_bytes=_valid_image_bytes(),
            mime="image/png",
            sha256="abc_disagree_sha",
        )
    )

    assert len(fake_client.calls) == 2
    # Verify fraud-layer guardrail finding is emitted
    sc_findings = [f for f in outcome.findings if f.check_name == "self_consistency_disagreement"]
    assert len(sc_findings) >= 1
    finding = sc_findings[0]
    assert finding.severity == "MEDIUM"
    assert finding.evidence["field"] == "total_net_payout_period"
    assert finding.evidence["pass1_value"] == 15000.0
    assert finding.evidence["pass2_value"] == 25000.0

    # Verify extraction confidence is lowered below completeness threshold (0.55)
    assert outcome.extraction_confidence <= 0.35
    assert outcome.data["total_net_payout_period"]["confidence"] <= 0.2


def test_self_consistency_utility_bill_disagreement(tmp_path):
    p1 = _make_sample_utility_bill(total_due=1250.0, units=120)
    p2 = UtilityBillExtractionPermuted.model_validate(
        _make_sample_utility_bill(total_due=1850.0, units=200).model_dump()
    )
    fake_client = FakeLLMClient([p1, p2])
    cache = ExtractionCache(tmp_path)

    service = ExtractionService(
        llm_client=fake_client,
        cache=cache,
        mock_llm=False,
        model_name="test-model",
        self_consistency=True,
    )

    import asyncio

    outcome = asyncio.run(
        service.extract_document(
            doc_type="UTILITY_BILL",
            file_bytes=_valid_image_bytes(),
            mime="image/png",
            sha256="bill_disagree_sha",
        )
    )

    sc_findings = [f for f in outcome.findings if f.check_name == "self_consistency_disagreement"]
    fields_flagged = {f.evidence["field"] for f in sc_findings}
    assert "total_amount_due" in fields_flagged
    assert "units_consumed" in fields_flagged
    assert outcome.extraction_confidence <= 0.35


def test_self_consistency_lowered_confidence_triggers_confidence_gate():
    scorecard_cfg = load_scorecard()
    policy_cfg = load_policy()

    # Normal profile that would APPROVE based on score >= 70
    scoring_input = {
        "utility_tenure_months": 24.0,
        "utility_on_time_ratio": 1.0,
        "weekly_inflow_cv": 0.2,
        "avg_daily_balance_inr": 25000.0,
        "low_balance_day_ratio": 0.05,
        "gig_active_days_per_week": 6.0,
        "gig_weekly_earnings_cv": 0.15,
        "gig_tenure_weeks": 52.0,
        "income_reconciliation_ratio": 1.0,
        "authenticity_score": 1.0,
        "verified_monthly_income_inr": 35000.0,
    }
    bd = compute_score(scoring_input, scorecard_cfg)
    assert bd.total >= 70  # Tier APPROVE

    # Case 1: High confidence (no disagreement) -> APPROVE
    decision_high_conf = decide(
        score_breakdown=bd,
        fraud_severity="NONE",
        identity_check_status="PASS",
        suspected_instruction_text=False,
        requested_line_inr=25000.0,
        verified_monthly_income_inr=35000.0,
        min_extraction_confidence=0.95,
        policy=policy_cfg,
    )
    assert decision_high_conf.outcome == "APPROVE"

    # Case 2: Self-consistency disagreement lowers min_extraction_confidence to 0.35 (< 0.55)
    decision_low_conf = decide(
        score_breakdown=bd,
        fraud_severity="NONE",
        identity_check_status="PASS",
        suspected_instruction_text=False,
        requested_line_inr=25000.0,
        verified_monthly_income_inr=35000.0,
        min_extraction_confidence=0.35,  # lowered by self-consistency
        policy=policy_cfg,
    )
    # Outcome is capped at REFER by the confidence gate
    assert decision_low_conf.outcome == "REFER"
    assert any(
        "confidence_gate" in r and "capped at REFER" in r for r in decision_low_conf.rules_fired
    )
    assert "RC09" in decision_low_conf.reason_codes


def test_self_consistency_guardrail_finding_converts_to_fraud_finding():
    fraud_policy = load_fraud_policy()
    gf = GuardrailFinding(
        check_name="self_consistency_disagreement",
        severity="MEDIUM",
        message="Disagreement on total_net_payout_period: pass 1=15000.0, pass 2=25000.0",
        evidence={
            "field": "total_net_payout_period",
            "pass1_value": 15000.0,
            "pass2_value": 25000.0,
        },
    )
    doc_id = uuid.uuid4()
    finding = _guardrail_to_finding(gf, fraud_policy, doc_id)

    assert finding.check_name == "self_consistency_disagreement"
    assert finding.severity == "MEDIUM"
    assert finding.penalty_points == 15
    assert finding.document_id == doc_id
    assert finding.evidence["field"] == "total_net_payout_period"
    assert finding.evidence["pass1_value"] == 15000.0
    assert finding.evidence["pass2_value"] == 25000.0
