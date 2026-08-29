"""Stable domain models shared by API, graph and provider adapters."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

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


class ToolCallRecord(BaseModel):
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    result: Any = None
    error: str | None = None
    duration_ms: float | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ChatResult(BaseModel):
    reply: str
    trace_id: str
    session_id: str
    provider: str
    tool_calls: list[ToolCallRecord] = Field(default_factory=list)
    agent_latency_ms: float | None = Field(default=None, ge=0)
    digital_human_latency_ms: float | None = Field(default=None, ge=0)
    interrupted: bool = False


class SessionRecord(BaseModel):
    model_config = ConfigDict(validate_assignment=True)

    session: AvatarSession
    last_activity: datetime
    interrupted: bool = False
    # A new token is issued for every request run.  Replacing it automatically
    # steers an older run to stop without making the session unusable.
    active_run_id: str | None = None
