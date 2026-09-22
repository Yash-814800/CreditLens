#!/usr/bin/env python3
"""Seeds `historical_borrowers` from data/synth/history.parquet (Phase 6,
item 2) -- the peer universe Phase 6's pgvector precedent match (app/services/
vectors/precedents.py) queries against. Every row's `signal_vector` is
produced by the SAME deterministic embedder (app/services/vectors/embedder.py)
a live application's own features are embedded with at decision time, so
cosine similarity between the two is meaningful.

Seeds the FULL dataset (train + val + test splits, all 2000 rows), not just
one split: this table represents the whole available peer population for
k-NN lookup, which is a different concern from Phase 5/8's train/val/test
discipline for TUNING/VALIDATING the scorecard itself (that discipline governs
what data may inform scorecard_v1.yaml's bin edges, not what a live
application is allowed to be compared against once the scorecard is frozen).

Idempotent: deletes every existing synthetic row before re-inserting, so
`make seed` can be re-run safely (e.g. after `make datagen` regenerates
history.parquet with a different seed) without accumulating duplicates.

Unlike the other scripts/ helpers (tier_distribution.py, eval_*.py), this one
needs a live DATABASE_URL pointing at `db:5432`, which only resolves inside
the docker compose network -- so `make seed` runs this INSIDE the backend
container (docker-compose.yml bind-mounts ./scripts read-only there), not via
`uv run --project backend` from the host. The path resolution below mirrors
backend/tests/paths.py's dual-environment trick so the same file works
unmodified in both places:
  - host:      scripts/seed_history.py -> parents[1] = <repo root>, and
               <repo root>/backend exists, so that's added to sys.path.
  - container: /app/scripts/seed_history.py -> parents[1] = /app, and
               /app/backend does NOT exist (the image's own app package
               lives directly at /app/app) -- /app itself is added instead.
`data/` resolves identically either way: <repo root>/data on the host,
/app/data in the container (docker-compose.yml's bind mount), both a direct
child of the same `parents[1]` path.

Run from the repo root:
    docker compose exec -T backend python scripts/seed_history.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
_HOST_BACKEND_DIR = REPO_ROOT / "backend"
BACKEND_DIR = _HOST_BACKEND_DIR if _HOST_BACKEND_DIR.exists() else REPO_ROOT
sys.path.insert(0, str(BACKEND_DIR))

import pandas as pd  # noqa: E402
from sqlalchemy import delete  # noqa: E402

from app.db.models import HistoricalBorrower  # noqa: E402
from app.db.session import async_session_factory  # noqa: E402
from app.services.scoring.features import CANONICAL_FEATURE_NAMES  # noqa: E402
from app.services.vectors.embedder import embed_features  # noqa: E402

HISTORY_PATH = REPO_ROOT / "data" / "synth" / "history.parquet"

# authenticity_score is Phase 4's fraud-report output; the synthetic history
# dataset never simulated fraud (see docs/data_card.md), so it has no column
# for it and it is left out of both `features` and the embedding (the
# embedder's own bounds config has no dimension for it either).
from typing import TYPE_CHECKING  # noqa: E402

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

_HISTORY_FEATURE_NAMES = [n for n in CANONICAL_FEATURE_NAMES if n != "authenticity_score"]


async def _seed_with_session(session: AsyncSession, df: pd.DataFrame) -> int:
    await session.execute(
        delete(HistoricalBorrower).where(HistoricalBorrower.synthetic.is_(True))
    )

    count = 0
    for _, row in df.iterrows():
        features = {
            name: (None if pd.isna(row.get(name)) else float(row[name]))
            for name in _HISTORY_FEATURE_NAMES
        }
        embedding = embed_features(features)
        session.add(
            HistoricalBorrower(
                features=features,
                signal_vector=embedding,
                defaulted=bool(row["defaulted"]),
                synthetic=True,
                cohort=str(row["cohort"]) if pd.notna(row.get("cohort")) else None,
            )
        )
        count += 1
    await session.commit()
    return count


async def seed(df: pd.DataFrame, session: AsyncSession | None = None) -> int:
    if session is not None:
        return await _seed_with_session(session, df)
    async with async_session_factory() as sess:
        return await _seed_with_session(sess, df)


def main() -> None:
    if not HISTORY_PATH.exists():
        raise SystemExit(f"{HISTORY_PATH} not found -- run `make datagen` first")
    df = pd.read_parquet(HISTORY_PATH)
    inserted = asyncio.run(seed(df))
    print(f"seeded {inserted} historical_borrowers rows from {HISTORY_PATH}")


if __name__ == "__main__":
    main()
