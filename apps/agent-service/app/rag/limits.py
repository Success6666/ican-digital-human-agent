"""Resource limits for document ingest requests."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


DEFAULT_MAX_METADATA_BYTES = 64 * 1024
DEFAULT_MAX_METADATA_ITEMS = 128
DEFAULT_MAX_METADATA_DEPTH = 6


@dataclass(frozen=True)
class MetadataLimits:
    """Bound metadata traversal and its approximate JSON size."""

    max_bytes: int = DEFAULT_MAX_METADATA_BYTES
    max_items: int = DEFAULT_MAX_METADATA_ITEMS
    max_depth: int = DEFAULT_MAX_METADATA_DEPTH

    def __post_init__(self) -> None:
        if self.max_bytes <= 0 or self.max_items <= 0 or self.max_depth <= 0:
            raise ValueError("metadata limits must be positive")


class MetadataLimitError(ValueError):
    """Raised when metadata exceeds a configured resource boundary."""


def validate_metadata(metadata: dict[str, Any], limits: MetadataLimits) -> None:
    """Validate metadata without serializing the whole object.

    The iterative walk keeps validation stack-bounded and stops as soon as a
    limit is exceeded. The byte count is a conservative JSON-like estimate,
    sufficient for rejecting oversized input before downstream processing.
    """

    if not isinstance(metadata, dict):
        raise MetadataLimitError("metadata must be a JSON object")

    total_bytes = 2  # object braces
    item_count = 0
    stack: list[tuple[Any, int]] = [(metadata, 0)]
    while stack:
        value, depth = stack.pop()
        if depth > limits.max_depth:
            raise MetadataLimitError(f"metadata nesting exceeds {limits.max_depth} levels")

        if isinstance(value, dict):
            total_bytes += 2
            for key, child in value.items():
                item_count += 1
                if item_count > limits.max_items:
                    raise MetadataLimitError(f"metadata items exceed {limits.max_items}")
                total_bytes += _string_bytes(str(key), limits.max_bytes) + 6
                stack.append((child, depth + 1))
        elif isinstance(value, (list, tuple)):
            total_bytes += 2
            for child in value:
                item_count += 1
                if item_count > limits.max_items:
                    raise MetadataLimitError(f"metadata items exceed {limits.max_items}")
                stack.append((child, depth + 1))
        elif isinstance(value, str):
            total_bytes += _string_bytes(value, limits.max_bytes) + 2
        elif value is None or isinstance(value, bool):
            total_bytes += 5
        elif isinstance(value, (int, float)):
            total_bytes += len(str(value))
        else:
            raise MetadataLimitError("metadata contains unsupported value type")

        if total_bytes > limits.max_bytes:
            raise MetadataLimitError(f"metadata exceeds {limits.max_bytes} bytes")


def _string_bytes(value: str, max_bytes: int) -> int:
    """Measure a string only after a cheap UTF-8 upper-bound check."""

    if len(value) > max_bytes:
        raise MetadataLimitError(f"metadata exceeds {max_bytes} bytes")
    encoded_length = len(value.encode("utf-8"))
    if encoded_length > max_bytes:
        raise MetadataLimitError(f"metadata exceeds {max_bytes} bytes")
    return encoded_length


def max_base64_chars(max_decoded_bytes: int) -> int:
    """Return the maximum padded Base64 length for a byte limit."""

    if max_decoded_bytes <= 0:
        raise ValueError("max_decoded_bytes must be positive")
    return ((max_decoded_bytes + 2) // 3) * 4
