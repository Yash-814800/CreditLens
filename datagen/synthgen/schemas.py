"""Pydantic schemas for every sidecar `<name>.truth.json`.

`visible_fields` is exactly what is rendered onto the artifact (i.e. what a
perfect OCR / vision model would read back) -- this is what MOCK_LLM reads in
later phases instead of calling a real vision model. `original_fields` is the
pre-tamper ground truth, identical to `visible_fields` for clean documents.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

DocType = Literal["GIG_PAYOUT", "UTILITY_BILL", "BANK_STATEMENT"]
Split = Literal["train", "dev", "test", "reuse", "demo", "adversarial"]


class TamperEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: str
    field: str
    original: Any
    tampered: Any
    bbox: list[int] | None = None  # [x0, y0, x1, y1] in pixel space, when applicable


class PersonaMeta(BaseModel):
    """Identity metadata for the (fictional) applicant behind one document.

    NOT the same thing as the hand-crafted demo personas P01-P08 -- this is a
    per-document synthetic identity used for the bulk fraud-eval corpus.
    """

    model_config = ConfigDict(extra="forbid")

    persona_id: str
    full_name: str
    phone: str
    declared_address: str
    stated_vocation: str


class TruthSidecar(BaseModel):
    model_config = ConfigDict(extra="forbid")

    doc_type: DocType
    doc_id: str
    split: Split
    clean: bool
    visible_fields: dict[str, Any]
    original_fields: dict[str, Any]
    tamper_manifest: list[TamperEvent] = []
    persona: PersonaMeta
    reuse_of: str | None = None  # doc_id of the source document, for reuse variants
    reuse_variant_type: str | None = None
    hard_negative_group: str | None = None  # shared-template-group id, utility bills only
    metadata_stamp: str | None = None  # simulated EXIF/PDF Producer tag, when tampered that way
    adversarial: bool = False
    injected_string: str | None = None
    true_fields: dict[str, Any] | None = None
    clean_twin: str | None = None
    injection_type: str | None = None
