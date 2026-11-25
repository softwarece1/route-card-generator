"""Plant-scoped WorkCenter master and extraction resolver."""

from __future__ import annotations

import csv
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import HTTPException
from pony.orm import commit, db_session, desc, select

from app.config.settings import settings
from app.route_card.models import RcMachine, RcWorkCenter
from app.route_card.op_templates import (
    _can_write_dept,
    _dept,
    _is_admin,
    _is_sbu_head,
    _validate_dept_name,
)

WORK_CENTRES_CSV = Path(__file__).resolve().parent / "data" / "work_centres.csv"
DUMMY_WC_CODES = {"QUALITY", "ASM", "BOND", "TORQUE", "PCB", "SPECIAL", "CABLE"}
DUMMY_PLANT_CODES = {
    "1100", "1200", "1300", "1400", "1500", "1600", "1700", "1800",
    "1900", "2000", "2100", "2200", "2300", "2400", "2500", "2600",
    "2700", "2800", "2900", "3000",
}

VALID_MODES = {"manual", "machine", "hybrid"}
LINK_LINKED = "linked"
LINK_PARTIAL = "partial"
LINK_UNRESOLVED = "unresolved"
LINK_OVERRIDE = "manual_override"

# Heuristic bucket → capability tag (mirrors route_generator._work_centre)
HEURISTIC_TAG_MAP = {
    "Torque": "torque",
    "Bonding": "bonding",
    "PCB Assembly": "pcb",
    "Quality": "inspect",
    "Special Assembly": "special",
    "Assembly": "assembly",
    "Cable Prep": "cable",
}

# Generator heuristic label → seeded WC code (dept wcAliases override these)
BUILTIN_WC_ALIASES = {
    "PCB Assembly": "PCB",
    "Quality": "QUALITY",
    "Assembly": "ASM",
    "Bonding": "BOND",
    "Torque": "TORQUE",
    "Cable Prep": "CABLE",
    "Special Assembly": "SPECIAL",
}

# Legacy seed→plant remaps — used ONLY when no plant catalog is loaded (bootstrap).
# With a live plant catalog, resolve scores by WC name/code/keywords instead.
SEED_CODE_FALLBACKS: dict[str, list[str]] = {
    "ASM": ["ASSY", "AFMM", "AMMM", "AMW1", "AMW2", "AVPAT"],
    "BOND": ["ASSY", "APLQ", "APMC"],
    "TORQUE": ["ASSY", "AFMM", "AMMM"],
    "SPECIAL": ["ASSY", "AMW2", "AVPAT", "AMMM"],
    "QUALITY": ["AIPH", "QTEST", "DMMI", "ATPG"],
    "PCB": ["ASOL", "ASSY", "APMC"],
    "CABLE": ["ACFM", "ACSL", "AMCC", "AMW1", "AWSA"],
}

# Soft verb/phrase families for scoring instruction text against WC names
_SEMANTIC_NAME_HINTS: list[tuple[tuple[str, ...], tuple[str, ...]]] = [
    (
        ("INSPECT", "VERIFY", "VISUAL", "WARPAGE", "WEIGHT", "MASS", "CHECK"),
        ("INSPECT", "INSPECTION", "PHYSICAL", "TEST", "QUALITY", "METROLOGY"),
    ),
    (
        ("WIRE", "WIRING", "CRIMP", "CABLE", "HARNESS", "ENAMELED", "ENAMEL"),
        ("WIRE", "WIRING", "CABLE", "CRIMP", "HARNESS", "MTG", "MECH"),
    ),
    (
        ("SOLDER", "PCB", "ROHS", "LEAD-FREE", "BARE BOARD", "CONFORMAL"),
        ("SOLDER", "SOLDERING", "PCB", "BOARD", "COATING"),
    ),
    (
        ("BOND", "GLUE", "PASTE", "STICK", "ADHESIVE", "PEEL", "MASK"),
        ("BOND", "ADHESIVE", "GLUE", "PASTE", "MASK", "POTTING"),
    ),
    (
        ("ASSEMBLE", "ASSEMBLY", "INSTALL", "MOUNT", "FIT", "PLACE", "TIGHTEN", "TORQUE"),
        ("ASSY", "ASSEMBLY", "MTG", "MOUNT", "MECH", "TORQUE", "FASTEN"),
    ),
]

# Fields rewritten by the resolver (manual_override keeps the prior values)
RESOLVER_LINK_KEYS = (
    "workCentre",
    "workCentreName",
    "workCentreId",
    "machine",
    "machineId",
    "linkStatus",
    "linkConfidence",
    "linkReason",
    "sapCode",
    "plant",
    "type",
    "tool",
)

DEFAULT_SHARED_SEED = [
    {
        "code": "QUALITY",
        "name": "Quality",
        "mode": "manual",
        "capability_tags": ["inspect", "quality"],
        "match_keywords": ["INSPECT", "WEIGHT", "MASS", "VERIFY", "WARPAGE"],
        "sort_order": 10,
    },
]

DEFAULT_DEPT_SEED = [
    {
        "code": "ASM",
        "name": "Assembly",
        "mode": "hybrid",
        "capability_tags": ["assembly"],
        "match_keywords": ["ASSEMBLE", "INSTALL", "FIT", "MOUNT", "PLACE"],
        "sort_order": 20,
    },
    {
        "code": "BOND",
        "name": "Bonding",
        "mode": "manual",
        "capability_tags": ["bonding"],
        "match_keywords": [
            "CLEAN",
            "PEEL OFF",
            "PASTE",
            "STICK",
            "GLUE",
            "BOND",
            "ADHERE",
            "APPLY",
            "MASK",
        ],
        "sort_order": 30,
    },
    {
        "code": "TORQUE",
        "name": "Torque",
        "mode": "hybrid",
        "capability_tags": ["torque"],
        "match_keywords": ["TORQUE"],
        "sort_order": 40,
    },
    {
        "code": "PCB",
        "name": "PCB Assembly",
        "mode": "manual",
        "capability_tags": ["pcb", "solder"],
        "match_keywords": [
            "DRILL",
            "SOLDER",
            "TRANSFORMER",
            "SHORT",
            "ROHS",
            "LEAD-FREE",
            "BARE BOARD",
        ],
        "sort_order": 50,
    },
    {
        "code": "SPECIAL",
        "name": "Special Assembly",
        "mode": "hybrid",
        "capability_tags": ["special"],
        "match_keywords": ["HEAT SINK", "SFPDP", "OPTICAL"],
        "sort_order": 60,
    },
    {
        "code": "CABLE",
        "name": "Cable Prep",
        "mode": "manual",
        "capability_tags": ["cable"],
        "match_keywords": ["CABLE", "WIRE", "CRIMP", "HARNESS"],
        "sort_order": 70,
    },
]


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (s or "").lower())


def _as_list(val: Any) -> list[str]:
    if val is None:
        return []
    if isinstance(val, list):
        return [str(x).strip() for x in val if str(x).strip()]
    if isinstance(val, str) and val.strip():
        return [x.strip() for x in val.split(",") if x.strip()]
    return []


