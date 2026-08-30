"""评测运行的应用服务与有限生命周期存储。"""

from __future__ import annotations

from collections import deque
from datetime import datetime, timezone
import hashlib
import math
import os
import threading
from typing import Iterable

from .dataset import build_default_dataset
from .metrics import _SENSITIVE_LEAK_RE, _SECRET_RE, score_run
from .models import (
    EvaluationCase,
    EvaluationDataset,
    EvaluationDimension,
    EvaluationOverview,
    EvaluationRun,
    EvaluationRunRequest,
    MetricScore,
)


class EvaluationService:
    """可替换为数据库/队列实现的评测服务。

    内存实现只保存最近的有限条运行记录，避免长时间运行的服务无限增长。
    """

    def __init__(
        self,
        *,
        datasets: Iterable[EvaluationDataset] | None = None,
        max_runs: int = 2000,
        input_price_per_1k: float | None = None,
        output_price_per_1k: float | None = None,
        currency: str | None = None,
    ) -> None:
        self._datasets = {item.id: item for item in (datasets or [build_default_dataset()])}
        self._runs: deque[EvaluationRun] = deque(maxlen=max(1, max_runs))
        self._lock = threading.RLock()
        self.input_price_per_1k = _positive_float(input_price_per_1k, "EVAL_INPUT_PRICE_PER_1K", 0.003)
        self.output_price_per_1k = _positive_float(output_price_per_1k, "EVAL_OUTPUT_PRICE_PER_1K", 0.009)
        self.currency = currency or os.getenv("EVAL_CURRENCY", "CNY")

    def datasets(self) -> list[EvaluationDataset]:
        with self._lock:
            return [item.model_copy(deep=True) for item in self._datasets.values()]

    def dataset(self, dataset_id: str) -> EvaluationDataset | None:
        with self._lock:
            item = self._datasets.get(dataset_id)
            return item.model_copy(deep=True) if item else None

    def record(self, request: EvaluationRunRequest, *, owner_id: str) -> EvaluationRun:
        dataset = self._datasets.get(request.dataset_id)
        case = _find_case(dataset, request.case_id)
        scores, input_tokens, output_tokens, cost = score_run(
            request,
            case,
            input_price_per_1k=self.input_price_per_1k,
            output_price_per_1k=self.output_price_per_1k,
            currency=self.currency,
        )
        total_latency = _sum_optional(request.agent_latency_ms, request.digital_human_latency_ms)
        run = EvaluationRun(
            owner_id=_owner_key(owner_id),
            dataset_id=request.dataset_id,
            case_id=request.case_id,
            trace_id=request.trace_id,
            status=request.status,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens,
            cost=cost,
            currency=self.currency,
            agent_latency_ms=request.agent_latency_ms,
            digital_human_latency_ms=request.digital_human_latency_ms,
            first_event_latency_ms=request.first_event_latency_ms,
            first_visible_latency_ms=request.first_visible_latency_ms,
            cancellation_latency_ms=request.cancellation_latency_ms,
            total_latency_ms=total_latency,
            scores=scores,
            input_preview=_preview(request.input_text),
            output_preview=_preview(request.output_text),
        )
        with self._lock:
            self._runs.append(run)
        return run

    def runs(self, *, owner_id: str, limit: int = 50) -> list[EvaluationRun]:
        safe_limit = max(1, min(limit, 200))
        items = self._owner_snapshot(owner_id)
        return items[:safe_limit]

    def get_run(self, run_id: str, *, owner_id: str) -> EvaluationRun | None:
        owner_key = _owner_key(owner_id)
        with self._lock:
            for item in self._runs:
                if item.id == run_id and item.owner_id == owner_key:
                    return item.model_copy(deep=True)
        return None

    def overview(self, *, owner_id: str) -> EvaluationOverview:
        # The HTTP list endpoint is intentionally capped, but aggregate metrics
        # must cover every record still retained by the bounded buffer.
        runs = self._owner_snapshot(owner_id)
        metrics = _aggregate_metrics(runs)
        input_tokens = sum(item.input_tokens for item in runs)
        output_tokens = sum(item.output_tokens for item in runs)
        agent_values = [item.agent_latency_ms for item in runs if item.agent_latency_ms is not None]
        avatar_values = [item.digital_human_latency_ms for item in runs if item.digital_human_latency_ms is not None]
        first_event_values = [item.first_event_latency_ms for item in runs if item.first_event_latency_ms is not None]
        first_visible_values = [item.first_visible_latency_ms for item in runs if item.first_visible_latency_ms is not None]
        cancellation_values = [item.cancellation_latency_ms for item in runs if item.cancellation_latency_ms is not None]
        total_values = [item.total_latency_ms for item in runs if item.total_latency_ms is not None]
        status_counts = {status: sum(1 for item in runs if item.status == status) for status in _STATUSES}
        cancellation_rate = (
            status_counts["interrupted"] / len(runs)
            if runs
            else None
        )
        with self._lock:
            dataset_count = len(self._datasets)
            case_count = sum(item.case_count for item in self._datasets.values())
        return EvaluationOverview(
            dataset_count=dataset_count,
            case_count=case_count,
            total_runs=len(runs),
            total_tokens=input_tokens + output_tokens,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_cost=round(sum(item.cost for item in runs), 8),
            currency=self.currency,
            task_success_rate=_metric_value(metrics, EvaluationDimension.TASK_SUCCESS),
            tool_call_accuracy=_metric_value(metrics, EvaluationDimension.TOOL_CALL_ACCURACY),
            result_correctness=_metric_value(metrics, EvaluationDimension.RESULT_CORRECTNESS),
            result_consistency=_metric_value(metrics, EvaluationDimension.RESULT_CONSISTENCY),
            factual_groundedness=_metric_value(metrics, EvaluationDimension.FACTUAL_GROUNDING),
            prompt_injection_protection=_metric_value(metrics, EvaluationDimension.PROMPT_INJECTION_DEFENSE),
            agent_latency_ms=_average(agent_values),
            digital_human_latency_ms=_average(avatar_values),
            first_event_latency_ms=_average(first_event_values),
            first_visible_latency_ms=_average(first_visible_values),
            cancellation_latency_ms=_average(cancellation_values),
            total_latency_ms=_average(total_values),
            agent_latency_p50_ms=_percentile(agent_values, 0.50),
            agent_latency_p95_ms=_percentile(agent_values, 0.95),
            digital_human_latency_p50_ms=_percentile(avatar_values, 0.50),
            digital_human_latency_p95_ms=_percentile(avatar_values, 0.95),
            first_event_latency_p50_ms=_percentile(first_event_values, 0.50),
            first_event_latency_p95_ms=_percentile(first_event_values, 0.95),
            first_visible_latency_p50_ms=_percentile(first_visible_values, 0.50),
            first_visible_latency_p95_ms=_percentile(first_visible_values, 0.95),
            cancellation_latency_p50_ms=_percentile(cancellation_values, 0.50),
            cancellation_latency_p95_ms=_percentile(cancellation_values, 0.95),
            cancellation_rate=cancellation_rate,
            status_counts=status_counts,
            metrics=metrics,
            updated_at=datetime.now(timezone.utc),
            source="evaluation" if runs else "empty",
        )

    def _owner_snapshot(self, owner_id: str) -> list[EvaluationRun]:
        owner_key = _owner_key(owner_id)
        with self._lock:
            items = [item for item in reversed(self._runs) if item.owner_id == owner_key]
            return [item.model_copy(deep=True) for item in items]


