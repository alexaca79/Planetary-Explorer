"""HTTP boundary middleware for request limits and response security headers."""

from __future__ import annotations

import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response


DEFAULT_MAX_REQUEST_BODY_BYTES = 32 * 1024 * 1024
_BODY_METHODS = {"PATCH", "POST", "PUT"}


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


class RequestBodyLimitMiddleware(BaseHTTPMiddleware):
    """Reject oversized request bodies before endpoint processing."""

    def __init__(self, app, max_body_bytes: int = DEFAULT_MAX_REQUEST_BODY_BYTES) -> None:
        super().__init__(app)
        if max_body_bytes < 1:
            raise ValueError("max_body_bytes must be positive")
        self._max_body_bytes = max_body_bytes

    async def dispatch(self, request: Request, call_next):
        if request.method not in _BODY_METHODS:
            return await call_next(request)

        content_length = request.headers.get("content-length")
        if content_length:
            try:
                declared_bytes = int(content_length)
            except ValueError:
                return JSONResponse(status_code=400, content={"error": "Invalid Content-Length"})
            if declared_bytes > self._max_body_bytes:
                return JSONResponse(status_code=413, content={"error": "Request body too large"})

        body = await request.body()
        if len(body) > self._max_body_bytes:
            return JSONResponse(status_code=413, content={"error": "Request body too large"})
        return await call_next(request)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Attach a server-generated request ID and response security headers."""

    async def dispatch(self, request: Request, call_next):
        request.state.request_id = uuid.uuid4().hex
        response = await call_next(request)
        return apply_security_headers(response, request)