def wc_dict(wc: RcWorkCenter, *, include_machines: bool = False) -> dict:
    out = {
        "id": wc.id,
        "sbu": wc.sbu or "",
        "code": wc.code,
        "name": wc.name,
        "mode": wc.mode or "hybrid",
        "isShared": bool(wc.is_shared),
        "plant": wc.plant or "",
        "sapCode": wc.sap_code or "",
        "capabilityTags": list(wc.capability_tags or []),
        "matchKeywords": list(wc.match_keywords or []),
        "defaultTool": wc.default_tool or "",
        "isActive": bool(wc.is_active),
        "sortOrder": wc.sort_order,
        "updatedAt": wc.updated_at.isoformat() + "Z" if wc.updated_at else None,
        "machineCount": len([m for m in wc.machines if m.is_active]),
    }
    if include_machines:
        out["machines"] = [
            machine_dict(m)
            for m in sorted(wc.machines, key=lambda x: (x.sort_order, x.name))
            if m.is_active
        ]
    return out


def machine_dict(m: RcMachine) -> dict:
    wc = m.work_center
    return {
        "id": m.id,
        "plant": m.plant or (wc.plant if wc else "") or "",
        "workCentre": m.work_centre or (wc.name if wc else "") or "",
        "workCenterId": wc.id if wc else None,
        "sbu": m.sbu or (wc.sbu if wc else "") or "",
        "code": m.code or "",
        "sapCode": m.sap_code or "",
        "name": m.name,
        "description": m.description or "",
        "capabilityTags": list(m.capability_tags or []),
        "isManualPlaceholder": bool(m.is_manual_placeholder),
        "isActive": bool(m.is_active),
        "sortOrder": m.sort_order,
        "type": "Manual" if m.is_manual_placeholder else "Machine",
        "status": "Active" if m.is_active else "Inactive",
    }


def _assert_read_dept(user: dict, dept: str) -> None:
    if _is_admin(user):
        return
    d = _dept(user)
    if not d:
        raise HTTPException(403, "Department required")
    # engineers/sbu_heads can read own dept (+ shared handled separately)
    if dept and dept != d and not _is_admin(user):
        # allow empty dept filter meaning "my dept"
        pass


def _can_edit_wc(user: dict, wc: RcWorkCenter) -> bool:
    if _is_admin(user):
        return True
    if wc.is_shared:
        return False
    plant = (wc.plant or "").strip()
    if plant and _is_sbu_head(user):
        user_plant = _plant_for_dept_name(_dept(user))
        if user_plant and user_plant == plant:
            return True
    return _can_write_dept(user, wc.sbu or "")


def _plant_for_dept_name(dept: str) -> str:
    from app.route_card.models import RcSbu

    want = (dept or "").strip()
    if not want:
        return ""
    rows = select(
        d for d in RcSbu if d.is_active and (d.name == want or d.code == want)
    )[:1]
    if not rows:
        return ""
    return (rows[0].plant_id or "").strip()


@db_session
def list_work_centers(
    user: dict,
    dept: str | None = None,
    plant: str | None = None,
    include_shared: bool = True,
    active_only: bool = True,
    include_machines: bool = False,
) -> list[dict]:
    role = (user or {}).get("role") or ""
    user_dept = _dept(user)
    want_dept = (dept or "").strip()
    want_plant = (plant or "").strip()

    if role == "sbu_head":
        want_dept = user_dept
    elif role == "engineer" and not want_dept and not want_plant:
        want_dept = user_dept
    elif role != "admin" and want_dept and want_dept != user_dept:
        raise HTTPException(403, "Not allowed to list another SBU")

    if want_dept and not want_plant:
        want_plant = _plant_for_dept_name(want_dept)

    rows = select(w for w in RcWorkCenter)[:]
    out: list[RcWorkCenter] = []
    for w in rows:
        if active_only and not w.is_active:
            continue
        if want_plant:
            if (w.plant or "").strip() != want_plant:
                continue
            out.append(w)
            continue
        if w.is_shared:
            if include_shared:
                out.append(w)
            continue
        if want_dept:
            if (w.sbu or "") == want_dept:
                out.append(w)
        elif _is_admin(user):
            out.append(w)
        elif (w.sbu or "") == user_dept:
            out.append(w)
    out.sort(key=lambda w: ((w.plant or ""), w.sort_order, (w.code or "").lower(), w.name.lower()))
    return [wc_dict(w, include_machines=include_machines) for w in out]


@db_session
def catalog_for_dropdowns(
    user: dict, dept: str | None = None, plant: str | None = None
) -> dict:
    """Slim catalog for route editor / templates — plant-scoped for the SBU."""
    d = (dept or _dept(user) or "").strip()
    want_plant = (plant or "").strip() or (_plant_for_dept_name(d) if d else "")
    if want_plant:
        items = list_work_centers(
            user,
            plant=want_plant,
            include_shared=False,
            active_only=True,
            include_machines=False,
        )
    else:
        items = list_work_centers(
            user,
            dept=d or None,
            include_shared=True,
            active_only=True,
            include_machines=False,
        )
    return {"items": items, "sbu": d, "plant": want_plant}


@db_session
def get_work_center(wc_id: int, user: dict) -> dict:
    wc = RcWorkCenter.get(id=wc_id)
    if not wc or not wc.is_active:
        raise HTTPException(404, "Work centre not found")
    if not _can_edit_wc(user, wc) and not _is_admin(user):
        role = (user or {}).get("role") or ""
        plant = (wc.plant or "").strip()
        user_plant = _plant_for_dept_name(_dept(user)) if role != "admin" else plant
        if plant and user_plant and plant == user_plant:
            pass
        elif not wc.is_shared and (wc.sbu or "") != _dept(user) and role != "admin":
            raise HTTPException(403, "Not allowed")
    return wc_dict(wc, include_machines=False)


def _parse_mode(mode: str) -> str:
    m = (mode or "hybrid").strip().lower()
    if m not in VALID_MODES:
        raise HTTPException(400, "mode must be manual, machine, or hybrid")
    return m


