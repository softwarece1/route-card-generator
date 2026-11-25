"""Security headers middleware for VAPT hardening."""
import base64
import hashlib
import re
from pathlib import Path

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

_SCRIPT_RE = re.compile(r"<script>(.*?)</script>", re.DOTALL)


def _script_hashes() -> list[str]:
    """sha256 hashes of inline theme scripts so script-src can drop unsafe-inline."""
    root = Path(__file__).resolve().parents[3]
    paths = [
        root / "frontend" / "index.html",
        root / "frontend" / "dist" / "index.html",
    ]
    found: list[str] = []
    seen: set[str] = set()
    for path in paths:
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        for match in _SCRIPT_RE.finditer(text):
            digest = hashlib.sha256(match.group(1).encode("utf-8")).digest()
            token = "sha256-" + base64.b64encode(digest).decode("ascii")
            if token not in seen:
                seen.add(token)
                found.append(f"'{token}'")
    return found


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp):
        super().__init__(app)
        script_sources = " ".join(["'self'", *_script_hashes()])
        # No inline-script hash (theme bootstrap missing) — keep the UI usable.
        if script_sources == "'self'":
            script_sources = "'self' 'unsafe-inline'"
        self.csp = (
            "default-src 'self'; "
            f"script-src {script_sources}; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; "
            "font-src 'self' data:; "
            "frame-ancestors 'none';"
        )

    async def dispatch(self, request: Request, call_next):
        response: Response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = self.csp
        return response
