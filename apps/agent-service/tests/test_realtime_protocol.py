from __future__ import annotations

import json

import pytest
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.main import build_container, create_app
from app.mcp.client import CompositeToolClient, LocalToolClient, StreamableHttpToolClient
from app.realtime.audio_handlers import RealtimeAudioHandlersMixin
from app.realtime.handlers import RealtimeHandlersMixin
from app.realtime.observability import RealtimeTelemetry
from app.realtime.state import ConnectionState
from app.realtime.protocol import RealtimeMessage
from app.settings import Settings


def _client() -> TestClient:
    settings = Settings(internal_token="test-token", mcp_allow_local_fallback=False)
    tools = CompositeToolClient(
        StreamableHttpToolClient(
            "http://127.0.0.1:1/mcp",
            internal_token="test-token",
            timeout_seconds=0.05,
        ),
        LocalToolClient(),
        allow_fallback=False,
    )
    return TestClient(create_app(container=build_container(settings, tool_client=tools)))


def _headers() -> dict[str, str]:
    return {
        "X-Internal-Token": "test-token",
        "X-User-Id": "u1",
        "X-User-Name": "Tester",
    }


def _session(client: TestClient) -> str:
    response = client.post("/internal/sessions", headers=_headers(), json={"provider": "mock"})
    assert response.status_code == 201
    return response.json()["sessionId"]


def _hello(ws, session_id: str) -> dict[str, object]:
    ws.send_json({"type": "hello", "protocol": "realtime.v1", "sessionId": session_id, "requestId": "h1"})
    ready = ws.receive_json()
    assert ready["type"] == "ready"
    assert ready["sessionId"] == session_id
    assert ready["protocol"] == "realtime.v1"
    return ready


def test_realtime_requires_internal_identity() -> None:
    with _client() as client:
        with pytest.raises(WebSocketDisconnect) as error:
            with client.websocket_connect("/internal/realtime"):
                pass
        assert error.value.code == 4401


def test_realtime_text_stream_preserves_run_generation() -> None:
    with _client() as client:
        session_id = _session(client)
        with client.websocket_connect("/internal/realtime", headers=_headers()) as ws:
            _hello(ws, session_id)
            ws.send_json(
                {
                    "type": "text",
                    "sessionId": session_id,
                    "utteranceId": "utt-1",
                    "revision": 1,
                    "text": "你好",
                }
            )
            ack = ws.receive_json()
            started = ws.receive_json()
            assert ack["type"] == "ack"
            assert ack["accepted"] is True
            assert started["type"] == "run_started"
            run_id = str(started["runId"])

            events: list[dict[str, object]] = []
            while True:
                event = ws.receive_json()
                events.append(event)
                if event["type"] == "run_done":
                    break
            assert any(event["type"] == "delta" for event in events)
            assert all(event.get("runId") == run_id for event in events if event.get("runId"))
            all_events = [ack, started, *events]
            assert [int(event["seq"]) for event in all_events] == list(
                range(2, 2 + len(all_events))
            )


def test_realtime_audio_frame_boundary_and_explicit_unsupported_asr() -> None:
    with _client() as client:
        session_id = _session(client)
        with client.websocket_connect("/internal/realtime", headers=_headers()) as ws:
            _hello(ws, session_id)
            ws.send_json(
                {
                    "type": "audio_start",
                    "sessionId": session_id,
                    "utteranceId": "utt-audio",
                    "revision": 1,
                    "codec": "pcm_s16le",
                    "sampleRate": 16000,
                    "channels": 1,
                    "frameMs": 20,
                }
            )
            assert ws.receive_json()["action"] == "audio_start"
            assert ws.receive_json()["type"] == "audio_queue"

            ws.send_bytes(b"\x00" * 640)
            queue_event = ws.receive_json()
            assert queue_event["type"] == "audio_queue"
            assert queue_event["frames"] == 1
            assert queue_event["bytesReceived"] == 640

            ws.send_json(
                {
                    "type": "audio_end",
                    "sessionId": session_id,
                    "utteranceId": "utt-audio",
                    "revision": 1,
                }
            )
            transcript = ws.receive_json()
            ack = ws.receive_json()
            assert transcript["type"] == "transcript"
            assert transcript["status"] == "unsupported"
            assert transcript["reason"] == "asr_unconfigured"
            assert ack["type"] == "ack"
            assert ack["accepted"] is True


