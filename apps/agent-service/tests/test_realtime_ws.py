from __future__ import annotations

import asyncio

import httpx
import pytest
from starlette.testclient import TestClient, WebSocketDisconnect

from app.main import build_container, create_app
from app.mcp.client import (
    CompositeToolClient,
    LocalToolClient,
    StreamableHttpToolClient,
)
from app.realtime.audio import AudioFormat
from app.realtime.media import HttpAsrIngress
from app.settings import Settings

HEADERS = {"X-Internal-Token": "test-token", "X-User-Id": "u1", "X-User-Name": "Tester"}


def _client() -> TestClient:
    settings = Settings(internal_token="test-token", mcp_allow_local_fallback=False)
    tools = CompositeToolClient(
        StreamableHttpToolClient("http://127.0.0.1:1/mcp", internal_token="test-token", timeout_seconds=0.1),
        LocalToolClient(),
        allow_fallback=False,
    )
    return TestClient(create_app(container=build_container(settings, tool_client=tools)))


def _session(client: TestClient) -> str:
    response = client.post("/internal/sessions", headers=HEADERS, json={"provider": "mock"})
    assert response.status_code == 201
    return response.json()["sessionId"]


def _until_done(websocket, *, limit: int = 128) -> list[dict[str, object]]:
    events: list[dict[str, object]] = []
    for _ in range(limit):
        event = websocket.receive_json()
        events.append(event)
        if event.get("type") == "run_done":
            return events
    raise AssertionError("realtime run did not terminate")


def test_realtime_requires_internal_gateway_headers() -> None:
    with _client() as client:
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect("/internal/realtime"):
                pass


def test_realtime_rejects_closed_session_during_hello() -> None:
    with _client() as client:
        session_id = _session(client)
        response = client.delete(f"/internal/sessions/{session_id}", headers=HEADERS)
        assert response.status_code == 200
        with client.websocket_connect("/internal/realtime", headers=HEADERS) as websocket:
            websocket.send_json({"type": "hello", "requestId": "closed-h1", "sessionId": session_id})
            error = websocket.receive_json()
            assert error["type"] == "error"
            assert error["code"] == "session_rejected"
            with pytest.raises(WebSocketDisconnect):
                websocket.receive_json()


def test_realtime_text_run_has_stable_ids_and_terminal_event() -> None:
    with _client() as client:
        session_id = _session(client)
        with client.websocket_connect("/internal/realtime", headers=HEADERS) as websocket:
            websocket.send_json({"type": "hello", "requestId": "h1", "sessionId": session_id})
            ready = websocket.receive_json()
            assert ready["type"] == "ready"
            assert ready["sessionId"] == session_id
            assert ready["capabilities"]["asr"] == "unsupported"

            websocket.send_json({"type": "text", "requestId": "t1", "utteranceId": "u1", "revision": 1, "text": "hello"})
            events = _until_done(websocket)
            assert events[0]["type"] == "ack"
            run_id = events[0]["runId"]
            assert run_id
            assert events[1]["type"] == "run_started"
            assert all(event.get("runId") in {None, run_id} for event in events)
            assert events[-1]["type"] == "run_done"
            assert events[-1]["status"] in {"ok", "error"}


def test_realtime_interim_then_final_same_revision_starts_one_run() -> None:
    with _client() as client:
        session_id = _session(client)
        with client.websocket_connect("/internal/realtime", headers=HEADERS) as websocket:
            websocket.send_json({"type": "hello", "sessionId": session_id})
            assert websocket.receive_json()["type"] == "ready"

            websocket.send_json(
                {
                    "type": "text",
                    "requestId": "interim-1",
                    "utteranceId": "correction-1",
                    "revision": 1,
                    "isFinal": False,
                    "text": "北京天气",
                }
            )
            partial = websocket.receive_json()
            partial_ack = websocket.receive_json()
            assert partial["type"] == "transcript"
            assert partial["status"] == "partial"
            assert partial_ack["accepted"] is True
            assert partial_ack["final"] is False

            websocket.send_json(
                {
                    "type": "text",
                    "requestId": "final-1",
                    "utteranceId": "correction-1",
                    "revision": 1,
                    "isFinal": True,
                    "text": "北京明天天气怎么样",
                }
            )
            final_ack = websocket.receive_json()
            started = websocket.receive_json()
            assert final_ack["type"] == "ack"
            assert final_ack["accepted"] is True
            assert started["type"] == "run_started"
            run_id = started["runId"]
            events = _until_done(websocket)
            assert events[-1]["type"] == "run_done"
            assert events[-1]["runId"] == run_id

            websocket.send_json(
                {
                    "type": "text",
                    "requestId": "duplicate-final",
                    "utteranceId": "correction-1",
                    "revision": 1,
                    "isFinal": True,
                    "text": "北京后天天气怎么样",
                }
            )
            duplicate = websocket.receive_json()
            assert duplicate["accepted"] is False
            assert duplicate["reason"] == "stale_revision"


