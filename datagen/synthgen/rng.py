"""Deterministic RNG derivation.

Every artifact gets its own numpy Generator seeded from a stable hash of
(base_seed, namespace, key) rather than a shared/advancing global RNG, so that
regenerating a single document (or the whole corpus, in any order) is
byte-for-byte reproducible. This is why `make datagen` can be re-run from a
clean checkout and produce identical output.
"""

from __future__ import annotations

import hashlib

import numpy as np

from synthgen import BASE_SEED


def derive_seed(namespace: str, key: str | int, base_seed: int = BASE_SEED) -> int:
    """Stable 32-bit seed derived from (base_seed, namespace, key).

    Uses SHA-256 rather than Python's salted `hash()` so the result is stable
    across processes and Python versions (PYTHONHASHSEED-independent).
    """
    digest = hashlib.sha256(f"{base_seed}:{namespace}:{key}".encode()).digest()
    return int.from_bytes(digest[:4], "big")


def rng_for(namespace: str, key: str | int, base_seed: int = BASE_SEED) -> np.random.Generator:
    return np.random.default_rng(derive_seed(namespace, key, base_seed))
