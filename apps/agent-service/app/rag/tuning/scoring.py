"""Deterministic hybrid scoring over fused candidates.

Fusion decides the order in which candidates arrive; this stage assigns each one
an interpretable score built from named, individually weighted signals. The
scoring is deterministic and LLM-free on purpose: it runs on every request, and
a score that cannot be explained cannot be debugged.

Two design rules are load-bearing:

* **Lexical agreement is a tie-breaker, not a driver.** Dense retrieval already
  encodes semantic similarity; re-weighting it heavily just reproduces the
  vector order while discarding the fusion decision.
* **Diversity is opt-in and defaults off.** Spreading results across dissimilar
  passages measurably trades away precision, so the default is to keep the
  relevance order and only suppress true duplicates.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from .tokenizer import bigrams, overlap_ratio, tokens


@dataclass(frozen=True)
class ScorerWeights:
    """Relative weight of each scoring signal.

    ``fusion`` and ``lexical`` are the only signals that drive the primary
    order. ``coverage`` and ``numeric`` refine without reordering across large
    score gaps, and ``quality`` is available for callers that carry a source
    trust signal in metadata.
    """

    fusion: float = 1.0
    lexical: float = 0.35
    coverage: float = 0.15
    numeric: float = 0.10
    quality: float = 0.10

    def normalized(self) -> "ScorerWeights":
        total = self.fusion + self.lexical + self.coverage + self.numeric + self.quality
        if total <= 0:
            return ScorerWeights()
        return ScorerWeights(
            fusion=self.fusion / total,
            lexical=self.lexical / total,
            coverage=self.coverage / total,
            numeric=self.numeric / total,
            quality=self.quality / total,
        )


DEFAULT_WEIGHTS = ScorerWeights()


@dataclass
class ScoredCandidate:
    position: int
    score: float
    signals: dict[str, float]


def score_candidates(
    *,
    query: str,
    texts: Sequence[str],
    positions: Sequence[int],
    fusion_scores: Sequence[float],
    weights: ScorerWeights | None = None,
    numeric_hit_positions: Sequence[int] = frozenset(),
    quality_scores: Sequence[float] | None = None,
) -> list[ScoredCandidate]:
    """Score candidate positions, returning them in descending score order.

    ``positions`` and ``texts`` are parallel; ``fusion_scores`` is parallel to
    ``positions`` and is min-max normalized so the scale of the fusion output
    does not change the scoring balance.
    """

    if not positions:
        return []

    active = (weights or DEFAULT_WEIGHTS).normalized()
    query_tokens = tokens(query)
    query_bigrams = bigrams(query)
    numeric_positions = set(numeric_hit_positions)

    normalized_fusion = _min_max(fusion_scores)
    scored: list[ScoredCandidate] = []

    for index, position in enumerate(positions):
        text = texts[index] if index < len(texts) else ""
        lexical = _lexical_agreement(query_tokens, query_bigrams, text)
        coverage = _coverage(query_tokens, text)
        numeric = 1.0 if position in numeric_positions else 0.0
        quality = _clamp(quality_scores[index]) if quality_scores and index < len(quality_scores) else 0.0

        total = (
            active.fusion * normalized_fusion[index]
            + active.lexical * lexical
            + active.coverage * coverage
            + active.numeric * numeric
            + active.quality * quality
        )
        scored.append(
            ScoredCandidate(
                position=position,
                score=total,
                signals={
                    "fusion": round(normalized_fusion[index], 6),
                    "lexical": round(lexical, 6),
                    "coverage": round(coverage, 6),
                    "numeric": numeric,
                    "quality": round(quality, 6),
                },
            )
        )

    scored.sort(key=lambda candidate: (-candidate.score, candidate.position))
    return scored


def _lexical_agreement(query_tokens: Sequence[str], query_bigrams: set[str], text: str) -> float:
    """Blend word-level and character-level agreement.

    Word overlap is precise but breaks when the segmenter splits a term
    differently; bigram overlap is noisier but robust to that. Mixing them keeps
    the signal from collapsing on either failure mode.
    """

    if not query_tokens and not query_bigrams:
        return 0.0
    word = overlap_ratio(query_tokens, text)
    if not query_bigrams:
        return word
    candidate_bigrams = bigrams(text)
    gram = len(query_bigrams & candidate_bigrams) / len(query_bigrams) if candidate_bigrams else 0.0
    if not query_tokens:
        return gram
    return 0.6 * word + 0.4 * gram


def _coverage(query_tokens: Sequence[str], text: str) -> float:
    """Fraction of distinct query terms present, rewarding term diversity."""

    distinct = {token for token in query_tokens if token}
    if not distinct:
        return 0.0
    return overlap_ratio(distinct, text)


def _min_max(values: Sequence[float]) -> list[float]:
    if not values:
        return []
    low = min(values)
    high = max(values)
    if high <= low:
        # All candidates tie: give them full credit so the signal neither helps
        # nor arbitrarily penalizes any of them.
        return [1.0 for _ in values]
    span = high - low
    return [(_clamp(value) - low) / span for value in values]


def _clamp(value: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, number))


__all__ = ["DEFAULT_WEIGHTS", "ScoredCandidate", "ScorerWeights", "score_candidates"]
