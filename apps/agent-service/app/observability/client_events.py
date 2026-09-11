"""Browser-originated telemetry contracts for end-to-end realtime tracing.

The browser owns facts the server cannot observe: microphone authorization,
recorder lifecycle, the delta -> speech projection, and the vendor avatar
SDK's speak lifecycle. These events are reporting-only: the server stamps
identity, ordering and timestamps so an untrusted client cannot forge a
trace's origin, ordering or ownership.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .redaction import redact, redact_text

MAX_CLIENT_EVENTS_PER_BATCH = 64
MAX_CLIENT_ATTRIBUTES = 24

_ALLOWED_EVENT_NAMES = frozenset(
    {
        # Microphone capture and recorder lifecycle.
        "capture.permission_request",
        "capture.permission_granted",
        "capture.permission_denied",
        "capture.recorder_started",
        "capture.recorder_stopped",
        "capture.recorder_failed",
        "capture.track_ended",
        "capture.first_frame",
        # Transport and run phase transitions observed in the browser.
        "realtime.client_connected",
        "realtime.client_disconnected",
        "realtime.client_send_failed",
        "realtime.phase",
        # delta -> speech projection, the boundary that gates avatar speech.
        "speech.assembled",
        "speech.skipped",
        "speech.dispatch_failed",
        # Speech loss markers. The avatar dropping the beginning of an answer
        # was invisible before these existed: the trace looked clean while the
        # user heard only the tail.
        "speech.dropped",
        "speech.ack_timeout",
        "speech.interrupted",
        # Vendor avatar SDK speak lifecycle.
        "speak.dispatched",
        "speak.started",
        "speak.ended",
        "speak.failed",
        "speak.timeout",
        "ttsa.warning",
        "ttsa.recovered",
        # Vendor avatar runtime lifecycle, kept next to the SDK speak markers
        # so a trace can show "the avatar never reached ready" without waiting
        # for a speak request to time out.
        "avatar.connect_started",
        "avatar.connect_failed",
        "avatar.ready_achieved",
        "avatar.ready_blocked",
        "avatar.phase_changed",
        # Mobile autoplay policy: a suspended AudioContext is the difference
        # between a desktop that speaks and a phone that stays silent.
        "avatar.audio_unlocked",
        "avatar.audio_blocked",
    }
)


class ClientTelemetryEvent(BaseModel):
    """One browser-reported marker belonging to an existing trace."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=128)
    trace_id: str = Field(min_length=1, max_length=128)
    run_id: str | None = Field(default=None, max_length=128)
    utterance_id: str | None = Field(default=None, max_length=128)
    revision: int | None = Field(default=None, ge=0)
    duration_ms: float | None = Field(default=None, ge=0)
    status: Literal["ok", "error", "unset"] = "ok"
    attributes: dict[str, Any] = Field(default_factory=dict)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        clean = value.strip()
        if clean not in _ALLOWED_EVENT_NAMES:
            raise ValueError("unknown client event name")
        return clean

    @field_validator("trace_id", "run_id", "utterance_id")
    @classmethod
    def validate_identifier(cls, value: str | None) -> str | None:
        if value is None:
            return None
        clean = value.strip()
        if not clean:
            return None
        if not all(char.isalnum() or char in "-_:" for char in clean):
            raise ValueError("identifier contains unsupported characters")
        return clean

    @field_validator("attributes")
    @classmethod
    def sanitize_attributes(cls, value: dict[str, Any]) -> dict[str, Any]:
        # Client payloads are untrusted. Bound the shape first, then reuse the
        # shared credential scrubber so a browser cannot smuggle a secret into
        # the trace buffer.
        bounded = dict(list(value.items())[:MAX_CLIENT_ATTRIBUTES])
        scrubbed = redact(bounded)
        return scrubbed if isinstance(scrubbed, dict) else {}


class ClientTelemetryBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    events: list[ClientTelemetryEvent] = Field(min_length=1, max_length=MAX_CLIENT_EVENTS_PER_BATCH)
    session_id: str | None = Field(default=None, max_length=128)
    connection_id: str | None = Field(default=None, max_length=128)

    @field_validator("events")
    @classmethod
    def require_events(cls, value: list[ClientTelemetryEvent]) -> list[ClientTelemetryEvent]:
        if not value:
            raise ValueError("at least one event is required")
        return value


class ClientTelemetryAck(BaseModel):
    accepted: int = Field(ge=0)
    rejected: int = Field(ge=0)
    reason: str | None = None

    @field_validator("reason", mode="before")
    @classmethod
    def sanitize_reason(cls, value: Any) -> str | None:
        return redact_text(value)


__all__ = [
    "ClientTelemetryAck",
    "ClientTelemetryBatch",
    "ClientTelemetryEvent",
    "MAX_CLIENT_EVENTS_PER_BATCH",
]
