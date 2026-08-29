"""Intent classification ports and a fast deterministic fallback."""

from __future__ import annotations

import asyncio
import inspect
import re
from collections.abc import Mapping
from typing import Any, Protocol

from .models import IntentDecision, IntentName, IntentSource


class IntentClassifier(Protocol):
    async def classify(
        self, message: str, *, context: Mapping[str, Any] | None = None
    ) -> IntentDecision: ...


class RuleIntentClassifier:
    """Low-latency Chinese/English heuristic classifier.

    This is deliberately conservative: it provides a useful route while a
    replaceable model classifier is unavailable, without pretending to solve
    domain intent understanding.
    """

    _control = re.compile(r"(?:停止|打断|中断|别说|停一下|取消|stop|cancel|interrupt)", re.I)
    _knowledge = re.compile(r"(?:查|搜索|检索|资料|文档|知识库|记忆|根据|什么是|为什么|如何|how|what|why|search|look\s*up)", re.I)
    _task = re.compile(r"(?:帮我|请你|执行|创建|生成|配置|分析|规划|安排|导出|调用|run|create|generate|configure|analy[sz]e)", re.I)
    _question = re.compile(r"(?:吗|么|呢|？|\?|what|why|how|when|where|who)", re.I)

    async def classify(
        self, message: str, *, context: Mapping[str, Any] | None = None
    ) -> IntentDecision:
        del context
        text = message.strip()
        if self._control.search(text):
            return IntentDecision(
                name=IntentName.CONTROL,
                confidence=0.99,
                source=IntentSource.RULE,
                rationale="命中中断或取消表达",
                requested_capabilities=["interrupt"],
            )
        if self._knowledge.search(text):
            return IntentDecision(
                name=IntentName.KNOWLEDGE,
                confidence=0.86,
                source=IntentSource.RULE,
                rationale="命中资料、记忆或检索表达",
                requested_capabilities=["retrieval"],
            )
        if self._task.search(text):
            return IntentDecision(
                name=IntentName.TASK,
                confidence=0.78,
                source=IntentSource.RULE,
                rationale="命中任务或执行表达",
                requested_capabilities=["task"],
            )
        if self._question.search(text):
            return IntentDecision(
                name=IntentName.CHAT,
                confidence=0.62,
                source=IntentSource.RULE,
                rationale="命中问句表达，暂按对话处理",
            )
        return IntentDecision(
            name=IntentName.UNKNOWN,
            confidence=0.45,
            source=IntentSource.FALLBACK,
            rationale="未命中明确模式，使用最小安全路由",
        )


class CompositeIntentClassifier:
    """Model-first classifier with a bounded fallback path.

    ``primary`` may be an async classifier, a sync callable, or an object with
    ``classify``.  A timeout/error never blocks the first response indefinitely.
    """

    def __init__(
        self,
        primary: IntentClassifier | Any | None = None,
        *,
        fallback: IntentClassifier | None = None,
        timeout_ms: int = 80,
    ) -> None:
        self.primary = primary
        self.fallback = fallback or RuleIntentClassifier()
        self.timeout_seconds = max(timeout_ms, 1) / 1000

    async def classify(
        self, message: str, *, context: Mapping[str, Any] | None = None
    ) -> IntentDecision:
        if self.primary is not None:
            try:
                if hasattr(self.primary, "classify"):
                    try:
                        result = self.primary.classify(message, context=context)
                    except TypeError:
                        result = self.primary.classify(message)
                else:
                    try:
                        result = self.primary(message, context=context)
                    except TypeError:
                        result = self.primary(message)
                if inspect.isawaitable(result):
                    result = await asyncio.wait_for(result, timeout=self.timeout_seconds)
                decision = result if isinstance(result, IntentDecision) else IntentDecision.model_validate(result)
                if decision.source == IntentSource.FALLBACK:
                    decision.source = IntentSource.MODEL
                return decision
            except Exception:
                pass
        fallback = self.fallback.classify(message, context=context)
        if inspect.isawaitable(fallback):
            fallback = await fallback
        return fallback