@db_session
def upsert_work_center(user: dict, body: dict, wc_id: int | None = None) -> dict:
    is_shared = bool(body.get("isShared") or body.get("is_shared"))
    if is_shared and not _is_admin(user):
        raise HTTPException(403, "Only admin can manage shared work centres")

    plant = (body.get("plant") or "").strip()
    # Plant-scoped master: empty dept is allowed when plant is set
    if is_shared:
        dept = ""
    elif plant and not (body.get("sbu") or "").strip():
        dept = ""
        if not _is_admin(user):
            user_plant = _plant_for_dept_name(_dept(user))
            if not user_plant or user_plant != plant:
                raise HTTPException(403, "Not allowed to edit work centres for this plant")
    else:
        dept = (body.get("sbu") or _dept(user) or "").strip()
        if _is_sbu_head(user):
            dept = _dept(user)
        if not _can_write_dept(user, dept):
            raise HTTPException(403, "Not allowed to edit this SBU")
        if dept:
            _validate_dept_name(dept)

    code = (body.get("code") or "").strip().upper()
    name = (body.get("name") or "").strip()
    if not code or not name:
        raise HTTPException(400, "code and name are required")

    if wc_id:
        wc = RcWorkCenter.get(id=wc_id)
        if not wc:
            raise HTTPException(404, "Work centre not found")
        if not _can_edit_wc(user, wc):
            raise HTTPException(403, "Not allowed")
    else:
        # uniqueness by plant+code (or shared/dept legacy)
        if plant:
            hit = select(
                w
                for w in RcWorkCenter
                if (w.plant or "") == plant and w.code == code and w.is_active
            )[:1]
        elif is_shared:
            hit = select(
                w for w in RcWorkCenter if w.is_shared and w.code == code and w.is_active
            )[:1]
        else:
            hit = select(
                w
                for w in RcWorkCenter
                if (not w.is_shared) and w.sbu == dept and w.code == code and w.is_active
            )[:1]
        if hit:
            raise HTTPException(400, f"Work centre code '{code}' already exists")
        wc = RcWorkCenter(
            sbu=dept,
            code=code,
            name=name,
            mode=_parse_mode(body.get("mode") or "manual"),
            is_shared=is_shared,
            plant=plant,
            sap_code=body.get("sapCode") or body.get("sap_code") or "",
            capability_tags=_as_list(body.get("capabilityTags") or body.get("capability_tags")),
            match_keywords=_as_list(body.get("matchKeywords") or body.get("match_keywords")),
            default_tool=body.get("defaultTool") or body.get("default_tool") or "",
            sort_order=int(body.get("sortOrder") or body.get("sort_order") or 0),
            is_active=True,
        )

    if wc_id:
        if "code" in body:
            wc.code = code
        if "name" in body:
            wc.name = name
        if "mode" in body:
            wc.mode = _parse_mode(body.get("mode"))
        if "plant" in body:
            wc.plant = body.get("plant") or ""
        if "sapCode" in body or "sap_code" in body:
            wc.sap_code = body.get("sapCode") or body.get("sap_code") or ""
        if "capabilityTags" in body or "capability_tags" in body:
            wc.capability_tags = _as_list(
                body.get("capabilityTags") or body.get("capability_tags")
            )
        if "matchKeywords" in body or "match_keywords" in body:
            wc.match_keywords = _as_list(
                body.get("matchKeywords") or body.get("match_keywords")
            )
        if "defaultTool" in body or "default_tool" in body:
            wc.default_tool = body.get("defaultTool") or body.get("default_tool") or ""
        if "sortOrder" in body or "sort_order" in body:
            wc.sort_order = int(body.get("sortOrder") or body.get("sort_order") or 0)
        if _is_admin(user) and ("dept" in body) and not wc.is_shared:
            new_dept = (body.get("sbu") or "").strip()
            if new_dept:
                _validate_dept_name(new_dept)
                wc.sbu = new_dept
        if "isActive" in body:
            wc.is_active = bool(body["isActive"])

    # machine-mode must have ≥1 active machine when activating
    if wc.is_active and (wc.mode or "") == "machine":
        active_m = [m for m in wc.machines if m.is_active and not m.is_manual_placeholder]
        if not active_m and wc_id:
            # allow create empty then add machines; only enforce on update activate
            if body.get("isActive") is True or "mode" in body:
                if not active_m:
                    raise HTTPException(
                        400, "Machine-mode work centre needs at least one active machine"
                    )

    wc.updated_at = datetime.utcnow()
    commit()
    return wc_dict(wc, include_machines=False)


@db_session
def delete_work_center(wc_id: int, user: dict) -> dict:
    wc = RcWorkCenter.get(id=wc_id)
    if not wc:
        raise HTTPException(404, "Work centre not found")
    if not _can_edit_wc(user, wc):
        raise HTTPException(403, "Not allowed")
    wc.is_active = False
    wc.updated_at = datetime.utcnow()
    for m in wc.machines:
        m.is_active = False
    commit()
    return {"ok": True, "id": wc_id}


@db_session
def upsert_machine(user: dict, body: dict, machine_id: int | None = None) -> dict:
    wc_id = body.get("workCenterId") or body.get("work_center_id")
    wc: RcWorkCenter | None = None
    if wc_id:
        wc = RcWorkCenter.get(id=int(wc_id))
        if not wc or not wc.is_active:
            raise HTTPException(404, "Work centre not found")
        if not _can_edit_wc(user, wc):
            raise HTTPException(403, "Not allowed")
    elif machine_id:
        m0 = RcMachine.get(id=machine_id)
        if not m0:
            raise HTTPException(404, "Machine not found")
        wc = m0.work_center
        if wc and not _can_edit_wc(user, wc):
            raise HTTPException(403, "Not allowed")
        if not wc and not _is_admin(user):
            raise HTTPException(403, "Not allowed")
    else:
        # legacy: create under workCentre string — admin only path
        if not _is_admin(user):
            raise HTTPException(400, "workCenterId is required")
        label = (body.get("workCentre") or body.get("work_centre") or "").strip()
        if not label:
            raise HTTPException(400, "workCenterId or workCentre required")
        # find or create shared/heuristic WC under admin dept or shared
        dept = (body.get("sbu") or "").strip()
        found = select(
            w
            for w in RcWorkCenter
            if w.is_active and ((w.sbu == dept and not w.is_shared) or w.name == label)
        )[:1]
        wc = found[0] if found else None
        if not wc:
            code = _norm(label).upper()[:16] or "WC"
            wc = RcWorkCenter(
                sbu=dept,
                code=code,
                name=label,
                mode="hybrid",
                is_shared=not bool(dept),
                plant=body.get("plant") or "",
                capability_tags=[],
                match_keywords=[],
                is_active=True,
            )

    if (wc.mode or "") == "manual" and not bool(
        body.get("isManualPlaceholder") or body.get("is_manual_placeholder")
    ):
        # still allow placeholders on manual WC; real machines discouraged but not blocked for hybrid migration
        pass

    name = (body.get("name") or "").strip()
    if not name and not machine_id:
        raise HTTPException(400, "name is required")

    if machine_id:
        m = RcMachine.get(id=machine_id)
        if not m:
            raise HTTPException(404, "Machine not found")
    else:
        m = RcMachine(
            plant=(body.get("plant") or (wc.plant if wc else "") or ""),
            work_centre=(wc.name if wc else body.get("workCentre") or ""),
            work_center=wc,
            sbu=(wc.sbu if wc else body.get("sbu") or ""),
            code=(body.get("code") or "").strip().upper(),
            sap_code=body.get("sapCode") or body.get("sap_code") or "",
            name=name,
            description=body.get("description") or "",
            capability_tags=_as_list(body.get("capabilityTags") or body.get("capability_tags")),
            is_manual_placeholder=bool(
                body.get("isManualPlaceholder") or body.get("is_manual_placeholder")
            ),
            sort_order=int(body.get("sortOrder") or body.get("sort_order") or 0),
            is_active=True,
        )

    if machine_id:
        if wc and ("workCenterId" in body or "work_center_id" in body):
            m.work_center = wc
            m.work_centre = wc.name
            m.sbu = wc.sbu or ""
            m.plant = wc.plant or m.plant or ""
        if "name" in body:
            m.name = name or m.name
        if "description" in body:
            m.description = body.get("description") or ""
        if "code" in body:
            m.code = (body.get("code") or "").strip().upper()
        if "sapCode" in body or "sap_code" in body:
            m.sap_code = body.get("sapCode") or body.get("sap_code") or ""
        if "capabilityTags" in body or "capability_tags" in body:
            m.capability_tags = _as_list(
                body.get("capabilityTags") or body.get("capability_tags")
            )
        if "isManualPlaceholder" in body or "is_manual_placeholder" in body:
            m.is_manual_placeholder = bool(
                body.get("isManualPlaceholder") or body.get("is_manual_placeholder")
            )
        if "sortOrder" in body or "sort_order" in body:
            m.sort_order = int(body.get("sortOrder") or body.get("sort_order") or 0)
        if "plant" in body:
            m.plant = body.get("plant") or ""
        if "isActive" in body:
            m.is_active = bool(body["isActive"])
        if "workCentre" in body and not wc:
            m.work_centre = body.get("workCentre") or m.work_centre

    if not m.name:
        raise HTTPException(400, "name is required")
    commit()
    return machine_dict(m)


