"""Extraction orchestration: rasterize -> call LLM (real or mock) -> range/
injection guardrails -> aggregate confidence -> cache. This is the one place
Phase 6's pipeline calls into; everything else in this package is a building
block it composes.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from pydantic import BaseModel

from app.schemas.extraction import EXTRACTION_SCHEMAS, EXTRACTION_SCHEMAS_PERMUTED
from app.services.extraction.cache import ExtractionCache
from app.services.extraction.guardrails import (
    GuardrailFinding,
    compare_extractions_for_self_consistency,
    validate_extraction_ranges,
)
from app.services.extraction.llm_client import ExtractionCallResult, LLMClient
from app.services.extraction.prompt_loader import load_prompt
from app.services.extraction.rasterize import rasterize_to_image_bytes


@dataclass
class ExtractionOutcome:
    doc_type: str
    data: dict
    model: str
    prompt_version: str
    sampling_params: dict
    source: str  # "llm" | "mock" | "cache"
    findings: list[GuardrailFinding] = field(default_factory=list)
    extraction_confidence: float = 0.0
    input_tokens: int | None = None
    output_tokens: int | None = None
    latency_ms: float = 0.0


def _aggregate_confidence(parsed: BaseModel) -> float:
    """Mean confidence across every top-level Extracted* field (the ones with a
    `confidence` attribute) -- see docs/feature_definitions.md for why mean
    (not min): one illegible field on an otherwise-clear document shouldn't
    drag a whole document's confidence to that field's floor, but it does
    lower the average enough for Phase 5's completeness gate to notice."""
    confidences = [
        value.confidence for value in parsed.__dict__.values() if hasattr(value, "confidence")
    ]
    if not confidences:
        return 1.0
    return round(sum(confidences) / len(confidences), 4)


class ExtractionService:
    def __init__(
        self,
        *,
        llm_client: LLMClient,
        cache: ExtractionCache,
        mock_llm: bool,
        model_name: str,
        self_consistency: bool = False,
    ) -> None:
        self._llm_client = llm_client
        self._cache = cache
        self._mock_llm = mock_llm
        self._model_name = model_name
        self._self_consistency = self_consistency

    async def extract_document(
        self,
        *,
        doc_type: str,
        file_bytes: bytes,
        mime: str,
        sha256: str,
        truth_fields: dict | None = None,
    ) -> ExtractionOutcome:
        if doc_type not in EXTRACTION_SCHEMAS:
            raise ValueError(f"no extraction schema for doc_type={doc_type!r}")

        # ---------------------------------------------------------------------
        # Pass 1: Canonical prompt and canonical schema
        # ---------------------------------------------------------------------
        prompt_version, prompt_text = load_prompt(doc_type, permuted=False)
        schema = EXTRACTION_SCHEMAS[doc_type]

        source = "llm"
        cached = (
            None if self._mock_llm else self._cache.get(sha256, prompt_version, self._model_name)
        )
        call_result: ExtractionCallResult | None = None
        image_bytes: bytes | None = None

        if cached is not None:
            parsed = schema.model_validate(cached["data"])
            sampling_params = cached["sampling_params"]
            model = cached["model"]
            source = "cache"
            input_tokens = output_tokens = None
            latency_ms = 0.0
        else:
            if not self._mock_llm:
                image_bytes = rasterize_to_image_bytes(file_bytes, mime)
            call_result = await self._llm_client.extract(
                doc_type=doc_type,
                image_bytes=image_bytes,
                prompt_version=prompt_version,
                prompt_text=prompt_text,
                truth_fields=truth_fields,
                schema=schema,
            )
            parsed = call_result.parsed
            if not isinstance(parsed, schema):
                parsed = schema.model_validate(parsed.model_dump())
            sampling_params = call_result.sampling_params
            model = call_result.model
            source = call_result.source
            input_tokens = call_result.input_tokens
            output_tokens = call_result.output_tokens
            latency_ms = call_result.latency_ms
            if not self._mock_llm:
                self._cache.put(
                    sha256,
                    prompt_version,
                    self._model_name,
                    {
                        "data": parsed.model_dump(),
                        "sampling_params": sampling_params,
                        "model": model,
                    },
                )

        # ---------------------------------------------------------------------
        # Pass 2 (optional): Self-consistency dual extraction with permuted prompt & schema
        # ---------------------------------------------------------------------
        sc_findings: list[GuardrailFinding] = []
        affected_fields: list[str] = []

        if self._self_consistency and doc_type in EXTRACTION_SCHEMAS_PERMUTED:
            permuted_version, permuted_text = load_prompt(doc_type, permuted=True)
            permuted_schema = EXTRACTION_SCHEMAS_PERMUTED[doc_type]

            cached_2 = (
                None
                if self._mock_llm
                else self._cache.get(sha256, permuted_version, self._model_name)
            )
            if cached_2 is not None:
                parsed_2 = permuted_schema.model_validate(cached_2["data"])
            else:
                if image_bytes is None and not self._mock_llm:
                    image_bytes = rasterize_to_image_bytes(file_bytes, mime)
                call_result_2 = await self._llm_client.extract(
                    doc_type=doc_type,
                    image_bytes=image_bytes,
                    prompt_version=permuted_version,
                    prompt_text=permuted_text,
                    truth_fields=truth_fields,
                    schema=permuted_schema,
                )
                parsed_2 = call_result_2.parsed
                if not isinstance(parsed_2, permuted_schema):
                    parsed_2 = permuted_schema.model_validate(parsed_2.model_dump())
                if not self._mock_llm:
                    self._cache.put(
                        sha256,
                        permuted_version,
                        self._model_name,
                        {
                            "data": parsed_2.model_dump(),
                            "sampling_params": call_result_2.sampling_params,
                            "model": call_result_2.model,
                        },
                    )

            parsed_2_canonical = (
                parsed_2.to_canonical()
                if hasattr(parsed_2, "to_canonical")
                else schema.model_validate(parsed_2.model_dump())
            )
            sc_findings, affected_fields = compare_extractions_for_self_consistency(
                doc_type, parsed, parsed_2_canonical
            )

        findings = validate_extraction_ranges(doc_type, parsed)
        if sc_findings:
            findings.extend(sc_findings)
            for f_name in affected_fields:
                if hasattr(parsed, f_name):
                    f_obj = getattr(parsed, f_name)
                    if hasattr(f_obj, "confidence"):
                        f_obj.confidence = min(f_obj.confidence, 0.2)
            # Lowers min_extraction_confidence to feed existing completeness/confidence gate
            confidence = min(_aggregate_confidence(parsed), 0.35)
        else:
            confidence = _aggregate_confidence(parsed)

        return ExtractionOutcome(
            doc_type=doc_type,
            data=parsed.model_dump(),
            model=model,
            prompt_version=prompt_version,
            sampling_params=sampling_params,
            source=source,
            findings=findings,
            extraction_confidence=confidence,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=latency_ms,
        )
