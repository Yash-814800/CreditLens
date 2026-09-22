"""Builds an ExtractionService wired from Settings -- the one place that
decides "mock or real" so nothing else in the codebase has to branch on
settings.mock_llm itself."""

from __future__ import annotations

from app.core.config import Settings
from app.services.extraction.cache import ExtractionCache
from app.services.extraction.call_budget import CallBudget
from app.services.extraction.llm_client import GeminiClient, MockLLMClient
from app.services.extraction.service import ExtractionService

# Module-level so the same budget is shared across every extraction call in one
# process lifetime, per GEMINI_MAX_CALLS_PER_RUN's definition ("per process run").
_call_budget: CallBudget | None = None


def get_call_budget(settings: Settings) -> CallBudget:
    global _call_budget
    if _call_budget is None:
        _call_budget = CallBudget(settings.gemini_max_calls_per_run)
    return _call_budget


def build_extraction_service(
    settings: Settings, *, cache_dir: str | None = None, temperature_supported: bool = True
) -> ExtractionService:
    cache = ExtractionCache(cache_dir) if cache_dir else ExtractionCache()

    if settings.mock_llm:
        return ExtractionService(
            llm_client=MockLLMClient(),
            cache=cache,
            mock_llm=True,
            model_name="mock",
            self_consistency=settings.extraction_self_consistency,
        )

    if not settings.gemini_api_key:
        raise RuntimeError("GEMINI_API_KEY is required when MOCK_LLM=false")
    if not settings.gemini_vision_model:
        raise RuntimeError(
            "GEMINI_VISION_MODEL is required when MOCK_LLM=false "
            "(run scripts/pick_gemini_models.py to choose one)"
        )

    llm_client = GeminiClient(
        api_key=settings.gemini_api_key,
        vision_model=settings.gemini_vision_model,
        call_budget=get_call_budget(settings),
        temperature_supported=temperature_supported,
    )
    return ExtractionService(
        llm_client=llm_client,
        cache=cache,
        mock_llm=False,
        model_name=settings.gemini_vision_model,
        self_consistency=settings.extraction_self_consistency,
    )
