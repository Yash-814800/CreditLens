"""Loads versioned prompt templates from backend/app/prompts/*.v1.md. Keeping
prompts as separate versioned files (not Python string literals) means a new
prompt version ships as a new file, and decision_artifacts/extraction records
can cite an exact prompt_version string that still exists on disk for audit."""

from __future__ import annotations

from functools import cache
from pathlib import Path

_PROMPTS_DIR = Path(__file__).resolve().parents[2] / "prompts"

PROMPT_FILES: dict[str, str] = {
    "GIG_PAYOUT": "gig_payout_extraction.v2.md",
    "UTILITY_BILL": "utility_bill_extraction.v2.md",
}

PERMUTED_PROMPT_FILES: dict[str, str] = {
    "GIG_PAYOUT": "gig_payout_extraction.v2_permuted.md",
    "UTILITY_BILL": "utility_bill_extraction.v2_permuted.md",
}


@cache
def load_prompt(doc_type: str, permuted: bool = False) -> tuple[str, str]:
    """Returns (prompt_version, prompt_text) with the YAML front-matter header
    stripped from the text handed to the model (the header is metadata for us,
    not part of the instructions). When permuted=True, loads the inverted field-order
    prompt for self-consistency testing."""
    filename = PERMUTED_PROMPT_FILES[doc_type] if permuted else PROMPT_FILES[doc_type]
    raw = (_PROMPTS_DIR / filename).read_text(encoding="utf-8")
    prompt_version = filename.removesuffix(".md")
    if raw.startswith("---"):
        _, _, rest = raw.partition("---\n")
        _, _, body = rest.partition("---\n")
        return prompt_version, body.strip()
    return prompt_version, raw.strip()