@db_session
def delete_machine(machine_id: int, user: dict) -> dict:
    m = RcMachine.get(id=machine_id)
    if not m:
        raise HTTPException(404, "Machine not found")
    wc = m.work_center
    if wc:
        if not _can_edit_wc(user, wc):
            raise HTTPException(403, "Not allowed")
    elif not _is_admin(user):
        raise HTTPException(403, "Not allowed")
    m.is_active = False
    commit()
    return {"ok": True, "id": machine_id}


@db_session
def list_machines(user: dict | None = None, active_only: bool = True) -> list[dict]:
    """Backward-compatible flat machine list (scoped when user provided)."""
    q = select(m for m in RcMachine)
    if active_only:
        q = select(m for m in RcMachine if m.is_active)
    rows = q.order_by(RcMachine.sort_order, RcMachine.name)[:]
    if user and not _is_admin(user):
        d = _dept(user)
        rows = [
            m
            for m in rows
            if (m.work_center and (m.work_center.is_shared or (m.sbu or "") == d))
            or ((m.sbu or "") == d)
            or (not m.work_center and _is_admin(user))
        ]
        # engineers/sbu_head: also include unscoped legacy if no dept on machine and shared wc
        if d:
            rows = [
                m
                for m in rows
                if (m.sbu or "") in ("", d)
                or (m.work_center and m.work_center.is_shared)
            ]
    return [machine_dict(m) for m in rows]


# ---------------------------------------------------------------------------
# Resolver
# ---------------------------------------------------------------------------


def _load_catalog(dept: str, plant: str | None = None) -> list[RcWorkCenter]:
    d = (dept or "").strip()
    want_plant = (plant or "").strip() or _plant_for_dept_name(d)
    rows = select(w for w in RcWorkCenter if w.is_active)[:]
    if want_plant:
        return [w for w in rows if (w.plant or "").strip() == want_plant]
    dept_rows = [w for w in rows if (not w.is_shared) and (w.sbu or "") == d]
    shared = [w for w in rows if w.is_shared]
    return dept_rows + shared


def _hint_tags(heuristic_wc: str, instruction: str) -> set[str]:
    tags: set[str] = set()
    hw = (heuristic_wc or "").strip()
    if hw in HEURISTIC_TAG_MAP:
        tags.add(HEURISTIC_TAG_MAP[hw])
    else:
        # After alias remap, heuristic may be a code (PCB, QUALITY, …)
        for label, code in BUILTIN_WC_ALIASES.items():
            if _norm(hw) == _norm(code) and label in HEURISTIC_TAG_MAP:
                tags.add(HEURISTIC_TAG_MAP[label])
                break
    t = (instruction or "").upper()
    if "TORQUE" in t:
        tags.add("torque")
    if any(
        k in t
        for k in (
            "SOLDER",
            "PCB",
            "DRILL",
            "ROHS",
            "SHORT",
            "JUMPER",
            "CONFORMAL",
            "TRANSFORMER",
            "BARE BOARD",
        )
    ):
        tags.add("pcb")
        tags.add("solder")
    if any(k in t for k in ("BOND", "GLUE", "PASTE", "PEEL", "MASK", "CLEAN", "MASKING")):
        tags.add("bonding")
    if any(k in t for k in ("INSPECT", "VERIFY", "WARPAGE", "WEIGHT", "VISUAL")):
        tags.add("inspect")
    if any(k in t for k in ("CABLE", "CRIMP", "WIRE", "HARNESS", "ENAMELED", "ENAMEL")):
        tags.add("cable")
    if any(k in t for k in ("HEAT SINK", "SFPDP", "OPTICAL")):
        tags.add("special")
    if not tags:
        tags.add("assembly")
    return tags


def _derived_keywords(wc: Any) -> list[str]:
    """Configured match_keywords plus tokens from code/name/sap (name is primary)."""
    toks: list[str] = []
    stop = {"WC", "NO", "OF", "THE", "AND", "OR", "FOR", "TO", "IN", "ON", "AT", "BY"}
    for k in getattr(wc, "match_keywords", None) or []:
        u = str(k).upper().strip()
        if u and u not in toks:
            toks.append(u)
    for src in (
        getattr(wc, "name", None),
        getattr(wc, "code", None),
        getattr(wc, "sap_code", None),
    ):
        for part in re.findall(r"[A-Za-z0-9]{2,}", str(src or "")):
            u = part.upper()
            if u not in toks and u not in stop:
                toks.append(u)
    return toks


def _name_phrases(wc: Any) -> list[str]:
    """Multi-word phrases from WC name for stronger instruction matching."""
    name = re.sub(r"\s+", " ", str(getattr(wc, "name", None) or "")).strip().upper()
    if not name:
        return []
    phrases = [name]
    parts = [p for p in re.split(r"[\s/&,]+", name) if len(p) >= 3]
    for i in range(len(parts) - 1):
        phrases.append(f"{parts[i]} {parts[i + 1]}")
    return phrases


def _effective_aliases(
    aliases: dict | None,
    *,
    include_builtins: bool = True,
) -> dict[str, str]:
    """Dept/session aliases; builtins only when no plant catalog (bootstrap)."""
    out: dict[str, str] = dict(BUILTIN_WC_ALIASES) if include_builtins else {}
    for k, v in (aliases or {}).items():
        key = str(k or "").strip()
        val = str(v or "").strip()
        if key and val:
            out[key] = val
    return out


def _catalog_code_set(catalog: list) -> set[str]:
    return {_norm(getattr(w, "code", None) or "") for w in (catalog or []) if getattr(w, "code", None)}


def remap_heuristic_to_catalog(
    heuristic: str,
    catalog: list,
    *,
    use_seed_fallbacks: bool = True,
) -> tuple[str, str]:
    """Map heuristic labels/codes onto a code that exists in the plant catalog.

    When ``use_seed_fallbacks`` is False (plant catalog present), only soft
    name/code matching is used — no hard-coded ASSY/BOND chains.
    """
    h = (heuristic or "").strip()
    if not h:
        return h, ""
    codes = _catalog_code_set(catalog)
    if not codes:
        return h, ""
    hn = _norm(h)
    if hn in codes:
        return h, ""
    if use_seed_fallbacks:
        for cand in SEED_CODE_FALLBACKS.get(h.upper(), []) or SEED_CODE_FALLBACKS.get(h, []):
            if _norm(cand) in codes:
                return cand, f"Mapped {h} → {cand} (plant catalog)"
        for seed, chain in SEED_CODE_FALLBACKS.items():
            if hn == _norm(seed):
                for cand in chain:
                    if _norm(cand) in codes:
                        return cand, f"Mapped {h} → {cand} (plant catalog)"
    # Soft match: catalog code/name vs heuristic
    for w in catalog or []:
        code = (getattr(w, "code", None) or "").strip()
        name = (getattr(w, "name", None) or "").strip()
        cn, nn = _norm(code), _norm(name)
        if not cn:
            continue
        if hn and (hn == nn or hn in nn or nn in hn or hn in cn or cn in hn):
            return code, f"Mapped {h} → {code} (name/code match)"
    return h, ""


