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
        self._client: Any = None
        self._response: Any = None

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


_jobs: dict[int, AnalyzeJob] = {}
_jobs_lock = threading.Lock()
_tls = threading.local()


def start_job(session_id: int) -> AnalyzeJob:
    job = AnalyzeJob(session_id)
    with _jobs_lock:
        prev = _jobs.get(int(session_id))
        if prev is not None:
            prev.request_cancel()
        _jobs[int(session_id)] = job
    _tls.job = job
    return job


def end_job(session_id: int) -> None:
    sid = int(session_id)
    with _jobs_lock:
        cur = _jobs.get(sid)
        if cur is not None and cur.session_id == sid:
            _jobs.pop(sid, None)
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
