"""Standalone Route Card Generator — FastAPI entry."""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.auth import get_current_user, router as auth_router
from app.auth.csrf import CookieCsrfMiddleware
from app.config.settings import cors_allow_origins, cors_origin_regex, settings
from app.database.connection import connect_to_db
from app.error_log import ensure_log_dir
from app.realtime import ws_router
from app.route_card.router import router as route_card_router
from app.security_startup import assert_runtime_secrets, flag_known_admin_password, is_prod


@asynccontextmanager
async def lifespan(_app: FastAPI):
    assert_runtime_secrets()
    try:
        ensure_log_dir()
    except Exception:
        pass
    connect_to_db()
    flag_known_admin_password()
    try:
        from app.route_card.job_queue import start_queue_worker

        start_queue_worker()
    except Exception:
        pass
    yield
    try:
        from app.route_card.job_queue import stop_queue_worker

        stop_queue_worker()
    except Exception:
        pass


_prod = is_prod()
app = FastAPI(
    title="Route Card Generator",
    description="Standalone Route Card Generator (offline PDF ingest: PyMuPDF + pdfplumber + optional Tesseract OCR).",
    version="1.0.0",
    lifespan=lifespan,
    docs_url=None if _prod else "/docs",
    redoc_url=None if _prod else "/redoc",
    openapi_url=None if _prod else "/openapi.json",
)

from app.middleware import IdleSessionMiddleware, SecurityHeadersMiddleware
from app.middleware.rate_limit import limiter, SlowAPIMiddleware
from app.middleware.same_host_cors import SameHostCorsMiddleware

# CORS — credentials required for httpOnly access cookie.
# Allow-list + loopback regex. SameHostCorsMiddleware reflects the server's own IP.
_cors_kwargs = dict(
    allow_origins=cors_allow_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition", "Content-Type", "Content-Length"],
)
_cors_re = cors_origin_regex()
if _cors_re:
    _cors_kwargs["allow_origin_regex"] = _cors_re
app.add_middleware(CORSMiddleware, **_cors_kwargs)
app.add_middleware(SameHostCorsMiddleware)

app.add_middleware(CookieCsrfMiddleware)
app.add_middleware(IdleSessionMiddleware)
app.add_middleware(SecurityHeadersMiddleware)

from slowapi.errors import RateLimitExceeded
from slowapi import _rate_limit_exceeded_handler

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)


def _skip_error_log(request: Request, status_code: int) -> bool:
    path = request.url.path or ""
    if path.rstrip("/") in {"/health", "/docs", "/openapi.json", "/redoc"}:
        return True
    if status_code == 401 and path.startswith("/api/v1/auth/"):
        return True
    return False


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    if not _skip_error_log(request, exc.status_code):
        from app.error_log import log_api_error

        log_api_error(
            request,
            status_code=exc.status_code,
            error=str(exc.detail) if not isinstance(exc.detail, (dict, list)) else "HTTP error",
            detail=exc.detail,
        )
    headers = getattr(exc, "headers", None) or None
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
        **({"headers": headers} if headers else {}),
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    from app.error_log import log_api_error

    log_api_error(
        request,
        status_code=422,
        error="Request validation failed",
        detail=exc.errors(),
        exc=exc,
    )
    return JSONResponse(status_code=422, content={"detail": exc.errors()})


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    from app.error_log import log_api_error

    log_api_error(
        request,
        status_code=500,
        error=f"{type(exc).__name__}: {exc}",
        exc=exc,
    )
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
    )


app.include_router(auth_router)
app.include_router(ws_router)

_protect = [Depends(get_current_user)] if settings.AUTH_ENABLED else []
app.include_router(route_card_router, dependencies=_protect)


@app.get("/health")
def health():
    return {"status": "ok"}


def _resolve_frontend_dist() -> Path | None:
    raw = (getattr(settings, "FRONTEND_DIST", None) or "").strip()
    if not raw:
        # Default: sibling frontend/dist when running from backend/
        candidates = [
            Path(__file__).resolve().parents[2] / "frontend" / "dist",
            Path.cwd() / "frontend" / "dist",
            Path.cwd().parent / "frontend" / "dist",
        ]
    else:
        p = Path(raw)
        candidates = [p if p.is_absolute() else (Path.cwd() / p)]
    for c in candidates:
        if c.is_dir() and (c / "index.html").is_file():
            return c
    return None


_frontend_dist = _resolve_frontend_dist()
if _frontend_dist is not None:
    _assets = _frontend_dist / "assets"
    if _assets.is_dir():
        app.mount("/assets", StaticFiles(directory=str(_assets)), name="fe_assets")

    @app.get("/{full_path:path}")
    async def spa_fallback(full_path: str):
        """Serve SPA index for non-API routes (same-origin LAN deploy)."""
        if full_path.startswith("api/") or full_path in {
            "docs",
            "openapi.json",
            "redoc",
            "health",
        }:
            return JSONResponse({"detail": "Not Found"}, status_code=404)
        root = _frontend_dist.resolve()
        candidate = (root / full_path).resolve()
        try:
            candidate.relative_to(root)
        except ValueError:
            return JSONResponse({"detail": "Not Found"}, status_code=404)
        if candidate.is_file():
            return FileResponse(candidate)
        index = root / "index.html"
        if not index.is_file():
            return JSONResponse({"detail": "Not Found"}, status_code=404)
        return FileResponse(index)
