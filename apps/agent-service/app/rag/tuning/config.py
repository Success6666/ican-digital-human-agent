"""Retrieval tuning configuration.

Every knob introduced by the tuning package lives here so the whole surface can
be read, overridden from the environment and asserted in tests from one place.
Defaults are deliberately conservative: each stage is independently switchable,
and the pipeline degrades to plain vector search when everything is disabled.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, replace

from .fusion import DEFAULT_K
from .scoring import DEFAULT_WEIGHTS, ScorerWeights
from .selection import Candidate


def _positive_int(raw: str | None, default: int) -> int:
    try:
        value = int(raw) if raw is not None else default
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


def _nonnegative_int(raw: str | None, default: int) -> int:
    try:
        value = int(raw) if raw is not None else default
    except (TypeError, ValueError):
        return default
    return value if value >= 0 else default


def _positive_float(raw: str | None, default: float) -> float:
    try:
        value = float(raw) if raw is not None else default
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


def _truthy(raw: str | None, default: bool) -> bool:
    if raw is None:
        return default
    return raw.strip().casefold() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class RetrievalTuning:
    """Tunable parameters for the hybrid retrieval pipeline."""

    # Multi-route recall
    lexical_enabled: bool = True
    lexical_route_top_k: int = 50
    candidate_multiplier: int = 8

    # Fusion
    rrf_k: float = DEFAULT_K
    lexical_route_weight: float = 1.0
    vector_route_weight: float = 1.0
    fusion_pool_size: int = 50

    # Scoring
    weights: ScorerWeights = DEFAULT_WEIGHTS

    # Selection
    redundancy_threshold: float = 0.8
    short_text_exempt_chars: int = 24

    # Numeric agreement
    numeric_boost_enabled: bool = True
    numeric_relative_tolerance: float = 0.05

    def with_overrides(self, **overrides: object) -> RetrievalTuning:
        return replace(self, **overrides)

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> RetrievalTuning:
        source = env if env is not None else os.environ
        return cls(
            lexical_enabled=_truthy(source.get("RAG_LEXICAL_ENABLED"), True),
            lexical_route_top_k=_positive_int(source.get("RAG_LEXICAL_TOP_K"), 50),
            candidate_multiplier=_positive_int(source.get("RAG_CANDIDATE_MULTIPLIER"), 8),
            rrf_k=_positive_float(source.get("RAG_RRF_K"), DEFAULT_K),
            lexical_route_weight=_positive_float(source.get("RAG_RRF_LEXICAL_WEIGHT"), 1.0),
            vector_route_weight=_positive_float(source.get("RAG_RRF_VECTOR_WEIGHT"), 1.0),
            fusion_pool_size=_positive_int(source.get("RAG_FUSION_POOL_SIZE"), 50),
            redundancy_threshold=_positive_float(source.get("RAG_REDUNDANCY_THRESHOLD"), 0.8),
            short_text_exempt_chars=_nonnegative_int(source.get("RAG_SHORT_TEXT_EXEMPT_CHARS"), 24),
            numeric_boost_enabled=_truthy(source.get("RAG_NUMERIC_BOOST_ENABLED"), True),
            numeric_relative_tolerance=_positive_float(source.get("RAG_NUMERIC_TOLERANCE"), 0.05),
        )


def pool_size(tuning: RetrievalTuning, top_k: int) -> int:
    """Candidate pool depth for a request, clamped for small corpora."""

    return max(top_k, min(tuning.fusion_pool_size, max(top_k * tuning.candidate_multiplier, top_k)))


__all__ = ["Candidate", "RetrievalTuning", "pool_size"]
