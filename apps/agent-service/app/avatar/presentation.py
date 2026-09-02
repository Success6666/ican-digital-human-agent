"""Presentation boundary between Agent Core and digital-human runtimes."""

from __future__ import annotations

import asyncio
from typing import Protocol

from ..domain.models import AgentResponse, ProviderResult
from ..domain.ports import AvatarProvider
from ..messaging import ReliableMessageBus
from .runtime_calls import send_text


class DigitalHumanRuntime(Protocol):
    """Runtime contract consumed by the presentation boundary."""

    name: str

    async def present(self, response: AgentResponse) -> ProviderResult: ...


class PresentationLayer:
    """Render a semantic AgentResponse through a provider adapter.

    Provider SDK details stay behind ``AvatarProvider``.  This layer is the
    only place where a graph response becomes a runtime operation, making a
    future Fay or vendor SDK replacement independent from LangGraph nodes.
    """

    def __init__(self, publisher: ReliableMessageBus | None = None) -> None:
        self.publisher = publisher

    async def present(self, runtime: AvatarProvider, response: AgentResponse) -> ProviderResult:
        if self.publisher is not None:
            task = asyncio.create_task(
                self.publisher.publish(topic="presentation", payload=response.model_dump(mode="json", by_alias=True))
            )
            task.add_done_callback(_consume_task)
        result = await send_text(runtime, response)
        result.metadata = {
            **result.metadata,
            "agentResponse": response.model_dump(mode="json", by_alias=True),
            "performance": response.performance,
        }
        return result


def _consume_task(task: asyncio.Task[object]) -> None:
    try:
        task.result()
    except BaseException:
        return


class ProviderRuntime:
    """Expose an AvatarProvider as a replaceable digital-human runtime."""

    def __init__(self, provider: AvatarProvider, presentation: PresentationLayer | None = None) -> None:
        self.provider = provider
        self.presentation = presentation or PresentationLayer()
        self.name = provider.name

    async def present(self, response: AgentResponse) -> ProviderResult:
        return await self.presentation.present(self.provider, response)
