"""LLMClient protocol + two implementations: GeminiClient (real vision +
structured-output extraction, via Google's google-genai SDK) and MockLLMClient
(reads a synthetic document's own truth.json sidecar -- dev/test only, forbidden
in production by Phase 1's config guard on MOCK_LLM).

CLAUDE.md rule 3: an LLM is used ONLY for document field extraction into this
strict schema (and, in Phase 6, a grounded summary) -- it never scores, decides,
or overrides anything. Every field below flows into app/services/scoring/features.py
as a plain validated number; nothing free-text ever reaches the scorer.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Protocol

from google import genai
from google.genai import types
from pydantic import BaseModel
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.schemas.extraction import (
    EXTRACTION_SCHEMAS,
    GigPayoutExtraction,
    GigPayoutWeek,
    UtilityBillExtraction,
    UtilityLineItem,
    UtilityPaymentHistoryRow,
)
from app.services.extraction.call_budget import CallBudget

REQUEST_TIMEOUT_SECONDS = 60.0


@dataclass
class ExtractionCallResult:
    parsed: BaseModel
    model: str
    prompt_version: str
    sampling_params: dict
    input_tokens: int | None
    output_tokens: int | None
    latency_ms: float
    source: str  # "llm" | "mock"


class LLMClient(Protocol):
    async def extract(
        self,
        *,
        doc_type: str,
        image_bytes: bytes | None,
        prompt_version: str,
        prompt_text: str,
        truth_fields: dict | None,
        schema: type[BaseModel] | None = None,
    ) -> ExtractionCallResult: ...


class GeminiClient:
    """Wraps google-genai's structured-output support (`GenerateContentConfig
    .response_schema` + `GenerateContentResponse.parsed`) -- the SDK-recommended
    path for "give me back exactly this Pydantic schema" as of the installed
    `google-genai` package version (see scripts/pick_gemini_models.py, which
    probed this against the live API rather than assuming it)."""

    def __init__(
        self,
        *,
        api_key: str,
        vision_model: str,
        call_budget: CallBudget,
        max_concurrency: int = 4,
        temperature_supported: bool = True,
    ) -> None:
        self._client = genai.Client(
            api_key=api_key,
            http_options=types.HttpOptions(timeout=int(REQUEST_TIMEOUT_SECONDS * 1000)),
        )
        self._vision_model = vision_model
        self._call_budget = call_budget
        self._temperature_supported = temperature_supported
        import asyncio

        self._semaphore = asyncio.Semaphore(max_concurrency)

    @retry(
        retry=retry_if_exception_type(Exception),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        reraise=True,
    )
    async def _call(self, *, prompt_text: str, image_bytes: bytes, schema: type[BaseModel]):
        config_kwargs: dict = dict(
            system_instruction=prompt_text,
            response_mime_type="application/json",
            response_schema=schema,
        )
        sampling_params: dict = {}
        if self._temperature_supported:
            config_kwargs["temperature"] = 0
            sampling_params["temperature"] = 0
        else:
            sampling_params["temperature"] = "unsupported_by_model"
        config = types.GenerateContentConfig(**config_kwargs)
        contents = [
            types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg"),
            "Extract the fields from the attached document image.",
        ]
        response = await self._client.aio.models.generate_content(
            model=self._vision_model, contents=contents, config=config
        )
        return response, sampling_params

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
        if image_bytes is None:
            raise ValueError("GeminiClient.extract requires image_bytes")
        target_schema = schema or EXTRACTION_SCHEMAS[doc_type]

        self._call_budget.consume(1)
        started = time.monotonic()
        async with self._semaphore:
            response, sampling_params = await self._call(
                prompt_text=prompt_text, image_bytes=image_bytes, schema=target_schema
            )
        latency_ms = (time.monotonic() - started) * 1000

        usage = getattr(response, "usage_metadata", None)
        return ExtractionCallResult(
            parsed=response.parsed,
            model=self._vision_model,
            prompt_version=prompt_version,
            sampling_params=sampling_params,
            input_tokens=getattr(usage, "prompt_token_count", None) if usage else None,
            output_tokens=getattr(usage, "candidates_token_count", None) if usage else None,
            latency_ms=latency_ms,
            source="llm",
        )


class MockLLMClient:
    """Dev/test-only stand-in. Builds a "perfect OCR" extraction directly from a
    synthetic document's own truth.json `visible_fields` -- no network call, no
    cost, deterministic. Forbidden in production: see
    Settings.production_guard_errors()."""

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
        if truth_fields is None:
            raise ValueError("MockLLMClient.extract requires truth_fields")
        parsed = build_extraction_from_truth(doc_type, truth_fields, schema=schema)
        return ExtractionCallResult(
            parsed=parsed,
            model="mock",
            prompt_version=prompt_version,
            sampling_params={"temperature": 0, "mode": "mock"},
            input_tokens=0,
            output_tokens=0,
            latency_ms=0.0,
            source="mock",
        )


def _wrap_field(value, field_cls):
    if value is None:
        return field_cls(value=None, confidence=0.0, legible=False)
    return field_cls(value=value, confidence=1.0, legible=True)


def build_extraction_from_truth(
    doc_type: str, visible_fields: dict, schema: type[BaseModel] | None = None
) -> BaseModel:
    from app.schemas.extraction import (
        EXTRACTION_SCHEMAS,
        ExtractedDate,
        ExtractedFloat,
        ExtractedInt,
        ExtractedStr,
    )

    if doc_type == "GIG_PAYOUT":
        canonical = GigPayoutExtraction(
            platform_name=_wrap_field(visible_fields.get("platform_name"), ExtractedStr),
            partner_name=_wrap_field(visible_fields.get("partner_name"), ExtractedStr),
            partner_id=_wrap_field(visible_fields.get("partner_id"), ExtractedStr),
            partner_since=_wrap_field(visible_fields.get("partner_since"), ExtractedDate),
            report_period_start=_wrap_field(
                visible_fields.get("report_period_start"), ExtractedDate
            ),
            report_period_end=_wrap_field(visible_fields.get("report_period_end"), ExtractedDate),
            weeks=[GigPayoutWeek(**w) for w in visible_fields.get("weeks", [])],
            total_net_payout_period=_wrap_field(
                visible_fields.get("total_net_payout_period"), ExtractedFloat
            ),
            payout_account_last4=_wrap_field(
                visible_fields.get("payout_account_last4"), ExtractedStr
            ),
            suspected_instruction_text=bool(
                visible_fields.get("suspected_instruction_text", False)
            ),
        )
    elif doc_type == "UTILITY_BILL":
        canonical = UtilityBillExtraction(
            utility_name=_wrap_field(visible_fields.get("utility_name"), ExtractedStr),
            consumer_name=_wrap_field(visible_fields.get("consumer_name"), ExtractedStr),
            consumer_number=_wrap_field(visible_fields.get("consumer_number"), ExtractedStr),
            service_address=_wrap_field(visible_fields.get("service_address"), ExtractedStr),
            connection_date=_wrap_field(visible_fields.get("connection_date"), ExtractedDate),
            meter_number=_wrap_field(visible_fields.get("meter_number"), ExtractedStr),
            bill_date=_wrap_field(visible_fields.get("bill_date"), ExtractedDate),
            due_date=_wrap_field(visible_fields.get("due_date"), ExtractedDate),
            billing_period_start=_wrap_field(
                visible_fields.get("billing_period_start"), ExtractedDate
            ),
            billing_period_end=_wrap_field(visible_fields.get("billing_period_end"), ExtractedDate),
            units_consumed=_wrap_field(visible_fields.get("units_consumed"), ExtractedInt),
            line_items=[UtilityLineItem(**li) for li in visible_fields.get("line_items", [])],
            total_amount_due=_wrap_field(visible_fields.get("total_amount_due"), ExtractedFloat),
            payment_history=[
                UtilityPaymentHistoryRow(**row) for row in visible_fields.get("payment_history", [])
            ],
            suspected_instruction_text=bool(
                visible_fields.get("suspected_instruction_text", False)
            ),
        )
    else:
        raise ValueError(f"no mock builder for doc_type={doc_type!r}")

    if schema is not None and schema != EXTRACTION_SCHEMAS.get(doc_type):
        return schema.model_validate(canonical.model_dump())
    return canonical
