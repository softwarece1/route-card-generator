"""Department master CRUD under SBU (admin or owning sbu_head; soft delete)."""

from __future__ import annotations

from fastapi import HTTPException
from pony.orm import commit, db_session, select

from app.route_card.models import RcDepartment, RcSbu, RcUser

DEFAULT_DEPTS = (
    ("PMG", "PMG", 10),
    ("IED", "IED", 20),
)


def dept_dict(d: RcDepartment) -> dict:
    sbu = d.sbu
    return {
        "id": d.id,
        "code": d.code,
        "name": d.name,
        "sbuId": sbu.id if sbu else None,
        "sbuName": (sbu.name if sbu else "") or "",
        "sbuCode": (sbu.code if sbu else "") or "",
        "plantId": ((sbu.plant_id if sbu else "") or "").strip(),
        "isActive": bool(d.is_active),
        "sortOrder": int(d.sort_order or 0),
        "label": d.name,
        "value": d.id,
    }


def ensure_default_departments(sbu: RcSbu) -> None:
    """Idempotent PMG + IED rows for an SBU (call inside db_session)."""
    if not sbu:
        return
    for code, name, sort_order in DEFAULT_DEPTS:
        existing = select(
            d for d in RcDepartment if d.sbu == sbu and d.code == code
        )[:1]
        if existing:
            continue
        RcDepartment(sbu=sbu, code=code, name=name, sort_order=sort_order, is_active=True)


def _resolve_sbu(*, sbu_id: int | None = None, sbu_name: str | None = None) -> RcSbu:
    if sbu_id is not None:
        sbu = RcSbu.get(id=int(sbu_id))
        if not sbu:
            raise HTTPException(404, "SBU not found")
        return sbu
    name = (sbu_name or "").strip()
    if not name:
        raise HTTPException(400, "sbuId or sbu is required")
    rows = select(s for s in RcSbu if s.name == name)[:1]
    if not rows:
        raise HTTPException(404, "SBU not found")
    return rows[0]


def _actor_may_manage_sbu(actor: dict | None, sbu: RcSbu) -> None:
    if not actor:
        raise HTTPException(401, "Not authenticated")
    role = (actor.get("role") or "").strip().lower()
    if role == "admin":
        return
    if role != "sbu_head":
        raise HTTPException(403, "SBU head or admin access required")
    actor_sbu = (actor.get("sbu") or "").strip()
    if not actor_sbu or actor_sbu != (sbu.name or "").strip():
        raise HTTPException(403, "You can only manage departments in your own SBU")


def _active_user_count(dept: RcDepartment) -> int:
    return select(
        u for u in RcUser if u.department == dept and u.is_active
    ).count()


@db_session
def list_departments(
    *,
    sbu_id: int | None = None,
    sbu_name: str | None = None,
    active_only: bool = True,
    actor: dict | None = None,
) -> list[dict]:
    role = ((actor or {}).get("role") or "").strip().lower()
    if role == "sbu_head":
        # Always scoped to the head's own SBU — never return the full catalog
        sbu_name = ((actor or {}).get("sbu") or "").strip()
        sbu_id = None
        if not sbu_name:
            raise HTTPException(
                400,
                "Your account has no SBU assigned — ask an admin to set it before managing departments",
            )
    if sbu_id is None and not (sbu_name or "").strip():
        if role != "admin":
            raise HTTPException(403, "SBU head or admin access required")
        # Admin listing all
        rows = select(d for d in RcDepartment)[:]
    else:
        sbu = _resolve_sbu(sbu_id=sbu_id, sbu_name=sbu_name)
        if role == "sbu_head":
            actor_sbu = ((actor or {}).get("sbu") or "").strip()
            if (sbu.name or "").strip() != actor_sbu:
                raise HTTPException(403, "You can only list departments in your own SBU")
        rows = select(d for d in RcDepartment if d.sbu == sbu)[:]
    out = []
    for d in rows:
        if active_only and not d.is_active:
            continue
        out.append(d)
    out.sort(key=lambda d: (d.sort_order or 0, d.name or "", d.code or ""))
    return [dept_dict(d) for d in out]


