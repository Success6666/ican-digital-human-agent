"""Helpers for releasing failed remote close claims."""

from __future__ import annotations


async def abort_close_claim(
    store: object,
    session_id: str,
    claim_token: str | None = None,
) -> None:
    """Release a claim without masking the original provider failure."""

    abort_close = getattr(store, "abort_close", None)
    if not callable(abort_close):
        return
    try:
        if claim_token is None:
            await abort_close(session_id)
        else:
            await abort_close(session_id, claim_token=claim_token)
    except Exception:
        # A later cleanup pass can repair an unavailable store backend.
        return


__all__ = ["abort_close_claim"]
