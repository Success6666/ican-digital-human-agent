from __future__ import annotations

import pytest
from starlette.types import Message, Receive, Scope, Send

from app.api.body_limit import RequestBodyLimitMiddleware


@pytest.mark.asyncio
async def test_chunked_body_is_rejected_at_receive_boundary() -> None:
    sent: list[Message] = []
    consumed = False

    async def app(scope: Scope, receive: Receive, send: Send) -> None:
        nonlocal consumed
        consumed = True
        while True:
            message = await receive()
            if message["type"] == "http.request" and not message.get("more_body", False):
                break
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    messages = iter(
        [
            {"type": "http.request", "body": b"1234", "more_body": True},
            {"type": "http.request", "body": b"56", "more_body": False},
        ]
    )

    async def receive() -> Message:
        return next(messages)

    async def send(message: Message) -> None:
        sent.append(message)

    scope: Scope = {"type": "http", "method": "POST", "headers": []}
    await RequestBodyLimitMiddleware(app, max_bytes=5)(scope, receive, send)

    assert consumed is True
    assert sent[0]["status"] == 413
    assert b"request body exceeds 5 bytes" in sent[1]["body"]


@pytest.mark.asyncio
async def test_content_length_is_rejected_without_calling_app() -> None:
    called = False

    async def app(scope: Scope, receive: Receive, send: Send) -> None:
        nonlocal called
        called = True

    sent: list[Message] = []

    async def receive() -> Message:
        return {"type": "http.request", "body": b""}

    async def send(message: Message) -> None:
        sent.append(message)

    scope: Scope = {
        "type": "http",
        "method": "POST",
        "headers": [(b"content-length", b"6")],
    }
    await RequestBodyLimitMiddleware(app, max_bytes=5)(scope, receive, send)

    assert called is False
    assert sent[0]["status"] == 413
