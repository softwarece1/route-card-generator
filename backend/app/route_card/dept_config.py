"""Dept rules + few-shot examples (Phase 4)."""

from __future__ import annotations

from datetime import datetime

from fastapi import HTTPException
from pony.orm import commit, db_session, desc, select

from app.route_card.models import RcDeptRules, RcFewShotExample, RcUser
from app.route_card.op_templates import _can_write_dept, _dept, _is_admin, _is_dept_head


def _rules_out(row: RcDeptRules) -> dict:
    return {
        "id": row.id,
        "dept": row.dept,
        "rules": row.rules or {},
        "updatedAt": row.updated_at.isoformat() + "Z" if row.updated_at else None,
        "updatedBy": row.updated_by,
    }


@db_session
def get_dept_rules(dept: str) -> dict:
    d = (dept or "").strip()
    row = RcDeptRules.get(dept=d)
    if not row:
        return {
            "dept": d,
            "rules": {
                "autoTemplateIds": [],
                "keywords": [],
                "wcAliases": {},
                "promptAddendum": "",
                "phrasing": [],
            },
        }
    return _rules_out(row)


@db_session
def upsert_dept_rules(user: dict, dept: str, rules: dict) -> dict:
    d = (dept or "").strip() or _dept(user)
    if not _can_write_dept(user, d) and not _is_admin(user):
        raise HTTPException(403, "Not allowed to edit department rules")
    row = RcDeptRules.get(dept=d)
    if not row:
        row = RcDeptRules(dept=d, rules=rules or {})
    else:
        row.rules = rules or {}
    row.updated_at = datetime.utcnow()
    row.updated_by = user.get("empId") or user.get("username") or ""
    commit()
    return _rules_out(row)


def few_shot_dict(e: RcFewShotExample) -> dict:
    return {
        "id": e.id,
        "dept": e.dept,
        "docType": e.doc_type or "drawing",
        "title": e.title,
        "inputExcerpt": e.input_excerpt or "",
        "outputExcerpt": e.output_excerpt or "",
        "isActive": bool(e.is_active),
        "createdAt": e.created_at.isoformat() + "Z" if e.created_at else None,
    }


@db_session
def list_few_shots(dept: str | None = None, active_only: bool = True) -> list[dict]:
    q = select(e for e in RcFewShotExample)
    if dept:
        q = select(e for e in RcFewShotExample if e.dept == dept.strip())
    if active_only:
        q = select(e for e in q if e.is_active)
    rows = q.order_by(desc(RcFewShotExample.created_at))[:100]
    return [few_shot_dict(e) for e in rows]


@db_session
def create_few_shot(user: dict, body: dict) -> dict:
    dept = (body.get("dept") or _dept(user) or "").strip()
    if not _can_write_dept(user, dept) and not _is_admin(user):
        raise HTTPException(403, "Not allowed")
    u = RcUser.get(id=user["id"]) if user.get("id") else None
    e = RcFewShotExample(
        dept=dept,
        doc_type=(body.get("docType") or "drawing"),
        title=(body.get("title") or "Example").strip(),
        input_excerpt=body.get("inputExcerpt") or "",
        output_excerpt=(body.get("outputExcerpt") or "").strip(),
        created_by=u,
        is_active=True,
    )
    if not e.output_excerpt:
        raise HTTPException(400, "outputExcerpt is required")
    commit()
    return few_shot_dict(e)


@db_session
def delete_few_shot(example_id: int, user: dict) -> dict:
    e = RcFewShotExample.get(id=example_id)
    if not e:
        raise HTTPException(404, "Example not found")
    if not _can_write_dept(user, e.dept) and not _is_admin(user):
        raise HTTPException(403, "Not allowed")
    e.is_active = False
    commit()
    return {"ok": True, "id": example_id}


def few_shot_prompt_block(dept: str | None, limit: int = 3) -> str:
    """Build text block for VLM prompt injection (call inside db_session)."""
    d = (dept or "").strip()
    if not d:
        rows = select(e for e in RcFewShotExample if e.is_active).order_by(
            desc(RcFewShotExample.created_at)
        )[:limit]
    else:
        rows = select(e for e in RcFewShotExample if e.is_active and e.dept == d).order_by(
            desc(RcFewShotExample.created_at)
        )[:limit]
    if not rows:
        return ""
    parts = [
        "Examples of good simple shop-floor instructions "
        "(short everyday English for ITI / Diploma operators):"
    ]
    for e in rows:
        parts.append(f"- {e.title}: {e.output_excerpt[:800]}")
    return "\n".join(parts)
