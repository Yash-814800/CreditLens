"""Deterministic, documented 10-dim signal embedding (Phase 6). See
backend/app/config/embedding_v1.yaml's header comment for the full design
rationale (fixed bounds, centering, L2-normalisation, why an engineered
numeric embedding rather than a third-party text/image embedding API).

Choosing an engineered embedding over calling an external embedding API is
itself a deliberate CLAUDE.md-aligned decision, not a shortcut:
  - Auditability: every dimension of the resulting vector traces back to one
    named, already-scored feature and one YAML-configured bound -- a reviewer
    can recompute it by hand. An opaque text/image embedding model's vector
    space has no such explanation.
  - Determinism: the same features always produce bit-identical output, so a
    precedent match is fully reproducible; an external embedding API's model
    can be silently retired or updated (see Phase 3/6's own experience with
    Gemini model catalog drift), which would silently reshape the entire
    historical_borrowers vector space underneath already-stored embeddings.
  - No PII leaves the system: an external embedding call would mean sending
    (at minimum) a serialized description of the applicant's financial
    profile to a third party. This module only ever touches the same 11
    already-sanitized canonical features the scorecard itself reads -- no
    name, address, phone, or free text is ever part of its input.

`Embedder` is a Protocol specifically so a future alternative (e.g. a learned
embedding trained on real outcome data once this moves past a synthetic
demo) can be swapped in without touching any caller.
"""

from __future__ import annotations

import math
from functools import cache
from pathlib import Path
from typing import Any, Protocol

import yaml

_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "embedding_v1.yaml"

EMBEDDING_DIM = 10


class Embedder(Protocol):
    def embed(self, features: dict[str, float | None]) -> list[float]: ...


@cache
def load_embedding_config(path: Path | None = None) -> dict[str, Any]:
    target = path or _CONFIG_PATH
    with target.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def clear_embedding_config_cache() -> None:
    load_embedding_config.cache_clear()


def _raw_value(features: dict[str, float | None], feature_name: str) -> float | None:
    """`log_verified_monthly_income_inr` is a derived dimension, not one of the
    11 CANONICAL_FEATURE_NAMES -- everything else is looked up directly."""
    if feature_name == "log_verified_monthly_income_inr":
        income = features.get("verified_monthly_income_inr")
        if income is None or income <= 0:
            return None
        return math.log(income)
    return features.get(feature_name)


class EngineeredFeatureEmbedder:
    """The one Embedder implementation this codebase uses (see module
    docstring for why). Stateless aside from the cached YAML config."""

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self._config = config or load_embedding_config()

    def embed(self, features: dict[str, float | None]) -> list[float]:
        scaled: list[float] = []
        for dim in self._config["dimensions"]:
            value = _raw_value(features, dim["feature"])
            if value is None:
                scaled.append(0.0)  # missing -> neutral center, not an extreme
                continue
            lo, hi = float(dim["min"]), float(dim["max"])
            clipped = max(lo, min(hi, value))
            mid = (lo + hi) / 2.0
            half_range = (hi - lo) / 2.0
            scaled.append((clipped - mid) / half_range)

        norm = math.sqrt(sum(x * x for x in scaled))
        if norm == 0.0:
            return scaled  # an all-missing profile embeds as the zero vector
        return [x / norm for x in scaled]


def embed_features(features: dict[str, float | None]) -> list[float]:
    """Module-level convenience wrapper -- most callers don't need to hold
    onto an Embedder instance."""
    return EngineeredFeatureEmbedder().embed(features)