def test_realtime_ready_uses_configured_session_lease_window() -> None:
    settings = Settings(
        internal_token="test-token",
        mcp_allow_local_fallback=False,
        session_heartbeat_interval_seconds=7,
        session_idle_timeout_seconds=21,
        realtime_handshake_timeout_seconds=3.0,
        realtime_idle_timeout_seconds=14.0,
        realtime_interrupt_timeout_seconds=0.5,
    )
    tools = CompositeToolClient(
        StreamableHttpToolClient(
            "http://127.0.0.1:1/mcp",
            internal_token="test-token",
            timeout_seconds=0.05,
        ),
        LocalToolClient(),
        allow_fallback=False,
    )
    container = build_container(settings, tool_client=tools)
    assert container.realtime_limits.heartbeat_interval_seconds == 7
    assert container.realtime_limits.idle_timeout_seconds == 14
    assert container.realtime_limits.handshake_timeout_seconds == 3.0
    assert container.realtime_limits.interrupt_timeout_seconds == 0.5
    with TestClient(create_app(container=container)) as client:
        session_id = _session(client)
        with client.websocket_connect("/internal/realtime", headers=_headers()) as ws:
            ready = _hello(ws, session_id)
            assert ready["heartbeatMs"] == 7_000


def test_realtime_rejects_stale_revision_without_starting_second_run() -> None:
    with _client() as client:
        session_id = _session(client)
        with client.websocket_connect("/internal/realtime", headers=_headers()) as ws:
            _hello(ws, session_id)
            frame = {
                "type": "text",
                "sessionId": session_id,
                "utteranceId": "utt-correction",
                "revision": 2,
                "isFinal": False,
                "text": "北京天气",
            }
            ws.send_text(json.dumps(frame, ensure_ascii=False))
            partial = ws.receive_json()
            accepted = ws.receive_json()
            assert partial["type"] == "transcript"
            assert accepted["accepted"] is True

            stale_frame = {**frame, "revision": 1}
            ws.send_text(json.dumps(stale_frame, ensure_ascii=False))
            stale = ws.receive_json()
            assert stale["type"] == "ack"
            assert stale["accepted"] is False
            assert stale["reason"] == "stale_revision"


@pytest.mark.asyncio
async def test_revision_accepts_interim_then_final_once() -> None:
    state = ConnectionState()

    assert await state.accept_revision("utt-1", 1, is_final=False, allow_open_update=True) is True
    assert await state.accept_revision("utt-1", 1, is_final=False, allow_open_update=True) is True
    assert await state.accept_revision("utt-1", 1, is_final=True, allow_open_update=True) is True
    assert await state.accept_revision("utt-1", 1, is_final=True) is False
    assert await state.accept_revision("utt-1", 0, is_final=True) is False
    assert await state.accept_revision("utt-1", 2, is_final=True) is True


@pytest.mark.asyncio
async def test_revision_rollback_restores_retryable_state() -> None:
    state = ConnectionState()
    ticket = await state.reserve_revision("utt-1", 1, is_final=True)
    assert ticket is not None
    assert await state.rollback_revision(ticket) is True
    assert await state.reserve_revision("utt-1", 1, is_final=True) is not None


@pytest.mark.asyncio
async def test_old_revision_rollback_cannot_remove_newer_revision() -> None:
    state = ConnectionState()
    ticket = await state.reserve_revision("utt-1", 1, is_final=True)
    assert ticket is not None
    assert await state.reserve_revision("utt-1", 2, is_final=True) is not None
    assert await state.rollback_revision(ticket) is False
    assert await state.accept_revision("utt-1", 1, is_final=True) is False


