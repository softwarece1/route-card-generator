"""Standalone Route Card Generator — FastAPI entry."""

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.auth import get_current_user, router as auth_router
from app.config.settings import settings
from app.database.connection import connect_to_db
from app.error_log import ensure_log_dir, log_api_error
from app.route_card.router import router as route_card_router


@asynccontextmanager
async def lifespan(_app: FastAPI):
    try:
        ensure_log_dir()
    except Exception:
        pass
    connect_to_db()
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


app = FastAPI(
    title="Route Card Generator",
    description="Standalone Route Card Generator (offline PDF ingest: PyMuPDF + pdfplumber + optional Tesseract OCR).",
    version="1.0.0",
    lifespan=lifespan,
)

from app.middleware import IdleSessionMiddleware, SecurityHeadersMiddleware
from app.middleware.rate_limit import limiter, SlowAPIMiddleware

# Configure CORS using explicit origins from settings
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition", "Content-Type", "Content-Length"],
)

# Register security middlewares
app.add_middleware(IdleSessionMiddleware)
app.add_middleware(SecurityHeadersMiddleware)

# Register rate limiting middleware and error handler
from slowapi.errors import RateLimitExceeded
from slowapi import _rate_limit_exceeded_handler

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)


def _skip_error_log(request: Request, status_code: int) -> bool:
    path = request.url.path or ""
    if path.rstrip("/") in {"/health", "/docs", "/openapi.json", "/redoc"}:
        return True
    # Idle / auth probes are noisy; still log real auth failures at 403+
    if status_code == 401 and path.startswith("/api/v1/auth/"):
        return True
    return False


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    if not _skip_error_log(request, exc.status_code):
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

_protect = [Depends(get_current_user)] if settings.AUTH_ENABLED else []
app.include_router(route_card_router, dependencies=_protect)


@app.get("/health")
def health():
    try:
        from app.route_card import admin_ops

        return admin_ops.health_extended()
    except Exception:
        return {"status": "ok", "auth_enabled": settings.AUTH_ENABLED}
