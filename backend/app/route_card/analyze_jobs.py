"""In-flight analyze job registry — cancel stops Ollama by closing the HTTP connection."""

from __future__ import annotations

import threading
from typing import Any


class AnalysisCancelled(Exception):
    """Raised when the user cancels analysis or the client disconnects."""


class AnalyzeJob:
    def __init__(self, session_id: int):
        self.session_id = int(session_id)
        self.cancel = threading.Event()
        self._lock = threading.Lock()
        self._cond = threading.Condition(self._lock)
        self._client: Any = None
        self._response: Any = None
        self.progress = 0
        self.message = "Please wait — preparing documents…"
        self.detail = ""
        self.counts: dict[str, Any] = {}
        self._rev = 0
        self._ended = False

    def request_cancel(self) -> None:
        self.cancel.set()
        with self._lock:
            resp = self._response
            client = self._client
        for closer in (resp, client):
            if closer is None:
                continue
            try:
                closer.close()
            except Exception:
                pass

    def attach_client(self, client: Any) -> None:
        with self._lock:
            self._client = client

    def attach_response(self, response: Any) -> None:
        with self._lock:
            self._response = response

    def clear_http(self) -> None:
        with self._lock:
            self._client = None
            self._response = None

    def update_progress(
        self,
        *,
        progress: int | None = None,
        message: str | None = None,
        detail: str | None = None,
        counts: dict[str, Any] | None = None,
    ) -> None:
        with self._cond:
            changed = False
            if progress is not None:
                try:
                    nxt = max(0, min(100, int(progress)))
                except (TypeError, ValueError):
                    nxt = self.progress
                if nxt != self.progress:
                    self.progress = nxt
                    changed = True
            if message is not None:
                msg = str(message)
                if msg != self.message:
                    self.message = msg
                    changed = True
            if detail is not None:
                det = str(detail)
                if det != self.detail:
                    self.detail = det
                    changed = True
            if counts is not None:
                self.counts = dict(counts)
                changed = True
            if changed:
                self._rev += 1
                self._cond.notify_all()

    def mark_ended(self) -> None:
        with self._cond:
            if self._ended:
                return
            self._ended = True
            self._rev += 1
            self._cond.notify_all()

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "running": not self._ended,
                "progress": self.progress,
                "message": self.message,
                "detail": self.detail,
                "counts": dict(self.counts),
                "done": self._ended,
                "rev": self._rev,
            }

    def wait_snapshot(self, last_rev: int, timeout: float = 1.5) -> dict[str, Any]:
        """Block until progress rev changes or timeout; always returns a snapshot."""
        with self._cond:
            if self._rev == last_rev and not self._ended:
                self._cond.wait(timeout=timeout)
            return {
                "running": not self._ended,
                "progress": self.progress,
                "message": self.message,
                "detail": self.detail,
                "counts": dict(self.counts),
                "done": self._ended,
                "rev": self._rev,
            }


_jobs: dict[int, AnalyzeJob] = {}
_jobs_lock = threading.Lock()
_tls = threading.local()


def start_job(session_id: int) -> AnalyzeJob:
    job = AnalyzeJob(session_id)
    with _jobs_lock:
        prev = _jobs.get(int(session_id))
        if prev is not None:
            prev.request_cancel()
            prev.mark_ended()
        _jobs[int(session_id)] = job
    _tls.job = job
    return job


def end_job(session_id: int) -> None:
    sid = int(session_id)
    cur: AnalyzeJob | None = None
    with _jobs_lock:
        cur = _jobs.get(sid)
        if cur is not None and cur.session_id == sid:
            _jobs.pop(sid, None)
    if cur is not None:
        cur.mark_ended()
    if getattr(_tls, "job", None) is not None and _tls.job.session_id == sid:
        _tls.job = None


def get_job(session_id: int | None = None) -> AnalyzeJob | None:
    if session_id is not None:
        with _jobs_lock:
            return _jobs.get(int(session_id))
    return getattr(_tls, "job", None)


def cancel_job(session_id: int) -> bool:
    job = get_job(session_id)
    if job is None:
        return False
    job.request_cancel()
    return True


def check_cancelled(cancel_event: threading.Event | None = None) -> None:
    ev = cancel_event
    if ev is None:
        job = get_job()
        ev = job.cancel if job else None
    if ev is not None and ev.is_set():
        raise AnalysisCancelled("Analysis cancelled")


def set_progress(
    session_id: int | None = None,
    *,
    progress: int | None = None,
    message: str | None = None,
    detail: str | None = None,
    counts: dict[str, Any] | None = None,
) -> None:
    """Publish live status for the in-flight sync analyze job (best-effort)."""
    job = get_job(session_id)
    if job is None:
        return
    job.update_progress(
        progress=progress,
        message=message,
        detail=detail,
        counts=counts,
    )


def get_progress(session_id: int) -> dict[str, Any]:
    job = get_job(int(session_id))
    if job is None:
        return {
            "running": False,
            "progress": 0,
            "message": "",
            "detail": "",
            "counts": {},
            "done": True,
        }
    return job.snapshot()
