"""Validates every sidecar truth.json actually on disk against TruthSidecar.
Skips (rather than fails) if `make datagen` hasn't been run yet in this
checkout -- this test is a real-artifact check, not a generator unit test.
"""

import json
from pathlib import Path

import pytest

from synthgen.schemas import TruthSidecar

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "data"


def _truth_files() -> list[Path]:
    if not DATA_DIR.exists():
        return []
    return list(DATA_DIR.rglob("*.truth.json"))


def test_every_generated_sidecar_matches_the_schema():
    files = _truth_files()
    if not files:
        pytest.skip("no generated data found -- run `make datagen` first")
    for path in files:
        data = json.loads(path.read_text())
        TruthSidecar.model_validate(data)  # raises on schema mismatch


def test_tampered_docs_have_a_nonempty_tamper_manifest_and_clean_docs_dont():
    files = _truth_files()
    if not files:
        pytest.skip("no generated data found -- run `make datagen` first")
    for path in files:
        data = json.loads(path.read_text())
        sidecar = TruthSidecar.model_validate(data)
        if sidecar.clean:
            assert sidecar.tamper_manifest == [], f"{path} is marked clean but has a tamper_manifest"
        elif sidecar.adversarial:
            assert sidecar.injected_string, f"{path} is marked adversarial but has no injected_string"
        else:
            assert sidecar.tamper_manifest != [], f"{path} is marked tampered but has an empty tamper_manifest"


def test_manifest_csv_counts_match_the_spec():
    manifest = DATA_DIR / "synth" / "manifest.csv"
    if not manifest.exists():
        pytest.skip("no generated corpus found -- run `make datagen` first")
    import csv

    rows = list(csv.DictReader(manifest.open()))
    for doc_type in ("GIG_PAYOUT", "UTILITY_BILL", "BANK_STATEMENT"):
        clean = [r for r in rows if r["doc_type"] == doc_type and r["clean"] == "True" and r["split"] != "reuse"]
        tampered = [r for r in rows if r["doc_type"] == doc_type and r["clean"] == "False"]
        assert len(clean) >= 40, f"{doc_type} has only {len(clean)} clean docs"
        assert len(tampered) >= 40, f"{doc_type} has only {len(tampered)} tampered docs"
