"""Small, bounded policies shared by the Docling parser."""

from __future__ import annotations

import mimetypes
from pathlib import PurePath


def infer_content_type(source_name: str, content_type: str | None, payload: bytes | None = None) -> str:
    """Prefer explicit metadata, then names, then conservative UTF-8 sniffing."""

    if content_type:
        return content_type.split(";", 1)[0].strip().lower()
    guessed, _ = mimetypes.guess_type(source_name)
    if guessed:
        return guessed.lower()
    suffix = PurePath(source_name).suffix.lower()
    named_type = {
        ".md": "text/markdown",
        ".markdown": "text/markdown",
        ".html": "text/html",
        ".htm": "text/html",
        ".txt": "text/plain",
    }.get(suffix)
    if named_type:
        return named_type
    return "text/plain" if payload is not None and looks_like_text(payload) else "application/octet-stream"


def looks_like_text(payload: bytes) -> bool:
    """Classify MIME-less UTF-8 text without trusting an untrusted file name."""

    sample = payload[:64 * 1024]
    if not sample or any(sample.startswith(signature) for signature in (
        b"%PDF-",
        b"PK\x03\x04",
        b"\x89PNG\r\n\x1a\n",
        b"\xff\xd8\xff",
        b"GIF8",
        b"RIFF",
    )):
        return False
    if b"\x00" in sample:
        return False
    try:
        text = sample.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        return False
    return not any(
        (ord(char) < 32 and char not in "\n\r\t\f") or ord(char) == 127
        for char in text
    )


def truthy(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


def positive_int(raw: str | None, default: int) -> int:
    try:
        value = int(raw) if raw is not None else default
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


def public_load_error(value: str | None) -> str | None:
    """Expose a useful status without leaking paths or SDK internals."""

    if not value:
        return None
    normalized = value.casefold()
    if "disabled" in normalized:
        return "Docling 已按配置关闭"
    if "not installed" in normalized or "modulenotfound" in normalized:
        return "Docling 依赖未安装"
    return "Docling 模型或依赖暂不可用"


__all__ = ["infer_content_type", "looks_like_text", "positive_int", "public_load_error", "truthy"]
