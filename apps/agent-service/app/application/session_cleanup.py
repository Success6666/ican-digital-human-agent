"""Expired-session cleanup orchestration and retry handling."""

from __future__ import annotations

import asyncio

from ..avatar.registry import ProviderRegistry
from ..domain.models import SessionRecord, SessionStatus
from ..domain.ports import SessionStore
from ..infrastructure.provider_lifecycle import ProviderLifecycleRegistry
from ..infrastructure.session_operations import SessionOperationRegistry


class SessionCleanupCoordinator:
    """Detach expired records and close their remote provider runtimes."""

    def __init__(
        self,
        *,
        providers: ProviderRegistry,
        store: SessionStore,
        operations: SessionOperationRegistry,
        provider_lifecycle: ProviderLifecycleRegistry,
    ) -> None:
        self.providers = providers
        self.store = store
        self._operations = operations
        self._provider_lifecycle = provider_lifecycle

    async def run(self) -> int:
        expired = await self.store.remove_expired()
        claim_cleanup = getattr(self.store, "claim_expired_cleanup", None)
        finish_cleanup = getattr(self.store, "finish_expired_cleanup", None)
        requeue_cleanup = getattr(self.store, "requeue_expired", None)
        for index, record in enumerate(expired):
            provider_succeeded = False
            record_requeued = False
            try:
                async with self._operations.hold(record.session.session_id):
                    if record.session.status == SessionStatus.CLOSED:
                        continue
                    # Keep provider -> generation ordering aligned with create.
                    # Reversing it can deadlock a slow cleanup against a create
                    # waiting inside the store's generation admission lock.
                    async with self._provider_lifecycle.hold(record.session.provider):
                        generation_id = getattr(record, "generation_id", None)
                        claimed = True
                        if callable(claim_cleanup):
                            claimed = await claim_cleanup(record.session.session_id, generation_id)
                        if not claimed:
                            # The id has already been reused by a newer
                            # generation; never close that newer runtime.
                            continue
                        try:
                            await self.providers.get(record.session.provider).close_session(
                                record.session.session_id
                            )
                            provider_succeeded = True
                        except asyncio.CancelledError:
                            record_requeued = await self._requeue_expired(requeue_cleanup, record)
                            raise
                        except Exception:
                            # A transient SDK/network failure remains actionable
                            # for the next cleanup pass.
                            record_requeued = await self._requeue_expired(requeue_cleanup, record)
                        finally:
                            if callable(finish_cleanup):
                                await self._finish_expired_cleanup(
                                    finish_cleanup,
                                    record.session.session_id,
                                    generation_id,
                                )
            except asyncio.CancelledError:
                # Cancellation while waiting on either lock must not lose this
                # snapshot or any records that have not been visited yet.
                if not provider_succeeded and not record_requeued:
                    await self._requeue_expired(requeue_cleanup, record)
                for pending in expired[index + 1 :]:
                    await self._requeue_expired(requeue_cleanup, pending)
                raise
        return len(expired)

    @staticmethod
    async def _requeue_expired(requeue_cleanup: object, record: SessionRecord) -> bool:
        if not callable(requeue_cleanup):
            return False
        operation = asyncio.create_task(requeue_cleanup(record))
        try:
            return bool(await asyncio.shield(operation))
        except asyncio.CancelledError:
            # Let the store operation finish even when the worker itself is
            # cancelled, preserving the snapshot for a later cleanup pass.
            try:
                return bool(await asyncio.shield(operation))
            except asyncio.CancelledError:
                operation.add_done_callback(SessionCleanupCoordinator._consume_task)
                return False
            except Exception:
                return False
        except Exception:
            return False

    @staticmethod
    async def _finish_expired_cleanup(
        finish_cleanup: object,
        session_id: str,
        generation_id: str | None,
    ) -> None:
        operation = asyncio.create_task(finish_cleanup(session_id, generation_id))  # type: ignore[misc]
        try:
            await asyncio.shield(operation)
        except asyncio.CancelledError:
            try:
                await asyncio.shield(operation)
            except asyncio.CancelledError:
                operation.add_done_callback(SessionCleanupCoordinator._consume_task)
            except Exception:
                return
        except Exception:
            return

    @staticmethod
    def _consume_task(operation: asyncio.Task[object]) -> None:
        try:
            operation.result()
        except BaseException:
            return


__all__ = ["SessionCleanupCoordinator"]
