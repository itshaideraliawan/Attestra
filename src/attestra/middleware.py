"""HTTP request context middleware."""

from uuid import UUID, uuid4

import structlog
from starlette.types import ASGIApp, Message, Receive, Scope, Send


class RequestIdMiddleware:
    """Bind a request ID to each request and include it in the response."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers", []))
        request_id = headers.get(b"x-request-id", b"").decode("ascii", errors="ignore").strip()
        try:
            parsed_request_id = UUID(request_id)
        except ValueError:
            request_id = str(uuid4())
        else:
            request_id = (
                str(parsed_request_id)
                if len(request_id) == 36 and str(parsed_request_id) == request_id.lower()
                else str(uuid4())
            )

        scope.setdefault("state", {})["request_id"] = request_id

        structlog.contextvars.bind_contextvars(request_id=request_id)

        async def send_with_request_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                response_headers = list(message.get("headers", []))
                response_headers.append((b"x-request-id", request_id.encode("ascii")))
                message["headers"] = response_headers
            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        finally:
            structlog.contextvars.clear_contextvars()
