"""Request authentication and service-container dependencies."""

from __future__ import annotations

import hashlib
import re
import secrets
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request, status


def get_container(request: Request):
    return request.app.state.container


async def require_internal_context(
    request: Request,
    internal_token: Annotated[str | None, Header(alias="X-Internal-Token")] = None,
    user_id: Annotated[str | None, Header(alias="X-User-Id")] = None,
    user_name: Annotated[str | None, Header(alias="X-User-Name")] = None,
):
    settings = request.app.state.container.settings
    if not internal_token or not secrets.compare_digest(internal_token, settings.internal_token):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="unauthorized")
    if not user_id or not user_name:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="user context required")
    clean_id = _bounded_header(user_id, identity=True)
    clean_name = _bounded_header(user_name)
    if not clean_id or not clean_name:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="user context required")
    return {"user_id": clean_id, "user_name": clean_name}


def _bounded_header(value: str, *, identity: bool = False) -> str:
    """Strip control characters and preserve uniqueness for oversized IDs."""

    clean = re.sub(r"[\x00-\x1f\x7f]", " ", value).strip()
    if not clean:
        return ""
    if len(clean) <= 128:
        return clean
    digest = hashlib.sha256(clean.encode("utf-8")).hexdigest()[:31]
    prefix_length = 96 if identity else 80
    return f"{clean[:prefix_length]}:{digest}"


InternalContext = Annotated[dict[str, str], Depends(require_internal_context)]
