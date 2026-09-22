"""Loads backend/app/config/fraud_policy_v1.yaml. Every threshold and penalty
the fraud checks use comes from here, never a hardcoded constant in the check
modules themselves -- see the YAML's own header comment for why (re-tunable,
versioned, and scripts/eval_fraud.py can rewrite the empirical thresholds
without anyone touching Python).
"""

from __future__ import annotations

from functools import cache
from pathlib import Path
from typing import Any

import yaml

_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "fraud_policy_v1.yaml"


@cache
def load_fraud_policy(path: Path | None = None) -> dict[str, Any]:
    target = path or _CONFIG_PATH
    with target.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def policy_version(policy: dict[str, Any]) -> str:
    return policy["version"]


def clear_policy_cache() -> None:
    """Used by scripts/eval_fraud.py after it rewrites the YAML file mid-run,
    and by tests that load a temporary policy file."""
    load_fraud_policy.cache_clear()
