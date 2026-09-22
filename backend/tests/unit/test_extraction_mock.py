import json

import pytest

from app.services.extraction.llm_client import build_extraction_from_truth
from tests.paths import DEMO_PACK

pytestmark = pytest.mark.unit

PERSONAS = sorted(p.name for p in DEMO_PACK.iterdir() if p.is_dir())


def _load_truth(persona: str, doc_glob: str) -> dict | None:
    matches = list((DEMO_PACK / persona).glob(f"{doc_glob}.*.truth.json"))
    if not matches:
        return None
    return json.loads(matches[0].read_text())


class TestMockExtractionOnAllPersonas:
    @pytest.mark.parametrize("persona", PERSONAS)
    def test_gig_payout_extracts_without_error(self, persona):
        truth = _load_truth(persona, "gig_payout")
        if truth is None:
            pytest.skip(f"{persona} has no gig payout document")
        extraction = build_extraction_from_truth("GIG_PAYOUT", truth["visible_fields"])
        assert extraction.platform_name.value == truth["visible_fields"]["platform_name"]
        assert len(extraction.weeks) == len(truth["visible_fields"]["weeks"])

    @pytest.mark.parametrize("persona", PERSONAS)
    def test_utility_bill_extracts_without_error(self, persona):
        truth = _load_truth(persona, "utility_bill")
        if truth is None:
            pytest.skip(f"{persona} has no utility bill document")
        extraction = build_extraction_from_truth("UTILITY_BILL", truth["visible_fields"])
        assert extraction.consumer_name.value == truth["visible_fields"]["consumer_name"]
        assert len(extraction.payment_history) == len(truth["visible_fields"]["payment_history"])

    def test_p08_has_no_gig_or_utility_documents(self):
        # P08 is the thin-file persona: bank statement only.
        assert _load_truth("P08", "gig_payout") is None
        assert _load_truth("P08", "utility_bill") is None

    def test_p06_bill_visibly_carries_p05_identity(self):
        """The pHash-collision demo (Phase 4) depends on this at the data
        layer: P06's utility bill document must extract P05's consumer
        identity, not P06's own KYC name -- otherwise there is nothing for the
        fraud layer's cross-field-consistency + corroboration check to find."""
        p05_truth = _load_truth("P05", "utility_bill")
        p06_truth = _load_truth("P06", "utility_bill")
        p06_kyc = json.loads((DEMO_PACK / "P06" / "kyc.json").read_text())

        p06_extraction = build_extraction_from_truth("UTILITY_BILL", p06_truth["visible_fields"])
        assert p06_extraction.consumer_name.value == p05_truth["visible_fields"]["consumer_name"]
        assert p06_extraction.consumer_name.value != p06_kyc["full_name"]


class TestMissingFieldsBecomeIllegible:
    def test_missing_field_maps_to_null_and_illegible(self):
        truth = {
            "platform_name": "ZipRide Partner",
            "partner_name": None,
            "partner_id": "ZIP-1",
            "partner_since": "2025-01-01",
            "report_period_start": "2025-12-01",
            "report_period_end": "2026-01-01",
            "weeks": [],
            "total_net_payout_period": 1000.0,
            "payout_account_last4": "1234",
        }
        extraction = build_extraction_from_truth("GIG_PAYOUT", truth)
        assert extraction.partner_name.value is None
        assert extraction.partner_name.legible is False
        assert extraction.platform_name.legible is True
