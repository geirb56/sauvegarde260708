"""SSE-aware GZip middleware.

Drop-in replacement for ``fastapi.middleware.gzip.GZipMiddleware`` that skips
compression for Server-Sent Events responses so SSE frames are delivered
immediately without ``Content-Encoding: gzip``.

GZip remains active for all other response types.
"""

from __future__ import annotations

from fastapi.middleware.gzip import GZipMiddleware
from starlette.types import Receive, Scope, Send


class SSEAwareGZipMiddleware(GZipMiddleware):
    """GZipMiddleware that bypasses compression for SSE (text/event-stream) responses.

    When a request carries ``Accept: text/event-stream`` or targets a path
    ending with ``/stream``, GZip is skipped entirely so frames are delivered
    immediately and ``Content-Encoding: gzip`` is never set on SSE responses.
    All other responses remain compressed normally (minimum_size=1000).
    """

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            headers = {k.lower(): v for k, v in scope.get("headers", [])}
            accept = headers.get(b"accept", b"").decode("latin-1")
            if "text/event-stream" in accept:
                await self.app(scope, receive, send)
                return
        await super().__call__(scope, receive, send)
