"""Output contract for Phase 6's grounded summary (app/services/explain/summary.py)."""

from __future__ import annotations

from pydantic import BaseModel


class SummaryResult(BaseModel):
    text: str
    source: str  # "llm" | "template"
    model: str | None
    prompt_version: str
    verified: bool
    sampling_params: dict = {}
