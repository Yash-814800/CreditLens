"""Maps a document's sha256 back to its own synthetic truth.json sidecar, so
Phase 6's pipeline can run MOCK_LLM=true extraction on a document AFTER it has
already been uploaded and stored (only its bytes/sha256 are on hand at that
point -- the pipeline runs as a background task, decoupled from whichever
request originally uploaded the file).

Scope, by design: MOCK_LLM=true only ever supports documents that are actually
part of this repo's synthetic corpus (data/demo_pack/ and data/synth/) -- by
construction, mock mode's whole purpose is deterministic dev/demo runs against
KNOWN synthetic ground truth (CLAUDE.md: "Mocks only in tests and behind
MOCK_LLM=true"), never real end-user documents (those require MOCK_LLM=false
and a real Gemini call). An unrecognised sha256 under MOCK_LLM=true is
therefore a real, clear error, not silently faked -- see pipeline.py's
EXTRACTION_MOCK_UNRECOGNIZED_DOCUMENT handling.
"""

from __future__ import annotations

import json
from functools import cache

from app.core.paths import data_dir as _data_dir


class UnrecognizedMockDocument(RuntimeError):
    """Raised when MOCK_LLM=true is asked to extract a document whose sha256
    doesn't match any known synthetic fixture's own truth.json sidecar."""


@cache
def _build_index() -> dict[str, dict]:
    """One-time scan of data/demo_pack/**/*.truth.json + data/synth/**/*.truth.json,
    keyed by the sha256 of the ARTIFACT the sidecar describes (computed once,
    here, from the sidecar's own sibling file -- never trusted from the
    sidecar's own content). Cached: this only needs to run once per process,
    and both corpora are static within one `make datagen` generation."""
    import hashlib

    index: dict[str, dict] = {}
    data_dir = _data_dir()
    for corpus_dir in (data_dir / "demo_pack", data_dir / "synth"):
        if not corpus_dir.exists():
            continue
        for truth_path in corpus_dir.rglob("*.truth.json"):
            artifact_path = truth_path.with_name(truth_path.name.removesuffix(".truth.json"))
            if not artifact_path.exists():
                continue
            sha256 = hashlib.sha256(artifact_path.read_bytes()).hexdigest()
            index[sha256] = json.loads(truth_path.read_text(encoding="utf-8"))
    return index


def clear_truth_index_cache() -> None:
    """Used by tests, and useful after `make datagen` regenerates the corpus
    with a different seed mid-process (the cache would otherwise go stale)."""
    _build_index.cache_clear()


def lookup_truth_fields(sha256: str) -> dict:
    """Returns the `visible_fields` dict a document's own truth.json sidecar
    carries. Raises UnrecognizedMockDocument if this sha256 isn't part of the
    known synthetic corpus."""
    entry = _build_index().get(sha256)
    if entry is None:
        raise UnrecognizedMockDocument(
            f"MOCK_LLM=true cannot extract sha256={sha256!r}: it does not match any "
            "known synthetic document in data/demo_pack or data/synth. MOCK_LLM only "
            "supports this repo's own synthetic corpus; use MOCK_LLM=false for real "
            "documents."
        )
    return entry["visible_fields"]
