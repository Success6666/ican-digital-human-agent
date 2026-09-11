"""Internal diagnostics routes for telemetry health and recent events."""

from __future__ import annotations

from typing import Any

from .client_events import ClientTelemetryAck, ClientTelemetryBatch
from .service import ObservabilityService, get_observability

try:
    from fastapi import APIRouter, Depends
except ImportError:  # pragma: no cover
    APIRouter = None  # type: ignore[assignment,misc]
    Depends = None  # type: ignore[assignment]


def _auth_dependency():
    try:
        from app.api.dependencies import require_internal_context

        return require_internal_context
    except ImportError:
        async def require_internal_context(request: Any, x_internal_token: str | None = None):
            del request
            import os

            expected = os.getenv("AGENT_INTERNAL_TOKEN", "dev-agent-internal-token")
            if not x_internal_token or x_internal_token != expected:
                from fastapi import HTTPException

                raise HTTPException(status_code=401, detail="unauthorized")
            return {"user_id": "system", "user_name": "system"}

        return require_internal_context


def build_router(service: ObservabilityService | None = None, *, prefix: str = "/internal/observability"):
    if APIRouter is None:
        return None
    selected = service or get_observability()
    auth_dependency = _auth_dependency()
    api = APIRouter(prefix=prefix, tags=["observability"])

    @api.get("/health")
    async def health(context: dict[str, str] = Depends(auth_dependency)) -> dict[str, Any]:
        del context
        return selected.health().model_dump(mode="json")

    @api.get("/recent")
    async def recent(
        limit: int = 100,
        context: dict[str, str] = Depends(auth_dependency),
    ) -> dict[str, Any]:
        limit = max(1, min(limit, 500))
        return {
            "events": [
                event.model_dump(mode="json")
                for event in selected.recent(limit, owner_id=context["user_id"])
            ]
        }

    @api.get("/traces")
    async def traces(
        limit: int = 30,
        context: dict[str, str] = Depends(auth_dependency),
    ) -> dict[str, Any]:
        return {
            "traces": [
                item.model_dump(mode="json")
                for item in selected.trace_summaries(limit=limit, owner_id=context["user_id"])
            ]
        }

    @api.post("/events")
    async def ingest_events(
        batch: ClientTelemetryBatch,
        context: dict[str, str] = Depends(auth_dependency),
    ) -> dict[str, Any]:
        """Accept browser-reported markers into the owner-scoped trace buffer."""
        try:
            accepted = selected.ingest_client_events(
                batch.events,
                owner_id=context["user_id"],
                session_id=_optional(batch.session_id),
                connection_id=_optional(batch.connection_id),
            )
        except Exception as exc:  # pragma: no cover - defensive boundary
            return ClientTelemetryAck(
                accepted=0, rejected=len(batch.events), reason=str(exc)
            ).model_dump(mode="json")
        return ClientTelemetryAck(accepted=accepted, rejected=0).model_dump(mode="json")

    @api.get("/traces/{trace_id}")
    async def trace_replay(
        trace_id: str,
        context: dict[str, str] = Depends(auth_dependency),
    ) -> dict[str, Any]:
        if not _valid_trace_id(trace_id):
            from fastapi import HTTPException

            raise HTTPException(status_code=422, detail="invalid trace id")
        result = selected.trace_replay(trace_id, owner_id=context["user_id"])
        if result is None:
            from fastapi import HTTPException

            raise HTTPException(status_code=404, detail="trace not found")
        return result.model_dump(mode="json")

    return api


router = build_router()


def _valid_trace_id(value: str) -> bool:
    return 1 <= len(value) <= 128 and all(char.isalnum() or char in "-_" for char in value)


def _optional(value: str | None) -> str | None:
    clean = (value or "").strip()
    return clean[:128] if clean else None


__all__ = ["build_router", "router"]
