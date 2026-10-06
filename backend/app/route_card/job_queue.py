"""Durable analyze job queue + single VLM worker (Phase 3)."""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime
from typing import Any

from fastapi import HTTPException
from pony.orm import commit, db_session, desc, select

from app.config.settings import settings
from app.route_card.analyze_jobs import cancel_job as cancel_inflight
from app.route_card.analyze_jobs import end_job, start_job
from app.route_card.models import RcAnalyzeJob, RcSession, RcUser

logger = logging.getLogger(__name__)

_worker_thread: threading.Thread | None = None
_worker_stop = threading.Event()
_vlm_lock = threading.Lock()


def job_dict(j: RcAnalyzeJob) -> dict:
    return {
        "id": j.id,
        "sessionId": j.session.id if j.session else None,
        "userId": j.user.id if j.user else None,
        "userEmpId": j.user.emp_id if j.user else None,
        "status": j.status,
        "progress": j.progress,
        "message": j.message or "",
        "errorMessage": j.error_message,
        "vlmPageIndexes": j.vlm_page_indexes,
        "createdAt": j.created_at.isoformat() + "Z" if j.created_at else None,
        "startedAt": j.started_at.isoformat() + "Z" if j.started_at else None,
        "finishedAt": j.finished_at.isoformat() + "Z" if j.finished_at else None,
    }


