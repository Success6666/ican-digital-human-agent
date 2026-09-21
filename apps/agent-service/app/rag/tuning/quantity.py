"""Quantity extraction and comparison for numeric retrieval evidence.

Technical queries frequently target a specific measurement (``支持 4K 输出``,
``延迟低于 200ms``, ``最多 8 路并发``). Treating those as ordinary tokens loses
the two things that matter: the numeric value and its unit. This module pulls
quantities out of text so a retrieval stage can check whether a candidate
passage actually contains a compatible figure rather than a nearby number.

Comparison is deliberately four-valued. ``missing`` and ``conflict`` are
distinct outcomes because they call for different downstream behaviour: absent
evidence should fall back to other passages, while contradictory evidence
should be surfaced rather than silently dropped.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
import re
from typing import Literal

Relation = Literal["exact", "compatible", "conflict", "missing"]

# Relative tolerance for "close enough" numeric agreement. Values within +/-5%
# are treated as the same figure: documentation rounds, and exact equality is
# too brittle for text extracted from tables and prose.
DEFAULT_RELATIVE_TOLERANCE = 0.05

_NUMBER = r"\d+(?:\.\d+)?"
_UNIT = r"[A-Za-z%/]+|毫秒|秒钟|分钟|小时|天|周|个月|年|像素|帧率|路|个|条|次|台|核|线程"
_QUANTITY = re.compile(rf"(?P<value>{_NUMBER})\s*(?P<unit>{_UNIT})?", re.IGNORECASE)

# Display resolutions are written as a bare number plus a resolution class
# ("4K", "1080p", "2k"). Catching them before the generic pattern keeps the
# resolution class as the unit, so 4K and 1080p do not compare as raw numbers
# and a query for one does not silently match the other.
_RESOLUTION = re.compile(r"(?<![A-Za-z0-9])(?P<number>\d{1,4})\s*(?P<class>[kKpP])(?![A-Za-z0-9])")
def _resolution_label(number: float, suffix: str) -> str | None:
    """Classify a shorthand like ``4K`` / ``1080p`` / ``2k``.

    The suffix alone is ambiguous, so the numeric magnitude decides: ``k`` means
    thousands of horizontal pixels, ``p`` means vertical pixels.
    """

    suffix = suffix.casefold()
    if suffix == "k":
        if number >= 7:
            return "res:8k"
        if number >= 3:
            return "res:4k"
        if number >= 1.5:
            return "res:2k"
        return None
    if suffix == "p":
        if number >= 2100:
            return "res:4k"
        if number >= 1300:
            return "res:2k"
        if number >= 1000:
            return "res:1080p"
        if number >= 650:
            return "res:720p"
        return None
    return None

# Multipliers normalize common Chinese numeric shorthands so "万" and "w" do not
# read as 10000x different from the same figure written out in full.
_SCALE_SUFFIXES = {
    "万": 10_000.0,
    "w": 10_000.0,
    "千": 1_000.0,
    "k": 1_000.0,
    "m": 1_000_000.0,
    "亿": 100_000_000.0,
}

_UNIT_ALIASES = {
    "ms": "ms",
    "毫秒": "ms",
    "s": "s",
    "秒": "s",
    "秒钟": "s",
    "sec": "s",
    "seconds": "s",
    "fps": "fps",
    "帧": "fps",
    "帧率": "fps",
    "k": "k",
    "p": "p",
    "px": "px",
    "像素": "px",
    "路": "channel",
    "个": "count",
    "条": "count",
    "次": "count",
    "台": "count",
    "核": "core",
    "线程": "thread",
    "mb": "mb",
    "kb": "kb",
    "gb": "gb",
    "tb": "tb",
    "分钟": "min",
    "小时": "hour",
    "天": "day",
}


@dataclass(frozen=True)
class Quantity:
    """A numeric value with an optional normalized unit."""

    value: float
    unit: str | None = None
    raw: str = ""

    def __str__(self) -> str:
        return self.raw or (f"{self.value:g}{self.unit or ''}")


def _normalize_unit(unit: str | None) -> str | None:
    if not unit:
        return None
    key = unit.strip().casefold()
    return _UNIT_ALIASES.get(key, key)


def _apply_scale(value: float, unit: str | None) -> tuple[float, str | None]:
    """Fold a scale suffix into the value and drop the pseudo-unit."""

    if unit:
        scale = _SCALE_SUFFIXES.get(unit.strip().casefold())
        if scale is not None:
            return value * scale, None
    return value, unit


def parse_quantities(text: str) -> list[Quantity]:
    """Extract every numeric quantity from text, in order of appearance."""

    if not text:
        return []

    quantities: list[Quantity] = []
    # Resolutions first; their spans are excluded from the generic pass so
    # "2160p" is not also read as a bare 2160 count.
    resolution_spans: list[tuple[int, int]] = []
    for match in _RESOLUTION.finditer(text):
        try:
            number = float(match.group("number"))
        except (TypeError, ValueError):
            continue
        unit = _resolution_label(number, match.group("class"))
        if unit is None:
            continue
        quantity = Quantity(value=number, unit=unit, raw=match.group(0).strip())
        if quantity not in quantities:
            quantities.append(quantity)
        resolution_spans.append((match.start(), match.end()))

    for match in _QUANTITY.finditer(text):
        if any(start <= match.start() < end for start, end in resolution_spans):
            continue
        try:
            value = float(match.group("value"))
        except (TypeError, ValueError):
            continue
        unit = _normalize_unit(match.group("unit"))
        value, unit = _apply_scale(value, unit)
        quantity = Quantity(value=value, unit=unit, raw=match.group(0).strip())
        if quantity not in quantities:
            quantities.append(quantity)
    return quantities


def _resolution_class_of(width: float | None, height: float | None) -> str | None:
    """Map a pixel dimension pair onto a display resolution class.

    ``3840x2160`` and ``4K`` denote the same mode, so a query written one way
    must be able to match evidence written the other way. Recognized classes are
    intentionally coarse; anything unrecognized returns ``None`` and falls back
    to plain numeric comparison.
    """

    if width is None or height is None:
        return None
    long_edge = max(width, height)
    if long_edge >= 7000:
        return "res:8k"
    if long_edge >= 3600:
        return "res:4k"
    if long_edge >= 2300:
        return "res:2k"
    if long_edge >= 1700:
        return "res:1080p"
    if long_edge >= 1100:
        return "res:720p"
    return None


# Matches a pixel dimension pair such as "3840x2160" or "1920 × 1080".
_DIMENSIONS = re.compile(r"(?<!\d)(\d{3,5})\s*[x×*]\s*(\d{3,5})(?!\d)")


def resolution_classes(text: str) -> set[str]:
    """Display resolution classes implied by any dimension pairs in ``text``."""

    if not text:
        return set()
    classes: set[str] = set()
    for match in _DIMENSIONS.finditer(text):
        try:
            width = float(match.group(1))
            height = float(match.group(2))
        except (TypeError, ValueError):
            continue
        label = _resolution_class_of(width, height)
        if label:
            classes.add(label)
    for match in _RESOLUTION.finditer(text):
        try:
            number = float(match.group("number"))
        except (TypeError, ValueError):
            continue
        label = _resolution_label(number, match.group("class"))
        if label:
            classes.add(label)
    return classes


def compare(
    expected: Quantity,
    candidate: Quantity,
    *,
    relative_tolerance: float = DEFAULT_RELATIVE_TOLERANCE,
) -> Relation:
    """Compare two quantities into a four-valued relation.

    Units must match when both sides declare one; a unit mismatch is a
    ``conflict`` rather than ``missing`` because the passage is talking about a
    different dimension, not staying silent.
    """

    if expected.unit and candidate.unit and expected.unit != candidate.unit:
        return "conflict"

    difference = abs(expected.value - candidate.value)
    if difference == 0:
        return "exact"

    scale = max(abs(expected.value), 1e-9)
    if difference / scale <= relative_tolerance:
        return "compatible"
    return "conflict"


def best_relation(
    expected: Quantity,
    candidates: Sequence[Quantity],
    *,
    relative_tolerance: float = DEFAULT_RELATIVE_TOLERANCE,
) -> Relation:
    """Strongest relation available between ``expected`` and any candidate."""

    if not candidates:
        return "missing"

    best: Relation = "missing"
    for candidate in candidates:
        relation = compare(expected, candidate, relative_tolerance=relative_tolerance)
        if relation == "exact":
            return "exact"
        if relation == "compatible":
            best = "compatible"
        elif relation == "conflict" and best == "missing":
            best = "conflict"
    return best


def _matches_resolution_class(expected: Quantity, text: str) -> bool:
    """Whether ``text`` expresses the same display class as ``expected``."""

    if not expected.unit or not expected.unit.startswith("res:"):
        return False
    return expected.unit in resolution_classes(text)


def contains_compatible_value(
    query: str,
    text: str,
    *,
    relative_tolerance: float = DEFAULT_RELATIVE_TOLERANCE,
) -> bool:
    """Whether ``text`` carries a numerically compatible figure for ``query``.

    Returns ``True`` when the query has no numeric expectation at all, so the
    caller can use this as a pure filter without special-casing queries that do
    not ask for a number.

    Compatibility requires every expected quantity to find a matching or
    near-matching figure. A present-but-contradictory figure counts as a miss:
    the passage does discuss the property, but not at the value the query asks
    about, so it should not be boosted as corroborating evidence.

    Display resolutions are compared by class rather than by number, so ``4K``
    in a query matches ``3840x2160`` in the evidence.
    """

    expected_quantities = parse_quantities(query)
    if not expected_quantities:
        return True

    text_classes = resolution_classes(text)
    candidate_quantities = parse_quantities(text)

    for expected in expected_quantities:
        if expected.unit and expected.unit.startswith("res:"):
            # A resolution expectation is satisfied only by the same class,
            # whether it was written as "4K" or as an explicit dimension pair.
            if expected.unit not in text_classes:
                return False
            continue
        if best_relation(expected, candidate_quantities, relative_tolerance=relative_tolerance) not in {"exact", "compatible"}:
            return False
    return True


__all__ = [
    "DEFAULT_RELATIVE_TOLERANCE",
    "Quantity",
    "Relation",
    "best_relation",
    "compare",
    "contains_compatible_value",
    "parse_quantities",
    "resolution_classes",
]
