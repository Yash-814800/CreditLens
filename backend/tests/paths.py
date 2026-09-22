"""Locates the repo's top-level data/ directory (Phase 2's synthetic corpus +
demo personas) from either environment tests run in:

- On the host, `backend/` is a subdirectory of the repo root, so `data/` is a
  sibling one level further up from `backend/`.
- Inside the backend container, only `backend/`'s own contents are copied to
  `/app` (see backend/Dockerfile) and docker-compose bind-mounts the repo's
  `data/` directory directly at `/app/data` -- i.e. as a CHILD of the
  container's "backend root", not a sibling.

Both cases are one lookup here instead of duplicated `parents[N]` arithmetic
(and a latent host/container mismatch) in every test file that needs it.
"""

from pathlib import Path

_BACKEND_ROOT = Path(__file__).resolve().parents[1]  # backend/ on host, /app in container

_CONTAINER_CANDIDATE = _BACKEND_ROOT / "data"
_HOST_CANDIDATE = _BACKEND_ROOT.parent / "data"


def _resolve_data_dir() -> Path:
    for candidate in (_CONTAINER_CANDIDATE, _HOST_CANDIDATE):
        if (candidate / "demo_pack").exists():
            return candidate
    return _CONTAINER_CANDIDATE if _CONTAINER_CANDIDATE.exists() else _HOST_CANDIDATE


DATA_DIR = _resolve_data_dir()
DEMO_PACK = DATA_DIR / "demo_pack"
SYNTH_DIR = DATA_DIR / "synth"
