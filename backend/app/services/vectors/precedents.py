"""pgvector k-NN precedent matching (Phase 6). Cosine similarity over the
engineered signal embedding (app/services/vectors/embedder.py) against
`historical_borrowers` (seeded by scripts/seed_history.py from the synthetic
history dataset -- see data_card.md). This is the "peer comparison" half of
CLAUDE.md's ★ two-signal decision rule; app/services/scoring/decision.py's
`decide()` already knows how to act on a `PrecedentSignal`, built here for
real for the first time.

No PII of any kind is involved: both sides of the k-NN comparison are pure
numeric feature vectors.
"""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import HistoricalBorrower, PrecedentMatch
from app.schemas.scoring import PrecedentSignal

DEFAULT_K = 35
_Z_95 = 1.959963985  # two-sided 95% z-score, used by the Wilson score interval


@dataclass(frozen=True)
class MatchedPrecedent:
    """One anonymised historical peer (Phase 7's Precedent Panel table row)."""

    historical_id: uuid.UUID
    rank: int
    similarity: float  # cosine similarity, 1.0 = identical direction
    features: dict
    defaulted: bool
    cohort: str | None


@dataclass(frozen=True)
class PrecedentMatchResult:
    matches: list[MatchedPrecedent]
    peer_default_rate: float  # plain (equal-weight) mean over `matches`
    # Similarity-weighted mean default rate -- an additional, informational
    # statistic only. NOT used for the CI or the two-signal policy gate: the
    # standard Wilson score interval assumes equal-weight iid Bernoulli
    # trials, and re-deriving a valid CI for a weighted proportion would need
    # an effective-sample-size correction this project does not implement.
    # Reported honestly as a separate number rather than silently treated as
    # equivalent to the plain rate.
    peer_default_rate_weighted: float
    ci_lower: float
    ci_upper: float
    sample_size: int

    def to_signal(self) -> PrecedentSignal:
        return PrecedentSignal(
            peer_default_rate=self.peer_default_rate,
            ci_lower=self.ci_lower,
            ci_upper=self.ci_upper,
            sample_size=self.sample_size,
        )


def wilson_score_interval(successes: int, n: int, z: float = _Z_95) -> tuple[float, float]:
    """95% Wilson score interval for a binomial proportion -- better-behaved
    than a naive normal-approximation CI at small n or extreme (near 0/1)
    proportions, both of which are realistic here (a k=25 neighbourhood is a
    small sample, and a very strong or very weak peer cohort can have a
    default rate near either extreme)."""
    if n == 0:
        return 0.0, 1.0  # no information at all -> maximally uninformative
    phat = successes / n
    denom = 1 + z**2 / n
    center = phat + z**2 / (2 * n)
    margin = z * math.sqrt(phat * (1 - phat) / n + z**2 / (4 * n**2))
    lower = max(0.0, (center - margin) / denom)
    upper = min(1.0, (center + margin) / denom)
    return lower, upper


async def find_precedents(
    session: AsyncSession, *, embedding: list[float], k: int = DEFAULT_K
) -> PrecedentMatchResult:
    """Cosine k-NN against historical_borrowers.signal_vector via pgvector's
    HNSW index (see db/models.py's `vector_cosine_ops` index). pgvector's
    `<=>` operator (exposed here as `.cosine_distance()`) returns cosine
    DISTANCE (1 - similarity); we convert back to similarity for the
    caller-facing result and the two-signal policy calculation."""
    distance_col = HistoricalBorrower.signal_vector.cosine_distance(embedding).label("distance")
    stmt = (
        select(HistoricalBorrower, distance_col)
        .where(HistoricalBorrower.signal_vector.is_not(None))
        .order_by(distance_col)
        .limit(k)
    )
    rows = (await session.execute(stmt)).all()

    matches: list[MatchedPrecedent] = []
    for rank, (borrower, distance) in enumerate(rows, start=1):
        similarity = max(0.0, 1.0 - float(distance))
        matches.append(
            MatchedPrecedent(
                historical_id=borrower.id,
                rank=rank,
                similarity=round(similarity, 5),
                features=borrower.features,
                defaulted=borrower.defaulted,
                cohort=borrower.cohort,
            )
        )

    n = len(matches)
    if n == 0:
        return PrecedentMatchResult(
            matches=[],
            peer_default_rate=0.0,
            peer_default_rate_weighted=0.0,
            ci_lower=0.0,
            ci_upper=1.0,
            sample_size=0,
        )

    defaults = sum(1 for m in matches if m.defaulted)
    plain_rate = defaults / n
    weight_sum = sum(m.similarity for m in matches)
    weighted_rate = (
        sum(m.similarity for m in matches if m.defaulted) / weight_sum
        if weight_sum > 0
        else plain_rate
    )
    ci_lower, ci_upper = wilson_score_interval(defaults, n)

    return PrecedentMatchResult(
        matches=matches,
        peer_default_rate=round(plain_rate, 4),
        peer_default_rate_weighted=round(weighted_rate, 4),
        ci_lower=round(ci_lower, 4),
        ci_upper=round(ci_upper, 4),
        sample_size=n,
    )


async def persist_precedent_matches(
    session: AsyncSession, *, application_id: uuid.UUID, result: PrecedentMatchResult
) -> None:
    """Replace any prior rows for this application (pipeline re-runs must be
    idempotent -- CLAUDE.md Phase 6 requirement -- not accumulate duplicates)."""
    await session.execute(
        PrecedentMatch.__table__.delete().where(PrecedentMatch.application_id == application_id)
    )
    for m in result.matches:
        session.add(
            PrecedentMatch(
                application_id=application_id,
                historical_id=m.historical_id,
                similarity=m.similarity,
                rank=m.rank,
            )
        )
