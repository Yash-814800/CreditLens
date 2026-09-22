import pytest

from app.services.extraction.cache import ExtractionCache

pytestmark = pytest.mark.unit


class TestExtractionCache:
    def test_miss_returns_none(self, tmp_path):
        cache = ExtractionCache(tmp_path)
        assert cache.get("abc123", "gig_payout_extraction.v1", "gpt-test") is None

    def test_put_then_get_roundtrip(self, tmp_path):
        cache = ExtractionCache(tmp_path)
        payload = {
            "data": {"foo": "bar"},
            "sampling_params": {"temperature": 0},
            "model": "gpt-test",
        }
        cache.put("abc123", "gig_payout_extraction.v1", "gpt-test", payload)
        assert cache.get("abc123", "gig_payout_extraction.v1", "gpt-test") == payload

    def test_key_is_specific_to_sha_prompt_and_model(self, tmp_path):
        cache = ExtractionCache(tmp_path)
        cache.put(
            "abc123", "v1", "model-a", {"data": {}, "sampling_params": {}, "model": "model-a"}
        )
        assert cache.get("abc123", "v1", "model-b") is None
        assert cache.get("abc123", "v2", "model-a") is None
        assert cache.get("xyz999", "v1", "model-a") is None
