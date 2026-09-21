"""Result selection: near-duplicate suppression and coverage-aware pruning.

Vector search tends to return clusters of near-identical passages, because a
long document is split into overlapping chunks that all match the same query.
Spending the final answer budget on eight paraphrases of one sentence is a
measurable loss: the caller gets less information for the same context window.

The selector here removes redundancy by content signature. Character-level
n-gram containment is used rather than token overlap because it survives
segmentation differences and language mixing, and because it catches the common
case of one passage being a near-copy of another with a few edited words.

An explicit vocabulary-free signature is also deliberately *not* used for
diversity ranking. Spreading results across dissimilar passages trades away
precision in ways that measured negatively in practice; suppressing true
duplicates while otherwise preserving relevance order is the safer lever.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
import re

from .tokenizer import normalize_term

_SIGNATURE_GRAM = 3
_SHORT_TEXT_CHARS = 24


@dataclass(frozen=True)
class Candidate:
    """A retrieved passage considered for the final result set."""

    position: int
    text: str
    score: float

    @property
    def key(self) -> int:
        return self.position


def content_signature(text: str) -> frozenset[str]:
    """Character n-gram signature used for duplicate detection.

    Whitespace is stripped so formatting differences (line breaks from a parser,
    indentation from a table) do not make two copies of the same text look
    distinct.
    """

    compact = re.sub(r"\s+", "", normalize_term(text))
    if not compact:
        return frozenset()
    if len(compact) <= _SIGNATURE_GRAM:
        return frozenset({compact})
    return frozenset(compact[index : index + _SIGNATURE_GRAM] for index in range(len(compact) - _SIGNATURE_GRAM + 1))


def signature_similarity(left: frozenset[str], right: frozenset[str]) -> float:
    """Containment similarity between two signatures (0.0 .. 1.0)."""

    if not left or not right:
        return 0.0
    smaller, larger = (left, right) if len(left) <= len(right) else (right, left)
    return len(smaller & larger) / len(smaller)


def is_duplicate(
    left: str,
    right: str,
    *,
    threshold: float = 0.8,
    short_text_chars: int = _SHORT_TEXT_CHARS,
) -> bool:
    """Whether two passages should be treated as the same content.

    ``short_text_chars`` mirrors the exemption applied by :func:`select_distinct`
    so a direct pairwise check agrees with what the selector would do. Character
    n-grams are unstable at short lengths, and short passages are frequently
    distinct identifiers that happen to look alike.
    """

    if not threshold or threshold <= 0:
        return False
    if _compact_length(left) <= short_text_chars or _compact_length(right) <= short_text_chars:
        return False
    return signature_similarity(content_signature(left), content_signature(right)) >= threshold


def _compact_length(text: str) -> int:
    return len(re.sub(r"\s+", "", text or ""))


def select_distinct(
    candidates: Sequence[Candidate],
    *,
    limit: int,
    redundancy_threshold: float = 0.8,
    short_text_chars: int = _SHORT_TEXT_CHARS,
) -> list[Candidate]:
    """Keep the best candidates while suppressing near-duplicates.

    ``candidates`` is expected in relevance order. The first occurrence of any
    piece of content is always kept; later near-copies are dropped. Very short
    passages are exempt from suppression because character n-grams are unstable
    at that length and short snippets are frequently the most precise answer.
    """

    if limit < 1:
        return []

    selected: list[Candidate] = []
    selected_signatures: list[frozenset[str]] = []

    for candidate in candidates:
        if len(selected) >= limit:
            break
        text = candidate.text or ""
        compact_length = _compact_length(text)
        signature = content_signature(text) if compact_length > short_text_chars else frozenset()

        if signature and any(
            signature_similarity(signature, kept) >= redundancy_threshold for kept in selected_signatures
        ):
            continue

        selected.append(candidate)
        if signature:
            selected_signatures.append(signature)

    return selected


def prune_pool(
    candidates: Sequence[Candidate],
    *,
    pool_size: int,
    redundancy_threshold: float = 0.8,
    short_text_chars: int = _SHORT_TEXT_CHARS,
) -> list[Candidate]:
    """Reduce a candidate pool before reranking or fusion.

    Keeps the pool diverse enough that later stages see distinct content, while
    retaining relevance order for everything that survives.
    """

    return select_distinct(
        candidates,
        limit=pool_size,
        redundancy_threshold=redundancy_threshold,
        short_text_chars=short_text_chars,
    )


def dedupe_texts(
    texts: Sequence[str],
    *,
    threshold: float = 0.8,
    short_text_chars: int = _SHORT_TEXT_CHARS,
) -> list[str]:
    """Return ``texts`` with near-duplicates removed, preserving order."""

    candidates = [Candidate(position=index, text=text, score=0.0) for index, text in enumerate(texts)]
    return [
        candidate.text
        for candidate in select_distinct(
            candidates,
            limit=len(candidates),
            redundancy_threshold=threshold,
            short_text_chars=short_text_chars,
        )
    ]


__all__ = [
    "Candidate",
    "content_signature",
    "dedupe_texts",
    "is_duplicate",
    "prune_pool",
    "select_distinct",
    "signature_similarity",
]
