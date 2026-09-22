import pytest

from app.core.config import Settings
from app.services.extraction.factory import build_extraction_service
from app.services.extraction.llm_client import GeminiClient, MockLLMClient

pytestmark = pytest.mark.unit


def _settings(**overrides) -> Settings:
    base = dict(mock_llm=True, gemini_api_key="", gemini_vision_model="")
    base.update(overrides)
    return Settings(**base)


class TestBuildExtractionService:
    def test_mock_mode_uses_mock_client(self, tmp_path):
        service = build_extraction_service(_settings(mock_llm=True), cache_dir=str(tmp_path))
        assert isinstance(service._llm_client, MockLLMClient)
        assert service._mock_llm is True
        assert service._model_name == "mock"

    def test_real_mode_requires_api_key(self, tmp_path):
        with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
            build_extraction_service(
                _settings(mock_llm=False, gemini_api_key="", gemini_vision_model="gemini-x"),
                cache_dir=str(tmp_path),
            )

    def test_real_mode_requires_vision_model(self, tmp_path):
        with pytest.raises(RuntimeError, match="GEMINI_VISION_MODEL"):
            build_extraction_service(
                _settings(mock_llm=False, gemini_api_key="fake-key", gemini_vision_model=""),
                cache_dir=str(tmp_path),
            )

    def test_real_mode_builds_gemini_client(self, tmp_path):
        service = build_extraction_service(
            _settings(mock_llm=False, gemini_api_key="fake-key", gemini_vision_model="gemini-fake"),
            cache_dir=str(tmp_path),
        )
        assert isinstance(service._llm_client, GeminiClient)
        assert service._model_name == "gemini-fake"
