"""Admin health, storage, backup, machines (Phase 6)."""

from __future__ import annotations

import shutil
import subprocess
import zipfile
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import HTTPException
from pony.orm import commit, db_session, desc, select

from app.config.settings import settings
from app.route_card.models import RcDocument, RcMachine, RcRouteCard, RcSession
from app.route_card.service import get_local_upload_root


def _backup_root() -> Path:
    raw = (getattr(settings, "BACKUP_ROOT", None) or "").strip()
    if raw:
        p = Path(raw).expanduser()
        if not p.is_absolute():
            p = Path.cwd() / p
        return p.resolve()
    return (get_local_upload_root().parent / "backups").resolve()


@db_session
def health_extended() -> dict:
    from app.route_card import job_queue

    pg_ok = True
    try:
        select(s.id for s in RcSession)[:1]
    except Exception as exc:
        pg_ok = False
        pg_err = str(exc)
    else:
        pg_err = None

    ollama_ok = False
    ollama_err = None
    try:
        import httpx

        base = (settings.OLLAMA_BASE_URL or "http://127.0.0.1:11434").rstrip("/")
        with httpx.Client(timeout=3.0, trust_env=False) as client:
            r = client.get(f"{base}/api/tags")
            ollama_ok = r.status_code == 200
            if not ollama_ok:
                ollama_err = f"HTTP {r.status_code}"
    except Exception as exc:
        ollama_err = str(exc)[:200]

    root = get_local_upload_root()
    disk = {}
    try:
        usage = shutil.disk_usage(str(root if root.exists() else Path.cwd()))
        disk = {
            "path": str(root),
            "totalBytes": usage.total,
            "usedBytes": usage.used,
            "freeBytes": usage.free,
        }
    except Exception as exc:
        disk = {"path": str(root), "error": str(exc)}

    q = job_queue.queue_stats()
    return {
        "status": "ok" if pg_ok else "degraded",
        "auth_enabled": settings.AUTH_ENABLED,
        "postgres": {"ok": pg_ok, "error": pg_err},
        "ollama": {
            "ok": ollama_ok,
            "error": ollama_err,
            "baseUrl": settings.OLLAMA_BASE_URL,
            "model": settings.OLLAMA_VLM_MODEL,
            "engine": settings.DRAWING_MIND_ENGINE,
        },
        "disk": disk,
        "queue": q,
    }


@db_session
def storage_stats() -> dict:
    root = get_local_upload_root()
    by_dept: dict[str, int] = {}
    by_user: dict[str, int] = {}
    sessions = []
    total = 0
    for doc in select(d for d in RcDocument):
        sz = int(doc.size_bytes or 0)
        total += sz
        sess = doc.session
        emp = ""
        dept = ""
        if sess and sess.user:
            emp = sess.user.emp_id or ""
            dept = sess.user.dept or ""
        by_dept[dept or "(none)"] = by_dept.get(dept or "(none)", 0) + sz
        by_user[emp or "(none)"] = by_user.get(emp or "(none)", 0) + sz
    for sess in select(s for s in RcSession).order_by(desc(RcSession.updated_at))[:100]:
        sz = sum(int(d.size_bytes or 0) for d in sess.documents)
        sessions.append(
            {
                "sessionId": sess.id,
                "status": sess.status,
                "bytes": sz,
                "empId": sess.user.emp_id if sess.user else None,
                "dept": sess.user.dept if sess.user else None,
                "updatedAt": sess.updated_at.isoformat() + "Z" if sess.updated_at else None,
            }
        )
    return {
        "uploadRoot": str(root),
        "totalBytes": total,
        "byDept": [{"dept": k, "bytes": v} for k, v in sorted(by_dept.items())],
        "byUser": [{"empId": k, "bytes": v} for k, v in sorted(by_user.items(), key=lambda x: -x[1])[:50]],
        "recentSessions": sessions,
    }


