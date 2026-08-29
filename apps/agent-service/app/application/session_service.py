"""Session lifecycle use cases."""

from __future__ import annotations

from uuid import uuid4

from ..avatar.errors import ProviderError
from ..avatar.registry import ProviderRegistry
from ..domain.models import AvatarSession, SessionRecord, SessionStatus
from ..domain.ports import SessionStore
from .errors import ProviderUnavailableError, SessionNotFoundError, SessionOwnershipError


class SessionApplicationService:
    def __init__(self, *, providers: ProviderRegistry, store: SessionStore) -> None:
        self.providers = providers
        self.store = store

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

    async def interrupt(self, *, user_id: str, session_id: str) -> AvatarSession:
        record = await self.get_for_user(user_id=user_id, session_id=session_id)
        if record.session.status == SessionStatus.CLOSED:
            return record.session
        provider = self.providers.get(record.session.provider)
        try:
            await provider.interrupt(session_id)
        except ProviderError as exc:
            raise ProviderUnavailableError(str(exc)) from exc
        updated = await self.store.mark_interrupted(session_id, run_id=record.active_run_id)
        return (updated or record).session

    async def close(self, *, user_id: str, session_id: str) -> AvatarSession | None:
        record = await self.store.get(session_id)
        if record is None:
            # DELETE is intentionally idempotent for an already-expired session.
            return None
        self._ensure_owner(record, user_id)
        if record.session.status != SessionStatus.CLOSED:
            provider = self.providers.get(record.session.provider)
            try:
                await provider.close_session(session_id)
            except ProviderError as exc:
                raise ProviderUnavailableError(str(exc)) from exc
        updated = await self.store.close(session_id)
        return (updated or record).session

    async def cleanup_expired(self) -> int:
        expired = await self.store.remove_expired()
        for record in expired:
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
