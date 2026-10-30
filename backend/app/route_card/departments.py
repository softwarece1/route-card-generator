"""Department master CRUD (admin write; public list via auth.list_departments)."""

from __future__ import annotations

from fastapi import HTTPException
from pony.orm import commit, db_session, select

from app.route_card.models import RcDepartment, RcPlant, RcUser


def dept_dict(d: RcDepartment) -> dict:
    return {
        "id": d.id,
        "code": d.code,
        "name": d.name,
        "plantId": (d.plant_id or "").strip(),
        "isActive": bool(d.is_active),
        "sortOrder": d.sort_order,
        "label": d.name,
        "value": d.name,
    }


def _assert_plant_code(plant_code: str) -> str:
    code = (plant_code or "").strip()
    if not code:
        raise HTTPException(400, "plantId is required")
    hit = select(p for p in RcPlant if p.is_active and p.code == code)[:1]
    if not hit:
        raise HTTPException(400, f"Unknown or inactive plant '{code}'")
    return hit[0].code


@db_session
def list_departments(*, active_only: bool = False) -> list[dict]:
    rows = select(d for d in RcDepartment)[:]
    out = []
    for d in rows:
        if active_only and not d.is_active:
            continue
        out.append(d)
    out.sort(key=lambda d: (d.sort_order, d.name))
    return [dept_dict(d) for d in out]


@db_session
def upsert_department(body: dict, dept_id: int | None = None) -> dict:
    code = (body.get("code") or "").strip().upper().replace(" ", "_")
    name = (body.get("name") or "").strip()
    if not code or not name:
        raise HTTPException(400, "code and name are required")
    plant = _assert_plant_code(body.get("plantId") or body.get("plant_id") or "")

    if dept_id:
        d = RcDepartment.get(id=dept_id)
        if not d:
            raise HTTPException(404, "Department not found")
        clash = select(
            x for x in RcDepartment if x.code == code and x.id != d.id
        )[:1]
        if clash:
            raise HTTPException(400, f"Department code '{code}' already exists")
        name_clash = select(
            x for x in RcDepartment if x.name == name and x.id != d.id and x.is_active
        )[:1]
        if name_clash:
            raise HTTPException(400, f"Department name '{name}' already exists")
    else:
        existing = RcDepartment.get(code=code)
        if existing and existing.is_active:
            raise HTTPException(400, f"Department code '{code}' already exists")
        name_clash = select(
            x for x in RcDepartment if x.name == name and x.is_active
        )[:1]
        if name_clash and (not existing or name_clash[0].id != existing.id):
            raise HTTPException(400, f"Department name '{name}' already exists")
        d = existing or RcDepartment(code=code, name=name, plant_id=plant)

    d.code = code
    d.name = name
    d.plant_id = plant
    if "sortOrder" in body or "sort_order" in body:
        d.sort_order = int(body.get("sortOrder") or body.get("sort_order") or 0)
    if "isActive" in body:
        d.is_active = bool(body["isActive"])
    else:
        d.is_active = True
    commit()
    return dept_dict(d)


@db_session
def dept_heads_for_dept(dept_name: str) -> list[dict]:
    """Active dept_heads in a department (for reporting-officer dropdown)."""
    d = (dept_name or "").strip()
    if not d:
        return []
    rows = select(
        u
        for u in RcUser
        if u.is_active and u.role == "dept_head" and u.dept == d
    ).order_by(RcUser.name)[:]
    return [
        {
            "id": u.id,
            "empId": u.emp_id,
            "name": u.name,
            "dept": u.dept or "",
            "label": f"{u.name} ({u.emp_id})",
            "value": u.id,
        }
        for u in rows
    ]
