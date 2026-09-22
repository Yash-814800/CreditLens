"""Versioned consent document loader and verification helper.

Provides active consent text, version metadata, and cryptographic digest
for client display, server-side enforcement, and tamper-evident audit logging.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from functools import cache
from pathlib import Path

_CONFIG_DIR = Path(__file__).resolve().parents[1] / "config"
ACTIVE_CONSENT_VERSION = "v1"


@dataclass(frozen=True)
class ConsentDocument:
    text: str
    version: str
    sha256: str


@cache
def get_consent_document(version: str = ACTIVE_CONSENT_VERSION) -> ConsentDocument:
    path = _CONFIG_DIR / f"consent_{version}.md"
    if not path.exists():
        raise FileNotFoundError(f"consent document not found: {path}")
    text = path.read_text(encoding="utf-8")
    sha256 = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return ConsentDocument(text=text, version=version, sha256=sha256)
