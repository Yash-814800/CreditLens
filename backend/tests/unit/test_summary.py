import pytest

from app.core.config import Settings
from app.services.explain import summary as summary_module
from app.services.explain.summary import (
    SummaryCallResult,
    build_template_summary,
    generate_summary,
)

pytestmark = pytest.mark.unit


def _settings(**overrides) -> Settings:
    base = dict(mock_llm=True, gemini_api_key="", gemini_summary_model="")
    base.update(overrides)
    return Settings(**base)


class _FakeGeminiSummaryClient:
    """Stands in for summary.GeminiSummaryClient without any network access."""

    def __init__(self, *, texts: list[str], model: str = "gemini-fake", **_kwargs) -> None:
        self._texts = list(texts)
        self._model = model
        self.calls = 0

    def __call__(self, **_init_kwargs):
        # Used as a drop-in replacement for the GeminiSummaryClient constructor.
        return self

    async def generate(self, *, prompt_text: str, computed_values_json: str) -> SummaryCallResult:
        self.calls += 1
        text = self._texts[min(self.calls - 1, len(self._texts) - 1)]
        return SummaryCallResult(text=text, model=self._model, sampling_params={"temperature": 0})


_COMPUTED_VALUES = {
    "outcome": "APPROVE",
    "score": 82,
    "fraud_severity": "LOW",
    "data_completeness": 1.0,
    "reason_codes": ["RC07"],
    "eligible_line_inr": 25000,
    "requested_line_inr": 25000,
    "precedent": {"sample_size": 25, "peer_default_rate": 0.04},
    "top_recourse": {"text": "Keep balances above 3,500 for 30 days.", "points_gain": 8},
}


class TestBuildTemplateSummary:
    def test_full_computed_values_produce_every_sentence_kind(self):
        text = build_template_summary(_COMPUTED_VALUES)
        assert "approved" in text
        assert "82 out of 100" in text
        assert "Data completeness" in text
        assert "low-severity concern" in text
        assert "RC07" in text
        assert "25 similar historical profiles" in text
        assert "INR 25,000" in text
        assert "suggested next step" in text

    def test_decline_and_refer_labels(self):
        assert "declined" in build_template_summary({**_COMPUTED_VALUES, "outcome": "DECLINE"})
        assert "referred for manual review" in build_template_summary(
            {**_COMPUTED_VALUES, "outcome": "REFER"}
        )

    def test_minimal_values_omit_optional_sentences(self):
        text = build_template_summary({"outcome": "APPROVE", "score": 90})
        assert "Data completeness" not in text
        assert "historical profiles" not in text
        assert "suggested next step" not in text

    def test_none_fraud_severity_is_not_mentioned(self):
        text = build_template_summary({**_COMPUTED_VALUES, "fraud_severity": "NONE"})
        assert "concern" not in text

    def test_unknown_outcome_falls_back_to_lowercased_value(self):
        text = build_template_summary({"outcome": "WEIRD", "score": 50})
        assert "weird" in text


class TestLoadSummaryPrompt:
    def test_strips_yaml_frontmatter(self):
        assert not summary_module._load_summary_prompt().startswith("---")

    def test_falls_back_to_raw_text_when_no_frontmatter(self, tmp_path, monkeypatch):
        prompt_file = tmp_path / "no_frontmatter.md"
        prompt_file.write_text("Just a plain prompt body.\n", encoding="utf-8")
        monkeypatch.setattr(summary_module, "_PROMPT_PATH", prompt_file)
        assert summary_module._load_summary_prompt() == "Just a plain prompt body."


class TestGenerateSummaryMockMode:
    @pytest.mark.asyncio
    async def test_mock_llm_returns_grounded_template(self):
        result = await generate_summary(_COMPUTED_VALUES, settings=_settings(mock_llm=True))
        assert result.source == "template"
        assert result.model is None
        assert result.verified is True
        assert result.prompt_version == summary_module.PROMPT_VERSION


class TestGenerateSummaryRealMode:
    @pytest.mark.asyncio
    async def test_missing_api_key_raises(self):
        with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
            await generate_summary(
                _COMPUTED_VALUES,
                settings=_settings(mock_llm=False, gemini_api_key="", gemini_summary_model="x"),
            )

    @pytest.mark.asyncio
    async def test_missing_summary_model_raises(self):
        with pytest.raises(RuntimeError, match="GEMINI_SUMMARY_MODEL"):
            await generate_summary(
                _COMPUTED_VALUES,
                settings=_settings(mock_llm=False, gemini_api_key="k", gemini_summary_model=""),
            )

    @pytest.mark.asyncio
    async def test_grounded_first_attempt_is_used_as_is(self, monkeypatch):
        # Every number here traces back to a leaf in _COMPUTED_VALUES (score=82,
        # data_completeness=1.0 -> "100%", precedent.sample_size=25,
        # precedent.peer_default_rate=0.04 -> "4%", eligible/requested=25000,
        # top_recourse.points_gain=8) -- deliberately avoids a bare "out of 100",
        # which the real grounding verifier actually rejects (see the
        # ungrounded-fallback test below, which mirrors a real observed Gemini
        # response from docs/PROGRESS.md's Phase 6 live smoke test).
        good_text = (
            "This application was approved. The scorecard score reached 82. "
            "Data completeness was 100%. The principal reason code is RC07. "
            "Among 25 similar historical profiles, the observed default rate was 4%. "
            "The eligible credit line is INR 25,000 against a requested INR 25,000. "
            "A suggested next step could gain 8 points."
        )
        fake = _FakeGeminiSummaryClient(texts=[good_text])
        monkeypatch.setattr(summary_module, "GeminiSummaryClient", fake)

        result = await generate_summary(
            _COMPUTED_VALUES,
            settings=_settings(mock_llm=False, gemini_api_key="k", gemini_summary_model="m"),
        )
        assert result.source == "llm"
        assert result.verified is True
        assert result.model == "gemini-fake"
        assert fake.calls == 1

    @pytest.mark.asyncio
    async def test_ungrounded_both_attempts_falls_back_to_template(self, monkeypatch):
        bad_text = "This application was approved, based on a score of 999999 out of 100."
        fake = _FakeGeminiSummaryClient(texts=[bad_text, bad_text])
        monkeypatch.setattr(summary_module, "GeminiSummaryClient", fake)

        result = await generate_summary(
            _COMPUTED_VALUES,
            settings=_settings(mock_llm=False, gemini_api_key="k", gemini_summary_model="m"),
        )
        assert result.source == "template"
        assert result.verified is True
        assert result.model == "gemini-fake"
        assert fake.calls == summary_module.MAX_ATTEMPTS

    @pytest.mark.asyncio
    async def test_first_attempt_ungrounded_second_grounded_recovers(self, monkeypatch):
        bad_text = "This application was approved, based on a score of 999999 out of 100."
        good_text = (
            "This application was approved. The scorecard score reached 82. "
            "Data completeness was 100%."
        )
        fake = _FakeGeminiSummaryClient(texts=[bad_text, good_text])
        monkeypatch.setattr(summary_module, "GeminiSummaryClient", fake)

        result = await generate_summary(
            _COMPUTED_VALUES,
            settings=_settings(mock_llm=False, gemini_api_key="k", gemini_summary_model="m"),
        )
        assert result.source == "llm"
        assert result.verified is True
        assert fake.calls == 2
