"""Small, conservative redaction helper for structured telemetry."""

from __future__ import annotations

from collections.abc import Mapping
import re
from typing import Any


_SECRET_PARTS = (
    "password",
    "passwd",
    "secret",
    "token",
    "api_key",
    "apikey",
    "access_key",
    "secret_key",
    "authorization",
    "cookie",
    "credential",
)
_MAX_STRING = 2048
_MAX_TEXT = 512

_AUTH_TEXT = re.compile(
    r"(?i)(?P<label>\b(?:authorization|proxy-authorization)\b\s*[:=]\s*)"
    r"(?:bearer\s+)?(?P<value>[^\s,;&]+)"
)
_KEY_VALUE_TEXT = re.compile(
    r"(?i)(?P<label>\b(?:api[_-]?key|access[_-]?key|secret(?:[_-]?key)?|"
    r"token|password|passwd|credential|cookie)\b\s*[:=]\s*)"
    r"(?P<quote>['\"]?)(?P<value>[^'\"\s,;&]+)(?P=quote)"
)
_BEARER_TEXT = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{8,}")
_COMMON_KEY_TEXT = re.compile(r"\b(?:sk|rk|pk)-[A-Za-z0-9_-]{12,}\b")
_AWS_KEY_TEXT = re.compile(r"\bAKIA[0-9A-Z]{16}\b")
_JWT_TEXT = re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9._-]+\.[A-Za-z0-9._-]+\b")


def redact(value: Any, *, key: str | None = None, depth: int = 0) -> Any:
    if key and any(part in key.casefold() for part in _SECRET_PARTS):
        return "[REDACTED]"
    if depth > 5:
        return "[TRUNCATED]"
    if isinstance(value, Mapping):
        return {str(item_key): redact(item_value, key=str(item_key), depth=depth + 1) for item_key, item_value in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [redact(item, depth=depth + 1) for item in value]
    if isinstance(value, str) and len(value) > _MAX_STRING:
        return value[:_MAX_STRING] + "...[TRUNCATED]"
    return value


def redact_text(value: str | None, *, max_length: int = _MAX_TEXT) -> str | None:
    """Remove common credential forms from free-form errors and diagnostics."""

    if value is None:
        return None
    text = str(value)
    text = _AUTH_TEXT.sub(_redact_auth_match, text)
    text = _KEY_VALUE_TEXT.sub(
        lambda match: f"{match.group('label')}{match.group('quote')}[REDACTED]{match.group('quote')}",
        text,
    )
    text = _BEARER_TEXT.sub("Bearer [REDACTED]", text)
    text = _COMMON_KEY_TEXT.sub("[REDACTED]", text)
    text = _AWS_KEY_TEXT.sub("[REDACTED]", text)
    text = _JWT_TEXT.sub("[REDACTED]", text)
    if len(text) > max_length:
        return text[:max_length] + "...[TRUNCATED]"
    return text


def _redact_auth_match(match: re.Match[str]) -> str:
    scheme = "Bearer " if re.search(r"(?i)\bbearer\s+", match.group(0)) else ""
    return f"{match.group('label')}{scheme}[REDACTED]"
