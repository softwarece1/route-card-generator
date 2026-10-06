"""Standalone Route Card Generator — FastAPI entry."""

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.auth import get_current_user, router as auth_router
from app.config.settings import settings
from app.database.connection import connect_to_db
from app.route_card.router import router as route_card_router


@asynccontextmanager
async def lifespan(_app: FastAPI):
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

# Permit localhost + LAN Vite origins (fixes Network Error via 172.x / 192.168.x)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition", "Content-Type", "Content-Length"],
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
