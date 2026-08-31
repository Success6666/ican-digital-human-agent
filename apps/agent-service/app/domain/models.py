"""Stable domain models shared by API, graph and provider adapters."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class SessionStatus(StrEnum):
    ACTIVE = "active"
    INTERRUPTED = "interrupted"
    CLOSED = "closed"
    EXPIRED = "expired"


class AvatarCapabilities(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text_input: bool = True
    interrupt: bool = True
    # ``local`` means the Agent suppresses stale output only. A real provider
    # must declare ``run`` once its SDK can stop one remote utterance by run id.
    interrupt_scope: Literal["run", "session", "local", "unsupported"] = "local"
    streaming: bool = False
    audio_input: bool = False
    video_output: bool = False
    external_runtime: bool = False


class AvatarHealth(BaseModel):
    provider: str
    status: str
    configured: bool = False
    detail: str | None = None


class AvatarSession(BaseModel):
    session_id: str
    provider: str
    user_id: str
    capabilities: AvatarCapabilities
    created_at: datetime
    expires_at: datetime
    status: SessionStatus = SessionStatus.ACTIVE
    client_params: dict[str, Any] = Field(default_factory=dict)


class ProviderResult(BaseModel):
    provider: str
    text: str = ""
    status: str = "ok"
    trace_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentResponse(BaseModel):
    """Provider-neutral output passed from Agent Core to presentation.

    The graph owns the meaning of the response; presentation adapters decide
    how to render the semantic cues on a concrete digital-human runtime.
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    text: str = Field(default="", max_length=20_000)
    emotion: str = Field(default="neutral", min_length=1, max_length=64)
    gesture: str | None = Field(default=None, max_length=64)
    presentation: dict[str, Any] = Field(default_factory=dict)
    performance: dict[str, Any] = Field(default_factory=dict)
    trace_id: str | None = Field(default=None, alias="traceId")
    session_id: str | None = Field(default=None, alias="sessionId")
    run_id: str | None = Field(default=None, alias="runId")
    interruptible: bool = True


class ToolCallRecord(BaseModel):
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    result: Any = None
    error: str | None = None
    duration_ms: float | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ChatResult(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    reply: str
    trace_id: str
    session_id: str
    run_id: str | None = Field(default=None, alias="runId")
    provider: str
    tool_calls: list[ToolCallRecord] = Field(default_factory=list)
    agent_latency_ms: float | None = Field(default=None, ge=0)
    digital_human_latency_ms: float | None = Field(default=None, ge=0)
    first_event_latency_ms: float | None = Field(default=None, ge=0)
    first_visible_latency_ms: float | None = Field(default=None, ge=0)
    cancellation_latency_ms: float | None = Field(default=None, ge=0)
    interrupted: bool = False
    agent_response: AgentResponse | None = Field(default=None, alias="agentResponse")


class SessionRecord(BaseModel):
    model_config = ConfigDict(validate_assignment=True)

    session: AvatarSession
    last_activity: datetime
    interrupted: bool = False
    # A new token is issued for every request run.  Replacing it automatically
    # steers an older run to stop without making the session unusable.
    active_run_id: str | None = None
    # Store generation token used by expiry cleanup.  It is deliberately
    # separate from the provider session id, which may be reused by an
    # adapter or test double.
    generation_id: str | None = None
