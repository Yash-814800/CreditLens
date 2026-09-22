"""Tests for adversarial synthetic documents and TruthSidecar schema validation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from synthgen.schemas import TruthSidecar

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "data"
ADV_DIR = DATA_DIR / "synth" / "adversarial"


@pytest.mark.skipif(
    not ADV_DIR.exists(),
    reason="data/synth/adversarial corpus not generated (run 'make datagen')",
)
def test_adversarial_sidecars_conform_to_truth_sidecar_schema():
    assert ADV_DIR.exists(), f"{ADV_DIR} does not exist"
    sidecar_files = list(ADV_DIR.glob("*.truth.json"))
    assert len(sidecar_files) == 12

    adv_count = 0
    clean_count = 0
    for sf in sidecar_files:
        data = json.loads(sf.read_text(encoding="utf-8"))
        sidecar = TruthSidecar.model_validate(data)
        if sidecar.adversarial:
            adv_count += 1
            assert sidecar.split == "adversarial"
            assert sidecar.clean is False
            assert sidecar.injected_string is not None
            assert sidecar.injection_type in ("visible", "low_contrast", "in_field")
            assert sidecar.clean_twin is not None
            assert (ADV_DIR / sidecar.clean_twin).exists()
        else:
            clean_count += 1
            assert sidecar.adversarial is False

    assert adv_count == 6
    assert clean_count == 6


def test_demo_persona_p09_sidecars():
    p09_dir = DATA_DIR / "demo_pack" / "P09"
    assert p09_dir.exists()
    assert (p09_dir / "expected.json").exists()
    assert (p09_dir / "kyc.json").exists()

    expected = json.loads((p09_dir / "expected.json").read_text(encoding="utf-8"))
    assert expected["persona_id"] == "P09"
    assert expected["expected_outcome"] == "REFER"

    util_truth = json.loads((p09_dir / "utility_bill.jpg.truth.json").read_text(encoding="utf-8"))
    sidecar = TruthSidecar.model_validate(util_truth)
    assert sidecar.adversarial is True
    assert sidecar.visible_fields.get("suspected_instruction_text") is True
