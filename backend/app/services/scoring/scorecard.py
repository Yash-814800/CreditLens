"""Transparent additive scorecard (CLAUDE.md rule 3: no black-box decisioning;
rule 6: pure functions, no I/O). Every number `compute_score()` returns traces
back to backend/app/config/scorecard_v1.yaml -- nothing here is a hardcoded
constant or a model's opinion.

`compute_score()` takes a sanitizer-cleaned ScoringInput (see
app/services/guardrails/sanitizer.py) so this module never even has the
*option* of touching a protected attribute -- it only knows the 7 factor
names the YAML config lists.
"""

from __future__ import annotations

from functools import cache
from pathlib import Path
from typing import Any

import yaml

from app.schemas.scoring import ScoreBreakdown, ScoreFactor
from app.services.guardrails.sanitizer import ScoringInput

_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "scorecard_v1.yaml"


@cache
def load_scorecard(path: Path | None = None) -> dict[str, Any]:
    target = path or _CONFIG_PATH
    with target.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def clear_scorecard_cache() -> None:
    """Used by tests that load a temporary/malformed scorecard file."""
    load_scorecard.cache_clear()


def _bin_for_value(value: float, bins: list[dict[str, Any]]) -> dict[str, Any]:
    """First bin (ascending by upper_bound) that `value` is strictly less
    than; `upper_bound: null` means +infinity, so the last bin always
    matches whatever falls through every earlier one."""
    for b in bins:
        if b["upper_bound"] is None or value < b["upper_bound"]:
            return b
    return bins[-1]  # unreachable if the YAML's last bin has upper_bound: null


def score_factor(name: str, value: float | None, config: dict[str, Any]) -> ScoreFactor:
    factor_cfg = config["factors"][name]
    if value is None:
        return ScoreFactor(
            name=name,
            value=None,
            bin_label="Not available (document not submitted)",
            points=0,
            max_up=factor_cfg["max_up"],
            max_down=factor_cfg["max_down"],
            direction=factor_cfg["direction"],
            reason_code=factor_cfg["reason_code_on_penalty"],
        )
    b = _bin_for_value(value, factor_cfg["bins"])
    return ScoreFactor(
        name=name,
        value=value,
        bin_label=b["label"],
        points=b["points"],
        max_up=factor_cfg["max_up"],
        max_down=factor_cfg["max_down"],
        direction=factor_cfg["direction"],
        reason_code=factor_cfg["reason_code_on_penalty"],
    )


def compute_score(
    scoring_input: ScoringInput, config: dict[str, Any] | None = None
) -> ScoreBreakdown:
    cfg = config or load_scorecard()
    factor_names = list(cfg["factors"].keys())
    factors = [score_factor(name, scoring_input.get(name), cfg) for name in factor_names]

    base = cfg["base"]
    total = max(0, min(100, base + sum(f.points for f in factors)))
    present = sum(1 for f in factors if f.value is not None)
    data_completeness = round(present / len(factor_names), 4)

    return ScoreBreakdown(
        version=cfg["version"],
        base=base,
        total=total,
        factors=factors,
        data_completeness=data_completeness,
    )
