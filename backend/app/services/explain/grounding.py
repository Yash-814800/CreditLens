"""Grounding verifier for Phase 6's LLM summary (CLAUDE.md ★ addition): every
number, currency amount, or percentage the model writes must trace back to a
value that was actually in the computed-values JSON it was given -- otherwise
the summary is rejected and a deterministic template is used instead (see
summary.py). This is what keeps the LLM from ever "deciding" or fabricating a
number CLAUDE.md rule 3 says only the scorecard/policy engine may produce.

Two independent checks:
  1. every numeric-looking token in the text must be within tolerance of some
     numeric leaf value found anywhere in the input (also checked against
     that value x100, so a written percentage like "62%" matches an input
     ratio of 0.62).
  2. the text must not contain any of a fixed list of protected-attribute /
     PII-adjacent terms -- defense in depth: the summary's input JSON never
     actually contains this information (CLAUDE.md rule 7), so this check
     should never fire in practice, but the phase spec explicitly asks for it
     and a future input-shape bug is exactly the kind of regression this
     guards against.
"""

from __future__ import annotations

import math
import re
from typing import Any

# Matches a number optionally preceded by a currency symbol and/or followed by
# a percent sign, e.g. "25,000", "₹25,000", "62%", "0.62". A negative
# lookbehind on a preceding letter/digit keeps this from matching the digits
# inside an alphanumeric code like "RC01" or a persona id like "P01".
_NUMBER_PATTERN = re.compile(r"(?<![A-Za-z0-9])₹?\s?\d[\d,]*(?:\.\d+)?\s?%?")

_RELATIVE_TOLERANCE = 0.02
_ABSOLUTE_TOLERANCE = 1.0

# CLAUDE.md rule 7's protected-attribute list, plus a few PII-adjacent terms.
# The summary's input JSON never contains any of this (see summary.py's
# SummaryInput construction in pipeline.py), so this is a belt-and-braces
# check on the MODEL'S OWN OUTPUT, not a filter on the input.
FORBIDDEN_TERMS = (
    "male",
    "female",
    "gender",
    "religion",
    "hindu",
    "muslim",
    "christian",
    "sikh",
    "caste",
    "married",
    "unmarried",
    "divorced",
    "widow",
    "years old",
    "pincode",
    "aadhaar",
    "pan card",
    "vocation",
)


def _numeric_leaves(value: Any) -> list[float]:
    """Recursively collect every int/float leaf in a nested dict/list -- the
    computed-values JSON is a plain tree of dicts/lists/scalars, no custom
    objects, so this simple walk covers every value the model could see."""
    leaves: list[float] = []
    if isinstance(value, bool):
        return leaves  # bool is a subclass of int in Python; not a "number" here
    if isinstance(value, int | float):
        leaves.append(float(value))
    elif isinstance(value, dict):
        for v in value.values():
            leaves.extend(_numeric_leaves(v))
    elif isinstance(value, list):
        for v in value:
            leaves.extend(_numeric_leaves(v))
    return leaves


def _parse_token(raw: str) -> tuple[float, bool]:
    """Returns (numeric_value, was_percent)."""
    is_percent = raw.rstrip().endswith("%")
    cleaned = raw.replace("₹", "").replace("%", "").replace(",", "").strip()
    return float(cleaned), is_percent


def _matches_any(value: float, is_percent: bool, allowed: list[float]) -> bool:
    for a in allowed:
        if math.isclose(value, a, rel_tol=_RELATIVE_TOLERANCE, abs_tol=_ABSOLUTE_TOLERANCE):
            return True
        if is_percent and math.isclose(
            value, a * 100, rel_tol=_RELATIVE_TOLERANCE, abs_tol=_ABSOLUTE_TOLERANCE
        ):
            return True
        # A ratio in the input (e.g. 0.62) can also be written as a bare
        # decimal in the text ("0.62") without a "%" -- already covered by
        # the first isclose() check above; kept explicit here in a comment
        # rather than a second branch to avoid a redundant no-op comparison.
    return False


def find_ungrounded_numbers(text: str, computed_values: dict) -> list[str]:
    """Returns the raw text of every numeric token that could NOT be matched
    to a value in computed_values -- empty list means fully grounded."""
    allowed = _numeric_leaves(computed_values)
    ungrounded: list[str] = []
    for match in _NUMBER_PATTERN.finditer(text):
        raw = match.group()
        try:
            value, is_percent = _parse_token(raw)
        except ValueError:
            continue
        if not _matches_any(value, is_percent, allowed):
            ungrounded.append(raw)
    return ungrounded


def find_forbidden_terms(text: str) -> list[str]:
    lowered = text.lower()
    return [term for term in FORBIDDEN_TERMS if term in lowered]


def is_grounded(text: str, computed_values: dict) -> tuple[bool, dict]:
    """Returns (ok, evidence) -- evidence always included (even when ok) so
    the pipeline can persist exactly what was checked, per CLAUDE.md's
    no-black-box-decisioning spirit applied to the verifier itself."""
    ungrounded = find_ungrounded_numbers(text, computed_values)
    forbidden = find_forbidden_terms(text)
    ok = not ungrounded and not forbidden
    return ok, {"ungrounded_numbers": ungrounded, "forbidden_terms_found": forbidden}