def test_realtime_audio_lifecycle_is_bounded_and_explicitly_unsupported() -> None:
    with _client() as client:
        session_id = _session(client)
        with client.websocket_connect("/internal/realtime", headers=HEADERS) as websocket:
            websocket.send_json({"type": "hello", "sessionId": session_id})
            assert websocket.receive_json()["type"] == "ready"
            websocket.send_json({"type": "audio_start", "requestId": "a1", "utteranceId": "audio-1", "revision": 1})
            assert websocket.receive_json()["type"] == "ack"
            queue_event = websocket.receive_json()
            assert queue_event["type"] == "audio_queue"
            websocket.send_bytes(b"\x00" * 640)
            queue_event = websocket.receive_json()
            assert queue_event["type"] == "audio_queue"
            assert queue_event["frames"] == 1
            websocket.send_json({"type": "audio_end", "requestId": "a2", "utteranceId": "audio-1", "revision": 1})
            transcript = websocket.receive_json()
            assert transcript["type"] == "transcript"
            assert transcript["status"] == "unsupported"
            assert transcript["reason"] == "asr_unconfigured"
            assert websocket.receive_json()["type"] == "ack"


def test_realtime_audio_final_forwards_asr_text_to_agent_run() -> None:
    settings = Settings(
        internal_token="test-token",
        mcp_allow_local_fallback=False,
        asr_endpoint="https://asr.test/transcribe",
        asr_api_key="test-asr-token",
    )
    tools = CompositeToolClient(
        StreamableHttpToolClient("http://127.0.0.1:1/mcp", internal_token="test-token", timeout_seconds=0.1),
        LocalToolClient(),
        allow_fallback=False,
    )
    container = build_container(settings, tool_client=tools)
    assert isinstance(container.audio_ingress, HttpAsrIngress)
    asyncio.run(container.audio_ingress._client.aclose())
    container.audio_ingress._client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json={"text": "语音转写文本"}))
    )
    messages: list[str] = []
    original_stream = container.chat_service.stream

    async def recording_stream(**kwargs):
        messages.append(kwargs["message"])
        return await original_stream(**kwargs)

    container.chat_service.stream = recording_stream
    with TestClient(create_app(container=container)) as client:
        session_id = _session(client)
        with client.websocket_connect("/internal/realtime", headers=HEADERS) as websocket:
            websocket.send_json({"type": "hello", "requestId": "h1", "sessionId": session_id})
            ready = websocket.receive_json()
            assert ready["type"] == "ready"
            assert ready["capabilities"]["audioInput"] is True
            assert ready["capabilities"]["asr"] == "supported"

            websocket.send_json({"type": "audio_start", "requestId": "a1", "utteranceId": "audio-1", "revision": 1})
            assert websocket.receive_json()["type"] == "ack"
            assert websocket.receive_json()["type"] == "audio_queue"
            websocket.send_bytes(b"\x00" * AudioFormat().frame_bytes)
            assert websocket.receive_json()["type"] == "audio_queue"
            websocket.send_json({"type": "audio_end", "requestId": "a2", "utteranceId": "audio-1", "revision": 1})

            events: list[dict[str, object]] = []
            for _ in range(128):
                event = websocket.receive_json()
                events.append(event)
                if event.get("type") == "run_done":
                    break
            else:
                raise AssertionError("realtime ASR run did not terminate")

    transcript = next(event for event in events if event.get("type") == "transcript")
    assert transcript["status"] == "final"
    assert transcript["source"] == "asr"
    assert transcript["text"] == "语音转写文本"
    assert any(event.get("type") == "ack" and event.get("action") == "audio_end" and event.get("accepted") is True for event in events)
    started = next(event for event in events if event.get("type") == "run_started")
    assert started["runId"]
    assert events[-1]["type"] == "run_done"
    assert events[-1]["runId"] == started["runId"]
    assert messages == ["语音转写文本"]


def test_realtime_speech_end_discards_active_audio_without_transcription() -> None:
    with _client() as client:
        session_id = _session(client)
        with client.websocket_connect("/internal/realtime", headers=HEADERS) as websocket:
            websocket.send_json({"type": "hello", "sessionId": session_id})
            assert websocket.receive_json()["type"] == "ready"
            websocket.send_json({"type": "audio_start", "requestId": "a1", "utteranceId": "audio-cancel", "revision": 1})
            assert websocket.receive_json()["type"] == "ack"
            assert websocket.receive_json()["type"] == "audio_queue"
            websocket.send_json({"type": "speech_end", "requestId": "cancel", "reason": "voice_mode_stopped"})
            interrupted = websocket.receive_json()
            assert interrupted["type"] == "audio_queue"
            assert interrupted["status"] == "interrupted"
            cancelled = websocket.receive_json()
            assert cancelled["type"] == "ack"
            assert cancelled["action"] == "speech_end"
            websocket.send_json({"type": "audio_end", "requestId": "late", "utteranceId": "audio-cancel", "revision": 1})
            late = websocket.receive_json()
            assert late["type"] == "ack"
            assert late["accepted"] is False
