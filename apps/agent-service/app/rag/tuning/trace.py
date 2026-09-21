"""Per-query retrieval attribution.

When a query fails to surface a passage that exists in the store, the useful
question is *which stage* lost it. Without that answer, tuning degenerates into
guesswork: raising top-k, weakening thresholds and widening pools all "help" by
masking an unknown cause.

This module records a per-candidate outcome for each stage boundary, so a single
query can be replayed and read as a funnel:

    recalled -> fused -> filtered -> selected

Every candidate that entered a route gets exactly one terminal bucket, and the
buckets are mutually exclusive by construction, which means the counts can be
summed and compared across runs without double-counting.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

Bucket = Literal[
    "selected",
    "rank_too_low",
    "filtered_out",
    "dropped_in_fusion",
    "not_recalled",
]

BUCKETS: tuple[Bucket, ...] = (
    "selected",
    "rank_too_low",
    "filtered_out",
    "dropped_in_fusion",
    "not_recalled",
)


@dataclass
class RouteStats:
    """Recall statistics for a single route within one query."""

    name: str
    recalled: int = 0
    contributed: int = 0


@dataclass
class QueryTrace:
    """Attribution for one query across the retrieval pipeline."""

    query: str
    namespace: str = ""
    routes: list[RouteStats] = field(default_factory=list)
    candidates_seen: int = 0
    candidates_fused: int = 0
    candidates_selected: int = 0
    buckets: dict[Bucket, int] = field(default_factory=lambda: dict.fromkeys(BUCKETS, 0))

    def record(self, bucket: Bucket, *, count: int = 1) -> None:
        if bucket not in BUCKETS:
            raise ValueError(f"unknown bucket: {bucket}")
        self.buckets[bucket] = self.buckets.get(bucket, 0) + count

    def as_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "namespace": self.namespace,
            "routes": [{"name": route.name, "recalled": route.recalled, "contributed": route.contributed} for route in self.routes],
            "candidates_seen": self.candidates_seen,
            "candidates_fused": self.candidates_fused,
            "candidates_selected": self.candidates_selected,
            "buckets": dict(self.buckets),
        }


def classify_candidates(
    *,
    positions: Sequence[int],
    fused_positions: Sequence[int],
    filtered_positions: Sequence[int],
    selected_positions: Sequence[int],
    final_limit: int,
) -> dict[Bucket, int]:
    """Assign each recalled position to exactly one terminal bucket.

    ``selected_positions`` are the positions that survived to the answer, while
    ``filtered_positions`` are those that passed fusion but were rejected by a
    predicate (metadata filter, hard constraint). Positions beyond ``final_limit``
    in the fused order are ``rank_too_low``; positions absent from the fused
    order were ``dropped_in_fusion``.
    """

    counts: dict[Bucket, int] = dict.fromkeys(BUCKETS, 0)
    fused_index = {position: index for index, position in enumerate(fused_positions)}
    filtered = set(filtered_positions)
    selected = set(selected_positions)

    for position in positions:
        if position in selected:
            counts["selected"] += 1
            continue
        index = fused_index.get(position)
        if index is None:
            counts["dropped_in_fusion"] += 1
            continue
        if position not in filtered:
            counts["filtered_out"] += 1
            continue
        if index >= final_limit:
            counts["rank_too_low"] += 1
            continue
        # Survived filtering, ranked inside the window, yet not chosen: the
        # selector preferred other content (dedup suppression or diversity).
        counts["rank_too_low"] += 1
    return counts


def summarize_traces(traces: Sequence[QueryTrace]) -> dict[str, Any]:
    """Aggregate traces into per-bucket totals and shares."""

    totals: dict[Bucket, int] = dict.fromkeys(BUCKETS, 0)
    for trace in traces:
        for bucket in BUCKETS:
            totals[bucket] += trace.buckets.get(bucket, 0)

    grand_total = sum(totals.values())
    shares = {bucket: (totals[bucket] / grand_total if grand_total else 0.0) for bucket in BUCKETS}
    return {
        "queries": len(traces),
        "totals": totals,
        "shares": {bucket: round(value, 6) for bucket, value in shares.items()},
        "candidates_selected": sum(trace.candidates_selected for trace in traces),
    }


def diagnose(traces: Sequence[QueryTrace]) -> str:
    """Return a one-line human-readable reading of where recall is lost."""

    summary = summarize_traces(traces)
    totals = summary["totals"]
    dominant = max(BUCKETS, key=lambda bucket: totals[bucket])
    if not any(totals.values()):
        return "no candidates recorded"
    return (
        f"{summary['queries']} queries, dominant loss = {dominant} "
        f"({totals[dominant]}/{sum(totals.values())})"
    )


__all__ = [
    "BUCKETS",
    "Bucket",
    "QueryTrace",
    "RouteStats",
    "classify_candidates",
    "diagnose",
    "summarize_traces",
]
