from __future__ import annotations

import asyncio
import logging
import os
import sys
from types import SimpleNamespace
from pathlib import Path
import unittest
from unittest.mock import patch


SERVICE_ROOT = Path(__file__).resolve().parents[1]
if str(SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVICE_ROOT))

from app.observability.futureagi import FutureAGIConfig, FutureAGISink  # noqa: E402
from app.observability.futureagi_runtime import FutureAGIRuntime  # noqa: E402
from app.observability.local import LocalJsonLogSink  # noqa: E402
from app.observability.models import ObservabilityHealth, TelemetryEvent  # noqa: E402
from app.observability.service import ObservabilityService  # noqa: E402


class ObservabilityTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.local = LocalJsonLogSink(logger=logging.getLogger("test-observability"), max_events=20)
        self.sink = FutureAGISink(
            FutureAGIConfig(enabled=False),
            fallback=self.local,
            logger=logging.getLogger("test-futureagi"),
        )
        self.observability = ObservabilityService(self.sink, local_sink=self.local)

    async def test_missing_credentials_use_local_sink(self) -> None:
        async with self.observability.start_trace("request") as trace:
            trace.set_attribute("authorization", "do-not-log")
            with self.observability.mcp_call("system_status") as span:
                span.set_attribute("api_key", "do-not-log")
        await asyncio.sleep(0)
        events = self.observability.recent()
        self.assertGreaterEqual(len(events), 3)
        self.assertEqual(self.observability.health().backend, "local")
        self.assertEqual(events[-1].status, "ok")
        self.assertTrue(any(event.attributes.get("api_key") == "[REDACTED]" for event in events))

    async def test_error_span_is_recorded_without_raising(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "boom"):
            async with self.observability.langgraph_node("receive"):
                raise RuntimeError("boom")
        await asyncio.sleep(0)
        self.assertTrue(any(event.status == "error" for event in self.observability.recent()))

    async def test_semantic_helpers_keep_trace_relationship(self) -> None:
        async with self.observability.start_trace("agent") as trace:
            async with self.observability.rag_retrieval(attributes={"hit_count": 2}) as child:
                self.assertEqual(child.trace_id, trace.trace_id)
                self.assertEqual(child.parent_span_id, trace.span_id)
        await asyncio.sleep(0)
        self.assertTrue(any(event.event_type == "rag.retrieval" for event in self.observability.recent()))

    async def test_recent_can_be_scoped_to_owner(self) -> None:
        self.observability.record_event("u1-event", attributes={"owner_id": "u1"})
        self.observability.record_event("u2-event", attributes={"owner_id": "u2"})
        names = [event.name for event in self.observability.recent(owner_id="u1")]
        self.assertEqual(names, ["u1-event"])

    async def test_official_register_uses_provider_headers_without_global_state(self) -> None:
        class ProjectType:
            OBSERVE = object()

        class FakeSpan:
            def __init__(self) -> None:
                self.attributes: dict[str, object] = {}
                self.exceptions: list[Exception] = []
                self.ended = False

            def set_attribute(self, key: str, value: object) -> None:
                self.attributes[key] = value

            def record_exception(self, error: Exception) -> None:
                self.exceptions.append(error)

            def end(self) -> None:
                self.ended = True

        span = FakeSpan()

        class FakeTracer:
            def start_span(self, name: str) -> FakeSpan:
                self.name = name
                return span

        tracer = FakeTracer()

        class FakeProvider:
            def get_tracer(self, scope: str) -> FakeTracer:
                self.scope = scope
                return tracer

        provider = FakeProvider()
        calls: dict[str, object] = {}

        def register(**kwargs: object) -> FakeProvider:
            calls.update(kwargs)
            return provider

        module = SimpleNamespace(register=register, ProjectType=ProjectType)
        config = FutureAGIConfig(
            enabled=True,
            api_key="api-value",
            secret_key="secret-value",
            project="ican-test",
            endpoint="https://collector.example.test",
        )
        sink = FutureAGISink(config, fallback=self.local)
        previous_base_url = os.environ.get("FI_BASE_URL")

        event = TelemetryEvent(
            event_type="agent.test",
            name="test-span",
            trace_id="trace-1",
            attributes={"api_key": "must-not-leak"},
            error_message="authorization: Bearer super-secret-token",
        )
        with patch(
            "app.observability.futureagi_runtime._load_instrumentation",
            return_value=module,
        ):
            sink.emit_sync(event)

        self.assertEqual(sink.backend, "futureagi")
        self.assertIs(calls["project_type"], ProjectType.OBSERVE)
        self.assertEqual(calls["project_name"], "ican-test")
        self.assertEqual(calls["headers"], {"X-Api-Key": "api-value", "X-Secret-Key": "secret-value"})
        self.assertFalse(calls["set_global_tracer_provider"])
        self.assertEqual(provider.scope, "ican-test")
        self.assertEqual(tracer.name, "test-span")
        self.assertEqual(span.attributes["api_key"], "[REDACTED]")
        self.assertEqual(str(span.exceptions[0]), "authorization: Bearer [REDACTED]")
        self.assertTrue(span.ended)
        self.assertEqual(os.environ.get("FI_BASE_URL"), previous_base_url)

    async def test_remote_export_failure_degrades_with_redacted_error(self) -> None:
        class BrokenTracer:
            def start_span(self, name: str) -> None:
                del name
                raise RuntimeError("authorization: Bearer super-secret-token")

        runtime = FutureAGIRuntime(
            module=SimpleNamespace(),
            provider=SimpleNamespace(),
            tracer=BrokenTracer(),
        )
        sink = FutureAGISink(
            FutureAGIConfig(enabled=True, api_key="api", secret_key="secret"),
            fallback=self.local,
        )
        event = TelemetryEvent(event_type="test", name="broken", trace_id="trace-2")
        with patch("app.observability.futureagi.register_runtime", return_value=runtime):
            sink.emit_sync(event)

        self.assertEqual(sink.backend, "local")
        self.assertIn("Bearer [REDACTED]", sink.last_error or "")
        self.assertNotIn("super-secret-token", sink.last_error or "")
        self.assertTrue(any(item.name == "broken" for item in self.local.recent()))

    async def test_error_fields_are_redacted_at_model_boundary(self) -> None:
        event = TelemetryEvent(
            event_type="test",
            name="error",
            trace_id="trace-3",
            error_message='token="top-secret" sk-abcdefghijklmnop',
        )
        health = ObservabilityHealth(
            backend="local",
            configured=False,
            last_error="api_key=top-secret",
        )
        self.assertNotIn("top-secret", event.error_message or "")
        self.assertNotIn("abcdefghijklmnop", event.error_message or "")
        self.assertNotIn("top-secret", health.last_error or "")


if __name__ == "__main__":
    unittest.main()
