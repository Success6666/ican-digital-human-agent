"""Offline retrieval metrics for comparing tuning configurations.

Changing a retrieval knob is only defensible if the change can be measured. The
metrics here are the ones that separate *ranking* quality from *recall* quality,
because those two failure modes call for opposite fixes:

* Recall@k answers "is the answer reachable at all", which is a pool-depth and
  route-coverage question.
* MRR and nDCG answer "is the answer ranked early", which is a fusion and
  scoring question.
* Precision@k answers "how much of the context window is useful", which is a
  selection and suppression question.

Reporting only one of them invites the classic mistake of raising ``top_k`` to
paper over a ranking defect. They are therefore computed together.

Comparisons between two configurations use a paired test, since both see the
same queries and only the configuration differs. A paired bootstrap is used
rather than a t-test because metric distributions are bounded and clearly
non-normal at the sample sizes a retrieval eval typically has.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
import math
import random
from typing import Any

DEFAULT_BOOTSTRAP_SAMPLES = 2000
DEFAULT_CONFIDENCE = 0.95


@dataclass(frozen=True)
class RetrievalCase:
    """One judged query: a query and the passages that answer it.

    ``relevant`` holds stable passage identifiers; ``retrieved`` is the ranked
    list of identifiers a configuration returned. Identifiers are opaque strings
    so the caller can use chunk ids, positions or document ids as convenient.
    """

    query: str
    relevant: frozenset[str]
    retrieved: tuple[str, ...] = ()

    def with_retrieved(self, retrieved: Sequence[str]) -> "RetrievalCase":
        return RetrievalCase(query=self.query, relevant=self.relevant, retrieved=tuple(retrieved))


def recall_at_k(case: RetrievalCase, k: int) -> float:
    """Share of the judged relevant passages that appear in the top ``k``."""

    if not case.relevant or k < 1:
        return 0.0
    return len(set(case.retrieved[:k]) & case.relevant) / len(case.relevant)


def precision_at_k(case: RetrievalCase, k: int) -> float:
    """Share of the top ``k`` slots occupied by relevant passages.

    The denominator is the number of *returned* passages when fewer than ``k``
    came back, so a short result list is not rewarded for being short.
    """

    if k < 1:
        return 0.0
    window = case.retrieved[:k]
    if not window:
        return 0.0
    return len(set(window) & case.relevant) / len(window)


def reciprocal_rank(case: RetrievalCase) -> float:
    """Reciprocal of the rank of the first relevant passage (0.0 if absent)."""

    for index, identifier in enumerate(case.retrieved, start=1):
        if identifier in case.relevant:
            return 1.0 / index
    return 0.0


def average_precision(case: RetrievalCase) -> float:
    """Mean of the precision values at each relevant position."""

    if not case.relevant:
        return 0.0
    hits = 0
    total = 0.0
    for index, identifier in enumerate(case.retrieved, start=1):
        if identifier in case.relevant:
            hits += 1
            total += hits / index
    return total / len(case.relevant)


def dcg(gains: Sequence[float]) -> float:
    """Discounted cumulative gain with the ``log2(rank + 1)`` discount."""

    return sum(gain / math.log2(index + 1) for index, gain in enumerate(gains, start=1))


def ndcg_at_k(case: RetrievalCase, k: int) -> float:
    """Normalized DCG over binary relevance, normalized by the ideal ranking."""

    if k < 1 or not case.relevant:
        return 0.0
    gains = [1.0 if identifier in case.relevant else 0.0 for identifier in case.retrieved[:k]]
    ideal = [1.0] * min(k, len(case.relevant))
    ideal_dcg = dcg(ideal)
    return dcg(gains) / ideal_dcg if ideal_dcg else 0.0


def hit_rate_at_k(case: RetrievalCase, k: int) -> float:
    """Whether at least one relevant passage appears in the top ``k``."""

    return 1.0 if set(case.retrieved[:k]) & case.relevant else 0.0


@dataclass
class MetricSummary:
    """Aggregate of one metric across cases, with an uncertainty interval."""

    name: str
    mean: float
    sample_count: int
    lower: float | None = None
    upper: float | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "mean": round(self.mean, 6),
            "sample_count": self.sample_count,
            "lower": round(self.lower, 6) if self.lower is not None else None,
            "upper": round(self.upper, 6) if self.upper is not None else None,
        }


@dataclass
class EvaluationReport:
    """Per-metric summary plus a few diagnostic counts for one configuration."""

    metrics: dict[str, MetricSummary] = field(default_factory=dict)
    case_count: int = 0
    empty_result_cases: int = 0
    misses: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "case_count": self.case_count,
            "empty_result_cases": self.empty_result_cases,
            "misses": self.misses,
            "metrics": {name: summary.as_dict() for name, summary in self.metrics.items()},
        }


def _mean_with_interval(values: Sequence[float]) -> tuple[float, float | None, float | None]:
    if not values:
        return 0.0, None, None
    average = sum(values) / len(values)
    if len(values) < 2:
        return average, average, average
    variance = sum((value - average) ** 2 for value in values) / (len(values) - 1)
    standard_error = math.sqrt(variance / len(values))
    margin = 1.96 * standard_error
    return average, max(0.0, average - margin), min(1.0, average + margin)


def evaluate_retrieval(
    cases: Sequence[RetrievalCase],
    *,
    k_values: Sequence[int] = (1, 3, 5, 10),
) -> EvaluationReport:
    """Summarize a configuration across judged queries."""

    report = EvaluationReport(case_count=len(cases))
    if not cases:
        return report

    collectors: dict[str, list[float]] = {}
    for k in k_values:
        collectors[f"recall@{k}"] = []
        collectors[f"precision@{k}"] = []
        collectors[f"ndcg@{k}"] = []
        collectors[f"hit_rate@{k}"] = []
    collectors["mrr"] = []
    collectors["map"] = []

    for case in cases:
        if not case.retrieved:
            report.empty_result_cases += 1
        for k in k_values:
            collectors[f"recall@{k}"].append(recall_at_k(case, k))
            collectors[f"precision@{k}"].append(precision_at_k(case, k))
            collectors[f"ndcg@{k}"].append(ndcg_at_k(case, k))
            collectors[f"hit_rate@{k}"].append(hit_rate_at_k(case, k))
        collectors["mrr"].append(reciprocal_rank(case))
        collectors["map"].append(average_precision(case))
        if not any(identifier in case.relevant for identifier in case.retrieved):
            report.misses.append(case.query)

    for name, values in collectors.items():
        average, lower, upper = _mean_with_interval(values)
        report.metrics[name] = MetricSummary(
            name=name,
            mean=average,
            sample_count=len(values),
            lower=lower,
            upper=upper,
        )
    return report


def paired_bootstrap(
    baseline: Sequence[float],
    candidate: Sequence[float],
    *,
    samples: int = DEFAULT_BOOTSTRAP_SAMPLES,
    confidence: float = DEFAULT_CONFIDENCE,
    seed: int = 20260920,
) -> dict[str, Any]:
    """Paired bootstrap over per-query metric deltas.

    Both sequences must be aligned by query. Resampling queries (not scores)
    preserves the pairing, which is what makes the test sensitive: query
    difficulty cancels out and only the configuration effect remains.
    """

    if len(baseline) != len(candidate):
        raise ValueError("paired bootstrap requires equally sized samples")
    if not baseline:
        return {
            "mean_delta": 0.0,
            "lower": None,
            "upper": None,
            "confidence": confidence,
            "samples": 0,
            "wins": 0,
            "losses": 0,
            "ties": 0,
            "significant": False,
        }

    deltas = [candidate[index] - baseline[index] for index in range(len(baseline))]
    observed = sum(deltas) / len(deltas)
    rng = random.Random(seed)
    count = len(deltas)
    resampled: list[float] = []
    for _ in range(max(1, samples)):
        total = 0.0
        for _ in range(count):
            total += deltas[rng.randrange(count)]
        resampled.append(total / count)
    resampled.sort()
    alpha = max(0.0, min(1.0, (1.0 - confidence) / 2.0))
    lower_index = min(len(resampled) - 1, max(0, int(alpha * len(resampled))))
    upper_index = min(len(resampled) - 1, max(0, int((1.0 - alpha) * len(resampled)) - 1))
    lower = resampled[lower_index]
    upper = resampled[upper_index]

    wins = sum(1 for delta in deltas if delta > 1e-12)
    losses = sum(1 for delta in deltas if delta < -1e-12)
    # A change is only reported as significant when the interval excludes zero.
    # Direction is withheld deliberately: a regression is as reportable as a
    # gain, and the caller decides which one it has.
    significant = (lower > 0.0) or (upper < 0.0)
    return {
        "mean_delta": observed,
        "lower": lower,
        "upper": upper,
        "confidence": confidence,
        "samples": len(resampled),
        "wins": wins,
        "losses": losses,
        "ties": count - wins - losses,
        "significant": significant,
    }


def compare_configurations(
    baseline: Sequence[RetrievalCase],
    candidate: Sequence[RetrievalCase],
    *,
    metric: str = "mrr",
    k_values: Sequence[int] = (1, 3, 5, 10),
) -> dict[str, Any]:
    """Compare two configurations on one metric using per-query values."""

    if len(baseline) != len(candidate):
        raise ValueError("comparison requires equally sized case lists")
    baseline_values = [_metric_value(case, metric, k_values) for case in baseline]
    candidate_values = [_metric_value(case, metric, k_values) for case in candidate]
    result = paired_bootstrap(baseline_values, candidate_values)
    result["metric"] = metric
    result["baseline_mean"] = sum(baseline_values) / len(baseline_values) if baseline_values else 0.0
    result["candidate_mean"] = sum(candidate_values) / len(candidate_values) if candidate_values else 0.0
    return result


def _metric_value(case: RetrievalCase, metric: str, k_values: Sequence[int]) -> float:
    if metric == "mrr":
        return reciprocal_rank(case)
    if metric == "map":
        return average_precision(case)
    name, _, raw_k = metric.partition("@")
    k = int(raw_k) if raw_k.isdigit() else max(k_values)
    if name == "recall":
        return recall_at_k(case, k)
    if name == "precision":
        return precision_at_k(case, k)
    if name == "ndcg":
        return ndcg_at_k(case, k)
    if name in {"hit_rate", "hit"}:
        return hit_rate_at_k(case, k)
    raise ValueError(f"unknown metric: {metric}")


__all__ = [
    "DEFAULT_BOOTSTRAP_SAMPLES",
    "DEFAULT_CONFIDENCE",
    "EvaluationReport",
    "MetricSummary",
    "RetrievalCase",
    "average_precision",
    "compare_configurations",
    "dcg",
    "evaluate_retrieval",
    "hit_rate_at_k",
    "ndcg_at_k",
    "paired_bootstrap",
    "precision_at_k",
    "recall_at_k",
    "reciprocal_rank",
]
