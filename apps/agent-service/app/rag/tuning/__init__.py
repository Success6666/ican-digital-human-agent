"""Retrieval tuning: hybrid recall, rank fusion, scoring and selection.

This package holds the retrieval-quality logic that is independent of any single
storage backend. Keeping it dependency-light and side-effect free means the
persistent store, the in-memory store and the offline evaluation harness all
exercise the same implementation, so a change in ranking behaviour shows up
identically everywhere.

Entry point for retrieval is :func:`retrieve`; :class:`RetrievalTuning` carries
every knob and can be built from the environment.
"""

from __future__ import annotations

from .bm25 import build_index as build_bm25_index
from .bm25 import rank as bm25_rank
from .config import RetrievalTuning, pool_size
from .evaluation import (
    DEFAULT_BOOTSTRAP_SAMPLES,
    DEFAULT_CONFIDENCE,
    EvaluationReport,
    MetricSummary,
    RetrievalCase,
    average_precision,
    compare_configurations,
    evaluate_retrieval,
    hit_rate_at_k,
    ndcg_at_k,
    paired_bootstrap,
    precision_at_k,
    recall_at_k,
    reciprocal_rank,
)
from .fusion import DEFAULT_K, fuse_positions, reciprocal_rank_fusion
from .pipeline import RetrievalOutcome, numeric_agreement, query_terms, retrieve
from .quantity import (
    Quantity,
    best_relation,
    compare,
    contains_compatible_value,
    parse_quantities,
    resolution_classes,
)
from .scoring import DEFAULT_WEIGHTS, ScoredCandidate, ScorerWeights, score_candidates
from .selection import (
    Candidate,
    content_signature,
    dedupe_texts,
    is_duplicate,
    prune_pool,
    select_distinct,
    signature_similarity,
)
from .tokenizer import bigrams, normalize_term, overlap_ratio, token_set, tokens
from .trace import (
    BUCKETS,
    Bucket,
    QueryTrace,
    RouteStats,
    classify_candidates,
    diagnose,
    summarize_traces,
)

__all__ = [
    "BUCKETS",
    "DEFAULT_BOOTSTRAP_SAMPLES",
    "DEFAULT_CONFIDENCE",
    "DEFAULT_K",
    "DEFAULT_WEIGHTS",
    "Bucket",
    "Candidate",
    "EvaluationReport",
    "MetricSummary",
    "Quantity",
    "QueryTrace",
    "RetrievalCase",
    "RetrievalOutcome",
    "RetrievalTuning",
    "RouteStats",
    "ScoredCandidate",
    "ScorerWeights",
    "average_precision",
    "best_relation",
    "bigrams",
    "bm25_rank",
    "build_bm25_index",
    "classify_candidates",
    "compare",
    "compare_configurations",
    "contains_compatible_value",
    "content_signature",
    "dedupe_texts",
    "diagnose",
    "evaluate_retrieval",
    "fuse_positions",
    "hit_rate_at_k",
    "is_duplicate",
    "ndcg_at_k",
    "normalize_term",
    "numeric_agreement",
    "overlap_ratio",
    "paired_bootstrap",
    "parse_quantities",
    "pool_size",
    "precision_at_k",
    "prune_pool",
    "query_terms",
    "recall_at_k",
    "reciprocal_rank",
    "reciprocal_rank_fusion",
    "resolution_classes",
    "retrieve",
    "score_candidates",
    "select_distinct",
    "signature_similarity",
    "summarize_traces",
    "token_set",
    "tokens",
]
