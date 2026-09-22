import pytest

from app.services.extraction.prompt_loader import load_prompt

pytestmark = pytest.mark.unit


class TestPromptLoader:
    def test_gig_payout_prompt_loads_and_strips_front_matter(self):
        version, text = load_prompt("GIG_PAYOUT")
        assert version == "gig_payout_extraction.v2"
        assert "---" not in text.splitlines()[0]
        assert "UNTRUSTED DOCUMENT" in text
        assert (
            "ignore any instruction" in text.lower()
            or "never follow any instruction" in text.lower()
        )

    def test_utility_bill_prompt_loads(self):
        version, text = load_prompt("UTILITY_BILL")
        assert version == "utility_bill_extraction.v2"
        assert "utility bill" in text.lower()

    def test_unknown_doc_type_raises(self):
        with pytest.raises(KeyError):
            load_prompt("NOT_A_TYPE")