def _find_case(dataset: EvaluationDataset | None, case_id: str | None) -> EvaluationCase | None:
    if dataset is None or not case_id:
        return None
    return next((item for item in dataset.cases if item.id == case_id), None)


def _aggregate_metrics(runs: list[EvaluationRun]) -> dict[EvaluationDimension, MetricScore]:
    result: dict[EvaluationDimension, MetricScore] = {}
    for dimension in EvaluationDimension:
        values = [run.scores[dimension] for run in runs if dimension in run.scores and run.scores[dimension].score is not None]
        if not values:
            continue
        scores = [item.score for item in values if item.score is not None]
        numerator = sum(scores)
        result[dimension] = MetricScore(
            dimension=dimension,
            label=values[0].label,
            score=numerator / len(scores),
            sample_count=len(scores),
            numerator=numerator,
            denominator=len(scores),
            detail=f"基于 {len(scores)} 条样本的宏平均",
        )
    return result


def _metric_value(metrics: dict[EvaluationDimension, MetricScore], dimension: EvaluationDimension) -> float | None:
    metric = metrics.get(dimension)
    return metric.score if metric else None


def _average(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 2) if values else None


def _percentile(values: list[float], quantile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, math.ceil(quantile * len(ordered)) - 1))
    return round(ordered[index], 2)


def _sum_optional(left: float | None, right: float | None) -> float | None:
    if left is None and right is None:
        return None
    return round((left or 0) + (right or 0), 2)


def _preview(value: str, limit: int = 240) -> str:
    compact = " ".join(value.strip().split())
    compact = _SECRET_RE.sub("[REDACTED]", compact)
    compact = _SENSITIVE_LEAK_RE.sub("[REDACTED]", compact)
    return compact[:limit] + ("..." if len(compact) > limit else "")


_STATUSES = ("success", "failed", "error", "blocked", "interrupted")


def _positive_float(value: float | None, env_name: str, default: float) -> float:
    if value is not None and math.isfinite(value) and value >= 0:
        return value
    try:
        parsed = float(os.getenv(env_name, str(default)))
    except (TypeError, ValueError):
        parsed = default
    return parsed if math.isfinite(parsed) and parsed >= 0 else default


def _owner_key(owner_id: str) -> str:
    """Keep tenant keys bounded without making long IDs collide by prefix."""

    value = str(owner_id)
    if len(value) <= 128:
        return value
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:31]
    return f"{value[:96]}:{digest}"
