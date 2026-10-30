"""Dept-scoped WorkCenter + Machine master and extraction resolver."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from fastapi import HTTPException
from pony.orm import commit, db_session, desc, select

from app.config.settings import settings
from app.route_card.models import RcMachine, RcWorkCenter
from app.route_card.op_templates import (
    _can_write_dept,
    _dept,
    _is_admin,
    _is_dept_head,
    _validate_dept_name,
)

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
        "dept": wc.dept or "",
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
        "dept": m.dept or (wc.dept if wc else "") or "",
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
    # engineers/dept_heads can read own dept (+ shared handled separately)
    if dept and dept != d and not _is_admin(user):
        # allow empty dept filter meaning "my dept"
        pass


def _can_edit_wc(user: dict, wc: RcWorkCenter) -> bool:
    if _is_admin(user):
        return True
    if wc.is_shared:
        return False
    return _can_write_dept(user, wc.dept or "")


@db_session
def list_work_centers(
    user: dict,
    dept: str | None = None,
    include_shared: bool = True,
    active_only: bool = True,
) -> list[dict]:
    role = (user or {}).get("role") or ""
    user_dept = _dept(user)
    want = (dept or "").strip()
    if role == "dept_head":
        want = user_dept
    elif role == "engineer" and not want:
        want = user_dept
    elif role != "admin" and want and want != user_dept:
        raise HTTPException(403, "Not allowed to list another department")

    rows = select(w for w in RcWorkCenter)[:]
    out: list[RcWorkCenter] = []
    for w in rows:
        if active_only and not w.is_active:
            continue
        if w.is_shared:
            if include_shared:
                out.append(w)
            continue
        if want:
            if (w.dept or "") == want:
                out.append(w)
        elif _is_admin(user):
            out.append(w)
        elif (w.dept or "") == user_dept:
            out.append(w)
    out.sort(key=lambda w: (0 if w.is_shared else 1, w.sort_order, w.name.lower()))
    return [wc_dict(w, include_machines=True) for w in out]


@db_session
def catalog_for_dropdowns(user: dict, dept: str | None = None) -> dict:
    """Slim catalog for route editor / templates."""
    items = list_work_centers(user, dept=dept, include_shared=True, active_only=True)
    return {"items": items, "dept": (dept or _dept(user) or "").strip()}


@db_session
def get_work_center(wc_id: int, user: dict) -> dict:
    wc = RcWorkCenter.get(id=wc_id)
    if not wc or not wc.is_active:
        raise HTTPException(404, "Work centre not found")
    if not wc.is_shared:
        role = (user or {}).get("role") or ""
        if role != "admin" and (wc.dept or "") != _dept(user):
            raise HTTPException(403, "Not allowed")
    return wc_dict(wc, include_machines=True)


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

    if is_shared:
        dept = ""
    else:
        dept = (body.get("dept") or _dept(user) or "").strip()
        if _is_dept_head(user):
            dept = _dept(user)
        if not _can_write_dept(user, dept):
            raise HTTPException(403, "Not allowed to edit this department")
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
        # uniqueness
        if is_shared:
            hit = select(
                w for w in RcWorkCenter if w.is_shared and w.code == code and w.is_active
            )[:1]
        else:
            hit = select(
                w
                for w in RcWorkCenter
                if (not w.is_shared) and w.dept == dept and w.code == code and w.is_active
            )[:1]
        if hit:
            raise HTTPException(400, f"Work centre code '{code}' already exists")
        wc = RcWorkCenter(
            dept=dept,
            code=code,
            name=name,
            mode=_parse_mode(body.get("mode")),
            is_shared=is_shared,
            plant=body.get("plant") or "",
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
            new_dept = (body.get("dept") or "").strip()
            if new_dept:
                _validate_dept_name(new_dept)
                wc.dept = new_dept
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
    return wc_dict(wc, include_machines=True)


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
        dept = (body.get("dept") or "").strip()
        found = select(
            w
            for w in RcWorkCenter
            if w.is_active and ((w.dept == dept and not w.is_shared) or w.name == label)
        )[:1]
        wc = found[0] if found else None
        if not wc:
            code = _norm(label).upper()[:16] or "WC"
            wc = RcWorkCenter(
                dept=dept,
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
            dept=(wc.dept if wc else body.get("dept") or ""),
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
            m.dept = wc.dept or ""
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
            if (m.work_center and (m.work_center.is_shared or (m.dept or "") == d))
            or ((m.dept or "") == d)
            or (not m.work_center and _is_admin(user))
        ]
        # engineers/dept_head: also include unscoped legacy if no dept on machine and shared wc
        if d:
            rows = [
                m
                for m in rows
                if (m.dept or "") in ("", d)
                or (m.work_center and m.work_center.is_shared)
            ]
    return [machine_dict(m) for m in rows]


# ---------------------------------------------------------------------------
# Resolver
# ---------------------------------------------------------------------------


def _load_catalog(dept: str) -> list[RcWorkCenter]:
    d = (dept or "").strip()
    rows = select(w for w in RcWorkCenter if w.is_active)[:]
    dept_rows = [w for w in rows if (not w.is_shared) and (w.dept or "") == d]
    shared = [w for w in rows if w.is_shared]
    return dept_rows + shared


def _hint_tags(heuristic_wc: str, instruction: str) -> set[str]:
    tags: set[str] = set()
    hw = (heuristic_wc or "").strip()
    if hw in HEURISTIC_TAG_MAP:
        tags.add(HEURISTIC_TAG_MAP[hw])
    t = (instruction or "").upper()
    if "TORQUE" in t:
        tags.add("torque")
    if any(k in t for k in ("SOLDER", "PCB", "DRILL", "ROHS")):
        tags.add("pcb")
        tags.add("solder")
    if any(k in t for k in ("BOND", "GLUE", "PASTE", "PEEL", "MASK", "CLEAN")):
        tags.add("bonding")
    if any(k in t for k in ("INSPECT", "VERIFY", "WARPAGE", "WEIGHT")):
        tags.add("inspect")
    if any(k in t for k in ("CABLE", "CRIMP", "WIRE", "HARNESS")):
        tags.add("cable")
    if any(k in t for k in ("HEAT SINK", "SFPDP", "OPTICAL")):
        tags.add("special")
    if not tags:
        tags.add("assembly")
    return tags


def _score_wc(wc: RcWorkCenter, heuristic: str, instruction: str, aliases: dict) -> float:
    score = 0.0
    # 1) alias exact → code
    alias_target = aliases.get(heuristic or "")
    if alias_target and _norm(alias_target) in (_norm(wc.code), _norm(wc.name), _norm(wc.sap_code or "")):
        score += 100.0
    # 2) keywords
    text_u = (instruction or "").upper()
    kws = [str(k).upper() for k in (wc.match_keywords or []) if k]
    hits = sum(1 for k in kws if k and k in text_u)
    if hits:
        score += 40.0 + min(hits, 5) * 5.0
    # 3) capability tags
    want = _hint_tags(heuristic, instruction)
    have = {str(t).lower() for t in (wc.capability_tags or [])}
    overlap = want & have
    if overlap:
        score += 25.0 + 5.0 * len(overlap)
    # 4) fuzzy name/code vs heuristic
    hn = _norm(heuristic)
    if hn and hn in (_norm(wc.name), _norm(wc.code), _norm(wc.sap_code or "")):
        score += 50.0
    elif hn and (hn in _norm(wc.name) or _norm(wc.name) in hn):
        score += 20.0
    # prefer dept over shared slightly via sort_order tie-break outside
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


@db_session
def resolve_operations(
    operations: list[dict],
    *,
    dept: str,
    aliases: dict | None = None,
    notes: list | None = None,
) -> list[dict]:
    """Link free-text WC/machine on ops to dept catalog. Mutates copies."""
    if not getattr(settings, "WC_RESOLVER_ENABLED", True):
        return operations

    d = (dept or "").strip()
    catalog = _load_catalog(d)
    aliases = aliases or {}
    note_by_op: dict[int, str] = {}
    for n in notes or []:
        if isinstance(n, dict):
            note_by_op[int(n.get("stepNo") or 0)] = (
                (n.get("elaboratedText") or "") + " " + (n.get("text") or "")
            )

    has_dept_catalog = any(not w.is_shared for w in catalog)
    out: list[dict] = []
    for op in operations or []:
        row = dict(op)
        if (row.get("linkStatus") or row.get("link_status")) == LINK_OVERRIDE:
            out.append(row)
            continue

        heuristic = (row.get("workCentre") or row.get("workCenter") or "").strip()
        instruction = (
            (row.get("instructionText") or "")
            + " "
            + (row.get("operation") or "")
            + " "
            + note_by_op.get(int(row.get("opNo") or 0) // 10, "")
        )

        if not catalog:
            row["linkStatus"] = ""
            row["linkConfidence"] = None
            row["linkReason"] = "No WC master configured"
            out.append(row)
            continue

        # alias remap first (string)
        if heuristic in aliases:
            heuristic = aliases[heuristic]
            row["workCentre"] = heuristic

        scored = [( _score_wc(w, heuristic, instruction, aliases), w) for w in catalog]
        scored.sort(key=lambda x: (-x[0], 0 if not x[1].is_shared else 1, x[1].sort_order))
        best_score, best = scored[0]
        second = scored[1][0] if len(scored) > 1 else 0.0

        if best_score < 20.0:
            if has_dept_catalog:
                # stop inventing — keep heuristic label, mark unresolved
                row["linkStatus"] = LINK_UNRESOLVED
                row["linkConfidence"] = 0.0
                row["workCentreId"] = None
                row["machineId"] = None
                row["linkReason"] = "No matching work centre in department catalog"
            else:
                row["linkStatus"] = ""
                row["linkReason"] = "Using heuristic (shared catalog only / weak match)"
            out.append(row)
            continue

        if second > 0 and abs(best_score - second) < 5.0 and best_score < 80.0:
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
                # leave prior machine text if partial
                if mstatus == LINK_PARTIAL:
                    row["machineId"] = None
        row["linkStatus"] = mstatus
        row["linkConfidence"] = round(min(best_score / 100.0, 0.99), 3)
        row["linkReason"] = f"Matched {best.code} ({best.name})"
        out.append(row)
    return out


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
            dept=wc.dept or "",
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
            dept=wc.dept or "",
            code=code,
            sap_code=f"{(plant or 'P')}{wc.code}{i}",
            name=f"{wc.name} {suffix}",
            description=f"Sample machine {suffix} for {wc.dept or 'shared'}",
            capability_tags=list(wc.capability_tags or []),
            is_manual_placeholder=False,
            is_active=True,
            sort_order=10 * i,
        )
        created += 1
    return created


@db_session
def seed_default_catalog(dept: str | None = None, plant: str | None = None) -> dict:
    """Idempotent seed of shared + dept WCs/machines.

    If ``dept`` is omitted, seeds shared catalog plus every active RcDepartment
    using each department's ``plant_id``.
    """
    from app.route_card.models import RcDepartment

    created = 0
    machines = 0
    # shared
    for spec in DEFAULT_SHARED_SEED:
        hit = select(
            w
            for w in RcWorkCenter
            if w.is_shared and w.code == spec["code"]
        )[:1]
        if hit:
            wc = hit[0]
        else:
            wc = RcWorkCenter(
                dept="",
                code=spec["code"],
                name=spec["name"],
                mode=spec["mode"],
                is_shared=True,
                plant="",
                capability_tags=spec["capability_tags"],
                match_keywords=spec["match_keywords"],
                sort_order=spec["sort_order"],
                is_active=True,
            )
            created += 1
        machines += _seed_machines_for_wc(wc, "")

    targets: list[tuple[str, str]] = []
    d = (dept or "").strip()
    if d:
        plant_s = (plant or "").strip()
        if not plant_s:
            row = select(x for x in RcDepartment if x.is_active and x.name == d)[:1]
            plant_s = (row[0].plant_id or "").strip() if row else ""
        targets.append((d, plant_s))
    else:
        for row in select(x for x in RcDepartment if x.is_active).order_by(
            RcDepartment.sort_order
        )[:]:
            targets.append((row.name, (row.plant_id or "").strip()))

    for dept_name, plant_s in targets:
        for spec in DEFAULT_DEPT_SEED:
            hit = select(
                w
                for w in RcWorkCenter
                if (not w.is_shared) and w.dept == dept_name and w.code == spec["code"]
            )[:1]
            if hit:
                wc = hit[0]
                if plant_s and not (wc.plant or "").strip():
                    wc.plant = plant_s
            else:
                wc = RcWorkCenter(
                    dept=dept_name,
                    code=spec["code"],
                    name=spec["name"],
                    mode=spec["mode"],
                    is_shared=False,
                    plant=plant_s,
                    capability_tags=spec["capability_tags"],
                    match_keywords=spec["match_keywords"],
                    sort_order=spec["sort_order"],
                    is_active=True,
                )
                created += 1
            machines += _seed_machines_for_wc(wc, plant_s)

    commit()
    return {
        "created": created,
        "machinesCreated": machines,
        "dept": d or "*",
        "deptCount": len(targets),
    }


DEFAULT_SEED_PASSWORD = "Adm!n@123bel"


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


@db_session
def seed_dept_head_and_ied_users() -> dict:
    """Idempotent demo users: dept-head-{slug} + IED-{slug} per active department.

    empIds are random-looking stable 6-digit numbers (edit later in Users UI).
    Password for all: Adm!n@123bel
    """
    from app.route_card.models import RcDepartment, RcUser
    from app.security import hash_password

    pw_hash = hash_password(DEFAULT_SEED_PASSWORD)
    used = {u.emp_id for u in select(u for u in RcUser)[:]}
    created = 0
    skipped = 0

    for dept in select(d for d in RcDepartment if d.is_active).order_by(
        RcDepartment.sort_order
    )[:]:
        slug = _dept_name_slug(dept.code)
        specs = [
            (f"dept-head-{slug}", "dept_head"),
            (f"IED-{slug}", "ied"),
        ]
        for name, role in specs:
            existing = select(u for u in RcUser if u.name == name)[:1]
            if existing:
                skipped += 1
                continue
            emp_id = _stable_emp_id(f"{role}:{dept.code}", used)
            used.add(emp_id)
            RcUser(
                emp_id=emp_id,
                name=name,
                dept=dept.name,
                password_hash=pw_hash,
                role=role,
                is_active=True,
                must_change_password=False,
            )
            created += 1

    commit()
    return {"created": created, "skipped": skipped}


@db_session
def migrate_legacy_machines() -> dict:
    """Link orphan RcMachine rows (string work_centre) to RcWorkCenter."""
    linked = 0
    created_wc = 0
    for m in select(x for x in RcMachine if x.work_center is None)[:]:
        label = (m.work_centre or "").strip()
        if not label:
            continue
        dept = (m.dept or "").strip()
        wc = None
        if dept:
            found = select(
                w
                for w in RcWorkCenter
                if (not w.is_shared)
                and w.dept == dept
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
                dept=dept,
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
        m.dept = wc.dept or dept
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
    plant: str = "",
    is_shared: bool = True,
    dept: str = "",
) -> tuple[dict, bool]:
    """Find or create a work centre from a SAP Arbpl code. Returns (wc_dict, created)."""
    sap = (sap_code or "").strip()
    if not sap:
        raise HTTPException(400, "sap_code required")

    plant = (plant or "").strip()
    want_shared = bool(is_shared)
    if want_shared and not _is_admin(user):
        # Dept heads sync into their department instead of shared
        want_shared = False
    if want_shared:
        dept = ""
    else:
        dept = (dept or _dept(user) or "").strip()
        if _is_dept_head(user):
            dept = _dept(user)
        if not _can_write_dept(user, dept):
            raise HTTPException(403, "Not allowed to sync into this department")
        if dept:
            _validate_dept_name(dept)

    # Match existing by sap_code or code within the same shared/dept scope
    rows = select(w for w in RcWorkCenter if w.is_active)[:]
    hit: RcWorkCenter | None = None
    for w in rows:
        if not (_norm(w.sap_code or "") == _norm(sap) or _norm(w.code) == _norm(sap)):
            continue
        if want_shared and w.is_shared:
            hit = w
            break
        if (not want_shared) and (not w.is_shared) and (w.dept or "") == dept:
            hit = w
            break

    if hit:
        changed = False
        if plant and not (hit.plant or "").strip():
            hit.plant = plant
            changed = True
        if not (hit.sap_code or "").strip():
            hit.sap_code = sap
            changed = True
        if changed:
            hit.updated_at = datetime.utcnow()
            commit()
        return wc_dict(hit, include_machines=True), False

    code = _sap_code_to_wc_code(sap)
    # Avoid code collision within scope
    if want_shared:
        collision = select(
            w for w in RcWorkCenter if w.is_shared and w.code == code and w.is_active
        )[:1]
    else:
        collision = select(
            w
            for w in RcWorkCenter
            if (not w.is_shared) and w.dept == dept and w.code == code and w.is_active
        )[:1]
    if collision:
        code = f"{code[:56]}-{_norm(plant or 'P')[:6]}"[:64]

    wc = RcWorkCenter(
        dept=dept,
        code=code,
        name=sap,
        mode="hybrid",
        is_shared=want_shared,
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
    return wc_dict(wc, include_machines=True), True


def sync_work_centers_from_sap_events(
    user: dict,
    *,
    plant_code: str,
    from_date: str,
    to_date: str,
    part_number: str | None = None,
    is_shared: bool = True,
    dept: str = "",
):
    """Yield NDJSON-ready dict events while discovering unique SAP work centres."""
    import json

    from app.config.settings import settings
    from app.route_card import sap_oarc_client as sap

    def _line(obj: dict) -> str:
        return json.dumps(obj, default=str) + "\n"

    plant = (plant_code or "").strip()
    if not plant:
        yield _line({"type": "error", "message": "Plant code is required"})
        return
    if from_date > to_date:
        yield _line({"type": "error", "message": "From date cannot be after to date"})
        return

    part = (part_number or "").strip() or None
    yield _line(
        {
            "type": "status",
            "message": "Fetching production orders from SAP… This may take a while.",
            "phase": "list",
        }
    )

    try:
        list_result = sap.list_production_orders(plant, from_date, to_date, part)
    except Exception as exc:
        logger = __import__("logging").getLogger("route_card.work_centers")
        logger.exception("SAP order list failed")
        yield _line(
            {
                "type": "error",
                "message": f"SAP order list failed ({type(exc).__name__}). Check SAP credentials / gateway.",
            }
        )
        return

    status = str(list_result.get("status") or "S").upper()
    if status in ("E", "A", "X"):
        yield _line(
            {
                "type": "error",
                "message": f"SAP list rejected search: {list_result.get('message') or status}",
            }
        )
        return

    orders = list(
        dict.fromkeys(
            str(row.get("production_order") or "").strip()
            for row in (list_result.get("orders") or [])
            if str(row.get("production_order") or "").strip()
        )
    )
    max_orders = int(settings.SAP_MAX_ORDERS or 500)
    if len(orders) > max_orders:
        yield _line(
            {
                "type": "error",
                "message": f"Search returned {len(orders)} orders; narrow date range (limit {max_orders}).",
            }
        )
        return

    yield _line(
        {
            "type": "status",
            "message": f"Found {len(orders)} orders. Scanning operations for unique work centres…",
            "phase": "scan",
            "totalOrders": len(orders),
        }
    )

    seen: set[str] = set()
    created_count = 0
    existing_count = 0
    success_orders = 0
    failed_orders = 0

    for idx, order in enumerate(orders, start=1):
        yield _line(
            {
                "type": "progress",
                "orderIndex": idx,
                "totalOrders": len(orders),
                "productionOrder": order,
                "uniqueCount": len(seen),
                "message": f"Scanning order {idx} of {len(orders)}…",
            }
        )
        try:
            detail = sap.detail_production_order(order)
            dstatus = str(detail.get("status") or "S").upper()
            if dstatus in ("E", "A", "X"):
                failed_orders += 1
                continue
            success_orders += 1
            for op in detail.get("operations") or []:
                center = str(op.get("work_center") or "").strip()
                if not center:
                    continue
                key = center.upper()
                if key in seen:
                    continue
                seen.add(key)
                op_plant = str(op.get("work_center_plant") or plant or "").strip()
                try:
                    item, created = ensure_sap_work_center(
                        user,
                        sap_code=center,
                        plant=op_plant,
                        is_shared=is_shared,
                        dept=dept,
                    )
                except HTTPException as he:
                    yield _line(
                        {
                            "type": "warning",
                            "message": he.detail if isinstance(he.detail, str) else str(he.detail),
                            "sapCode": center,
                        }
                    )
                    continue
                if created:
                    created_count += 1
                else:
                    existing_count += 1
                yield _line(
                    {
                        "type": "work_center",
                        "created": created,
                        "item": item,
                        "uniqueCount": len(seen),
                        "message": (
                            f"Added {center}" if created else f"Already present: {center}"
                        ),
                    }
                )
        except Exception:
            failed_orders += 1
            logger = __import__("logging").getLogger("route_card.work_centers")
            logger.exception("Failed to fetch production order %r", order)

    yield _line(
        {
            "type": "done",
            "message": "Work-centre sync completed",
            "totalOrders": len(orders),
            "successfulOrders": success_orders,
            "failedOrders": failed_orders,
            "uniqueCount": len(seen),
            "createdCount": created_count,
            "existingCount": existing_count,
            "workCenters": sorted(seen),
        }
    )
