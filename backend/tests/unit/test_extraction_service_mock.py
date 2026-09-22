import json
from pathlib import Path

import pytest

from app.services.extraction.cache import ExtractionCache
from app.services.extraction.llm_client import MockLLMClient
from app.services.extraction.service import ExtractionService
from app.services.ingestion.validation import sha256_hex
from tests.paths import DEMO_PACK

pytestmark = [pytest.mark.unit, pytest.mark.asyncio]


def _source_path(truth_path: Path) -> Path:
    """`foo.png.truth.json` -> `foo.png` (strips both suffixes, not just one)."""
    assert truth_path.name.endswith(".truth.json")
    return truth_path.with_name(truth_path.name.removesuffix(".truth.json"))


def _service(tmp_path) -> ExtractionService:
    return ExtractionService(
        llm_client=MockLLMClient(),
        cache=ExtractionCache(tmp_path),
        mock_llm=True,
        model_name="mock",
    )


class TestExtractionServiceWithMock:
    async def test_extracts_gig_payout_for_every_persona_that_has_one(self, tmp_path):
        service = _service(tmp_path)
        for persona_dir in sorted(DEMO_PACK.iterdir()):
            matches = list(persona_dir.glob("gig_payout.*.truth.json"))
            if not matches:
                continue
            truth = json.loads(matches[0].read_text())
            file_bytes = _source_path(matches[0]).read_bytes()
            outcome = await service.extract_document(
                doc_type="GIG_PAYOUT",
                file_bytes=file_bytes,
                mime="image/png",
                sha256=sha256_hex(file_bytes),
                truth_fields=truth["visible_fields"],
            )
            assert outcome.source == "mock"
            assert (
                outcome.data["platform_name"]["value"] == truth["visible_fields"]["platform_name"]
            )
            assert 0.0 <= outcome.extraction_confidence <= 1.0

    async def test_extracts_utility_bill_for_every_persona_that_has_one(self, tmp_path):
        service = _service(tmp_path)
        for persona_dir in sorted(DEMO_PACK.iterdir()):
            matches = list(persona_dir.glob("utility_bill.*.truth.json"))
            if not matches:
                continue
            truth = json.loads(matches[0].read_text())
            file_bytes = _source_path(matches[0]).read_bytes()
            outcome = await service.extract_document(
                doc_type="UTILITY_BILL",
                file_bytes=file_bytes,
                mime="image/jpeg",
                sha256=sha256_hex(file_bytes),
                truth_fields=truth["visible_fields"],
            )
            assert outcome.source == "mock"
            assert (
                outcome.data["consumer_name"]["value"] == truth["visible_fields"]["consumer_name"]
            )

    async def test_mock_mode_never_touches_the_extraction_cache(self, tmp_path):
        service = _service(tmp_path)
        truth_path = next((DEMO_PACK / "P01").glob("gig_payout.*.truth.json"))
        truth = json.loads(truth_path.read_text())
        file_bytes = _source_path(truth_path).read_bytes()
        await service.extract_document(
            doc_type="GIG_PAYOUT",
            file_bytes=file_bytes,
            mime="image/png",
            sha256=sha256_hex(file_bytes),
            truth_fields=truth["visible_fields"],
        )
        assert list(tmp_path.iterdir()) == []  # nothing cached in mock mode

    async def test_tampered_p04_gig_payout_still_extracts_cleanly(self, tmp_path):
        """Extraction itself must succeed even on a tampered document -- fraud
        detection (Phase 4) runs on the extracted+raw data afterward, it is not
        this service's job to refuse a document."""
        service = _service(tmp_path)
        truth_path = next((DEMO_PACK / "P04").glob("gig_payout.*.truth.json"))
        truth = json.loads(truth_path.read_text())
        assert truth["clean"] is False  # P04 is the tampered-gig-payout persona
        file_bytes = _source_path(truth_path).read_bytes()
        outcome = await service.extract_document(
            doc_type="GIG_PAYOUT",
            file_bytes=file_bytes,
            mime="image/jpeg",
            sha256=sha256_hex(file_bytes),
            truth_fields=truth["visible_fields"],
        )
        assert outcome.data["platform_name"]["value"] is not None