@db_session
def cleanup_old_drafts(days: int = 90, dry_run: bool = True) -> dict:
    cutoff = datetime.utcnow() - timedelta(days=max(1, days))
    cards = select(
        c
        for c in RcRouteCard
        if c.status == "draft" and c.updated_at < cutoff
    )[:]
    ids = [c.id for c in cards]
    if not dry_run:
        for c in cards:
            c.delete()
        commit()
    return {"dryRun": dry_run, "days": days, "count": len(ids), "routeCardIds": ids[:200]}


def run_backup() -> dict:
    root = _backup_root()
    root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    dest_dir = root / f"backup_{stamp}"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dump_file = dest_dir / "route_card.sql"
    pg_ok = False
    pg_err = None
    try:
        env = {
            **dict(**{k: str(v) for k, v in __import__("os").environ.items()}),
            "PGPASSWORD": settings.DB_PASSWORD,
        }
        cmd = [
            "pg_dump",
            "-h",
            settings.DB_HOST,
            "-p",
            str(settings.DB_PORT),
            "-U",
            settings.DB_USER,
            "-d",
            settings.DB_NAME,
            "-f",
            str(dump_file),
        ]
        r = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=600)
        pg_ok = r.returncode == 0
        if not pg_ok:
            pg_err = (r.stderr or r.stdout or "pg_dump failed")[:500]
    except Exception as exc:
        pg_err = str(exc)[:500]

    uploads = get_local_upload_root()
    uploads_copied = False
    if uploads.exists():
        try:
            shutil.copytree(uploads, dest_dir / "uploads", dirs_exist_ok=True)
            uploads_copied = True
        except Exception as exc:
            pg_err = (pg_err or "") + f"; uploads copy: {exc}"

    zip_path = root / f"backup_{stamp}.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in dest_dir.rglob("*"):
            if p.is_file():
                zf.write(p, arcname=str(p.relative_to(dest_dir)))

    return {
        "ok": pg_ok or uploads_copied,
        "path": str(zip_path),
        "folder": str(dest_dir),
        "pgDumpOk": pg_ok,
        "uploadsCopied": uploads_copied,
        "error": pg_err,
    }


def machine_dict(m: RcMachine) -> dict:
    return {
        "id": m.id,
        "plant": m.plant or "",
        "workCentre": m.work_centre,
        "name": m.name,
        "description": m.description or "",
        "isActive": bool(m.is_active),
        "sortOrder": m.sort_order,
    }


@db_session
def list_machines(active_only: bool = True) -> list[dict]:
    q = select(m for m in RcMachine)
    if active_only:
        q = select(m for m in RcMachine if m.is_active)
    rows = q.order_by(RcMachine.sort_order, RcMachine.name)[:]
    return [machine_dict(m) for m in rows]


@db_session
def upsert_machine(body: dict, machine_id: int | None = None) -> dict:
    if machine_id:
        m = RcMachine.get(id=machine_id)
        if not m:
            raise HTTPException(404, "Machine not found")
    else:
        m = RcMachine(
            plant=body.get("plant") or "",
            work_centre=body.get("workCentre") or body.get("work_centre") or "",
            name=body.get("name") or "",
            description=body.get("description") or "",
            sort_order=int(body.get("sortOrder") or 0),
            is_active=True,
        )
    if machine_id:
        if "plant" in body:
            m.plant = body.get("plant") or ""
        if "workCentre" in body or "work_centre" in body:
            m.work_centre = body.get("workCentre") or body.get("work_centre") or m.work_centre
        if "name" in body:
            m.name = body["name"]
        if "description" in body:
            m.description = body.get("description") or ""
        if "sortOrder" in body:
            m.sort_order = int(body["sortOrder"] or 0)
        if "isActive" in body:
            m.is_active = bool(body["isActive"])
    if not m.name or not m.work_centre:
        raise HTTPException(400, "name and workCentre required")
    commit()
    return machine_dict(m)


@db_session
def delete_machine(machine_id: int) -> dict:
    m = RcMachine.get(id=machine_id)
    if not m:
        raise HTTPException(404, "Machine not found")
    m.is_active = False
    commit()
    return {"ok": True, "id": machine_id}
