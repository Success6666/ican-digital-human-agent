"""Hybrid retrieval pipeline: multi-route recall, fusion, scoring, selection.

The pipeline is intentionally storage-agnostic. It accepts already-materialized
rows and produces a ranked list of row positions, so the same logic serves the
persistent FAISS store and the in-memory store without either owning a copy.

Stage order and the reason for it:

1. **Recall** from independent routes. Dense vectors capture paraphrase; BM25
   captures exact terminology, identifiers and rare tokens. Neither subsumes the
   other, which is why both run.
2. **Fuse by rank** rather than by score, since route scores are not comparable.
3. **Score deterministically** over a bounded pool, blending fusion position
   with lexical agreement and numeric corroboration.
4. **Select** with near-duplicate suppression, so the answer budget is spent on
   distinct content.

Each stage is individually disableable. With every optional stage off the
pipeline reproduces a plain vector ranking, which keeps behaviour predictable
when a caller wants the conservative path.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from .bm25 import rank as bm25_rank
from .config import RetrievalTuning, pool_size
from .fusion import fuse_positions
from .quantity import contains_compatible_value, parse_quantities
from .scoring import score_candidates
from .selection import Candidate, select_distinct
from .trace import QueryTrace, RouteStats
from .tokenizer import tokens

VECTOR_ROUTE = 0
LEXICAL_ROUTE = 1


@dataclass
class RetrievalOutcome:
    """Result of one pipeline run over a fixed candidate set."""

    positions: list[int] = field(default_factory=list)
    scores: dict[int, float] = field(default_factory=dict)
    trace: QueryTrace | None = None


def retrieve(
    *,
    query: str,
    texts: Sequence[str],
    vector_ranked: Sequence[int],
    vector_scores: Sequence[float],
    top_k: int,
    tuning: RetrievalTuning | None = None,
    allowed_positions: Sequence[int] | None = None,
    trace_enabled: bool = False,
) -> RetrievalOutcome:
    """Run the hybrid pipeline and return ranked row positions.

    ``texts`` is the full row set; positions index into it. ``vector_ranked`` is
    the dense route's result as positions in descending similarity, with
    ``vector_scores`` parallel to it. ``allowed_positions`` restricts the result
    to rows surviving non-score predicates such as a metadata filter; when it is
    ``None`` every row is eligible.
    """

    active = tuning or RetrievalTuning()
    if top_k < 1 or not texts:
        return RetrievalOutcome(trace=QueryTrace(query=query) if trace_enabled else None)

    eligible = _eligibility_set(allowed_positions, len(texts))
    trace = QueryTrace(query=query) if trace_enabled else None

    # ---- Route 1: dense vectors -------------------------------------------
    dense_ranked = [position for position in vector_ranked if position in eligible]
    dense_score_by_position = {
        position: float(score)
        for position, score in zip(vector_ranked, vector_scores, strict=False)
        if position in eligible
    }
    if trace is not None:
        trace.routes.append(RouteStats(name="vector", recalled=len(dense_ranked)))

    # ---- Route 2: lexical / BM25 ------------------------------------------
    lexical_ranked: list[int] = []
    if active.lexical_enabled:
        candidate_documents = [texts[position] for position in sorted(eligible)]
        ranked = bm25_rank(query, candidate_documents, top_n=active.lexical_route_top_k)
        index_to_position = sorted(eligible)
        lexical_ranked = [index_to_position[index] for index, _ in ranked]
        if trace is not None:
            trace.routes.append(RouteStats(name="lexical", recalled=len(lexical_ranked)))

    if not dense_ranked and not lexical_ranked:
        if trace is not None:
            trace.record("not_recalled", count=len(eligible))
        return RetrievalOutcome(trace=trace)

    # ---- Fusion -----------------------------------------------------------
    pool = pool_size(active, top_k)
    if active.lexical_enabled:
        ranked_lists: list[Sequence[int]] = [dense_ranked, lexical_ranked]
        active_weights: dict[int, float] = {
            VECTOR_ROUTE: active.vector_route_weight,
            LEXICAL_ROUTE: active.lexical_route_weight,
        }
    else:
        ranked_lists = [dense_ranked]
        active_weights = {VECTOR_ROUTE: active.vector_route_weight}
    fused = fuse_positions(ranked_lists, k=active.rrf_k, top_n=pool, weights=active_weights)
    fused_positions = [position for position, _ in fused]
    fusion_scores = [score for _, score in fused]

    if not fused_positions:
        if trace is not None:
            trace.record("dropped_in_fusion", count=max(0, len(dense_ranked) + len(lexical_ranked)))
        return RetrievalOutcome(trace=trace)

    if trace is not None:
        trace.candidates_seen = len(dense_ranked) + len(lexical_ranked)
        trace.candidates_fused = len(fused_positions)

    # ---- Numeric corroboration -------------------------------------------
    numeric_hits: list[int] = []
    if active.numeric_boost_enabled and parse_quantities(query):
        numeric_hits = [
            position
            for position in fused_positions
            if contains_compatible_value(
                query,
                texts[position],
                relative_tolerance=active.numeric_relative_tolerance,
            )
        ]

    # ---- Scoring ----------------------------------------------------------
    scored = score_candidates(
        query=query,
        texts=[texts[position] for position in fused_positions],
        positions=fused_positions,
        fusion_scores=fusion_scores,
        weights=active.weights,
        numeric_hit_positions=numeric_hits,
    )
    if trace is not None:
        trace.routes.append(RouteStats(name="fused", recalled=len(fused_positions), contributed=len(scored)))

    # ---- Selection --------------------------------------------------------
    # Keep more than top_k candidates available to the selector so duplicate
    # suppression can refill from the pool instead of returning a short list.
    selection_pool = [
        Candidate(position=candidate.position, text=texts[candidate.position], score=candidate.score)
        for candidate in scored
    ]
    selected = select_distinct(
        selection_pool,
        limit=top_k,
        redundancy_threshold=active.redundancy_threshold,
        short_text_chars=active.short_text_exempt_chars,
    )

    positions = [candidate.position for candidate in selected]
    scores = {candidate.position: candidate.score for candidate in selected}

    if trace is not None:
        trace.candidates_selected = len(positions)
        trace.record("selected", count=len(positions))
        trace.record("rank_too_low", count=max(0, len(scored) - len(positions)))

    return RetrievalOutcome(positions=positions, scores=scores, trace=trace)


def _eligibility_set(allowed_positions: Sequence[int] | None, row_count: int) -> set[int]:
    if allowed_positions is None:
        return set(range(row_count))
    return {position for position in allowed_positions if 0 <= position < row_count}


def numeric_agreement(query: str, text: str, *, relative_tolerance: float = 0.05) -> bool:
    """Whether ``text`` corroborates the numeric expectation in ``query``."""

    return contains_compatible_value(query, text, relative_tolerance=relative_tolerance)


def query_terms(query: str) -> list[str]:
    """Expose the tokenizer for callers that need the query's terms."""

    return tokens(query)


__all__ = [
    "LEXICAL_ROUTE",
    "VECTOR_ROUTE",
    "RetrievalOutcome",
    "numeric_agreement",
    "query_terms",
    "retrieve",
]
