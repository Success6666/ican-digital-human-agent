"""MCP tool metadata, progressive disclosure and category routing."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol

from .models import IntentDecision, IntentName, ToolCategory, ToolRoutePlan, ToolSpec


class ToolRouter(Protocol):
    def route(self, decision: IntentDecision, *, message: str = "") -> ToolRoutePlan: ...


class ToolCatalog:
    """In-memory catalog replaceable by an MCP registry later."""

    def __init__(self, specs: Iterable[ToolSpec] | None = None) -> None:
        self._specs: dict[str, ToolSpec] = {}
        for spec in specs or _default_specs():
            self.register(spec)

    def register(self, spec: ToolSpec) -> None:
        self._specs[spec.name] = spec

    def get(self, name: str) -> ToolSpec | None:
        return self._specs.get(name)

    def all(self) -> list[ToolSpec]:
        return list(self._specs.values())

    def by_category(self, category: ToolCategory) -> list[ToolSpec]:
        return [spec for spec in self._specs.values() if spec.category == category and spec.enabled]


class ProgressiveToolRouter:
    """Expose a small summary first, then select only relevant tools.

    Core tools remain available for continuity checks.  Intent-specific tools
    are selected by category; disabled/unregistered capabilities are disclosed
    only as future capacity and are never invoked.
    """

    _intent_categories = {
        IntentName.CHAT: ToolCategory.COMMUNICATION,
        IntentName.KNOWLEDGE: ToolCategory.RETRIEVAL,
        IntentName.TASK: ToolCategory.TASK,
        IntentName.CONTROL: None,
        IntentName.UNKNOWN: ToolCategory.COMMUNICATION,
    }

    def __init__(self, catalog: ToolCatalog | None = None) -> None:
        self.catalog = catalog or ToolCatalog()

    def route(self, decision: IntentDecision, *, message: str = "") -> ToolRoutePlan:
        del message
        category = self._intent_categories[decision.name]
        core = [spec for spec in self.catalog.all() if spec.enabled and spec.always_available]
        specific = self.catalog.by_category(category) if category is not None else []
        disclosed = _unique_specs([*core, *specific])
        selected = [spec.name for spec in disclosed if spec.enabled]
        if decision.is_control:
            selected = []
        level = "expanded" if decision.confidence >= 0.75 else "summary"
        rationale = "先展示核心能力，再按意图开放对应分类"
        if decision.is_control:
            rationale = "控制意图由会话中断通道处理，不调用业务工具"
        return ToolRoutePlan(
            intent=decision.name,
            confidence=decision.confidence,
            disclosure_level=level,
            category=category,
            disclosed_tools=disclosed,
            selected_tools=selected,
            rationale=rationale,
        )


def _default_specs() -> list[ToolSpec]:
    return [
        ToolSpec(
            name="system_status",
            label="运行状态",
            category=ToolCategory.CORE,
            description="检查数字人运行链路是否正常",
            always_available=True,
        ),
        ToolSpec(
            name="echo",
            label="确认收到",
            category=ToolCategory.COMMUNICATION,
            description="确认已经理解本轮输入，不执行外部操作",
            keywords=["确认", "收到", "hello"],
        ),
        ToolSpec(
            name="memory_search",
            label="记忆检索",
            category=ToolCategory.RETRIEVAL,
            description="从授权的 RAG 记忆中查找相关内容",
            enabled=False,
        ),
        ToolSpec(
            name="task_runner",
            label="任务执行",
            category=ToolCategory.TASK,
            description="执行经过授权和确认的任务",
            enabled=False,
            requires_confirmation=True,
        ),
    ]


def _unique_specs(specs: Iterable[ToolSpec]) -> list[ToolSpec]:
    result: list[ToolSpec] = []
    seen: set[str] = set()
    for spec in specs:
        if spec.name not in seen:
            seen.add(spec.name)
            result.append(spec)
    return result
