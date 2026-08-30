"""Compatibility calls for provider runtimes.

The v0.1.3 protocol carries a run token so adapters can cancel exactly one
presentation.  The small signature check keeps older third-party adapters
usable while they migrate to the extended keyword arguments.
"""

from __future__ import annotations

import inspect
from typing import Any

from ..domain.models import AgentResponse, ProviderResult


async def send_text(provider: Any, response: AgentResponse) -> ProviderResult:
    method = provider.send_text
    kwargs: dict[str, Any] = {"mode": "agent_response"}
    if accepts_keyword(method, "run_id"):
        kwargs["run_id"] = response.run_id
    return await method(response.session_id or "", response.text, **kwargs)


async def interrupt(provider: Any, session_id: str, *, run_id: str | None = None) -> ProviderResult:
    method = provider.interrupt
    kwargs = {"run_id": run_id} if accepts_keyword(method, "run_id") else {}
    return await method(session_id, **kwargs)


def accepts_keyword(method: Any, name: str) -> bool:
    """Return whether a bound callable can receive a named keyword."""
    try:
        parameters = inspect.signature(method).parameters.values()
    except (TypeError, ValueError):
        # C-extension or proxy methods are safest when given the new keyword.
        return True
    return any(
        parameter.name == name or parameter.kind is inspect.Parameter.VAR_KEYWORD
        for parameter in parameters
    )
