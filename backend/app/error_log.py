"""Append API errors to backend/.logs for offline diagnosis."""

from __future__ import annotations

import re
import threading
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import Request

from app.config.settings import settings

_lock = threading.Lock()
_SESSION_RE = re.compile(r"/sessions/(\d+)", re.IGNORECASE)


def log_dir() -> Path:
    raw = (getattr(settings, "ERROR_LOG_DIR", None) or "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    # backend/.logs (this file lives in backend/app/)
    return Path(__file__).resolve().parents[1] / ".logs"


def ensure_log_dir() -> Path:
    path = log_dir()
    path.mkdir(parents=True, exist_ok=True)
    return path


def _client_ip(request: Request) -> str:
    forwarded = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
    if forwarded:
        return forwarded
    if request.client:
        return request.client.host or ""
    return ""


def _safe_jwt_claims(request: Request) -> dict[str, Any]:
    """Best-effort user identity from Bearer token — never raises."""
    auth = request.headers.get("authorization") or ""
    if not auth.lower().startswith("bearer "):
        return {}
    token = auth.split(" ", 1)[1].strip()
    if not token:
        return {}
    try:
        from jose import jwt

        payload = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.ALGORITHM],
            options={"verify_exp": False},
        )
        return {
            "empId": payload.get("sub") or "",
            "userId": payload.get("uid"),
            "role": payload.get("role") or "",
            "jti": payload.get("jti") or "",
        }
    except Exception:
        return {}


def _session_id_from_path(path: str) -> str:
    m = _SESSION_RE.search(path or "")
    return m.group(1) if m else ""


def _format_detail(detail: Any) -> str:
    if detail is None:
        return ""
    if isinstance(detail, str):
        return detail
    try:
        import json

        return json.dumps(detail, ensure_ascii=False, default=str)
    except Exception:
        return str(detail)


def log_api_error(
    request: Request | None,
    *,
    status_code: int,
    error: str,
    detail: Any = None,
    exc: BaseException | None = None,
    extra: dict | None = None,
) -> None:
    """Write one human-readable error block into a daily log file."""
    try:
        folder = ensure_log_dir()
        now = datetime.now(timezone.utc).astimezone()
        path = folder / f"errors-{now.strftime('%Y-%m-%d')}.log"

        method = getattr(request, "method", "") if request else ""
        api_path = ""
        query = ""
        if request is not None:
            api_path = request.url.path
            query = str(request.url.query or "")
        api = f"{method} {api_path}".strip()
        if query:
            api = f"{api}?{query}"

        user = _safe_jwt_claims(request) if request else {}
        session_id = _session_id_from_path(api_path)
        client = _client_ip(request) if request else ""

        lines = [
            f"----- {now.isoformat(timespec='seconds')} -----",
            f"API: {api or '(unknown)'}",
            f"Status: {status_code}",
            (
                "User: "
                f"empId={user.get('empId') or '-'} "
                f"userId={user.get('userId') if user.get('userId') is not None else '-'} "
                f"role={user.get('role') or '-'} "
                f"jti={(user.get('jti') or '-')[:12]}"
            ),
            f"Session: {session_id or '-'}",
            f"Client: {client or '-'}",
            f"Error: {error or '-'}",
        ]
        detail_text = _format_detail(detail)
        if detail_text and detail_text != error:
            lines.append(f"Detail: {detail_text}")
        if extra:
            for k, v in extra.items():
                lines.append(f"{k}: {v}")
        if exc is not None:
            lines.append("Traceback:")
            lines.append(
                "".join(
                    traceback.format_exception(type(exc), exc, exc.__traceback__)
                ).rstrip()
            )
        lines.append("")

        block = "\n".join(lines) + "\n"
        with _lock:
            with path.open("a", encoding="utf-8") as fh:
                fh.write(block)
                fh.flush()
    except Exception:
        # Logging must never break the API response path
        pass
