"""评测模块的稳定数据契约。

评测输入允许携带人工标注或离线裁判结果，但默认评分始终是确定性的，
方便在没有额外模型的环境中复现问题。
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class EvaluationDimension(StrEnum):
    TOKEN_USAGE = "token_usage"
    COST = "cost"
    TASK_SUCCESS = "task_success"
    TOOL_CALL_ACCURACY = "tool_call_accuracy"
    RESULT_CORRECTNESS = "result_correctness"
    RESULT_CONSISTENCY = "result_consistency"
    FACTUAL_GROUNDING = "factual_grounding"
    PROMPT_INJECTION_DEFENSE = "prompt_injection_defense"
    FIRST_EVENT_LATENCY = "first_event_latency"
    FIRST_VISIBLE_LATENCY = "first_visible_latency"
    CANCELLATION_LATENCY = "cancellation_latency"
    AGENT_LATENCY = "agent_latency"
    DIGITAL_HUMAN_LATENCY = "digital_human_latency"


class EvaluationCase(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    id: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=200)
    category: str = Field(min_length=1, max_length=64)
    intent: str = Field(min_length=1, max_length=64)
    prompt: str = Field(min_length=1, max_length=4000)
    expected_tools: list[str] = Field(default_factory=list)
    expected_keywords: list[str] = Field(default_factory=list)
    expected_evidence: list[str] = Field(default_factory=list)
    injection_attempt: bool = False
    expected_blocked: bool = False
    difficulty: Literal["basic", "intermediate", "complex"] = "basic"
    tags: list[str] = Field(default_factory=list)


class EvaluationDataset(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    id: str = Field(min_length=1, max_length=128)
    version: str = Field(min_length=1, max_length=32)
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=1000)
    source: Literal["project_builtin", "uploaded", "generated"] = "project_builtin"
    dimensions: list[EvaluationDimension] = Field(default_factory=list)
    cases: list[EvaluationCase] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)

    @property
    def case_count(self) -> int:
        return len(self.cases)


class EvaluationRunRequest(BaseModel):
    """提交一次可复现的评测样本。

    ``input_text``/``output_text`` 在入库时会做长度限制和凭据脱敏。
    生产环境可以由离线 runner 批量提交，也可以由实时 Agent 运行器调用。
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    dataset_id: str = Field(default="ican-agent-core", max_length=128)
    case_id: str | None = Field(default=None, max_length=128)
    trace_id: str | None = Field(default=None, max_length=128)
    input_text: str = Field(min_length=1, max_length=4000)
    output_text: str = Field(default="", max_length=8000)
    status: Literal["success", "failed", "error", "blocked", "interrupted"] = "success"
    task_success: bool | None = None
    expected_tools: list[str] | None = None
    actual_tools: list[str] = Field(default_factory=list)
    expected_keywords: list[str] | None = None
    expected_evidence: list[str] | None = None
    evidence: list[str] = Field(default_factory=list)
    injection_attempt: bool | None = None
    injection_blocked: bool | None = None
    comparison_outputs: list[str] = Field(default_factory=list)
    input_tokens: int | None = Field(default=None, ge=0, le=10_000_000)
    output_tokens: int | None = Field(default=None, ge=0, le=10_000_000)
    agent_latency_ms: float | None = Field(default=None, ge=0, le=86_400_000)
    digital_human_latency_ms: float | None = Field(default=None, ge=0, le=86_400_000)
    first_event_latency_ms: float | None = Field(default=None, ge=0, le=86_400_000)
    first_visible_latency_ms: float | None = Field(default=None, ge=0, le=86_400_000)
    cancellation_latency_ms: float | None = Field(default=None, ge=0, le=86_400_000)
    metadata: dict[str, Any] = Field(default_factory=dict)


class MetricScore(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    dimension: EvaluationDimension
    label: str
    score: float | None = Field(default=None, ge=0, le=1)
    sample_count: int = Field(default=0, ge=0)
    numerator: float | None = Field(default=None, ge=0)
    denominator: float | None = Field(default=None, ge=0)
    detail: str = ""


class EvaluationRun(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    id: str = Field(default_factory=lambda: uuid4().hex)
    owner_id: str = Field(min_length=1, max_length=128)
    dataset_id: str
    case_id: str | None = None
    trace_id: str | None = None
    status: Literal["success", "failed", "error", "blocked", "interrupted"]
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    total_tokens: int = Field(ge=0)
    cost: float = Field(ge=0)
    currency: str = "CNY"
    agent_latency_ms: float | None = Field(default=None, ge=0)
    digital_human_latency_ms: float | None = Field(default=None, ge=0)
    first_event_latency_ms: float | None = Field(default=None, ge=0)
    first_visible_latency_ms: float | None = Field(default=None, ge=0)
    cancellation_latency_ms: float | None = Field(default=None, ge=0)
    total_latency_ms: float | None = Field(default=None, ge=0)
    scores: dict[EvaluationDimension, MetricScore] = Field(default_factory=dict)
    input_preview: str = ""
    output_preview: str = ""
    created_at: datetime = Field(default_factory=utc_now)


class EvaluationOverview(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    dataset_count: int = Field(default=0, ge=0)
    case_count: int = Field(default=0, ge=0)
    total_runs: int = Field(default=0, ge=0)
    total_tokens: int = Field(default=0, ge=0)
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    total_cost: float = Field(default=0, ge=0)
    currency: str = "CNY"
    task_success_rate: float | None = Field(default=None, ge=0, le=1)
    tool_call_accuracy: float | None = Field(default=None, ge=0, le=1)
    result_correctness: float | None = Field(default=None, ge=0, le=1)
    result_consistency: float | None = Field(default=None, ge=0, le=1)
    factual_groundedness: float | None = Field(default=None, ge=0, le=1)
    prompt_injection_protection: float | None = Field(default=None, ge=0, le=1)
    agent_latency_ms: float | None = Field(default=None, ge=0)
    digital_human_latency_ms: float | None = Field(default=None, ge=0)
    first_event_latency_ms: float | None = Field(default=None, ge=0)
    first_visible_latency_ms: float | None = Field(default=None, ge=0)
    cancellation_latency_ms: float | None = Field(default=None, ge=0)
    total_latency_ms: float | None = Field(default=None, ge=0)
    agent_latency_p50_ms: float | None = Field(default=None, ge=0)
    agent_latency_p95_ms: float | None = Field(default=None, ge=0)
    digital_human_latency_p50_ms: float | None = Field(default=None, ge=0)
    digital_human_latency_p95_ms: float | None = Field(default=None, ge=0)
    first_event_latency_p50_ms: float | None = Field(default=None, ge=0)
    first_event_latency_p95_ms: float | None = Field(default=None, ge=0)
    first_visible_latency_p50_ms: float | None = Field(default=None, ge=0)
    first_visible_latency_p95_ms: float | None = Field(default=None, ge=0)
    cancellation_latency_p50_ms: float | None = Field(default=None, ge=0)
    cancellation_latency_p95_ms: float | None = Field(default=None, ge=0)
    cancellation_rate: float | None = Field(default=None, ge=0, le=1)
    status_counts: dict[str, int] = Field(default_factory=dict)
    metrics: dict[EvaluationDimension, MetricScore] = Field(default_factory=dict)
    updated_at: datetime = Field(default_factory=utc_now)
    source: Literal["evaluation", "empty"] = "evaluation"
