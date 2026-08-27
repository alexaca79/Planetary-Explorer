"""HTTP boundary middleware for request limits and response security headers."""

from __future__ import annotations

import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.datastructures import Headers
from starlette.requests import Request
from starlette.responses import JSONResponse, Response


DEFAULT_MAX_REQUEST_BODY_BYTES = 32 * 1024 * 1024
_BODY_METHODS = {"PATCH", "POST", "PUT"}
_HEALTH_PROBE_PATHS = frozenset({"/api/health"})


class HealthProbeTrustedHostMiddleware(TrustedHostMiddleware):
    """Apply trusted-host checks except for Azure's read-only health probe."""

    async def __call__(self, scope, receive, send) -> None:
        if (
            scope["type"] == "http"
            and scope.get("method") in {"GET", "HEAD"}
            and scope.get("path") in _HEALTH_PROBE_PATHS
        ):
            await self.app(scope, receive, send)
            return
        await super().__call__(scope, receive, send)


def apply_security_headers(response: Response, request: Request) -> Response:
    """Apply browser security headers to a response."""
    request_id = getattr(request.state, "request_id", None) or uuid.uuid4().hex
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault(
        "Permissions-Policy",
        "camera=(), microphone=(), geolocation=(self)",
    )
    response.headers.setdefault("X-Request-ID", request_id)

    if request.url.path.startswith("/api/"):
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'",
        )
        if not request.url.path.startswith("/api/pro/tile/"):
            response.headers.setdefault("Cache-Control", "no-store")

    forwarded_proto = request.headers.get("x-forwarded-proto", "").split(",", 1)[0].strip()
    if request.url.scheme == "https" or forwarded_proto == "https":
        response.headers.setdefault(
            "Strict-Transport-Security",
            "max-age=31536000; includeSubDomains",
        )
    if "server" in response.headers:
        del response.headers["server"]
    return response


class _RequestBodyTooLarge(Exception):
    """Stop request processing once the streamed body exceeds the limit."""


class RequestBodyLimitMiddleware:
    """Reject oversized request bodies before endpoint processing."""

    def __init__(self, app, max_body_bytes: int = DEFAULT_MAX_REQUEST_BODY_BYTES) -> None:
        if max_body_bytes < 1:
            raise ValueError("max_body_bytes must be positive")
        self.app = app
        self._max_body_bytes = max_body_bytes

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http" or scope.get("method") not in _BODY_METHODS:
            await self.app(scope, receive, send)
            return

        content_length = Headers(scope=scope).get("content-length")
        if content_length:
            try:
                declared_bytes = int(content_length)
            except ValueError:
                response = JSONResponse(
                    status_code=400,
                    content={"error": "Invalid Content-Length"},
                )
                await response(scope, receive, send)
                return
            if declared_bytes > self._max_body_bytes:
                response = JSONResponse(
                    status_code=413,
                    content={"error": "Request body too large"},
                )
                await response(scope, receive, send)
                return

        received_bytes = 0

        async def limited_receive():
            nonlocal received_bytes
            message = await receive()
            if message["type"] == "http.request":
                received_bytes += len(message.get("body", b""))
                if received_bytes > self._max_body_bytes:
                    raise _RequestBodyTooLarge
            return message

        try:
            await self.app(scope, limited_receive, send)
        except _RequestBodyTooLarge:
            response = JSONResponse(
                status_code=413,
                content={"error": "Request body too large"},
            )
            await response(scope, receive, send)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Attach a server-generated request ID and response security headers."""

    async def dispatch(self, request: Request, call_next):
        request.state.request_id = uuid.uuid4().hex
        response = await call_next(request)
        return apply_security_headers(response, request)