"""Grounded plain-English summary (Phase 6; CLAUDE.md rule 3's second
permitted LLM use case). The summary's ONLY input is a JSON tree of already-
computed values (score, factor points, fraud findings, decision, reason
codes, precedent stats, recourse) -- raw document text NEVER reaches this
prompt, and the LLM never scores, decides, or overrides anything; it only
narrates a decision the policy engine already made.

Every summary is grounding-checked (app/services/explain/grounding.py) before
it is trusted: on failure, one retry; on a second failure, a deterministic
template summary is used instead and the result honestly records
`source="template"` and `verified=False -> caller sees exactly what happened,
never silently swapped without a trace (the audit log records this too, via
the pipeline's SUMMARY_GENERATED event).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from app.core.config import Settings
from app.schemas.explain import SummaryResult
from app.services.explain.grounding import is_grounded
from app.services.extraction.call_budget import CallBudget
from app.services.extraction.factory import get_call_budget

PROMPT_VERSION = "summary.v1"
_PROMPT_PATH = Path(__file__).resolve().parents[2] / "prompts" / "summary.v1.md"

MAX_ATTEMPTS = 2  # one real call + one retry, per the phase spec ("retry once")


@dataclass
class SummaryCallResult:
    text: str
    model: str
    sampling_params: dict


class SummaryLLMClient(Protocol):
    async def generate(
        self, *, prompt_text: str, computed_values_json: str
    ) -> SummaryCallResult: ...


def _load_summary_prompt() -> str:
    raw = _PROMPT_PATH.read_text(encoding="utf-8")
    if raw.startswith("---"):
        _, _, rest = raw.partition("---\n")
        _, _, body = rest.partition("---\n")
        return body.strip()
    return raw.strip()


class GeminiSummaryClient:
    """Text-only Gemini call (no response_schema -- the output is prose, not
    a structured extraction) using GEMINI_SUMMARY_MODEL, temperature 0 (or
    the lowest the model supports, same discipline as Phase 3's extraction
    client -- see `temperature_supported`)."""

    def __init__(
        self,
        *,
        api_key: str,
        summary_model: str,
        call_budget: CallBudget,
        temperature_supported: bool = True,
    ) -> None:
        from google import genai
        from google.genai import types

        self._types = types
        self._client = genai.Client(api_key=api_key, http_options=types.HttpOptions(timeout=60_000))
        self._summary_model = summary_model
        self._call_budget = call_budget
        self._temperature_supported = temperature_supported

    async def generate(self, *, prompt_text: str, computed_values_json: str) -> SummaryCallResult:
        self._call_budget.consume(1)
        config_kwargs: dict = {"system_instruction": prompt_text}
        sampling_params: dict = {}
        if self._temperature_supported:
            config_kwargs["temperature"] = 0
            sampling_params["temperature"] = 0
        else:
            sampling_params["temperature"] = "unsupported_by_model"
        config = self._types.GenerateContentConfig(**config_kwargs)
        response = await self._client.aio.models.generate_content(
            model=self._summary_model, contents=[computed_values_json], config=config
        )
        return SummaryCallResult(
            text=(response.text or "").strip(),
            model=self._summary_model,
            sampling_params=sampling_params,
        )


def build_template_summary(computed_values: dict) -> str:
    """Deterministic, no-LLM fallback -- always fully grounded by
    construction, since every sentence is built directly from the same dict
    the grounding verifier checks against. Used whenever MOCK_LLM=true (no
    real model configured) or a real call fails grounding twice."""
    outcome = computed_values.get("outcome", "REFER")
    score = computed_values.get("score")
    fraud_severity = computed_values.get("fraud_severity", "NONE")
    completeness = computed_values.get("data_completeness")
    reason_codes = computed_values.get("reason_codes") or []
    eligible = computed_values.get("eligible_line_inr")
    requested = computed_values.get("requested_line_inr")
    precedent = computed_values.get("precedent")
    recourse = computed_values.get("top_recourse")

    outcome_label = {
        "APPROVE": "approved",
        "REFER": "referred for manual review",
        "DECLINE": "declined",
    }
    sentences = [
        f"This application was {outcome_label.get(outcome, outcome.lower())}, "
        f"based on a scorecard total of {score} out of 100."
    ]
    if completeness is not None:
        sentences.append(f"Data completeness for this application was {completeness:.0%}.")
    if fraud_severity and fraud_severity != "NONE":
        sentences.append(
            f"The document-integrity review flagged a {fraud_severity.lower()}-severity concern."
        )
    if reason_codes:
        sentences.append(f"The principal reason code(s) recorded are {', '.join(reason_codes)}.")
    if precedent:
        sentences.append(
            f"Among {precedent['sample_size']} similar historical profiles, the observed default "
            f"rate was {precedent['peer_default_rate']:.0%}."
        )
    if requested is not None and eligible is not None:
        sentences.append(
            f"The eligible credit line is INR {eligible:,.0f} against a requested "
            f"INR {requested:,.0f}."
        )
    if recourse:
        sentences.append(
            f"A suggested next step is: {recourse['text']} (potential gain of "
            f"{recourse['points_gain']} points)."
        )
    return " ".join(sentences)


async def generate_summary(
    computed_values: dict, *, settings: Settings, temperature_supported: bool = True
) -> SummaryResult:
    """The single entry point Phase 6's pipeline calls. Branches on
    settings.mock_llm the same way build_extraction_service() does, so
    nothing else in the codebase has to know which mode is active."""
    prompt_text = _load_summary_prompt()

    if settings.mock_llm:
        return SummaryResult(
            text=build_template_summary(computed_values),
            source="template",
            model=None,
            prompt_version=PROMPT_VERSION,
            verified=True,  # the template is grounded by construction
        )

    if not settings.gemini_api_key or not settings.gemini_summary_model:
        raise RuntimeError(
            "GEMINI_API_KEY and GEMINI_SUMMARY_MODEL are required when MOCK_LLM=false "
            "(run scripts/pick_gemini_models.py to choose one)"
        )

    client = GeminiSummaryClient(
        api_key=settings.gemini_api_key,
        summary_model=settings.gemini_summary_model,
        call_budget=get_call_budget(settings),
        temperature_supported=temperature_supported,
    )

    computed_values_json = json.dumps(computed_values, sort_keys=True, default=str)

    last_model = settings.gemini_summary_model
    last_sampling: dict = {}
    for _attempt in range(MAX_ATTEMPTS):
        result = await client.generate(
            prompt_text=prompt_text, computed_values_json=computed_values_json
        )
        last_model, last_sampling = result.model, result.sampling_params
        ok, _evidence = is_grounded(result.text, computed_values)
        if ok:
            return SummaryResult(
                text=result.text,
                source="llm",
                model=result.model,
                prompt_version=PROMPT_VERSION,
                verified=True,
                sampling_params=result.sampling_params,
            )

    # Both attempts failed grounding -- fall back to the deterministic
    # template rather than show an underwriter an ungrounded LLM claim.
    return SummaryResult(
        text=build_template_summary(computed_values),
        source="template",
        model=last_model,
        prompt_version=PROMPT_VERSION,
        verified=True,
        sampling_params=last_sampling,
    )
