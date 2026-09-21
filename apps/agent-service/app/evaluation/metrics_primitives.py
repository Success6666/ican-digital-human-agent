"""评测基础指标与通用文本计算辅助。"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable
from statistics import mean

from .models import EvaluationDimension, MetricScore

_TOKEN_RE = re.compile(r"[\w\u4e00-\u9fff]+", re.UNICODE)


def estimate_tokens(text: str) -> int:
    """对未提供 usage 的样本做保守估算；真实模型 usage 优先。"""

    if not text:
        return 0
    return max(1, math.ceil(len(text) / 4))


def binary_score(dimension: EvaluationDimension, label: str, value: bool) -> MetricScore:
    score = 1.0 if value else 0.0
    return MetricScore(dimension=dimension, label=label, score=score, sample_count=1, numerator=score, denominator=1)


def measurement_score(
    dimension: EvaluationDimension,
    label: str,
    value: float | None,
) -> MetricScore:
    """保留原始测量值；延迟不是 0~1 比例，不能伪造归一化分数。"""

    if value is None:
        return MetricScore(
            dimension=dimension,
            label=label,
            score=None,
            sample_count=0,
            detail="未提供测量值",
        )
    return MetricScore(
        dimension=dimension,
        label=label,
        score=None,
        sample_count=1,
        numerator=round(value, 2),
        detail=f"{value:.2f} ms",
    )


def tool_score(expected: Iterable[str], actual: Iterable[str]) -> MetricScore:
    expected_set, actual_set = set(expected), set(actual)
    if not expected_set and not actual_set:
        score = 1.0
        detail = "本样本不要求工具调用"
    elif not expected_set and actual_set:
        return MetricScore(
            dimension=EvaluationDimension.TOOL_CALL_ACCURACY,
            label="工具调用准确率",
            score=None,
            sample_count=0,
            detail="未提供期望工具标注",
        )
    elif not expected_set or not actual_set:
        score = 0.0
        detail = "期望工具与实际工具不一致"
    else:
        intersection = len(expected_set & actual_set)
        precision = intersection / len(actual_set)
        recall = intersection / len(expected_set)
        score = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        detail = f"precision {precision:.2f}，recall {recall:.2f}"
    return MetricScore(
        dimension=EvaluationDimension.TOOL_CALL_ACCURACY,
        label="工具调用准确率",
        score=score,
        sample_count=1,
        numerator=score,
        denominator=1,
        detail=detail,
    )


def keyword_score(
    dimension: EvaluationDimension,
    label: str,
    output: str,
    expected: Iterable[str],
) -> MetricScore:
    terms = [term.casefold() for term in expected if term.strip()]
    if not terms:
        return MetricScore(dimension=dimension, label=label, score=None, sample_count=0, detail="未提供人工校验关键词")
    text = output.casefold()
    matched = sum(1 for term in terms if term in text)
    score = matched / len(terms)
    return MetricScore(
        dimension=dimension,
        label=label,
        score=score,
        sample_count=1,
        numerator=matched,
        denominator=len(terms),
        detail=f"命中 {matched}/{len(terms)} 个关键词",
    )


def consistency_score(output: str, comparisons: Iterable[str]) -> MetricScore:
    values = [item for item in comparisons if item.strip()]
    if not values:
        return MetricScore(
            dimension=EvaluationDimension.RESULT_CONSISTENCY,
            label="结果一致性",
            score=None,
            sample_count=0,
            detail="需要同题重复运行样本",
        )
    base = tokens(output)
    scores = [jaccard(base, tokens(item)) for item in values]
    score = mean(scores) if scores else None
    return MetricScore(
        dimension=EvaluationDimension.RESULT_CONSISTENCY,
        label="结果一致性",
        score=score,
        sample_count=len(scores),
        numerator=sum(scores),
        denominator=len(scores),
        detail=f"比较 {len(scores)} 次重复回答",
    )


def tokens(text: str) -> set[str]:
    """按中英文词元提取集合，用于可解释的一致性近似。"""

    return {item.casefold() for item in _TOKEN_RE.findall(text) if item}


def jaccard(left: set[str], right: set[str]) -> float:
    if not left and not right:
        return 1.0
    union = left | right
    return len(left & right) / len(union) if union else 0.0


__all__ = [
    "_TOKEN_RE",
    "binary_score",
    "consistency_score",
    "estimate_tokens",
    "jaccard",
    "keyword_score",
    "measurement_score",
    "tokens",
    "tool_score",
]