def _semantic_name_score(instruction: str, wc: Any) -> float:
    """Soft overlap between instruction verbs and WC name tokens."""
    text_u = (instruction or "").upper()
    name_u = " ".join(
        [
            str(getattr(wc, "name", None) or ""),
            str(getattr(wc, "code", None) or ""),
        ]
    ).upper()
    if not text_u or not name_u:
        return 0.0
    score = 0.0
    for instr_keys, name_keys in _SEMANTIC_NAME_HINTS:
        if any(k in text_u for k in instr_keys) and any(k in name_u for k in name_keys):
            score += 18.0
    return min(score, 36.0)


def _score_wc(
    wc: RcWorkCenter,
    heuristic: str,
    instruction: str,
    aliases: dict,
    *,
    include_builtins: bool = True,
) -> float:
    score = 0.0
    aliases = _effective_aliases(aliases, include_builtins=include_builtins)
    # 1) alias exact → code / name / sap
    alias_target = aliases.get(heuristic or "")
    if alias_target and _norm(alias_target) in (
        _norm(wc.code),
        _norm(wc.name),
        _norm(wc.sap_code or ""),
    ):
        score += 100.0
    # 2) keywords (configured + derived from name/code)
    text_u = (instruction or "").upper()
    kws = _derived_keywords(wc)
    hits = sum(1 for k in kws if k and len(k) >= 2 and k in text_u)
    if hits:
        score += 40.0 + min(hits, 5) * 5.0
    # 2b) WC name phrases (primary signal for plant catalogs)
    phrase_hits = 0
    for ph in _name_phrases(wc):
        if len(ph) >= 4 and ph in text_u:
            phrase_hits += 1
        else:
            # partial: most tokens of a phrase appear in instruction
            toks = [t for t in ph.split() if len(t) >= 3]
            if len(toks) >= 2 and sum(1 for t in toks if t in text_u) >= max(2, len(toks) - 1):
                phrase_hits += 1
    if phrase_hits:
        score += 35.0 + min(phrase_hits, 3) * 8.0
    # 2c) soft semantic verb ↔ name
    score += _semantic_name_score(instruction, wc)
    # 3) capability tags
    want = _hint_tags(heuristic, instruction)
    have = {str(t).lower() for t in (wc.capability_tags or [])}
    overlap = want & have
    if overlap:
        score += 25.0 + 5.0 * len(overlap)
    # 4) fuzzy name/code vs heuristic (and vs aliased code)
    hn = _norm(heuristic)
    targets = (_norm(wc.name), _norm(wc.code), _norm(wc.sap_code or ""))
    if hn and hn in targets:
        score += 50.0
    elif hn and (hn in _norm(wc.name) or _norm(wc.name) in hn):
        score += 20.0
    if alias_target:
        an = _norm(alias_target)
        if an and an in targets:
            score += 30.0
    # Prefer plant (non-shared) rows slightly over shared fallbacks
    if not getattr(wc, "is_shared", False):
        score += 3.0
    score += max(0, 10 - (wc.sort_order or 0) * 0.01)
    return score


def _pick_machine(wc: RcWorkCenter, instruction: str) -> tuple[RcMachine | None, str]:
    mode = (wc.mode or "hybrid").lower()
    actives = [m for m in wc.machines if m.is_active]
    real = [m for m in actives if not m.is_manual_placeholder]
    if mode == "manual":
        return None, LINK_LINKED
    if mode == "machine":
        pool = real or actives
    else:
        pool = real if real else actives
    if not pool:
        if mode == "machine":
            return None, LINK_PARTIAL
        return None, LINK_LINKED
    if len(pool) == 1:
        return pool[0], LINK_LINKED
    want = _hint_tags("", instruction)
    scored = []
    for m in pool:
        have = {str(t).lower() for t in (m.capability_tags or [])}
        scored.append((len(want & have), m))
    scored.sort(key=lambda x: (-x[0], x[1].sort_order, x[1].name))
    if scored[0][0] > 0 and (len(scored) == 1 or scored[0][0] > scored[1][0]):
        return scored[0][1], LINK_LINKED
    return None, LINK_PARTIAL


def _note_text_bag(note: dict) -> str:
    return " ".join(
        str(note.get(k) or "")
        for k in ("text", "insight", "elaboratedText")
    )


def _instruction_bag(row: dict, note_by_step: dict[int, str]) -> str:
    op_no = int(row.get("opNo") or 0)
    step = op_no // 10 if op_no else 0
    note_bits = note_by_step.get(step) or note_by_step.get(op_no) or ""
    return " ".join(
        [
            str(row.get("instructionText") or ""),
            str(row.get("insight") or ""),
            str(row.get("operation") or ""),
            note_bits,
        ]
    )


