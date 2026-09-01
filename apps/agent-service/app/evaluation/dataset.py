"""与数字人 Agent 链路绑定的自建评测集。"""

from __future__ import annotations

from .cases import build_cases
from .models import EvaluationDataset, EvaluationDimension


def build_default_dataset() -> EvaluationDataset:
    cases = build_cases()
    dimensions = list(EvaluationDimension)
    return EvaluationDataset(
        id="ican-agent-core",
        version="2026.09.01.1",
        name="ICAN 数字人 Agent 核心评测集",
        description="覆盖安全、质量、RAG、工具治理、实时音频、可靠性、性能、租户隔离、个性化、缓存、用户体验、可观测性和成本的项目自建基线。",
        dimensions=dimensions,
        cases=cases,
    )
