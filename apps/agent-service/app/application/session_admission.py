"""Admission helpers for balancing remote provider session lifecycles."""

from __future__ import annotations

import asyncio
from typing import Any

from ..domain.ports import AvatarProvider


async def rollback_provider_session(provider: AvatarProvider, session_id: str) -> None:
    """Best-effort remote cleanup when local session admission fails."""

    try:
        operation = asyncio.create_task(provider.close_session(session_id))
        await asyncio.shield(operation)
    except asyncio.CancelledError:
        # Preserve the teardown across the first cancellation so a later
        # create cannot race an unfinished rollback.
        try:
            await asyncio.shield(operation)
        except asyncio.CancelledError:
            operation.add_done_callback(_consume_task)
        except Exception:
            pass
        raise
    except Exception:
        # Admission errors retain their original meaning even when provider
        # rollback is unavailable.
        return


def _consume_task(operation: asyncio.Task[Any]) -> None:
    try:
        operation.result()
    except BaseException:
        return


__all__ = ["rollback_provider_session"]
