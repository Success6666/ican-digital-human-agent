"""Small, shared helpers used while constructing the Agent graph."""

from __future__ import annotations

from contextlib import nullcontext
from typing import Any

from ..agent.models import IntentDecision, ToolRoutePlan
from ..agent.steering import RunToken, should_stop
from ..domain.ports import SessionStore
from ..observability.redaction import redact_text
from .state import AgentGraphState


def tool_arguments(name: str, message: str) -> dict[str, Any]:
    return {"message": message} if name == "echo" else {}


def decision_from_state(state: AgentGraphState) -> IntentDecision | None:
    value = state.get("intent")
    if not value:
        return None
    return value if isinstance(value, IntentDecision) else IntentDecision.model_validate(value)


def plan_from_state(state: AgentGraphState) -> ToolRoutePlan | None:
    value = state.get("tool_plan")
    if not value:
        return None
    return value if isinstance(value, ToolRoutePlan) else ToolRoutePlan.model_validate(value)


async def stopped(sessions: SessionStore, state: AgentGraphState) -> bool:
    token = run_token(state)
    return await should_stop(sessions, token)


def attrs(state: AgentGraphState, values: dict[str, Any]) -> dict[str, Any]:
    return {"owner_id": state.get("user_id", "unknown"), "run_id": state.get("run_id"), **values}


def span_context(
    observer: Any | None,
    factory: str,
    name: str,
    attributes: dict[str, Any],
    *,
    provider: str | None = None,
):
    if observer is None:
        return nullcontext()
    method = getattr(observer, factory)
    if factory == "provider_event":
        return method(provider or "unknown", name, attributes=attributes)
    return method(name, attributes=attributes)


def safe_error(exc: Exception) -> str:
    raw = str(exc).strip()
    message = raw.splitlines()[0] if raw else exc.__class__.__name__
    return redact_text(message, max_length=300) or exc.__class__.__name__


def run_token(state: AgentGraphState) -> RunToken | None:
    run_id = state.get("run_id")
    if not run_id:
        return None
    return RunToken(session_id=state["session_id"], run_id=run_id)


__all__ = [
    "attrs",
    "decision_from_state",
    "plan_from_state",
    "run_token",
    "safe_error",
    "span_context",
    "stopped",
    "tool_arguments",
]
