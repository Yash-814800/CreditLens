import logging
import re
import sys
from typing import Any

import structlog

# Key names that are always fully redacted regardless of content (CLAUDE.md rule 9:
# PII never in logs; rule 2: never print/log secrets).
_REDACT_KEYS = {
    "password",
    "aadhaar",
    "aadhaar_number",
    "aadhaar_hash",
    "pan",
    "pan_number",
    "phone",
    "phone_number",
    "authorization",
    "access_token",
    "jwt",
    "jwt_secret",
    "hmac_pepper",
    "gemini_api_key",
}

# Value-shaped redaction as a defence-in-depth net for PII that ends up in a free-text
# field (e.g. an exception message) rather than a well-named key.
_PII_VALUE_PATTERNS = [
    re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b"),  # PAN-shaped
    re.compile(r"\b\d{4}\s?\d{4}\s?\d{4}\b"),  # Aadhaar-shaped (12 digits)
    re.compile(r"\b[6-9]\d{9}\b"),  # Indian mobile-shaped (10 digits, starts 6-9)
]


def _redact_string(value: str) -> str:
    redacted = value
    for pattern in _PII_VALUE_PATTERNS:
        redacted = pattern.sub("[REDACTED]", redacted)
    return redacted


def _redact(value: Any) -> Any:
    if isinstance(value, str):
        return _redact_string(value)
    if isinstance(value, dict):
        return {
            k: ("[REDACTED]" if k.lower() in _REDACT_KEYS else _redact(v)) for k, v in value.items()
        }
    if isinstance(value, list):
        return [_redact(v) for v in value]
    return value


def pii_redaction_processor(
    logger: Any, method_name: str, event_dict: dict[str, Any]
) -> dict[str, Any]:
    for key in list(event_dict.keys()):
        if key.lower() in _REDACT_KEYS:
            event_dict[key] = "[REDACTED]"
        else:
            event_dict[key] = _redact(event_dict[key])
    return event_dict


def configure_logging(log_level: str) -> None:
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=log_level)
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            pii_redaction_processor,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.getLevelName(log_level)),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(*args: Any, **kwargs: Any):
    return structlog.get_logger(*args, **kwargs)
