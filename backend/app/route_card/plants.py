"""Plant / WERKS master for SAP sync dropdowns."""

from __future__ import annotations

from fastapi import HTTPException
from pony.orm import commit, db_session, select

from app.route_card.models import RcDepartment, RcPlant
from app.route_card.op_templates import _dept, _is_admin


def _sbu_names_by_plant() -> dict[str, list[str]]:
    """Map plant code → linked SBU display names (active departments)."""
    by_plant: dict[str, list[str]] = {}
    for d in select(d for d in RcDepartment if d.is_active)[:]:
        plant = (d.plant_id or "").strip()
        if not plant:
            continue
        label = (d.name or d.code or "").strip()
        if not label:
            continue
        by_plant.setdefault(plant, [])
        if label not in by_plant[plant]:
            by_plant[plant].append(label)
    return by_plant


def plant_dict(p: RcPlant, *, sbu_names: list[str] | None = None) -> dict:
    synced = getattr(p, "work_center_synced_at", None)
    sbus = [n for n in (sbu_names or []) if n]
    if sbus:
        label = f"{p.code} - {', '.join(sbus)}"
    elif (p.name or "").strip() and (p.name or "").strip() != (p.code or "").strip():
        label = f"{p.code} - {p.name.strip()}"
    else:
        label = p.code
    return {
        "id": p.id,
        "code": p.code,
        "name": p.name,
        "description": p.description or "",
        "isActive": bool(p.is_active),
        "sortOrder": p.sort_order,
        "workCenterSyncedAt": synced.isoformat() + "Z" if synced else None,
        "sbuNames": sbus,
        "sbuName": sbus[0] if sbus else "",
        "label": label,
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
    sbu_map = _sbu_names_by_plant()
    rows = select(p for p in RcPlant)[:]
    out = []
    for p in rows:
        if active_only and not p.is_active:
            continue
        out.append(p)
    out.sort(key=lambda p: (p.sort_order, p.code))
    return [plant_dict(p, sbu_names=sbu_map.get(p.code) or []) for p in out]


@db_session
def get_plant(plant_id: int) -> dict:
    p = RcPlant.get(id=plant_id)
    if not p:
        raise HTTPException(404, "Plant not found")
    sbu_map = _sbu_names_by_plant()
    return plant_dict(p, sbu_names=sbu_map.get(p.code) or [])


@db_session
def plant_id_for_dept(dept: str) -> str:
    return _plant_id_for_dept(dept)


@db_session
def resolve_sync_plant_code(user: dict, requested: str | None = None) -> str:
    """Admin / dept_head may sync a requested plant; otherwise use SBU plant_id."""
    code = (requested or "").strip()
    if code:
        if not (_is_admin(user) or _dept(user)):
            raise HTTPException(403, "Not allowed to sync this plant")
        # Dept heads may sync their own SBU plant or an explicitly opened plant
        hit = select(p for p in RcPlant if p.is_active and p.code == code)[:1]
        if not hit:
            return code
        return hit[0].code

    if _is_admin(user):
        raise HTTPException(400, "Plant is required")

    plant = _plant_id_for_dept(_dept(user))
    if not plant:
        raise HTTPException(
            400,
            "No plant code configured for your SBU. Ask an admin to set it on the SBU.",
        )
    return plant


@db_session
def mark_work_center_synced(plant_code: str):
    """Stamp last successful work-centre SAP sync on the plant row."""
    from datetime import datetime

    code = (plant_code or "").strip()
    if not code:
        return
    hit = select(p for p in RcPlant if p.code == code)[:1]
    if not hit:
        return
    hit[0].work_center_synced_at = datetime.utcnow()
    commit()


@db_session
def get_work_center_synced_at(plant_code: str):
    code = (plant_code or "").strip()
    if not code:
        return None
    hit = select(p for p in RcPlant if p.code == code)[:1]
    if not hit:
        return None
    return hit[0].work_center_synced_at


@db_session
def upsert_plant(body: dict, plant_id: int | None = None) -> dict:
    from app.route_card.models import RcMachine, RcWorkCenter

    code = (body.get("code") or "").strip()
    name = (body.get("name") or "").strip()
    if not code or not name:
        raise HTTPException(400, "code and name are required")
    old_code = ""
    if plant_id:
        p = RcPlant.get(id=plant_id)
        if not p:
            raise HTTPException(404, "Plant not found")
        old_code = (p.code or "").strip()
        if code != old_code:
            clash = RcPlant.get(code=code)
            if clash and clash.id != p.id:
                raise HTTPException(400, f"Plant code '{code}' already exists")
    else:
        existing = RcPlant.get(code=code)
        if existing and existing.is_active:
            raise HTTPException(400, f"Plant code '{code}' already exists")
        p = existing or RcPlant(code=code, name=name)
        old_code = (p.code or "").strip() if existing else ""
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

    # Departments / WCs / machines store WERKS as plain plant code — keep in sync
    if old_code and old_code != code:
        for d in select(d for d in RcDepartment if d.plant_id == old_code)[:]:
            d.plant_id = code
        for w in select(w for w in RcWorkCenter if w.plant == old_code)[:]:
            w.plant = code
        for m in select(m for m in RcMachine if m.plant == old_code)[:]:
            m.plant = code

    commit()
    sbu_map = _sbu_names_by_plant()
    return plant_dict(p, sbu_names=sbu_map.get(p.code) or [])
