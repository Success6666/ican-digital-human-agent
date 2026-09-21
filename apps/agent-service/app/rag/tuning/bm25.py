"""Self-contained BM25 lexical scoring.

The retrieval store needs a lexical route that does not depend on an external
search engine, so BM25 is implemented directly over the in-memory row set. Only
document frequency and average length are needed, and both are derived from the
candidate rows on each search, which keeps the index stateless and always
consistent with the stored text.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
import math

from .tokenizer import tokens

# Standard BM25 saturation and length-normalization constants. These values are
# the widely used defaults and were not worth tuning against a small corpus.
DEFAULT_K1 = 1.5
DEFAULT_B = 0.75


@dataclass
class Bm25Index:
    """Term statistics for a fixed document collection."""

    document_count: int = 0
    average_length: float = 0.0
    document_frequency: Counter[str] = field(default_factory=Counter)

    def score(self, query_tokens: Sequence[str], term_frequencies: Counter[str], length: int) -> float:
        if not query_tokens or not self.document_count or length <= 0:
            return 0.0
        if self.average_length <= 0:
            return 0.0

        total = 0.0
        for token in query_tokens:
            frequency = term_frequencies.get(token, 0)
            if not frequency:
                continue
            document_frequency = self.document_frequency.get(token, 0)
            # Probabilistic IDF with a floor: a term appearing in every document
            # carries no discriminative value, and the 0.5 floor keeps the value
            # non-negative for tiny collections where df > N/2.
            idf = math.log(1.0 + (self.document_count - document_frequency + 0.5) / (document_frequency + 0.5))
            denominator = frequency + DEFAULT_K1 * (1.0 - DEFAULT_B + DEFAULT_B * length / self.average_length)
            total += idf * (frequency * (DEFAULT_K1 + 1.0)) / denominator
        return total


def build_index(documents: Sequence[str]) -> tuple[Bm25Index, list[Counter[str]]]:
    """Build BM25 statistics and per-document term frequencies.

    Returns the shared index plus the per-document frequency tables so callers
    can score without re-tokenizing.
    """

    index = Bm25Index()
    frequencies: list[Counter[str]] = []
    total_length = 0
    document_frequency: Counter[str] = Counter()

    for document in documents:
        document_tokens = tokens(document)
        counts = Counter(document_tokens)
        frequencies.append(counts)
        total_length += len(document_tokens)
        document_frequency.update(counts.keys())

    count = len(documents)
    index.document_count = count
    index.average_length = (total_length / count) if count else 0.0
    index.document_frequency = document_frequency
    return index, frequencies


def rank(
    query: str,
    documents: Sequence[str],
    *,
    top_n: int | None = None,
) -> list[tuple[int, float]]:
    """Rank documents by BM25 against ``query``.

    Returns ``(position, score)`` pairs sorted by descending score. Documents
    with a zero score are dropped: they share no terms with the query and would
    only dilute fusion.
    """

    query_tokens = tokens(query)
    if not query_tokens or not documents:
        return []

    index, frequencies = build_index(documents)
    scored = [
        (position, index.score(query_tokens, frequencies[position], sum(frequencies[position].values())))
        for position in range(len(documents))
    ]
    positive = [(position, score) for position, score in scored if score > 0.0]
    positive.sort(key=lambda pair: (-pair[1], pair[0]))
    if top_n is not None:
        if top_n < 1:
            return []
        positive = positive[:top_n]
    return positive


__all__ = ["DEFAULT_B", "DEFAULT_K1", "Bm25Index", "build_index", "rank"]