@db_session
def upsert_department(actor: dict | None, body: dict, dept_id: int | None = None) -> dict:
    code = (body.get("code") or "").strip().upper().replace(" ", "_")
    name = (body.get("name") or "").strip()
    if not code or not name:
        raise HTTPException(400, "code and name are required")

    if dept_id:
        d = RcDepartment.get(id=int(dept_id))
        if not d:
            raise HTTPException(404, "Department not found")
        _actor_may_manage_sbu(actor, d.sbu)
        clash = select(
            x for x in RcDepartment if x.sbu == d.sbu and x.code == code and x.id != d.id
        )[:1]
        if clash:
            raise HTTPException(400, f"Department code '{code}' already exists in this SBU")
        d.code = code
        d.name = name
        if "isActive" in body:
            d.is_active = bool(body["isActive"])
        if "sortOrder" in body and body.get("sortOrder") is not None:
            try:
                d.sort_order = int(body["sortOrder"])
            except (TypeError, ValueError):
                pass
        commit()
        return dept_dict(d)

    raw_sbu_id = body.get("sbuId") if body.get("sbuId") is not None else body.get("sbu_id")
    sbu_name = body.get("sbu") or body.get("sbuName") or ""
    role = ((actor or {}).get("role") or "").strip().lower()
    if role == "sbu_head":
        sbu = _resolve_sbu(sbu_name=(actor or {}).get("sbu") or "")
    else:
        sbu = _resolve_sbu(
            sbu_id=int(raw_sbu_id) if raw_sbu_id is not None and str(raw_sbu_id).strip() != "" else None,
            sbu_name=sbu_name,
        )
    _actor_may_manage_sbu(actor, sbu)

    existing = select(x for x in RcDepartment if x.sbu == sbu and x.code == code)[:1]
    if existing:
        d = existing[0]
        if d.is_active:
            raise HTTPException(400, f"Department code '{code}' already exists in this SBU")
        # Reactivate soft-deleted row with same code
        d.name = name
        d.is_active = True
        if "sortOrder" in body and body.get("sortOrder") is not None:
            try:
                d.sort_order = int(body["sortOrder"])
            except (TypeError, ValueError):
                pass
        commit()
        return dept_dict(d)

    sort_order = 100
    if body.get("sortOrder") is not None:
        try:
            sort_order = int(body["sortOrder"])
        except (TypeError, ValueError):
            pass
    d = RcDepartment(
        sbu=sbu,
        code=code,
        name=name,
        is_active=True,
        sort_order=sort_order,
    )
    commit()
    return dept_dict(d)


@db_session
def soft_delete_department(actor: dict | None, dept_id: int) -> dict:
    d = RcDepartment.get(id=int(dept_id))
    if not d:
        raise HTTPException(404, "Department not found")
    _actor_may_manage_sbu(actor, d.sbu)
    if not d.is_active:
        return dept_dict(d)
    n = _active_user_count(d)
    if n > 0:
        raise HTTPException(
            400,
            f"Cannot deactivate department while {n} active user(s) are assigned. "
            "Reassign or deactivate those users first.",
        )
    d.is_active = False
    commit()
    return dept_dict(d)


@db_session
def dept_heads_for_department(department_id: int) -> list[dict]:
    """Active dept_heads in a department (engineer reporting-officer dropdown)."""
    dept = RcDepartment.get(id=int(department_id))
    if not dept or not dept.is_active:
        return []
    rows = select(
        u
        for u in RcUser
        if u.is_active and u.role == "dept_head" and u.department == dept
    ).order_by(RcUser.name)[:]
    return [
        {
            "id": u.id,
            "empId": u.emp_id,
            "name": u.name,
            "sbu": u.sbu or "",
            "departmentId": dept.id,
            "label": f"{u.name} ({u.emp_id})",
            "value": u.id,
        }
        for u in rows
    ]


def is_ied_department(dept: RcDepartment | None) -> bool:
    if not dept:
        return False
    return (dept.code or "").strip().upper() == "IED"


def user_in_ied_dept(user: RcUser | dict | None) -> bool:
    """True when the user belongs to an IED department (role-agnostic)."""
    if not user:
        return False
    if isinstance(user, dict):
        if user.get("isIedDept") is not None:
            return bool(user.get("isIedDept"))
        code = (user.get("departmentCode") or "").strip().upper()
        if code:
            return code == "IED"
        # Legacy fallback during rollout
        return (user.get("role") or "").strip().lower() == "ied"
    dept = getattr(user, "department", None)
    if dept is not None:
        return is_ied_department(dept)
    return (getattr(user, "role", None) or "").strip().lower() == "ied"
