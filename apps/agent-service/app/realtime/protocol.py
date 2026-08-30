"""Wire models and helpers for the authenticated realtime WebSocket."""

from __future__ import annotations

import json
import re
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from .payloads import sanitize_event_data


MAX_CONTROL_FRAME_BYTES = 64 * 1024
MAX_IDENTIFIER_LENGTH = 128
MAX_TEXT_LENGTH = 4000
MAX_REVISION = 1_000_000
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")


class RealtimeProtocolError(ValueError):
    """A client frame cannot be accepted under the realtime contract."""

    def __init__(self, code: str, message: str, *, close: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.close = close


class MessageType(StrEnum):
    HELLO = "hello"
    TEXT = "text"
    INTERRUPT = "interrupt"
    AUDIO_START = "audio_start"
    AUDIO_END = "audio_end"
    SPEECH_START = "speech_start"
    SPEECH_END = "speech_end"
    PING = "ping"
    PONG = "pong"
    CLOSE = "close"


class RealtimeMessage(BaseModel):
    """Common control frame; unknown message kinds are rejected separately."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    type: str = Field(min_length=1, max_length=32)
    request_id: str | None = Field(default=None, alias="requestId")
    session_id: str | None = Field(default=None, alias="sessionId")
    run_id: str | None = Field(default=None, alias="runId")
    utterance_id: str | None = Field(default=None, alias="utteranceId")
    revision: int | None = Field(default=None, ge=1, le=MAX_REVISION)
    text: str | None = Field(default=None, max_length=MAX_TEXT_LENGTH)
    protocol: str | None = Field(default=None, max_length=32)
    is_final: bool = Field(default=True, alias="isFinal")
    reason: str | None = Field(default=None, max_length=128)
    codec: str | None = Field(default=None, max_length=32)
    sample_rate: int | None = Field(default=None, alias="sampleRate", ge=8000, le=96_000)
    channels: int | None = Field(default=None, ge=1, le=2)
    frame_ms: int | None = Field(default=None, alias="frameMs", ge=5, le=100)

    @field_validator(
        "request_id",
        "session_id",
        "run_id",
        "utterance_id",
        "protocol",
        "reason",
        "codec",
        mode="before",
    )
    @classmethod
    def bounded_text(cls, value: Any) -> Any:
        if value is None:
            return value
        if not isinstance(value, str):
            raise ValueError("must be a string")
        clean = _CONTROL_CHARS.sub(" ", value).strip()
        if not clean or len(clean) > MAX_IDENTIFIER_LENGTH:
            raise ValueError("value is empty or too long")
        return clean

    @field_validator("text", mode="before")
    @classmethod
    def bounded_message(cls, value: Any) -> Any:
        if value is None:
            return value
        if not isinstance(value, str):
            raise ValueError("text must be a string")
        return _CONTROL_CHARS.sub(" ", value).strip()


def parse_control(raw: str, *, max_bytes: int = MAX_CONTROL_FRAME_BYTES) -> RealtimeMessage:
    """Decode and validate one JSON control frame without exposing parser detail."""

    if not isinstance(raw, str):
        raise RealtimeProtocolError("invalid_frame", "控制帧必须是文本", close=False)
    if len(raw.encode("utf-8")) > max_bytes:
        raise RealtimeProtocolError("frame_too_large", "控制帧超过大小限制", close=True)
    try:
        value = json.loads(raw)
    except (TypeError, json.JSONDecodeError) as exc:
        raise RealtimeProtocolError("invalid_json", "控制帧不是有效 JSON", close=False) from exc
    if not isinstance(value, dict):
        raise RealtimeProtocolError("invalid_message", "控制帧必须是 JSON 对象", close=False)
    try:
        message = RealtimeMessage.model_validate(value)
    except ValidationError as exc:
        del exc
        raise RealtimeProtocolError("invalid_message", "控制帧字段无效", close=False) from None
    try:
        MessageType(message.type)
    except ValueError as exc:
        raise RealtimeProtocolError("unknown_type", "不支持的实时消息类型", close=False) from exc
    return message


def require_hello(message: RealtimeMessage) -> None:
    if message.type != MessageType.HELLO:
        raise RealtimeProtocolError("hello_required", "连接建立后必须先发送 hello", close=True)
    if message.protocol not in {None, "realtime.v1"}:
        raise RealtimeProtocolError("unsupported_protocol", "不支持的实时协议版本", close=True)
    if not message.session_id:
        raise RealtimeProtocolError("session_required", "hello 缺少 sessionId", close=True)


def require_text(message: RealtimeMessage) -> None:
    if message.is_final and not message.text:
        raise RealtimeProtocolError("text_required", "文本消息不能为空", close=False)
    if not message.is_final:
        # Interim ASR text is acknowledged but must not accidentally launch a
        # graph run; the connection layer decides when a final revision starts.
        return


def require_audio_start(message: RealtimeMessage) -> None:
    if not message.utterance_id:
        raise RealtimeProtocolError("utterance_required", "audio_start 缺少 utteranceId", close=False)
    if message.codec not in {None, "pcm_s16le"}:
        raise RealtimeProtocolError("unsupported_codec", "仅支持 pcm_s16le 音频", close=False)
    if message.sample_rate not in {None, 16_000} or message.channels not in {None, 1}:
        raise RealtimeProtocolError("unsupported_audio", "音频必须为 16kHz 单声道", close=False)
    if message.frame_ms not in {None, 20}:
        raise RealtimeProtocolError("unsupported_frame", "音频帧必须为 20ms", close=False)


def event_payload(
    event_type: str,
    *,
    request_id: str | None = None,
    session_id: str | None = None,
    run_id: str | None = None,
    utterance_id: str | None = None,
    revision: int | None = None,
    seq: int | None = None,
    **fields: Any,
) -> dict[str, Any]:
    """Build a compact camelCase event while omitting unset identifiers."""

    payload: dict[str, Any] = {"type": event_type}
    for key, value in (
        ("requestId", request_id),
        ("sessionId", session_id),
        ("runId", run_id),
        ("utteranceId", utterance_id),
        ("revision", revision),
        ("seq", seq),
    ):
        if value is not None:
            payload[key] = value
    reserved = {"type", "requestId", "sessionId", "runId", "utteranceId", "revision", "seq"}
    payload.update({key: value for key, value in fields.items() if value is not None and key not in reserved})
    return payload


def agent_event_payload(
    event: dict[str, Any],
    *,
    session_id: str,
    run_id: str | None,
    utterance_id: str,
    revision: int,
) -> dict[str, Any] | None:
    """Translate one existing graph event into the realtime event namespace."""

    if not isinstance(event, dict):
        return None
    event_type = str(event.get("event") or "message").strip().lower()
    raw_data = event.get("data")
    data = sanitize_event_data(event_type, raw_data)
    for key in ("type", "requestId", "sessionId", "runId", "utteranceId", "revision", "seq"):
        data.pop(key, None)
    return event_payload(
        event_type,
        session_id=session_id,
        run_id=run_id,
        utterance_id=utterance_id,
        revision=revision,
        **data,
    )


__all__ = [
    "MAX_CONTROL_FRAME_BYTES",
    "MAX_IDENTIFIER_LENGTH",
    "MAX_REVISION",
    "MAX_TEXT_LENGTH",
    "MessageType",
    "RealtimeMessage",
    "RealtimeProtocolError",
    "agent_event_payload",
    "event_payload",
    "parse_control",
    "require_audio_start",
    "require_hello",
    "require_text",
]
