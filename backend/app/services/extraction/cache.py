"""Extraction cache keyed by sha256(document) + prompt_version + model, so
re-running an eval/demo never re-bills Gemini for a document already extracted
with the exact same prompt+model combination. A simple JSON-file cache is
enough for a hackathon-scoped single-node deployment; docs/PROGRESS.md notes
that a real deployment would move this to Postgres/Redis alongside the queue
worker described in Phase 6/9.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.core import paths


def _default_cache_dir() -> Path:
    return paths.data_dir() / ".extraction_cache"


class ExtractionCache:
    def __init__(self, cache_dir: str | Path | None = None) -> None:
        self._dir = Path(cache_dir) if cache_dir is not None else _default_cache_dir()
        self._dir.mkdir(parents=True, exist_ok=True)

    def _path(self, sha256: str, prompt_version: str, model: str) -> Path:
        key = f"{sha256}__{prompt_version}__{model}".replace("/", "_")
        return self._dir / f"{key}.json"

    def get(self, sha256: str, prompt_version: str, model: str) -> dict | None:
        path = self._path(sha256, prompt_version, model)
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def put(self, sha256: str, prompt_version: str, model: str, result: dict) -> None:
        path = self._path(sha256, prompt_version, model)
        path.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