class _FailOnceIngress:
    async def start(self, utterance_id: str, revision: int):
        if not hasattr(self, "failed"):
            self.failed = True
            raise RuntimeError("ingress unavailable")
        return type("Stats", (), {"utterance_id": utterance_id, "revision": revision, "status": "buffering"})()


class _AudioHarness(RealtimeAudioHandlersMixin):
    def __init__(self) -> None:
        self.state = ConnectionState()
        self.ingress = _FailOnceIngress()
        self.limits = type("Limits", (), {"max_audio_buffer_bytes": 1024})()
        self.telemetry = RealtimeTelemetry(None, "conn-audio")
        self.events: list[dict[str, object]] = []

    async def _clear_audio(self, *, reason: str | None = None) -> None:
        del reason

    async def _stop_active(self):
        return None

    async def _publish_interrupted(self, binding, *, reason: str):
        del binding, reason

    async def _emit(self, event_type: str, **fields):
        self.events.append({"type": event_type, **fields})

    async def _audio_queue(self, stats):
        self.events.append({"type": "audio_queue", "revision": stats.revision})


class _FinalIngress:
    async def finish(self):
        from app.realtime.audio import TranscriptResult
        return TranscriptResult(status="final", text="帮我查一下今天的天气", utterance_id="utt-final", revision=2)

    async def reset(self):
        return None


class _FinalAudioHarness(RealtimeAudioHandlersMixin):
    def __init__(self) -> None:
        self.state = ConnectionState(session_id="s1", hello_received=True)
        self.ingress = _FinalIngress()
        self.events: list[dict[str, object]] = []
        self.limits = type("Limits", (), {"max_audio_buffer_bytes": 1024})()
        self.telemetry = RealtimeTelemetry(None, "conn-final")

    async def _emit(self, event_type: str, **fields):
        self.events.append({"type": event_type, **fields})

    async def _reset_ingress_safely(self):
        return None

    async def _text(self, message):
        self.events.append({"type": "agent_text", "text": message.text, "utterance_id": message.utterance_id, "revision": message.revision})


@pytest.mark.asyncio
async def test_audio_start_failure_rolls_back_revision_for_retry() -> None:
    harness = _AudioHarness()
    message = RealtimeMessage(type="audio_start", utteranceId="utt-audio", revision=1)
    with pytest.raises(RuntimeError):
        await harness._audio_start(message)
    await harness._audio_start(message)
    assert harness.events[-2]["accepted"] is True


@pytest.mark.asyncio
async def test_final_asr_transcript_is_forwarded_into_agent_text_run() -> None:
    harness = _FinalAudioHarness()
    await harness.state.start_audio("utt-final", 2)
    await harness._audio_end(RealtimeMessage(type="audio_end", requestId="a2", utteranceId="utt-final", revision=2))
    assert harness.events[-1] == {
        "type": "agent_text",
        "text": "帮我查一下今天的天气",
        "utterance_id": "utt-final",
        "revision": 2,
    }


class _TextCapacityHarness(RealtimeHandlersMixin):
    def __init__(self) -> None:
        self.state = ConnectionState(user_id="u1", user_name="Tester", session_id="s1", hello_received=True)
        self.limits = type("Limits", (), {"max_pending_runs": 1})()
        self.run_tasks = {"existing": object()}
        self.container = type("Container", (), {})()
        self.events: list[dict[str, object]] = []

    async def _clear_audio(self, *, reason: str | None = None) -> None:
        del reason

    async def _stop_active(self, run_id: str | None = None):
        del run_id
        return None

    async def _emit(self, event_type: str, **fields):
        self.events.append({"type": event_type, **fields})

    async def _send_error(self, code: str, message: str, **fields):
        self.events.append({"type": "error", "code": code, "message": message, **fields})


@pytest.mark.asyncio
async def test_text_capacity_failure_rolls_back_revision() -> None:
    harness = _TextCapacityHarness()
    await harness._text(RealtimeMessage(type="text", utteranceId="utt-capacity", revision=1, text="hello"))
    assert harness.events[-1]["code"] == "run_capacity"
    assert await harness.state.reserve_revision("utt-capacity", 1, is_final=True) is not None
