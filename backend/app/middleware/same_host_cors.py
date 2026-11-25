"""Reflect credentialed CORS for the server's own IP, not every IP on the network.

Static allow-list and loopback origins are handled by CORSMiddleware.
This middleware covers the plant case: the browser opens the UI at
http://<this-host>:<ui-port> and calls http://<this-host>:<api-port>.
A page hosted on a different machine is not reflected.
"""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.config.settings import origin_is_allowed


def _apply(response: Response, origin: str, request: Request) -> None:
    response.headers["Access-Control-Allow-Origin"] = origin
    response.headers["Access-Control-Allow-Credentials"] = "true"
    response.headers["Access-Control-Expose-Headers"] = (
        "Content-Disposition, Content-Type, Content-Length"
    )
    vary = response.headers.get("vary")
    if not vary:
        response.headers["Vary"] = "Origin"
    elif "origin" not in vary.lower():
        response.headers["Vary"] = f"{vary}, Origin"
    if request.method.upper() == "OPTIONS":
        response.headers["Access-Control-Allow-Methods"] = (
            request.headers.get("access-control-request-method") or "*"
        )
        response.headers["Access-Control-Allow-Headers"] = (
            request.headers.get("access-control-request-headers") or "*"
        )
        response.headers["Access-Control-Max-Age"] = "600"


def _same_host_only(origin: str, host: str) -> bool:
    """True when the origin is allowed only because it matches this request's host."""
    if origin_is_allowed(origin, None):
        return False
    return origin_is_allowed(origin, host)


class SameHostCorsMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        origin = (request.headers.get("origin") or "").strip().rstrip("/")
        host = request.headers.get("host") or ""
        if not origin or not _same_host_only(origin, host):
            return await call_next(request)
        if request.method.upper() == "OPTIONS" and request.headers.get(
            "access-control-request-method"
        ):
            response = Response(status_code=204)
            _apply(response, origin, request)
            return response
        response = await call_next(request)
        _apply(response, origin, request)
        return response
