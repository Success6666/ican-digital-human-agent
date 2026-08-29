"""评测中心的内部 HTTP 接口。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from ..api.dependencies import InternalContext
from .models import EvaluationDimension, EvaluationRun, EvaluationRunRequest
from .service import EvaluationService


def build_router(service: EvaluationService, *, prefix: str = "/internal/evaluation") -> APIRouter:
    api = APIRouter(prefix=prefix, tags=["evaluation"])

    @api.get("/overview")
    async def overview(context: InternalContext) -> dict[str, Any]:
        return service.overview(owner_id=context["user_id"]).model_dump(mode="json")

    @api.get("/datasets")
    async def datasets(context: InternalContext) -> dict[str, Any]:
        del context
        items = []
        for dataset in service.datasets():
            items.append(
                {
                    "id": dataset.id,
                    "version": dataset.version,
                    "name": dataset.name,
                    "description": dataset.description,
                    "source": dataset.source,
                    "status": "ready",
                    "case_count": dataset.case_count,
                    "sample_count": dataset.case_count,
                    "updated_at": dataset.created_at,
                    "dimensions": [dimension.value for dimension in dataset.dimensions],
                    "cases": [
                        {
                            "id": case.id,
                            "name": case.name,
                            "category": case.category,
                            "intent": case.intent,
                            "difficulty": case.difficulty,
                            "tags": case.tags,
                            "injection_attempt": case.injection_attempt,
                        }
                        for case in dataset.cases
                    ],
                    "created_at": dataset.created_at,
                }
            )
        return {"datasets": items}

    @api.post("/runs", status_code=201)
    async def record_run(payload: EvaluationRunRequest, context: InternalContext):
        return _public_run(service.record(payload, owner_id=context["user_id"]))

    @api.get("/runs")
    async def runs(
        context: InternalContext,
        limit: int = Query(default=50, ge=1, le=200),
    ) -> dict[str, Any]:
        return {"runs": [_public_run(item) for item in service.runs(owner_id=context["user_id"], limit=limit)]}

    @api.get("/runs/{run_id}")
    async def run_detail(run_id: str, context: InternalContext):
        if not _valid_id(run_id):
            raise HTTPException(status_code=422, detail="invalid run id")
        item = service.get_run(run_id, owner_id=context["user_id"])
        if item is None:
            raise HTTPException(status_code=404, detail="evaluation run not found")
        return _public_run(item)

    return api


def _valid_id(value: str) -> bool:
    return 1 <= len(value) <= 128 and all(char.isalnum() or char in "-_" for char in value)


def _public_run(run: EvaluationRun) -> dict[str, Any]:
    """只返回评测所需的可读字段，不暴露 owner_id 等内部隔离字段。"""

    success = run.scores.get(EvaluationDimension.TASK_SUCCESS)
    return {
        "id": run.id,
        "dataset_id": run.dataset_id,
        "case_id": run.case_id,
        "trace_id": run.trace_id,
        "status": run.status,
        "success_rate": success.score if success else None,
        "input_tokens": run.input_tokens,
        "output_tokens": run.output_tokens,
        "total_tokens": run.total_tokens,
        "cost": run.cost,
        "currency": run.currency,
        "agent_latency_ms": run.agent_latency_ms,
        "digital_human_latency_ms": run.digital_human_latency_ms,
        "duration_ms": run.total_latency_ms,
        "scores": {dimension.value: score.model_dump(mode="json") for dimension, score in run.scores.items()},
        "input_preview": run.input_preview,
        "output_preview": run.output_preview,
        "created_at": run.created_at,
    }


__all__ = ["build_router"]
