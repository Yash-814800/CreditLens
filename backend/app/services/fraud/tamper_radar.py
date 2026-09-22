"""Combines ELA + noise-residual block scores into one radar_score (0-1) plus
flagged bounding boxes and a heatmap overlay, per CLAUDE.md Phase 4 check #2.

Known miss (documented honestly, quantified by scripts/eval_fraud.py, not
guessed): `consistent_edit` and `inserted_fake_credit_with_rebalanced_chain`
(Phase 2's two "hard case" tamper types) intentionally leave the WHOLE
document in one final compression/render generation, so there is no local
compression-generation or noise-floor mismatch for ELA/noise-residual to
find. Those are exactly what the semantic/arithmetic checks
(semantic_checks.py) exist to catch instead -- this module does not claim to
catch them.
"""

from __future__ import annotations

import numpy as np
from PIL import Image

from app.schemas.fraud import DocumentRadar, Finding
from app.services.fraud.imaging import (
    BlockScore,
    block_scores,
    compute_ela_map,
    compute_noise_residual_map,
    ela_applicable,
    generate_heatmap_png,
)

FLAGGED_BLOCK_ZSCORE = 2.0  # a block this many std-devs from the image's own mean is "flagged"


def run_tamper_radar(
    image: Image.Image, *, mime: str, policy: dict
) -> tuple[DocumentRadar, Finding | None, bytes]:
    """Returns (radar summary, a Finding if the score crosses a policy band,
    heatmap PNG bytes)."""
    applicable_checks = ["noise_residual"]
    ela_map = None
    if ela_applicable(mime):
        applicable_checks.append("ela")
        ela_map = compute_ela_map(image)

    noise_map = compute_noise_residual_map(image)
    scores: list[BlockScore] = block_scores(ela_map, noise_map)

    combined_scores = [max(s.ela_zscore, s.noise_zscore) for s in scores]
    # The 97th percentile, not the single highest block: a real document's
    # own text/edge content routinely produces one or two extreme single-block
    # z-score readings against a mostly-blank background even with ZERO
    # tampering (confirmed empirically -- max-of-all-blocks alone flagged
    # untouched documents as HIGH). A percentile is far less sensitive to any
    # one noisy block while still responding to a genuinely-sized tampered
    # region, which spans multiple adjacent blocks. scripts/eval_fraud.py
    # tunes the HIGH/MEDIUM bands this feeds into against real ground truth.
    percentile_score = float(np.percentile(combined_scores, 97)) if combined_scores else 0.0
    # Normalise a z-score of ~6 (an extreme, obviously-different block) to 1.0.
    radar_score = round(max(0.0, min(1.0, percentile_score / 6.0)), 4)

    flagged = [
        s.bbox for s, z in zip(scores, combined_scores, strict=True) if z >= FLAGGED_BLOCK_ZSCORE
    ]
    flagged_regions = [list(box) for box in flagged]

    heatmap_bytes = generate_heatmap_png(image, scores)

    radar_thresholds = policy["tamper_radar"]
    penalties = policy["penalties"]
    finding: Finding | None = None
    if radar_score >= radar_thresholds["high_score"]:
        finding = Finding(
            check_name="tamper_radar",
            severity="HIGH",
            penalty_points=penalties["tamper_radar_high"],
            message=(
                "Pixel forensics (error-level analysis / noise-residual) found a region "
                "whose compression or noise characteristics are markedly different from "
                "the rest of the document, consistent with a localised edit."
            ),
            evidence={
                "radar_score": radar_score,
                "flagged_regions": flagged_regions,
                "applicable_checks": applicable_checks,
            },
        )
    elif radar_score >= radar_thresholds["medium_score"]:
        finding = Finding(
            check_name="tamper_radar",
            severity="MEDIUM",
            penalty_points=penalties["tamper_radar_medium"],
            message=(
                "Pixel forensics found a mild but noticeable local inconsistency; "
                "worth a manual look but not conclusive on its own."
            ),
            evidence={
                "radar_score": radar_score,
                "flagged_regions": flagged_regions,
                "applicable_checks": applicable_checks,
            },
        )

    radar = DocumentRadar(
        doc_type="",  # filled in by the caller, which knows the document's doc_type
        radar_score=radar_score,
        applicable_checks=applicable_checks,
        flagged_regions=flagged_regions,
    )
    return radar, finding, heatmap_bytes