@db_session
def resolve_operations(
    operations: list[dict],
    *,
    dept: str,
    aliases: dict | None = None,
    notes: list | None = None,
    plant: str | None = None,
) -> list[dict]:
    """Link free-text WC/machine on ops to plant/dept catalog. Mutates copies."""
    if not getattr(settings, "WC_RESOLVER_ENABLED", True):
        return operations

    d = (dept or "").strip()
    catalog = _load_catalog(d, plant=plant)
    note_by_step: dict[int, str] = {}
    for n in notes or []:
        if not isinstance(n, dict):
            continue
        bag = _note_text_bag(n)
        try:
            step = int(n.get("stepNo") or 0)
        except (TypeError, ValueError):
            step = 0
        if step:
            note_by_step[step] = (note_by_step.get(step) or "") + " " + bag
        try:
            label = int(str(n.get("label") or "").strip() or 0)
        except (TypeError, ValueError):
            label = 0
        if label and label != step:
            note_by_step[label] = (note_by_step.get(label) or "") + " " + bag

    has_plant_catalog = any(not w.is_shared for w in catalog)
    # With a plant catalog: dept aliases only — no global Assembly→ASM / SEED→ASSY maps
    aliases = _effective_aliases(aliases, include_builtins=not has_plant_catalog)
    catalog_codes = _catalog_code_set(catalog)
    out: list[dict] = []
    for op in operations or []:
        row = dict(op)
        if (row.get("linkStatus") or row.get("link_status")) == LINK_OVERRIDE:
            out.append(row)
            continue

        heuristic = (row.get("workCentre") or row.get("workCenter") or "").strip()
        instruction = _instruction_bag(row, note_by_step)

        if not catalog:
            row["linkStatus"] = ""
            row["linkConfidence"] = None
            row["linkReason"] = "No WC master configured for this plant/SBU"
            out.append(row)
            continue

        remap_reason = ""
        # Explicit dept alias (label → real plant code)
        if heuristic in aliases:
            heuristic = aliases[heuristic]
            row["workCentre"] = heuristic

        if has_plant_catalog:
            remapped, remap_reason = remap_heuristic_to_catalog(
                heuristic, catalog, use_seed_fallbacks=False
            )
            if remapped != heuristic:
                heuristic = remapped
                row["workCentre"] = heuristic
            # Seed/dummy codes not in plant catalog → ignore; score by instruction vs names
            elif (
                heuristic.upper() in DUMMY_WC_CODES
                and _norm(heuristic) not in catalog_codes
            ):
                remap_reason = f"Ignored seed code {heuristic}; scoring catalog by instruction/name"
                heuristic = ""
        else:
            remapped, remap_reason = remap_heuristic_to_catalog(
                heuristic, catalog, use_seed_fallbacks=True
            )
            if remapped != heuristic:
                heuristic = remapped
                row["workCentre"] = heuristic

        scored = [
            (
                _score_wc(
                    w,
                    heuristic,
                    instruction,
                    aliases,
                    include_builtins=not has_plant_catalog,
                ),
                w,
            )
            for w in catalog
        ]
        scored.sort(key=lambda x: (-x[0], 0 if not x[1].is_shared else 1, x[1].sort_order))
        best_score, best = scored[0]
        second = scored[1][0] if len(scored) > 1 else 0.0

        if best_score < 20.0:
            if has_plant_catalog:
                row["linkStatus"] = LINK_UNRESOLVED
                row["linkConfidence"] = 0.0
                row["workCentreId"] = None
                row["machineId"] = None
                row["linkReason"] = "No matching work centre in plant catalog"
            else:
                row["linkStatus"] = ""
                row["linkReason"] = "Using heuristic (shared catalog only / weak match)"
            out.append(row)
            continue

        if second > 0 and abs(best_score - second) < 5.0 and best_score < 80.0:
            # Prefer non-shared when scores are nearly tied
            top = [s for s in scored if abs(s[0] - best_score) < 5.0]
            plant_hits = [s for s in top if not s[1].is_shared]
            if len(plant_hits) == 1 and plant_hits[0][0] >= 20.0:
                best_score, best = plant_hits[0]
            else:
                row["linkStatus"] = LINK_UNRESOLVED
                row["linkConfidence"] = round(min(best_score / 100.0, 0.99), 3)
                row["workCentreId"] = None
                row["machineId"] = None
                row["linkReason"] = "Ambiguous work centre match"
                out.append(row)
                continue

        # linked
        label = best.name
        code = best.code
        row["workCentre"] = code or label
        row["workCentreName"] = label
        row["workCentreId"] = best.id
        row["sapCode"] = (best.sap_code or code or "").strip()
        row["plant"] = (best.plant or "").strip()
        row["type"] = label
        if best.default_tool and not (row.get("tool") or "").strip():
            row["tool"] = best.default_tool

        mach, mstatus = _pick_machine(best, instruction)
        if mach:
            row["machine"] = mach.name
            row["machineId"] = mach.id
        else:
            if (best.mode or "").lower() == "manual":
                row["machine"] = ""
                row["machineId"] = None
            else:
                if mstatus == LINK_PARTIAL:
                    row["machineId"] = None
        row["linkStatus"] = mstatus
        row["linkConfidence"] = round(min(best_score / 100.0, 0.99), 3)
        reason = f"Matched {best.code} ({best.name})"
        if remap_reason:
            reason = f"{remap_reason}; {reason}"
        row["linkReason"] = reason
        out.append(row)
    return out


def merge_resolved_preserving_overrides(
    existing: list[dict],
    resolved: list[dict],
) -> tuple[list[dict], dict[str, int]]:
    """
    Apply resolver output onto existing ops.

    Rows with linkStatus=manual_override keep WC/machine fields unchanged.
    Returns (merged_ops, counts) where counts has linked/unresolved/partial/skippedOverrides.
    """
    by_no = {int(r.get("opNo") or 0): dict(r) for r in (resolved or []) if r}
    out: list[dict] = []
    counts = {"linked": 0, "unresolved": 0, "partial": 0, "skippedOverrides": 0, "other": 0}
    for op in existing or []:
        row = dict(op)
        op_no = int(row.get("opNo") or 0)
        status = (row.get("linkStatus") or row.get("link_status") or "").strip()
        if status == LINK_OVERRIDE:
            counts["skippedOverrides"] += 1
            out.append(row)
            continue
        fresh = by_no.get(op_no)
        if not fresh:
            out.append(row)
            continue
        for key in RESOLVER_LINK_KEYS:
            if key in fresh:
                row[key] = fresh.get(key)
        st = (row.get("linkStatus") or "").strip()
        if st == LINK_LINKED:
            counts["linked"] += 1
        elif st == LINK_UNRESOLVED:
            counts["unresolved"] += 1
        elif st == LINK_PARTIAL:
            counts["partial"] += 1
        else:
            counts["other"] += 1
        out.append(row)
    return out, counts


def unresolved_wc_messages(operations: list[dict]) -> list[str]:
    msgs = []
    for op in operations or []:
        if (op.get("linkStatus") or "") == LINK_UNRESOLVED:
            msgs.append(
                f"OP {op.get('opNo')}: work centre unresolved"
                + (f" — {op.get('linkReason')}" if op.get("linkReason") else "")
            )
        elif (op.get("linkStatus") or "") == LINK_PARTIAL:
            msgs.append(
                f"OP {op.get('opNo')}: work centre linked but machine needs selection"
            )
    return msgs


def _seed_machines_for_wc(wc: RcWorkCenter, plant: str) -> int:
    """Create 1–2 sample machines for non-manual WCs (idempotent by code)."""
    mode = (wc.mode or "").lower()
    if mode == "manual":
        # one manual placeholder so linking has something to pick
        code = f"{wc.code}-MAN"
        hit = select(
            m
            for m in RcMachine
            if m.work_center == wc and m.code == code
        )[:1]
        if hit:
            return 0
        RcMachine(
            plant=plant or "",
            work_centre=wc.name,
            work_center=wc,
            sbu=wc.sbu or "",
            code=code,
            name=f"{wc.name} (manual)",
            description="Manual / bench placeholder",
            capability_tags=list(wc.capability_tags or []),
            is_manual_placeholder=True,
            is_active=True,
            sort_order=10,
        )
        return 1

    created = 0
    for i, suffix in enumerate(("M1", "M2"), start=1):
        code = f"{wc.code}-{suffix}"
        hit = select(
            m
            for m in RcMachine
            if m.work_center == wc and m.code == code
        )[:1]
        if hit:
            continue
        RcMachine(
            plant=plant or "",
            work_centre=wc.name,
            work_center=wc,
            sbu=wc.sbu or "",
            code=code,
            sap_code=f"{(plant or 'P')}{wc.code}{i}",
            name=f"{wc.name} {suffix}",
            description=f"Sample machine {suffix} for {wc.sbu or 'shared'}",
            capability_tags=list(wc.capability_tags or []),
            is_manual_placeholder=False,
            is_active=True,
            sort_order=10 * i,
        )
        created += 1
    return created


@db_session
def deactivate_dummy_work_centers() -> dict:
    """Deactivate seeded Quality/ASM/… centres (empty/dummy plant) and their machines.

    Does not touch real spreadsheet centres that reuse codes like ASM/PCB on a
    real SAP plant.
    """
    deactivated = 0
    machines = 0
    for wc in select(w for w in RcWorkCenter if w.is_active)[:]:
        plant = (wc.plant or "").strip()
        code = (wc.code or "").strip().upper()
        is_dummy_seed = (
            wc.is_shared
            or plant in DUMMY_PLANT_CODES
            or (code in DUMMY_WC_CODES and plant == "")
        )
        if not is_dummy_seed:
            continue
        wc.is_active = False
        wc.updated_at = datetime.utcnow()
        deactivated += 1
        for m in wc.machines:
            if m.is_active:
                m.is_active = False
                machines += 1
    for m in select(x for x in RcMachine if x.is_active)[:]:
        wc = m.work_center
        if wc and not wc.is_active:
            m.is_active = False
            machines += 1
    commit()
    return {"deactivated": deactivated, "machinesDeactivated": machines}


