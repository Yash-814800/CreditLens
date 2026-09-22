"""Resolves the repo's top-level `data/` directory from either runtime
environment the backend app itself can run in -- the same dual host/container
trick backend/tests/paths.py uses for tests, factored out here because Phase 6
needs it from application code too (app/services/extraction/truth_lookup.py,
app/api/v1/demo.py), not just tests.

- host (e.g. a script run via `uv run --project backend ...`): this file is
  at backend/app/core/paths.py, so parents[2] = `backend/`, and `data/` is a
  sibling one level further up.
- container: the image's own `app` package lives directly at `/app/app`
  (see backend/Dockerfile), so parents[2] = `/app`, and docker-compose bind-
  mounts the repo's `data/` directly at `/app/data` -- a direct child of the
  same path.
"""

from __future__ import annotations

from pathlib import Path

_BACKEND_ROOT = Path(__file__).resolve().parents[2]
_CONTAINER_CANDIDATE = _BACKEND_ROOT / "data"
_HOST_CANDIDATE = _BACKEND_ROOT.parent / "data"


def data_dir() -> Path:
    # A genuine data directory must at least contain the committed demo_pack
    for candidate in (_CONTAINER_CANDIDATE, _HOST_CANDIDATE):
        if (candidate / "demo_pack").exists():
            return candidate
    if _CONTAINER_CANDIDATE.exists():
        return _CONTAINER_CANDIDATE
    if _HOST_CANDIDATE.exists():
        return _HOST_CANDIDATE
    raise FileNotFoundError(
        f"no data/ directory found at {_CONTAINER_CANDIDATE} or {_HOST_CANDIDATE}"
    )
