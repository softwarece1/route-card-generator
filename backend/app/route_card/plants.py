"""Plant codes derived from SBU master (no separate plants table)."""

from __future__ import annotations

from datetime import datetime

from fastapi import HTTPException
from pony.orm import commit, db_session, select

from app.route_card.models import RcSbu
from app.route_card.op_templates import _dept, _is_admin


def _sbu_rows_by_plant() -> dict[str, list[RcSbu]]:
    by_plant: dict[str, list[RcSbu]] = {}
    for d in select(d for d in RcSbu if d.is_active)[:]:
        plant = (d.plant_id or "").strip()
        if not plant:
            continue
        by_plant.setdefault(plant, []).append(d)
    return by_plant


def _plant_dict_from_sbus(plant_code: str, sbus: list[RcSbu]) -> dict:
    names = [(s.name or s.code or "").strip() for s in sbus]
    names = [n for n in names if n]
    # Prefer latest sync stamp among SBUs for this plant
    synced = None
    for s in sbus:
        ts = getattr(s, "work_center_synced_at", None)
        if ts and (synced is None or ts > synced):
            synced = ts
    if names:
        label = f"{plant_code} - {', '.join(names)}"
    else:
        label = plant_code
    return {
        "id": plant_code,
        "code": plant_code,
        "name": names[0] if names else plant_code,
        "description": "",
        "isActive": True,
        "workCenterSyncedAt": synced.isoformat() + "Z" if synced else None,
        "sbuNames": names,
        "sbuName": names[0] if names else "",
        "label": label,
        "value": plant_code,
    }


def _plant_id_for_sbu(sbu: str) -> str:
    want = (sbu or "").strip()
    if not want:
        return ""
    rows = select(
        d for d in RcSbu if d.is_active and (d.name == want or d.code == want)
    )[:1]
    if not rows:
        return ""
    return (rows[0].plant_id or "").strip()


@db_session
def list_plant_codes_from_sbus(active_only: bool = True) -> list[dict]:
    """Distinct plant codes from SBU rows (for WC page dropdowns)."""
    by_plant = _sbu_rows_by_plant()
    codes = sorted(by_plant.keys(), key=lambda c: c)
    return [_plant_dict_from_sbus(c, by_plant[c]) for c in codes]


@db_session
def list_plants(active_only: bool = True) -> list[dict]:
    return list_plant_codes_from_sbus(active_only=active_only)


@db_session
def plant_id_for_sbu(sbu: str) -> str:
    return _plant_id_for_sbu(sbu)


@db_session
def plant_id_for_dept(dept: str) -> str:
    """Alias — callers still named for dept string matching SBU name."""
    return _plant_id_for_sbu(dept)


@db_session
def resolve_sync_plant_code(user: dict, requested: str | None = None) -> str:
    """Admin / sbu_head may sync a requested plant; otherwise use SBU plant_id."""
    code = (requested or "").strip()
    if code:
        if not (_is_admin(user) or _dept(user)):
            raise HTTPException(403, "Not allowed to sync this plant")
        return code

    if _is_admin(user):
        raise HTTPException(400, "Plant is required")

    plant = _plant_id_for_sbu(_dept(user))
    if not plant:
        raise HTTPException(
            400,
            "No plant code configured for your SBU. Ask an admin to set it on the SBU.",
        )
    return plant


@db_session
def mark_work_center_synced(plant_code: str):
    """Stamp last successful WC SAP sync on all SBUs for this plant."""
    code = (plant_code or "").strip()
    if not code:
        return
    now = datetime.utcnow()
    for s in select(s for s in RcSbu if (s.plant_id or "").strip() == code)[:]:
        s.work_center_synced_at = now
    commit()


@db_session
def get_work_center_synced_at(plant_code: str):
    code = (plant_code or "").strip()
    if not code:
        return None
    latest = None
    for s in select(s for s in RcSbu if (s.plant_id or "").strip() == code)[:]:
        ts = s.work_center_synced_at
        if ts and (latest is None or ts > latest):
            latest = ts
    return latest


def _sbu_for_plant(plant_code: str) -> RcSbu | None:
    """Primary active SBU for a plant code (lowest sort_order, then code)."""
    code = (plant_code or "").strip()
    if not code:
        return None
    # Avoid `.strip()` inside Pony queries (not SQL-translatable on Optional).
    rows = [
        s
        for s in select(s for s in RcSbu if s.is_active and s.plant_id == code)[:]
    ]
    if not rows:
        rows = [
            s
            for s in select(s for s in RcSbu if s.is_active)[:]
            if (s.plant_id or "").strip() == code
        ]
    rows.sort(key=lambda s: (int(s.sort_order or 0), (s.code or "").lower()))
    return rows[0] if rows else None


@db_session
def sbu_name_for_plant(plant_code: str) -> str:
    sbu = _sbu_for_plant(plant_code)
    if not sbu:
        return ""
    return (sbu.name or sbu.code or "").strip()


@db_session
def sbu_code_for_plant(plant_code: str) -> str:
    sbu = _sbu_for_plant(plant_code)
    if not sbu:
        return ""
    return (sbu.code or "").strip()