@db_session
def import_work_centres_from_csv(csv_path: Path | None = None) -> dict:
    """Idempotent upsert of plant-scoped work centres from the end-user CSV."""
    path = Path(csv_path) if csv_path else WORK_CENTRES_CSV
    if not path.is_file():
        return {"created": 0, "updated": 0, "skipped": 0, "path": str(path), "error": "missing"}

    created = 0
    updated = 0
    skipped = 0
    # Index existing by (plant, code)
    existing = {
        ((w.plant or "").strip(), (w.code or "").strip().upper()): w
        for w in select(w for w in RcWorkCenter)[:]
    }

    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            plant = str(row.get("plant") or "").strip()
            code = str(row.get("code") or "").strip().upper()
            name = str(row.get("name") or "").strip() or code
            if not plant or not code:
                skipped += 1
                continue
            key = (plant, code)
            hit = existing.get(key)
            if hit:
                changed = False
                if (hit.name or "").strip() != name:
                    hit.name = name
                    changed = True
                if not (hit.sap_code or "").strip():
                    hit.sap_code = code
                    changed = True
                if hit.mode != "manual":
                    hit.mode = "manual"
                    changed = True
                if not hit.is_active:
                    hit.is_active = True
                    changed = True
                if hit.is_shared:
                    hit.is_shared = False
                    changed = True
                if changed:
                    hit.updated_at = datetime.utcnow()
                    updated += 1
            else:
                wc = RcWorkCenter(
                    sbu="",
                    code=code,
                    name=name,
                    mode="manual",
                    is_shared=False,
                    plant=plant,
                    sap_code=code,
                    capability_tags=[],
                    match_keywords=[code],
                    default_tool="",
                    sort_order=0,
                    is_active=True,
                )
                existing[key] = wc
                created += 1

    commit()
    return {
        "created": created,
        "updated": updated,
        "skipped": skipped,
        "path": str(path),
    }


@db_session
def seed_default_catalog(dept: str | None = None, plant: str | None = None) -> dict:
    """Deprecated: replaced by CSV import. Kept as no-op for callers."""
    return {
        "created": 0,
        "machinesCreated": 0,
        "sbu": (dept or "").strip() or "*",
        "deptCount": 0,
        "deprecated": True,
    }


# Legacy shared seed password — migrated to Admin@<empId> on startup
LEGACY_SEED_PASSWORD = "Adm!n@123bel"


def seed_password_for_emp(emp_id: str) -> str:
    """Per-user seed password: Admin@ + 6-digit empId (e.g. Admin@482917)."""
    return f"Admin@{str(emp_id or '').strip()}"


def _dept_name_slug(code: str) -> str:
    """MR → mr, MCE_NCS → mce-ncs, EW_A → ew-a."""
    s = (code or "").strip().lower().replace("_", "-").replace("/", "-")
    s = re.sub(r"[^a-z0-9\-]+", "", s)
    return s or "dept"


def _stable_emp_id(label: str, used: set[str]) -> str:
    """Deterministic 6-digit empId from label; bump on collision."""
    import hashlib

    h = int(hashlib.sha256(label.encode("utf-8")).hexdigest()[:8], 16)
    n = 100000 + (h % 900000)
    for _ in range(900000):
        cand = f"{n:06d}"
        if cand not in used:
            return cand
        n = 100000 + ((n + 1 - 100000) % 900000)
    raise RuntimeError("exhausted empId space")


# Demo org seed — only these SBUs (lean transactional cleanup set).
DEMO_ORG_SBU_CODES = ("MR", "MS", "ADSN", "NS1", "NS2")
DEMO_ORG_DEPT_CODES = ("PMG", "IED")


@db_session
def seed_sbu_head_and_ied_users() -> dict:
    """Idempotent demo org for DEMO_ORG_SBU_CODES.

    Per SBU: one sbu_head; per PMG/IED dept: one dept_head + one engineer.
    Wiring: engineer → dept_head; dept_head → sbu_head.
    Password: Admin@<empId>. Also migrates legacy shared-password accounts.
    """
    from app.route_card.departments import ensure_default_departments
    from app.route_card.models import RcDepartment, RcSbu, RcUser
    from app.security import hash_password, verify_password

    used = {u.emp_id for u in select(u for u in RcUser)[:]}
    created = 0
    skipped = 0
    linked = 0
    reset = 0
    keep = {c.upper() for c in DEMO_ORG_SBU_CODES}

    def _ensure_user(
        *,
        name: str,
        role: str,
        sbu: RcSbu,
        department: RcDepartment | None,
        reports_to: RcUser | None,
        match_existing: RcUser | None,
    ) -> RcUser:
        nonlocal created, skipped, linked
        u = match_existing
        if u is None:
            found = select(x for x in RcUser if x.name == name)[:1]
            u = found[0] if found else None
        if u is not None:
            skipped += 1
        else:
            emp_id = _stable_emp_id(f"{role}:{sbu.code}:{name}", used)
            used.add(emp_id)
            u = RcUser(
                emp_id=emp_id,
                name=name,
                sbu=sbu.name,
                password_hash=hash_password(seed_password_for_emp(emp_id)),
                role=role,
                is_active=True,
                must_change_password=False,
                department=department,
                reports_to=reports_to,
                approval_status="approved",
            )
            created += 1
            return u
        # Refresh org fields on existing seed users
        if (u.sbu or "").strip() != (sbu.name or "").strip():
            u.sbu = sbu.name
        if department is not None and u.department != department:
            u.department = department
        elif department is None and role == "sbu_head" and u.department is not None:
            u.department = None
        if u.role != role and role in ("sbu_head", "dept_head", "engineer"):
            # Do not demote admin
            if (u.role or "").strip().lower() != "admin":
                u.role = role
        if reports_to is not None and u.reports_to != reports_to:
            u.reports_to = reports_to
            linked += 1
        elif reports_to is None and role == "sbu_head" and u.reports_to is not None:
            u.reports_to = None
        return u

    for sbu in select(d for d in RcSbu if d.is_active and d.code.upper() in keep).order_by(
        RcSbu.sort_order, RcSbu.code
    )[:]:
        ensure_default_departments(sbu)
        slug = _dept_name_slug(sbu.code)

        existing_head = select(
            u
            for u in RcUser
            if u.role == "sbu_head"
            and u.is_active
            and (u.sbu == sbu.name or u.sbu == sbu.code)
        ).order_by(RcUser.id)[:1]
        sbu_head = _ensure_user(
            name=f"sbu-head-{slug}",
            role="sbu_head",
            sbu=sbu,
            department=None,
            reports_to=None,
            match_existing=existing_head[0] if existing_head else None,
        )

        for dept_code in DEMO_ORG_DEPT_CODES:
            depts = select(
                d for d in RcDepartment if d.sbu == sbu and d.code == dept_code and d.is_active
            )[:1]
            if not depts:
                continue
            dept = depts[0]
            dslug = dept_code.lower()

            existing_dh = select(
                u
                for u in RcUser
                if u.role == "dept_head" and u.is_active and u.department == dept
            ).order_by(RcUser.id)[:1]
            dept_head = _ensure_user(
                name=f"{dslug}-head-{slug}",
                role="dept_head",
                sbu=sbu,
                department=dept,
                reports_to=sbu_head,
                match_existing=existing_dh[0] if existing_dh else None,
            )

            existing_eng = select(
                u
                for u in RcUser
                if u.role == "engineer" and u.is_active and u.department == dept
            ).order_by(RcUser.id)[:1]
            _ensure_user(
                name=f"eng-{dslug}-{slug}",
                role="engineer",
                sbu=sbu,
                department=dept,
                reports_to=dept_head,
                match_existing=existing_eng[0] if existing_eng else None,
            )

    for u in select(
        u
        for u in RcUser
        if u.role in ("ied", "sbu_head", "dept_head", "engineer") and u.is_active
    )[:]:
        if not u.password_hash:
            continue
        if not verify_password(LEGACY_SEED_PASSWORD, u.password_hash):
            continue
        emp = (u.emp_id or "").strip()
        if not emp:
            continue
        u.password_hash = hash_password(seed_password_for_emp(emp))
        reset += 1

    commit()
    return {
        "created": created,
        "skipped": skipped,
        "linked": linked,
        "reset": reset,
    }


