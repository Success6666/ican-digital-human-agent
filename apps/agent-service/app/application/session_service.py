"""Session lifecycle use cases."""

from __future__ import annotations

import asyncio
from uuid import uuid4

from ..avatar.errors import ProviderError
from ..avatar.registry import ProviderRegistry
from ..avatar.runtime_calls import interrupt as interrupt_provider
from ..domain.models import AvatarSession, SessionRecord, SessionStatus
from ..domain.ports import SessionStore
from ..infrastructure.session_operations import SessionOperationRegistry
from .errors import ProviderUnavailableError, SessionNotFoundError, SessionOwnershipError


class SessionApplicationService:
    def __init__(self, *, providers: ProviderRegistry, store: SessionStore) -> None:
        self.providers = providers
        self.store = store
        self._operations = SessionOperationRegistry()

    async def create(self, *, user_id: str, provider_name: str) -> AvatarSession:
        try:
            provider = self.providers.get(provider_name)
            session = await provider.create_session(user_id)
        except ProviderError as exc:
            raise ProviderUnavailableError(str(exc)) from exc
        await self.store.create(session)
        return session

    async def get_for_user(self, *, user_id: str, session_id: str) -> SessionRecord:
        record = await self.store.get(session_id)
        if record is None:
            raise SessionNotFoundError("session expired or not found")
        self._ensure_owner(record, user_id)
        return record

    async def begin_run(self, *, user_id: str, session_id: str) -> str:
        """Start a fresh run so an interrupted session can continue later."""
        record = await self.get_for_user(user_id=user_id, session_id=session_id)
        begin = getattr(self.store, "begin_run", None)
        if begin is not None:
            run_id = await begin(session_id)
        else:  # compatibility for older store adapters
            touch = getattr(self.store, "touch", None)
            if touch is not None:
                try:
                    await touch(session_id, clear_interrupt=True)
                except TypeError:
                    await touch(session_id)
            record.interrupted = False
            run_id = uuid4().hex
        if not run_id:
            raise SessionNotFoundError("session is not available")
        return str(run_id)

    async def interrupt(
        self,
        *,
        user_id: str,
        session_id: str,
        run_id: str | None = None,
    ) -> AvatarSession:
        async with self._operations.hold(session_id):
            return await self._interrupt_serialized(
                user_id=user_id,
                session_id=session_id,
                run_id=run_id,
            )

    async def _interrupt_serialized(
        self,
        *,
        user_id: str,
        session_id: str,
        run_id: str | None,
    ) -> AvatarSession:
        record = await self.get_for_user(user_id=user_id, session_id=session_id)
        if record.session.status == SessionStatus.CLOSED:
            return record.session
        is_closing = getattr(self.store, "is_closing", None)
        if callable(is_closing) and await is_closing(session_id):
            # A close claim has already invalidated the run and owns provider
            # teardown. Do not issue a second remote interrupt concurrently.
            return record.session
        active_run_id = record.active_run_id
        # A delayed interrupt from an older browser stream must never stop a
        # newer run in the same session.  Missing run_id keeps the v0.1 API
        # behavior and targets the currently active run.
        if run_id is not None and active_run_id not in {None, run_id}:
            return record.session
        target_run_id = run_id or active_run_id
        # Publish the interruption before calling the provider so an in-flight
        # graph run observes the token change without waiting on remote I/O.
        updated = await self.store.mark_interrupted(session_id, run_id=target_run_id)
        if updated is None:
            return record.session
        if callable(is_closing) and await is_closing(session_id):
            return updated.session
        # The store may return a newer generation after a same-id rebuild;
        # never expose that generation to the caller before rechecking owner.
        self._ensure_owner(updated, user_id)
        if target_run_id is not None and updated.active_run_id not in {None, target_run_id}:
            return updated.session
        # Resolve the provider from the state that survived the ownership and
        # run checks. A session id can be rebuilt while the store operation is
        # in flight; using the initial snapshot could interrupt the old SDK
        # runtime instead of the current generation.
        provider = self.providers.get(updated.session.provider)
        try:
            await interrupt_provider(provider, session_id, run_id=target_run_id)
        except ProviderError as exc:
            raise ProviderUnavailableError(str(exc)) from exc
        return (updated or record).session

    async def mark_run_interrupted(self, *, session_id: str, run_id: str | None) -> None:
        """Invalidate a run after its transport disconnects.

        This path intentionally skips remote Provider I/O: the graph task is
        already being cancelled, and the store token is the authoritative
        guard against any late result.
        """
        await self.store.mark_interrupted(session_id, run_id=run_id)

    async def close(self, *, user_id: str, session_id: str) -> AvatarSession | None:
        async with self._operations.hold(session_id):
            return await self._close_serialized(user_id=user_id, session_id=session_id)

    async def _close_serialized(self, *, user_id: str, session_id: str) -> AvatarSession | None:
        record = await self.store.get(session_id)
        if record is None:
            # DELETE is intentionally idempotent for an already-expired session.
            return None
        self._ensure_owner(record, user_id)
        close_claim_token: str | None = None
        if record.session.status != SessionStatus.CLOSED:
            # Claim the close atomically before touching the remote runtime.
            # Provider teardown can be slow; keeping the claim authoritative
            # prevents a new run from being created in the teardown window.
            claim_close_token = getattr(self.store, "claim_close_token", None)
            claim_close = getattr(self.store, "claim_close", None)
            if callable(claim_close_token):
                # New stores return a generation token so a stale teardown
                # cannot complete or abort a replacement claim for this id.
                close_claim_token = await claim_close_token(session_id)
                claimed = close_claim_token is not None
            elif callable(claim_close):
                # Compatibility path for stores that only expose the v0.1
                # boolean claim API.
                claimed = await claim_close(session_id)
            else:
                claimed = True
            if callable(claim_close_token) or callable(claim_close):
                if not claimed:
                    is_closing = getattr(self.store, "is_closing", None)
                    if callable(is_closing) and await is_closing(session_id):
                        wait_for_close = getattr(self.store, "wait_for_close", None)
                        if callable(wait_for_close):
                            await wait_for_close(session_id)
                    latest = await self.store.get(session_id)
                    if latest is not None:
                        self._ensure_owner(latest, user_id)
                    return latest.session if latest is not None else None
            else:
                # Compatibility path for stores that predate close claims.
                await self.store.mark_interrupted(session_id, run_id=record.active_run_id)
            try:
                provider = self.providers.get(record.session.provider)
                await provider.close_session(session_id)
            except ProviderError as exc:
                await self._abort_close_claim(session_id, close_claim_token)
                raise ProviderUnavailableError(str(exc)) from exc
            except asyncio.CancelledError:
                await self._abort_close_claim(session_id, close_claim_token)
                raise
            except Exception:
                # Custom SDK adapters are not required to normalize every
                # exception to ProviderError. Never leave the atomic close
                # lease stuck when one of them fails unexpectedly.
                await self._abort_close_claim(session_id, close_claim_token)
                raise ProviderUnavailableError("provider teardown failed")
        complete_close = getattr(self.store, "complete_close", None)
        if callable(complete_close):
            try:
                if close_claim_token is None:
                    updated = await complete_close(session_id)
                else:
                    updated = await complete_close(session_id, claim_token=close_claim_token)
            except asyncio.CancelledError:
                # A cancellation after provider teardown must not strand the
                # close lease and block every later operation on this id.
                await self._abort_close_claim(session_id, close_claim_token)
                raise
            except Exception:
                await self._abort_close_claim(session_id, close_claim_token)
                raise
            if updated is None:
                # The close claim may have been replaced by a newly-created
                # session with the same id. Never apply the old teardown to
                # that new record, and return its current state if present.
                latest = await self.store.get(session_id)
                if latest is not None:
                    self._ensure_owner(latest, user_id)
                return latest.session if latest is not None else None
        else:
            updated = await self.store.close(session_id)
        return (updated or record).session

    async def cleanup_expired(self) -> int:
        expired = await self.store.remove_expired()
        for record in expired:
            async with self._operations.hold(record.session.session_id):
                if record.session.status == SessionStatus.CLOSED:
                    continue
                try:
                    await self.providers.get(record.session.provider).close_session(record.session.session_id)
                except Exception:
                    # Cleanup must continue even when a remote runtime is unavailable.
                    continue
        return len(expired)

    @staticmethod
    def _ensure_owner(record: SessionRecord, user_id: str) -> None:
        if record.session.user_id != user_id:
            raise SessionOwnershipError("session does not belong to user")

    async def _abort_close_claim(self, session_id: str, claim_token: str | None = None) -> None:
        abort_close = getattr(self.store, "abort_close", None)
        if not callable(abort_close):
            return
        try:
            if claim_token is None:
                await abort_close(session_id)
            else:
                await abort_close(session_id, claim_token=claim_token)
        except Exception:
            # Preserve the provider error and avoid leaving the request with
            # an unrelated cleanup exception. The store remains replaceable;
            # a later cleanup pass can repair an unavailable backend.
            return
