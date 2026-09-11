"""Telemetry event contracts shared by sinks and HTTP diagnostics."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .redaction import redact_text


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class TelemetryEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(default_factory=lambda: uuid4().hex)
    # Assigned by the observability facade before a sink receives the event.
    # A zero value keeps direct sink usage backwards compatible.
    sequence: int = Field(default=0, ge=0)
    event_type: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=256)
    trace_id: str
    span_id: str | None = None
    parent_span_id: str | None = None
    timestamp: datetime = Field(default_factory=_utc_now)
    duration_ms: float | None = Field(default=None, ge=0)
    status: Literal["ok", "error", "unset"] = "unset"
    attributes: dict[str, Any] = Field(default_factory=dict)
    error_type: str | None = None
    error_message: str | None = None

    @field_validator("error_message", mode="before")
    @classmethod
    def sanitize_error_message(cls, value: Any) -> str | None:
        return redact_text(value)


class ObservabilityHealth(BaseModel):
    status: Literal["ok", "degraded"] = "ok"
    backend: str
    configured: bool
    buffered_events: int = Field(default=0, ge=0)
    pending_tasks: int = Field(default=0, ge=0)
    dropped_events: int = Field(default=0, ge=0)
    last_error: str | None = None

    @field_validator("last_error", mode="before")
    @classmethod
    def sanitize_last_error(cls, value: Any) -> str | None:
        return redact_text(value)


class TraceStage(BaseModel):
    """Human-readable stage summary used by the evaluation console."""

    name: str
    sequence: int = Field(default=0, ge=0)
    event_type: str
    status: Literal["ok", "error", "unset"]
    duration_ms: float | None = Field(default=None, ge=0)
    timestamp: datetime
    error_message: str | None = None

    @field_validator("error_message", mode="before")
    @classmethod
    def sanitize_error_message(cls, value: Any) -> str | None:
        return redact_text(value)


class TracePhase(BaseModel):
    """One end-to-end stage of the realtime voice loop.

    A trace is assembled from markers produced by three different processes:
    the browser, the agent service and the vendor avatar SDK. Grouping them
    into named phases turns a flat event list into a waterfall that shows where
    a silent or slow turn actually spent its time.
    """

    key: Literal["capture", "asr", "agent", "speech", "playback"]
    label: str
    # Offset from the trace's first event, so the waterfall reads left to right.
    start_offset_ms: float = Field(ge=0)
    # Wall-clock span covered by this phase; None when it has a single marker.
    duration_ms: float | None = Field(default=None, ge=0)
    status: Literal["ok", "error", "unset"] = "unset"
    event_count: int = Field(default=0, ge=0)
    first_event_name: str | None = None
    last_event_name: str | None = None
    # False when the phase produced no marker at all, which is how the console
    # distinguishes "this stage was fast" from "this stage was never observed".
    observed: bool = False
    error_message: str | None = None

    @field_validator("error_message", mode="before")
    @classmethod
    def sanitize_error_message(cls, value: Any) -> str | None:
        return redact_text(value)


class TraceSummary(BaseModel):
    trace_id: str
    status: Literal["ok", "error", "unset"]
    started_at: datetime
    ended_at: datetime
    duration_ms: float = Field(ge=0)
    event_count: int = Field(ge=0)
    error_count: int = Field(ge=0)
    cancelled: bool = False
    first_event_latency_ms: float | None = Field(default=None, ge=0)
    first_visible_latency_ms: float | None = Field(default=None, ge=0)
    agent_latency_ms: float | None = Field(default=None, ge=0)
    digital_human_latency_ms: float | None = Field(default=None, ge=0)
    cancellation_latency_ms: float | None = Field(default=None, ge=0)
    stages: list[TraceStage] = Field(default_factory=list)
    phases: list[TracePhase] = Field(default_factory=list)
    # "browser" when the client reported into the trace, so the console can tell
    # a server-only trace from a genuinely end-to-end one.
    origin: Literal["browser", "server"] = "server"
    coverage: list[str] = Field(default_factory=list)


class TraceReplay(BaseModel):
    trace: TraceSummary
    events: list[TelemetryEvent] = Field(default_factory=list)
    truncated: bool = False
