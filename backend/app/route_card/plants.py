"""Plant / WERKS master for SAP sync dropdowns."""

from __future__ import annotations

from fastapi import HTTPException
from pony.orm import commit, db_session, select

from app.route_card.models import RcDepartment, RcPlant
from app.route_card.op_templates import _dept, _is_admin


def plant_dict(p: RcPlant) -> dict:
    return {
        "id": p.id,
        "code": p.code,
        "name": p.name,
        "description": p.description or "",
        "isActive": bool(p.is_active),
        "sortOrder": p.sort_order,
        "label": f"{p.code} — {p.name}",
        "value": p.code,
    }


def _plant_id_for_dept(dept: str) -> str:
    want = (dept or "").strip()
    if not want:
        return ""
    rows = select(
        d for d in RcDepartment if d.is_active and (d.name == want or d.code == want)
    )[:1]
    if not rows:
        return ""
    return (rows[0].plant_id or "").strip()


@db_session
def list_plants(active_only: bool = True) -> list[dict]:
    rows = select(p for p in RcPlant)[:]
    out = []
    for p in rows:
        if active_only and not p.is_active:
            continue
        out.append(p)
    out.sort(key=lambda p: (p.sort_order, p.code))
    return [plant_dict(p) for p in out]


@db_session
def get_plant(plant_id: int) -> dict:
    p = RcPlant.get(id=plant_id)
    if not p:
        raise HTTPException(404, "Plant not found")
    return plant_dict(p)


@db_session
def plant_id_for_dept(dept: str) -> str:
    return _plant_id_for_dept(dept)


@db_session
def resolve_sync_plant_code(user: dict, requested: str | None = None) -> str:
    """Admin may pick any plant; others always use their department plant_id."""
    if _is_admin(user):
        code = (requested or "").strip()
        if not code:
            raise HTTPException(400, "Plant is required")
        hit = select(p for p in RcPlant if p.is_active and p.code == code)[:1]
        if not hit:
            return code
        return hit[0].code

    plant = _plant_id_for_dept(_dept(user))
    if not plant:
        raise HTTPException(
            400,
            "No plant_id configured for your department. Ask an admin to set it on the department.",
        )
    return plant


@db_session
def upsert_plant(body: dict, plant_id: int | None = None) -> dict:
    code = (body.get("code") or "").strip()
    name = (body.get("name") or "").strip()
    if not code or not name:
        raise HTTPException(400, "code and name are required")
    if plant_id:
        p = RcPlant.get(id=plant_id)
        if not p:
            raise HTTPException(404, "Plant not found")
    else:
        existing = RcPlant.get(code=code)
        if existing and existing.is_active:
            raise HTTPException(400, f"Plant code '{code}' already exists")
        p = existing or RcPlant(code=code, name=name)
    p.code = code
    p.name = name
    if "description" in body:
        p.description = body.get("description") or ""
    if "sortOrder" in body or "sort_order" in body:
        p.sort_order = int(body.get("sortOrder") or body.get("sort_order") or 0)
    if "isActive" in body:
        p.is_active = bool(body["isActive"])
    else:
        p.is_active = True
    commit()
    return plant_dict(p)