@db_session
def enqueue_analyze(
    session_id: int,
    user: dict,
    vlm_page_indexes: list[int] | None = None,
) -> dict:
    session = RcSession.get(id=session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    # cancel prior queued for same session
    for prev in select(
        j
        for j in RcAnalyzeJob
        if j.session == session and j.status in ("queued", "running")
    ):
        if prev.status == "queued":
            prev.status = "cancelled"
            prev.finished_at = datetime.utcnow()
            prev.message = "Superseded by newer job"
    u = RcUser.get(id=user["id"]) if user.get("id") else None
    # Pony Optional(Json) rejects explicit None — omit for "auto all pages"
    job_kwargs: dict[str, Any] = {
        "session": session,
        "user": u,
        "status": "queued",
        "progress": 0,
        "message": "Queued",
    }
    if vlm_page_indexes is not None:
        job_kwargs["vlm_page_indexes"] = list(vlm_page_indexes)
    job = RcAnalyzeJob(**job_kwargs)
    session.status = "queued"
    session.updated_at = datetime.utcnow()
    commit()
    return job_dict(job)


@db_session
def enqueue_batch(session_ids: list[int], user: dict) -> dict:
    items = []
    for sid in session_ids:
        try:
            session = RcSession.get(id=int(sid))
            if not session:
                items.append({"sessionId": sid, "error": "Session not found"})
                continue
            for prev in select(
                j
                for j in RcAnalyzeJob
                if j.session == session and j.status in ("queued", "running")
            ):
                if prev.status == "queued":
                    prev.status = "cancelled"
                    prev.finished_at = datetime.utcnow()
                    prev.message = "Superseded by newer job"
            u = RcUser.get(id=user["id"]) if user.get("id") else None
            job = RcAnalyzeJob(
                session=session,
                user=u,
                status="queued",
                progress=0,
                message="Queued",
            )
            session.status = "queued"
            session.updated_at = datetime.utcnow()
            items.append(job_dict(job))
        except Exception as exc:
            items.append({"sessionId": sid, "error": str(exc)})
    commit()
    return {"jobs": items}


@db_session
def list_jobs(user: dict, limit: int = 50, mine_only: bool = True) -> list[dict]:
    role = (user or {}).get("role")
    uid = user.get("id")
    if role == "admin" and not mine_only:
        rows = select(j for j in RcAnalyzeJob).order_by(desc(RcAnalyzeJob.created_at))[
            :limit
        ]
    else:
        rows = select(j for j in RcAnalyzeJob if j.user and j.user.id == uid).order_by(
            desc(RcAnalyzeJob.created_at)
        )[:limit]
    return [job_dict(j) for j in rows]


@db_session
def get_job(job_id: int, user: dict) -> dict:
    j = RcAnalyzeJob.get(id=job_id)
    if not j:
        raise HTTPException(404, "Job not found")
    if (user or {}).get("role") != "admin" and (not j.user or j.user.id != user.get("id")):
        raise HTTPException(403, "Not your job")
    return job_dict(j)


@db_session
def cancel_db_job(job_id: int, user: dict) -> dict:
    j = RcAnalyzeJob.get(id=job_id)
    if not j:
        raise HTTPException(404, "Job not found")
    if (user or {}).get("role") != "admin" and (not j.user or j.user.id != user.get("id")):
        raise HTTPException(403, "Not your job")
    if j.status in ("done", "failed", "cancelled"):
        return job_dict(j)
    sid = j.session.id
    was_running = j.status == "running"
    # Always try to stop in-flight work (closes Ollama HTTP stream if attached)
    cancel_inflight(sid)
    j.status = "cancelled"
    j.message = "Cancelled by user"
    j.finished_at = datetime.utcnow()
    if j.session and j.session.status in ("analyzing", "queued"):
        j.session.status = "cancelled"
    commit()
    if was_running:
        # Free VRAM/RAM — model often stays loaded after the HTTP stream is closed
        try:
            from app.route_card.drawing_mind.ollama_client import unload_model

            unload_model()
        except Exception:
            logger.debug("ollama unload after cancel failed", exc_info=True)
    return job_dict(j)


@db_session
def _job_status(job_id: int) -> str | None:
    j = RcAnalyzeJob.get(id=job_id)
    return j.status if j else None


@db_session
def _claim_next_job() -> int | None:
    row = select(j for j in RcAnalyzeJob if j.status == "queued").order_by(
        RcAnalyzeJob.created_at
    )[:1]
    if not row:
        return None
    j = row[0]
    j.status = "running"
    j.started_at = datetime.utcnow()
    j.progress = 5
    j.message = "Starting analysis"
    j.session.status = "analyzing"
    commit()
    return j.id


@db_session
def _finish_job(job_id: int, ok: bool, message: str = "", error: str | None = None) -> dict:
    j = RcAnalyzeJob.get(id=job_id)
    if not j:
        return {}
    # Do not overwrite a user cancel with done/failed from a late-finishing worker
    if j.status == "cancelled":
        if message and not j.message:
            j.message = message
        if not j.finished_at:
            j.finished_at = datetime.utcnow()
        user_id = j.user.id if j.user else None
        session_id = j.session.id
        emp = j.user.emp_id if j.user else None
        commit()
        return {
            "userId": user_id,
            "sessionId": session_id,
            "empId": emp,
            "ok": False,
            "status": "cancelled",
        }
    j.status = "done" if ok else ("cancelled" if error == "cancelled" else "failed")
    j.progress = 100 if ok else j.progress
    j.message = message or j.message
    j.error_message = error
    j.finished_at = datetime.utcnow()
    user_id = j.user.id if j.user else None
    session_id = j.session.id
    emp = j.user.emp_id if j.user else None
    commit()
    return {
        "userId": user_id,
        "sessionId": session_id,
        "empId": emp,
        "ok": ok,
        "status": j.status,
    }


@db_session
def _job_context(job_id: int) -> dict | None:
    j = RcAnalyzeJob.get(id=job_id)
    if not j:
        return None
    return {
        "sessionId": j.session.id,
        "user": {
            "id": j.user.id if j.user else None,
            "empId": j.user.emp_id if j.user else None,
            "dept": j.user.dept if j.user else "",
            "role": j.user.role if j.user else "engineer",
            "name": j.user.name if j.user else "",
        }
        if j.user
        else {},
        "vlmPageIndexes": j.vlm_page_indexes,
    }


def _run_one(job_id: int) -> None:
    from app.route_card import notifications
    from app.route_card import service
    from app.route_card.analyze_jobs import AnalysisCancelled
    from app.route_card.drawing_mind.ollama_client import unload_model

    ctx = _job_context(job_id)
    if not ctx:
        return
    sid = ctx["sessionId"]
    user = ctx["user"] or {}
    try:
        with _vlm_lock:
            # User may have cancelled between claim and lock acquire
            if _job_status(job_id) != "running":
                return
            job = start_job(sid)
            # Cancel raced before start_job — honor it now
            if _job_status(job_id) != "running":
                job.request_cancel()
                end_job(sid)
                try:
                    unload_model()
                except Exception:
                    pass
                return
            try:
                service.analyze_session(
                    sid,
                    user=user,
                    cancel_event=job.cancel,
                    vlm_page_indexes=ctx.get("vlmPageIndexes"),
                )
            finally:
                end_job(sid)
        if _job_status(job_id) != "running":
            # Cancelled while finishing — do not mark done
            return
        meta = _finish_job(job_id, True, message="Analysis complete")
        if meta.get("userId") and meta.get("status") == "done":
            notifications.create_notification(
                meta["userId"],
                "Analysis complete",
                f"Session {sid} finished analyzing.",
                link=f"/generator?sessionId={sid}",
            )
    except AnalysisCancelled:
        try:
            unload_model()
        except Exception:
            pass
        meta = _finish_job(job_id, False, message="Cancelled", error="cancelled")
        if meta.get("userId"):
            notifications.create_notification(
                meta["userId"],
                "Analysis cancelled",
                f"Session {sid} was cancelled.",
                link=f"/history",
            )
    except Exception as exc:
        logger.exception("analyze job %s failed", job_id)
        meta = _finish_job(job_id, False, message="Failed", error=str(exc)[:500])
        if meta.get("userId") and meta.get("status") == "failed":
            notifications.create_notification(
                meta["userId"],
                "Analysis failed",
                f"Session {sid}: {str(exc)[:200]}",
                link=f"/history",
            )


def _worker_loop() -> None:
    poll = float(getattr(settings, "ANALYZE_QUEUE_POLL_SEC", 2.0) or 2.0)
    while not _worker_stop.is_set():
        try:
            if not getattr(settings, "ANALYZE_QUEUE_ENABLED", True):
                time.sleep(poll)
                continue
            jid = _claim_next_job()
            if jid:
                _run_one(jid)
            else:
                time.sleep(poll)
        except Exception:
            logger.exception("queue worker error")
            time.sleep(poll)


def start_queue_worker() -> None:
    global _worker_thread
    if _worker_thread and _worker_thread.is_alive():
        return
    _worker_stop.clear()
    _worker_thread = threading.Thread(target=_worker_loop, name="analyze-queue", daemon=True)
    _worker_thread.start()
    logger.info("analyze queue worker started")


def stop_queue_worker() -> None:
    _worker_stop.set()


@db_session
def queue_stats() -> dict:
    queued = select(j for j in RcAnalyzeJob if j.status == "queued").count()
    running = select(j for j in RcAnalyzeJob if j.status == "running").count()
    last = select(j for j in RcAnalyzeJob).order_by(desc(RcAnalyzeJob.created_at))[:1]
    return {
        "queued": queued,
        "running": running,
        "vlmLocked": _vlm_lock.locked(),
        "lastJob": job_dict(last[0]) if last else None,
    }
