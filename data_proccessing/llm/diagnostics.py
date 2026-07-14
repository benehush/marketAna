"""Shared LLM diagnostic codes and redaction helpers."""

from __future__ import annotations

import re
from typing import Iterable


LLM_ERROR_TYPES = frozenset(
    {
        "request_timeout",
        "network_error",
        "http_error",
        "empty_sse_response",
        "provider_response_error",
        "invalid_json",
        "product_mismatch",
        "invalid_direction",
        "empty_reason",
        "invalid_confidence",
        "invalid_evidence",
        "unexpected_error",
    }
)

_BEARER_PATTERN = re.compile(r"(?i)\bBearer\s+[^\s,;\"']+")
_QUERY_SECRET_PATTERN = re.compile(
    r"(?i)([?&](?:api[_-]?key|access[_-]?token|token|secret|password)=)[^&\s]+"
)
_KEY_VALUE_SECRET_PATTERN = re.compile(
    r"(?i)(\b(?:api[_-]?key|access[_-]?token|token|secret|password)\b\s*[:=]\s*)"
    r"(?:\"[^\"]*\"|'[^']*'|[^\s,;&]+)"
)


def sanitize_text(value: object, *, secrets: Iterable[str] = (), limit: int = 1000) -> str:
    """Redact credentials and bound diagnostic text before persistence/logging."""
    text = str(value or "")
    for secret in secrets:
        if secret:
            text = text.replace(str(secret), "[REDACTED]")
    text = _BEARER_PATTERN.sub("Bearer [REDACTED]", text)
    text = _QUERY_SECRET_PATTERN.sub(r"\1[REDACTED]", text)
    text = _KEY_VALUE_SECRET_PATTERN.sub(r"\1[REDACTED]", text)
    return text[: max(0, limit)]