@db_session
def migrate_legacy_machines() -> dict:
    """Link orphan RcMachine rows (string work_centre) to RcWorkCenter."""
    linked = 0
    created_wc = 0
    for m in select(x for x in RcMachine if x.work_center is None)[:]:
        label = (m.work_centre or "").strip()
        if not label:
            continue
        dept = (m.sbu or "").strip()
        wc = None
        if dept:
            found = select(
                w
                for w in RcWorkCenter
                if (not w.is_shared)
                and w.sbu == dept
                and (_norm(w.name) == _norm(label) or _norm(w.code) == _norm(label))
            )[:1]
            wc = found[0] if found else None
        if not wc:
            found = select(
                w
                for w in RcWorkCenter
                if w.is_shared
                and (_norm(w.name) == _norm(label) or _norm(w.code) == _norm(label))
            )[:1]
            wc = found[0] if found else None
        if not wc:
            code = _norm(label).upper()[:16] or f"WC{m.id}"
            wc = RcWorkCenter(
                sbu=dept,
                code=code,
                name=label,
                mode="hybrid",
                is_shared=not bool(dept),
                plant=m.plant or "",
                capability_tags=[],
                match_keywords=[],
                is_active=True,
            )
            created_wc += 1
        m.work_center = wc
        m.sbu = wc.sbu or dept
        if not m.work_centre:
            m.work_centre = wc.name
        linked += 1
    commit()
    return {"linked": linked, "createdWorkCenters": created_wc}


def _sap_code_to_wc_code(sap_code: str) -> str:
    raw = (sap_code or "").strip().upper()
    cleaned = re.sub(r"[^A-Z0-9_-]+", "", raw)
    return (cleaned or "SAPWC")[:64]


@db_session
def ensure_sap_work_center(
    user: dict,
    *,
    sap_code: str,
    name: str = "",
    plant: str = "",
    is_shared: bool = False,
    dept: str = "",
) -> tuple[dict, bool]:
    """Find or create a plant-scoped work centre from a SAP Arbpl code.

    Uses the SAP description when supplied. Returns (wc_dict, created).
    """
    sap = (sap_code or "").strip()
    if not sap:
        raise HTTPException(400, "sap_code required")

    plant = (plant or "").strip()
    if not plant:
        raise HTTPException(400, "plant is required for SAP work centre upsert")

    # Plant-scoped master — ignore shared/dept copies
    code = _sap_code_to_wc_code(sap)
    rows = select(w for w in RcWorkCenter if w.plant == plant)[:]
    hit: RcWorkCenter | None = None
    for w in rows:
        if _norm(w.sap_code or "") == _norm(sap) or _norm(w.code) == _norm(code):
            hit = w
            break

    if hit:
        changed = False
        if not hit.is_active:
            hit.is_active = True
            changed = True
        if not (hit.sap_code or "").strip():
            hit.sap_code = sap
            changed = True
        if name.strip() and hit.name != name.strip():
            hit.name = name.strip()
            changed = True
        elif not (hit.name or "").strip():
            hit.name = sap
            changed = True
        if hit.is_shared:
            hit.is_shared = False
            changed = True
        if changed:
            hit.updated_at = datetime.utcnow()
            commit()
        return wc_dict(hit, include_machines=False), False

    wc = RcWorkCenter(
        sbu=(dept or "").strip(),
        code=code,
        name=name.strip() or sap,
        mode="manual",
        is_shared=False,
        plant=plant,
        sap_code=sap,
        capability_tags=[],
        match_keywords=[sap.upper()],
        default_tool="",
        sort_order=500,
        is_active=True,
    )
    wc.updated_at = datetime.utcnow()
    commit()
    return wc_dict(wc, include_machines=False), True


def sync_work_centers_from_sap(
    user: dict,
    *,
    plant_code: str,
    dept: str = "",
) -> dict[str, Any]:
    """Fetch organization mapping and work centres without scanning orders."""
    from app.route_card import plants as plants_mod
    from app.route_card import sap_org_client as sap

    plant = (plant_code or "").strip()
    if not plant:
        raise HTTPException(400, "Plant code is required")
    mapping = sap.fetch_plant_sbu_mapping(plant)
    data = sap.fetch_sap_data(plant, "WORKCENTER")
    seen: set[str] = set()
    created_count = 0
    existing_count = 0
    failures: list[dict[str, str]] = []

    for row in sap.extract_items(data.get("ItCrhd")):
        center = str(row.get("Arbpl") or "").strip()
        row_plant = str(row.get("Werks") or "").strip() or plant
        if not center or row_plant != plant or center.upper() in seen:
            continue
        seen.add(center.upper())
        try:
            _item, created = ensure_sap_work_center(
                user,
                sap_code=center,
                name=str(row.get("Ktext") or "").strip(),
                plant=plant,
                sbu=dept,
            )
        except HTTPException as exc:
            failures.append({"work_center": center, "message": str(exc.detail)})
            continue
        if created:
            created_count += 1
        else:
            existing_count += 1

    synced_at = None
    if seen and not failures:
        plants_mod.mark_work_center_synced(plant)
        synced_at = plants_mod.get_work_center_synced_at(plant)

    return {
        "message": (
            f"Fetched {mapping['count']} Plant/SBU mapping(s). "
            f"Synced {created_count + existing_count} work centre(s); {created_count} newly added."
        ),
        "status": "S" if not failures else "P",
        "criteria": {"plant_code": plant, "sbu": (dept or "").strip()},
        "plant_sbu": mapping["items"],
        "plant_sbu_count": mapping["count"],
        "failed_work_centers": failures,
        "failed_work_centers_count": len(failures),
        "count": len(seen),
        "work_centers": sorted(seen),
        "created_count": created_count,
        "existing_count": existing_count,
        "workCenterSyncedAt": (
            synced_at.isoformat() + "Z" if synced_at else None
        ),
    }
