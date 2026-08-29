"""与数字人 Agent 链路绑定的自建评测集。"""

from __future__ import annotations

from .cases import build_cases
from .models import EvaluationDataset, EvaluationDimension


def build_default_dataset() -> EvaluationDataset:
    cases = build_cases()
    dimensions = list(EvaluationDimension)
    return EvaluationDataset(
        id="ican-agent-core",
        version="2026.08.29",
        name="ICAN 数字人 Agent 核心评测集",
        description="覆盖会话、意图识别、Docling/RAG、MCP 路由、并发、中断恢复、Provider 降级、Trace、成本、延迟预算和提示词注入防护的项目自建基线。",
        dimensions=dimensions,
        cases=cases,
    )
