"""Chinese-aware tokenization for lexical retrieval.

Lexical recall has to work on mixed Chinese/English technical text, and it has
to keep working when optional NLP dependencies are unavailable. jieba is used
when present because word-level tokens match how Chinese is actually written;
otherwise the tokenizer degrades to a character bigram model, which is a weaker
but still usable signal.

Tokenization is deliberately deterministic and side-effect free: the same text
always yields the same token set, so cached retrieval results stay coherent.
"""

from __future__ import annotations

import contextlib
import re
from collections.abc import Iterable
from functools import lru_cache

# Latin/number runs are kept whole so identifiers like ``bge-small-zh-v1.5``
# stay searchable; CJK is tokenized by the word segmenter below.
_ASCII_RUN = re.compile(r"[A-Za-z0-9_]+(?:[.\-][A-Za-z0-9_]+)*")
_CJK_RUN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]+")

# Very common function words carry no discriminative value in short queries and
# would otherwise inflate lexical overlap between unrelated passages.
_STOP_WORDS = frozenset(
    {
        "的", "了", "是", "在", "和", "与", "或", "及", "对", "为", "从", "到", "把", "被",
        "有", "无", "不", "也", "就", "都", "而", "并", "等", "中", "上", "下", "后", "前",
        "这", "那", "什么", "怎么", "如何", "哪", "哪些", "吗", "呢", "啊", "请", "我", "你",
        "他", "她", "它", "们", "一个", "可以", "需要", "进行", "通过", "使用", "以及",
        "the", "a", "an", "of", "to", "in", "on", "for", "and", "or", "is", "are", "be",
        "with", "by", "at", "as", "it", "this", "that", "how", "what", "which",
    }
)

# Digit-bearing tokens are treated as high-signal: version numbers, clause
# numbers and measurements are usually exactly what a technical query targets.
_HIGH_SIGNAL = re.compile(r"\d")


def _segment_cjk(run: str) -> Iterable[str]:
    """Segment a CJK run into words, falling back to bigrams."""

    segmenter = _jieba_segmenter()
    if segmenter is not None:
        yield from segmenter(run)
        return
    if len(run) == 1:
        yield run
        return
    for index in range(len(run) - 1):
        yield run[index : index + 2]


@lru_cache(maxsize=1)
def _jieba_segmenter():
    """Return a cached jieba tokenizer, or ``None`` when unavailable.

    Importing jieba is comparatively expensive and it ships its own dictionary
    load, so the import is attempted once and cached for the process lifetime.
    """

    try:
        import jieba  # type: ignore[import-not-found]
    except Exception:  # pragma: no cover - exercised only without jieba
        return None

    # Older jieba builds have no setLogLevel; silence is acceptable there.
    with contextlib.suppress(Exception):  # pragma: no cover - older jieba builds
        jieba.setLogLevel(60)

    def segment(text: str) -> list[str]:
        return [token for token in jieba.cut(text, HMM=False) if token.strip()]

    return segment


def normalize_term(term: str) -> str:
    """Normalize a term for matching: case, width and surrounding space."""

    return term.strip().casefold().replace("\u3000", " ")


def tokens(text: str, *, keep_stop_words: bool = False) -> list[str]:
    """Tokenize text into an ordered token list.

    Order is preserved and duplicates are kept so callers that need frequencies
    (BM25) and callers that need presence (overlap) can both use one pass.
    """

    if not text or not text.strip():
        return []

    lowered = normalize_term(text)
    collected: list[str] = []
    for match in _ASCII_RUN.finditer(lowered):
        token = match.group(0)
        if len(token) > 1 or _HIGH_SIGNAL.search(token):
            collected.append(token)
    for match in _CJK_RUN.finditer(lowered):
        collected.extend(_segment_cjk(match.group(0)))

    if keep_stop_words:
        return [token for token in collected if token]

    filtered = [token for token in collected if token not in _STOP_WORDS]
    # If stop-word removal erases a very short query entirely, the query was
    # almost pure function words; return the raw tokens rather than nothing so
    # retrieval still has a signal to work with.
    return filtered or [token for token in collected if token]


def token_set(text: str) -> set[str]:
    """Return the unique token set for a piece of text."""

    return set(tokens(text))


def bigrams(text: str) -> set[str]:
    """Return compacted character bigrams, a segmentation-free fallback signal.

    Character bigrams survive tokenizer mistakes and handle paraphrases that a
    word segmenter would split differently.
    """

    compact = re.sub(r"\s+", "", normalize_term(text))
    if len(compact) < 2:
        return {compact} if compact else set()
    return {compact[index : index + 2] for index in range(len(compact) - 1)}


def overlap_ratio(query_tokens: Iterable[str], text: str) -> float:
    """Fraction of query tokens that also occur in ``text`` (0.0 .. 1.0)."""

    query = {token for token in query_tokens if token}
    if not query:
        return 0.0
    candidates = token_set(text)
    if not candidates:
        return 0.0
    return len(query & candidates) / len(query)


__all__ = [
    "bigrams",
    "normalize_term",
    "overlap_ratio",
    "token_set",
    "tokens",
]
