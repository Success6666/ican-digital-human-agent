"""Perceived-latency policies for responsive streaming conversations."""

from __future__ import annotations

from typing import Protocol

from .models import FillerPhase, FillerPlan, IntentDecision, IntentName
from .performance import PerformancePlanner


class FillerPolicy(Protocol):
    def plan(self, decision: IntentDecision, *, message: str = "") -> FillerPlan: ...


class AdaptiveFillerPolicy:
    """Create a short, interruptible acknowledgement before slow work."""

    _copy = {
        IntentName.CHAT: ("我听到了，马上回应。", 80),
        IntentName.KNOWLEDGE: ("我先查一下相关资料。", 180),
        IntentName.TASK: ("我先确认执行步骤。", 160),
        # The stream already reaches the user quickly; do not insert a
        # speculative sentence before intent classification.
        IntentName.UNKNOWN: ("", 0),
        IntentName.CONTROL: ("好的，我先停下来。", 0),
    }

    def __init__(self, *, planner: PerformancePlanner | None = None) -> None:
        self.planner = planner or PerformancePlanner()

    def plan(self, decision: IntentDecision, *, message: str = "") -> FillerPlan:
        del message
        text, expected_delay = self._copy[decision.name]
        phase = FillerPhase.ACKNOWLEDGE if decision.name == IntentName.CONTROL else FillerPhase.THINKING
        return FillerPlan(
            should_emit=decision.name != IntentName.CONTROL and bool(text),
            text=text,
            phase=phase,
            expected_delay_ms=expected_delay,
            cue=self.planner.for_phase(phase),
        )
