"""Rejects an oversized request body before routing/parsing.

Pure ASGI middleware (not a Starlette BaseHTTPMiddleware) so it can
respond directly and short-circuit before FastAPI/Pydantic ever reads
the body into memory -- an unbounded JSON/form body is a resource-
consumption vector independent of what any individual field's own
`max_length` eventually bounds, since Starlette buffers the whole body
before validation runs.

Checked via the Content-Length header only, not by consuming the body
stream. This covers the overwhelming majority of real HTTP clients
(every one used by this app's own frontend, and httpx/TestClient in
tests) which always declare Content-Length for a request with a body.
A request that omits it (chunked transfer-encoding) is not covered by
this check -- see SECURITY.md for that residual gap.
"""

from __future__ import annotations

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send


class MaxBodySizeMiddleware:
    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(
        self, scope: Scope, receive: Receive, send: Send
    ) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        content_length = _content_length(scope)

        if content_length is not None and content_length > self.max_bytes:
            response = JSONResponse(
                {"detail": "request body too large"},
                status_code=413,
            )
            await response(scope, receive, send)
            return

        await self.app(scope, receive, send)


def _content_length(scope: Scope) -> int | None:
    for name, value in scope.get("headers", ()):
        if name == b"content-length":
            try:
                return int(value)
            except ValueError:
                return None
    return None
