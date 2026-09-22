#!/usr/bin/env python3
"""Produces backend/app/config/calibration_v1.json (Phase 6, item 4): observed
default rate by score decile on data/synth/history.parquet's VALIDATION split,
scored with the real, frozen Phase 5 scorecard. Phase 7's Precedent Panel
shows this next to a live application's actual peer-cohort default rate (from
app/services/vectors/precedents.py) as an "expected default band for this
score" reference point -- CLAUDE.md rule 4: every number here comes from this
script, never hand-typed.

Same VALIDATION-only discipline as scripts/tier_distribution.py (Phase 5) --
never run against the TEST split, which is reserved for Phase 8's frozen-
scorecard validation report.

Run from the repo root:
    uv run --project backend python scripts/calibrate.py
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = REPO_ROOT / "backend"
sys.path.insert(0, str(BACKEND_DIR))

import pandas as pd  # noqa: E402

from app.services.scoring.scorecard import compute_score, load_scorecard  # noqa: E402

HISTORY_PATH = REPO_ROOT / "data" / "synth" / "history.parquet"
OUTPUT_PATH = BACKEND_DIR / "app" / "config" / "calibration_v1.json"

# Same documented stand-in as tier_distribution.py: the synthetic history
# dataset never simulated fraud, so authenticity_score has no real column --
# a clean/typical value lets the other 6 real factors drive the calibration.
_STUB_AUTHENTICITY_SCORE = 0.95
DECILE_EDGES = list(range(0, 101, 10))  # [0,10,20,...,100] -> 10 bands


def _band_label(lo: int, hi: int) -> str:
    return f"{lo}-{hi}"


def main() -> None:
    if not HISTORY_PATH.exists():
        raise SystemExit(f"{HISTORY_PATH} not found -- run `make datagen` first")

    df = pd.read_parquet(HISTORY_PATH)
    val = df[df["split"] == "val"].copy()
    if val.empty:
        raise SystemExit(f"No 'val' split rows found in {HISTORY_PATH}")

    scorecard_cfg = load_scorecard()
    scores = []
    for _, row in val.iterrows():
        scoring_input = {
            name: (None if pd.isna(row.get(name)) else float(row[name]))
            for name in scorecard_cfg["factors"]
            if name in row.index
        }
        scoring_input.setdefault("authenticity_score", _STUB_AUTHENTICITY_SCORE)
        scores.append(compute_score(scoring_input, scorecard_cfg).total)
    val["score"] = scores

    bands = []
    for lo, hi in zip(DECILE_EDGES[:-1], DECILE_EDGES[1:], strict=True):
        # Last band is inclusive of 100; every other band's upper edge belongs
        # to the NEXT band (score==30 falls in "30-40", not "20-30").
        upper_bound_mask = val["score"] < hi if hi < 100 else val["score"] <= hi
        in_band = val[(val["score"] >= lo) & upper_bound_mask]
        n = len(in_band)
        bands.append(
            {
                "band": _band_label(lo, hi),
                "score_min": lo,
                "score_max": hi,
                "n": n,
                "default_rate": round(float(in_band["defaulted"].mean()), 4) if n > 0 else None,
            }
        )

    output = {
        "version": "v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "source": str(HISTORY_PATH.relative_to(REPO_ROOT)),
        "split": "val",
        "n_total": len(val),
        "scorecard_version": scorecard_cfg["version"],
        "note": (
            "SYNTHETIC data. Default rates below are calibration bands for "
            "this demo's synthetic history dataset only -- not a real-world "
            "predictive-accuracy claim (CLAUDE.md rule 4)."
        ),
        "bands": bands,
    }
    OUTPUT_PATH.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {OUTPUT_PATH}")
    for b in bands:
        rate = f"{b['default_rate']:.1%}" if b["default_rate"] is not None else "n/a"
        print(f"  {b['band']:>7s}  n={b['n']:4d}  default_rate={rate}")


if __name__ == "__main__":
    main()
