"""Reciprocal Rank Fusion for merging ranked lists from independent routes.

Different recall routes (dense vectors, lexical/BM25, field-aware keyword) score
documents on incomparable scales. Averaging raw scores would let whichever route
happens to produce large numbers dominate. RRF sidesteps the calibration problem
by consuming only *ranks*:

    RRF(d) = sum over routes of  weight_route / (k + rank_route(d))

with ``rank`` 1-based and ``k`` (default 60) damping the influence of the very
top of each list. The constant makes fusion robust when one route is confident
and another is noisy, which is the common case in hybrid retrieval.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import TypeVar

T = TypeVar("T")

DEFAULT_K = 60.0


def reciprocal_rank_fusion(
    ranked_lists: Sequence[Sequence[T]],
    *,
    k: float = DEFAULT_K,
    top_n: int | None = None,
    weights: Sequence[float] | Mapping[int, float] | None = None,
) -> list[tuple[T, float]]:
    """Fuse ranked lists into a single ranked list of ``(item, score)``.

    Ties are broken by first-seen order so the result is deterministic, which
    matters because fused order feeds caching and evaluation comparisons.

    ``weights`` may be either a sequence aligned with ``ranked_lists`` or a
    mapping of route index to weight. Missing weights default to 1.0.
    """

    if k <= 0:
        raise ValueError("k must be positive")

    fused: dict[T, float] = {}
    first_seen: dict[T, int] = {}
    order = 0

    for route_index, ranked in enumerate(ranked_lists):
        weight = _route_weight(weights, route_index)
        if not weight:
            continue
        seen_in_route: set[T] = set()
        rank = 0
        for item in ranked:
            # A route should not be able to double-count one document; keep the
            # first (best) occurrence and ignore repeats.
            if item in seen_in_route:
                continue
            seen_in_route.add(item)
            rank += 1
            fused[item] = fused.get(item, 0.0) + weight / (k + rank)
            if item not in first_seen:
                first_seen[item] = order
                order += 1

    ranked_items = sorted(fused.items(), key=lambda pair: (-pair[1], first_seen[pair[0]]))
    if top_n is not None:
        if top_n < 1:
            return []
        ranked_items = ranked_items[:top_n]
    return ranked_items


def _route_weight(weights: Sequence[float] | Mapping[int, float] | None, route_index: int) -> float:
    if weights is None:
        return 1.0
    if isinstance(weights, Mapping):
        raw = weights.get(route_index, 1.0)
    else:
        raw = weights[route_index] if route_index < len(weights) else 1.0
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return 1.0
    return value if value >= 0 else 0.0


def fuse_positions(
    ranked_lists: Sequence[Sequence[int]],
    *,
    k: float = DEFAULT_K,
    top_n: int | None = None,
    weights: Sequence[float] | Mapping[int, float] | None = None,
) -> list[tuple[int, float]]:
    """Convenience wrapper for the common case of integer row positions."""

    return reciprocal_rank_fusion(ranked_lists, k=k, top_n=top_n, weights=weights)


__all__ = ["DEFAULT_K", "fuse_positions", "reciprocal_rank_fusion"]
