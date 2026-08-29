"""Small, stable contracts for intent, tool routing and avatar performance."""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class IntentName(StrEnum):
    """Coarse intent groups used for routing, not business-specific skills."""

    CHAT = "chat"
    KNOWLEDGE = "knowledge"
    TASK = "task"
    CONTROL = "control"
    UNKNOWN = "unknown"


class IntentSource(StrEnum):
    RULE = "rule"
    MODEL = "model"
    FALLBACK = "fallback"


class IntentDecision(BaseModel):
    """An intentionally provider-neutral intent result.

    ``entities`` and ``requested_capabilities`` are extension points for a
    future model classifier.  The deterministic classifier only fills the
    fields it can justify.
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    name: IntentName
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    source: IntentSource = IntentSource.FALLBACK
    rationale: str = ""
    entities: dict[str, Any] = Field(default_factory=dict)
    requested_capabilities: list[str] = Field(default_factory=list)

    @property
    def requires_retrieval(self) -> bool:
        return self.name == IntentName.KNOWLEDGE

    @property
    def is_control(self) -> bool:
        return self.name == IntentName.CONTROL


class ToolCategory(StrEnum):
    CORE = "core"
    COMMUNICATION = "communication"
    RETRIEVAL = "retrieval"
    TASK = "task"
    SYSTEM = "system"


class ToolSpec(BaseModel):
    """Human-readable MCP tool metadata.

    The full JSON schema is deliberately not part of this contract.  The
    router can disclose a summary first and request a detailed schema later.
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    name: str = Field(min_length=1, max_length=128)
    label: str = Field(min_length=1, max_length=128)
    category: ToolCategory
    description: str = Field(default="", max_length=500)
    keywords: list[str] = Field(default_factory=list)
    enabled: bool = True
    always_available: bool = False
    requires_confirmation: bool = False


class ToolRoutePlan(BaseModel):
    """Result of progressive disclosure and category routing."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    intent: IntentName
    confidence: float = Field(ge=0.0, le=1.0)
    disclosure_level: Literal["summary", "expanded"] = "summary"
    category: ToolCategory | None = None
    disclosed_tools: list[ToolSpec] = Field(default_factory=list)
    selected_tools: list[str] = Field(default_factory=list)
    rationale: str = ""


class FillerPhase(StrEnum):
    ACKNOWLEDGE = "acknowledge"
    THINKING = "thinking"
    SPEAKING = "speaking"
    COMPLETE = "complete"
    INTERRUPTED = "interrupted"


class ExpressionName(StrEnum):
    LISTENING = "listening"
    THINKING = "thinking"
    SPEAKING = "speaking"
    ACKNOWLEDGING = "acknowledging"
    RELIEVED = "relieved"
    INTERRUPTED = "interrupted"
    NEUTRAL = "neutral"


class PerformanceCue(BaseModel):
    """Vendor-neutral micro-expression/performance instruction.

    Avatar adapters may map these semantic cues to blend shapes, gaze and
    gestures.  No vendor SDK fields leak into the graph or API contract.
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    expression: ExpressionName
    intensity: float = Field(default=0.45, ge=0.0, le=1.0)
    duration_ms: int = Field(default=700, alias="durationMs", ge=0, le=120_000)
    gaze: Literal["camera", "user", "away", "none"] = "camera"
    gesture: str | None = Field(default=None, max_length=64)
    lip_sync: bool = Field(default=False, alias="lipSync")
    interruptible: bool = True


class FillerPlan(BaseModel):
    """A short acknowledgement used to reduce perceived first-token delay."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    should_emit: bool = Field(default=True, alias="shouldEmit")
    text: str = Field(default="", max_length=120)
    phase: FillerPhase
    expected_delay_ms: int = Field(default=120, alias="expectedDelayMs", ge=0, le=30_000)
    cue: PerformanceCue
