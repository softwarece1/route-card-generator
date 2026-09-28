"""Department-owned operation template packs (CRUD + duplicate)."""

from __future__ import annotations

from datetime import datetime

from fastapi import HTTPException
from pony.orm import db_session, flush, select

from app.route_card.models import RcDepartment, RcOperationTemplate, RcOperationTemplateStep, RcUser

VALID_PLACEMENTS = {"pre", "post", "any"}
VALID_ROLES = {"admin", "dept_head", "engineer"}


def _role(user: dict | None) -> str:
    return (user or {}).get("role") or ""


def _dept(user: dict | None) -> str:
    return ((user or {}).get("dept") or "").strip()


def _is_admin(user: dict | None) -> bool:
    return _role(user) == "admin"


def _is_dept_head(user: dict | None) -> bool:
    return _role(user) == "dept_head"


def _can_write_dept(user: dict | None, dept: str) -> bool:
    if _is_admin(user):
        return True
    if _is_dept_head(user) and _dept(user) and _dept(user) == (dept or "").strip():
        return True
    return False


def _can_read_template(user: dict | None, tpl: RcOperationTemplate) -> bool:
    if _is_admin(user) or _is_dept_head(user):
        return True
    return _dept(user) == (tpl.dept or "").strip()


def _validate_placement(placement: str) -> str:
    p = (placement or "any").strip().lower()
    if p not in VALID_PLACEMENTS:
        raise HTTPException(400, "placement must be pre, post, or any")
    return p


def _validate_dept_name(dept: str) -> str:
    d = (dept or "").strip()
    if not d:
        raise HTTPException(400, "dept is required")
    master = select(x for x in RcDepartment if x.is_active and x.name == d)[:1]
    if not master:
        raise HTTPException(400, "Select a valid department")
    return d


def _step_out(s: RcOperationTemplateStep) -> dict:
    return {
        "id": s.id,
        "sortOrder": s.sort_order,
        "operation": s.operation or "",
        "workCentre": s.work_centre or "",
        "setup": s.setup or "",
        "time": s.time or "",
        "instructionText": s.instruction_text or "",
        "inspection": s.inspection or "",
        "machine": s.machine or "",
        "tool": s.tool or "",
        "generates_output_serial": bool(s.generates_output_serial),
        "requires_input_material": bool(s.requires_input_material),
        "manual_operation": s.manual_operation is not False,
    }


def _template_root_id(tpl: RcOperationTemplate) -> int:
    """Original pack id for duplicate tracking (follow one hop)."""
    return int(tpl.copied_from_id) if tpl.copied_from_id else int(tpl.id)


def _dept_has_copy(dept: str, root_id: int) -> bool:
    """True if dept already has an active pack copied from this root (or is the root)."""
    if not dept or not root_id:
        return False
    hit = select(
        t
        for t in RcOperationTemplate
        if t.is_active
        and t.dept == dept
        and (t.id == root_id or t.copied_from_id == root_id)
    )[:1]
    return bool(hit)


def _template_out(
    tpl: RcOperationTemplate,
    *,
    include_steps: bool = True,
    viewer_dept: str | None = None,
) -> dict:
    steps = sorted(tpl.steps, key=lambda x: (x.sort_order, x.id))
    root_id = _template_root_id(tpl)
    out = {
        "id": tpl.id,
        "dept": tpl.dept or "",
        "name": tpl.name or "",
        "description": tpl.description or "",
        "placement": tpl.placement or "any",
        "isActive": bool(tpl.is_active),
        "stepCount": len(steps),
        "copiedFromId": tpl.copied_from_id,
        "rootTemplateId": root_id,
        "createdByUserId": tpl.created_by.id if tpl.created_by else None,
        "createdAt": tpl.created_at.isoformat() if tpl.created_at else None,
        "updatedAt": tpl.updated_at.isoformat() if tpl.updated_at else None,
    }
    if viewer_dept is not None:
        # Already present in viewer's dept (as original or as a prior copy)
        out["alreadyCopied"] = _dept_has_copy(viewer_dept, root_id)
    if include_steps:
        out["steps"] = [_step_out(s) for s in steps]
    return out


def _normalize_steps(raw_steps: list | None) -> list[dict]:
    steps = raw_steps or []
    if not steps:
        raise HTTPException(400, "At least one operation step is required")
    normalized = []
    for i, raw in enumerate(steps):
        if isinstance(raw, dict):
            op = (raw.get("operation") or "").strip()
            work = raw.get("workCentre") if "workCentre" in raw else raw.get("work_centre")
            setup = raw.get("setup")
            time_v = raw.get("time")
            instr = raw.get("instructionText") if "instructionText" in raw else raw.get("instruction_text")
            insp = raw.get("inspection")
            machine = raw.get("machine")
            tool = raw.get("tool")
            gen = raw.get("generates_output_serial", False)
            req = raw.get("requires_input_material", False)
            manual = raw.get("manual_operation", True)
        else:
            op = (getattr(raw, "operation", None) or "").strip()
            work = getattr(raw, "workCentre", "")
            setup = getattr(raw, "setup", "")
            time_v = getattr(raw, "time", "")
            instr = getattr(raw, "instructionText", "")
            insp = getattr(raw, "inspection", "")
            machine = getattr(raw, "machine", "")
            tool = getattr(raw, "tool", "")
            gen = getattr(raw, "generates_output_serial", False)
            req = getattr(raw, "requires_input_material", False)
            manual = getattr(raw, "manual_operation", True)
        if not op:
            raise HTTPException(400, f"Step {i + 1}: operation name is required")
        normalized.append(
            {
                "sort_order": (i + 1) * 10,
                "operation": op[:512],
                "work_centre": (work or "")[:128],
                "setup": str(setup or "")[:32],
                "time": str(time_v or "")[:64],
                "instruction_text": instr or "",
                "inspection": (insp or "")[:256],
                "machine": (machine or "")[:128],
                "tool": (tool or "")[:256],
                "generates_output_serial": bool(gen),
                "requires_input_material": bool(req),
                "manual_operation": manual is not False,
            }
        )
    return normalized


def _replace_steps(tpl: RcOperationTemplate, steps: list[dict]) -> None:
    for old in list(tpl.steps):
        old.delete()
    for s in steps:
        RcOperationTemplateStep(
            template=tpl,
            sort_order=s["sort_order"],
            operation=s["operation"],
            work_centre=s["work_centre"],
            setup=s["setup"],
            time=s["time"],
            instruction_text=s["instruction_text"],
            inspection=s["inspection"],
            machine=s["machine"],
            tool=s["tool"],
            generates_output_serial=s["generates_output_serial"],
            requires_input_material=s["requires_input_material"],
            manual_operation=s["manual_operation"],
        )


def _assert_unique_name(dept: str, name: str, *, exclude_id: int | None = None) -> None:
    q = select(
        t
        for t in RcOperationTemplate
        if t.is_active and t.dept == dept and t.name == name
    )
    for t in q[:]:
        if exclude_id is not None and t.id == exclude_id:
            continue
        raise HTTPException(400, f"Template '{name}' already exists in {dept}")


@db_session
def list_templates(
    user: dict | None,
    *,
    scope: str | None = None,
    dept: str | None = None,
) -> dict:
    if not user:
        raise HTTPException(401, "Not authenticated")

    scope_n = (scope or "own").strip().lower()
    dept_filter = (dept or "").strip()

    if scope_n == "other":
        if not (_is_admin(user) or _is_dept_head(user)):
            raise HTTPException(403, "Only department heads and admins can browse other departments")
        own = _dept(user)
        rows = [
            t
            for t in RcOperationTemplate.select(lambda t: t.is_active).order_by(
                RcOperationTemplate.dept, RcOperationTemplate.name
            )[:]
            if (not own or t.dept != own) and (not dept_filter or t.dept == dept_filter)
        ]
    elif scope_n == "all" and _is_admin(user):
        rows = [
            t
            for t in RcOperationTemplate.select(lambda t: t.is_active).order_by(
                RcOperationTemplate.dept, RcOperationTemplate.name
            )[:]
            if not dept_filter or t.dept == dept_filter
        ]
    else:
        # own dept (engineers + dept_head + admin with optional dept filter)
        target = dept_filter if (_is_admin(user) and dept_filter) else _dept(user)
        if not target:
            return {"items": [], "total": 0}
        rows = list(
            RcOperationTemplate.select(
                lambda t: t.is_active and t.dept == target
            ).order_by(RcOperationTemplate.name)[:]
        )

    viewer_dept = _dept(user)
    annotate = scope_n == "other" and bool(viewer_dept)

    own_root_ids: set[int] = set()
    own_names: set[str] = set()
    if annotate:
        for ot in RcOperationTemplate.select(
            lambda t: t.is_active and t.dept == viewer_dept
        )[:]:
            own_root_ids.add(_template_root_id(ot))
            own_root_ids.add(int(ot.id))
            if ot.copied_from_id:
                own_root_ids.add(int(ot.copied_from_id))
            if ot.name:
                own_names.add(ot.name.strip().lower())

    items = []
    for t in rows:
        out = _template_out(t, include_steps=False)
        if annotate:
            root = _template_root_id(t)
            legacy_name = (t.name or "").strip().lower()
            legacy_copy = f"{legacy_name} (copy)"
            out["alreadyCopied"] = (
                root in own_root_ids
                or legacy_name in own_names
                or legacy_copy in own_names
            )
        items.append(out)

    return {
        "items": items,
        "total": len(items),
    }


@db_session
def get_template(template_id: int, user: dict | None) -> dict:
    tpl = RcOperationTemplate.get(id=template_id)
    if not tpl or not tpl.is_active:
        raise HTTPException(404, "Template not found")
    if not _can_read_template(user, tpl):
        raise HTTPException(403, "Not allowed to view this template")
    return _template_out(tpl, include_steps=True)


@db_session
def create_template(body: dict, user: dict | None) -> dict:
    if not (_is_admin(user) or _is_dept_head(user)):
        raise HTTPException(403, "Department head or admin access required")

    name = (body.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "name is required")

    placement = _validate_placement(body.get("placement") or "any")
    steps = _normalize_steps(body.get("steps"))

    if _is_admin(user) and body.get("dept"):
        dept = _validate_dept_name(body.get("dept"))
    else:
        dept = _validate_dept_name(_dept(user))

    if not _can_write_dept(user, dept):
        raise HTTPException(403, "Cannot create templates for another department")

    _assert_unique_name(dept, name)

    creator = None
    uid = (user or {}).get("id")
    if uid:
        creator = RcUser.get(id=int(uid))

    now = datetime.utcnow()
    tpl = RcOperationTemplate(
        dept=dept,
        name=name,
        description=(body.get("description") or "").strip(),
        placement=placement,
        created_by=creator,
        created_at=now,
        updated_at=now,
        is_active=True,
    )
    _replace_steps(tpl, steps)
    flush()
    return _template_out(tpl, include_steps=True)


@db_session
def update_template(template_id: int, body: dict, user: dict | None) -> dict:
    tpl = RcOperationTemplate.get(id=template_id)
    if not tpl or not tpl.is_active:
        raise HTTPException(404, "Template not found")
    if not _can_write_dept(user, tpl.dept):
        raise HTTPException(403, "Cannot edit this template")

    if body.get("name") is not None:
        name = (body.get("name") or "").strip()
        if not name:
            raise HTTPException(400, "name is required")
        _assert_unique_name(tpl.dept, name, exclude_id=tpl.id)
        tpl.name = name

    if body.get("description") is not None:
        tpl.description = (body.get("description") or "").strip()

    if body.get("placement") is not None:
        tpl.placement = _validate_placement(body.get("placement"))

    if body.get("steps") is not None:
        steps = _normalize_steps(body.get("steps"))
        _replace_steps(tpl, steps)

    tpl.updated_at = datetime.utcnow()
    flush()
    return _template_out(tpl, include_steps=True)


@db_session
def delete_template(template_id: int, user: dict | None) -> dict:
    tpl = RcOperationTemplate.get(id=template_id)
    if not tpl or not tpl.is_active:
        raise HTTPException(404, "Template not found")
    if not _can_write_dept(user, tpl.dept):
        raise HTTPException(403, "Cannot delete this template")
    tpl.is_active = False
    tpl.updated_at = datetime.utcnow()
    return {"ok": True, "id": template_id}


@db_session
def duplicate_template(template_id: int, body: dict, user: dict | None) -> dict:
    if not (_is_admin(user) or _is_dept_head(user)):
        raise HTTPException(403, "Department head or admin access required")

    src = RcOperationTemplate.get(id=template_id)
    if not src or not src.is_active:
        raise HTTPException(404, "Template not found")

    # dept_head / admin can read any; engineers cannot call this anyway
    if not (_is_admin(user) or _is_dept_head(user)):
        raise HTTPException(403, "Not allowed")

    target_dept = _validate_dept_name(_dept(user) if not _is_admin(user) else (_dept(user) or src.dept))
    if _is_admin(user) and body.get("dept"):
        target_dept = _validate_dept_name(body.get("dept"))
    elif not _is_admin(user):
        target_dept = _validate_dept_name(_dept(user))

    if not _can_write_dept(user, target_dept):
        raise HTTPException(403, "Cannot duplicate into this department")

    root_id = _template_root_id(src)
    if _dept_has_copy(target_dept, root_id):
        raise HTTPException(
            400,
            f"This template is already in {target_dept}. Delete the existing copy first to duplicate again.",
        )
    # Legacy copies (pre copied_from_id): block by name match
    src_name = (src.name or "").strip().lower()
    if src_name:
        legacy = select(
            t
            for t in RcOperationTemplate
            if t.is_active
            and t.dept == target_dept
            and (
                t.name.lower() == src_name
                or t.name.lower() == f"{src_name} (copy)"
            )
        )[:1]
        if legacy:
            raise HTTPException(
                400,
                f"This template is already in {target_dept}. Delete the existing copy first to duplicate again.",
            )

    new_name = (body.get("name") or "").strip() or f"{src.name} (copy)"
    _assert_unique_name(target_dept, new_name)

    creator = None
    uid = (user or {}).get("id")
    if uid:
        creator = RcUser.get(id=int(uid))

    now = datetime.utcnow()
    tpl = RcOperationTemplate(
        dept=target_dept,
        name=new_name,
        description=src.description or "",
        placement=src.placement or "any",
        copied_from_id=root_id,
        created_by=creator,
        created_at=now,
        updated_at=now,
        is_active=True,
    )
    src_steps = sorted(src.steps, key=lambda x: (x.sort_order, x.id))
    for i, s in enumerate(src_steps):
        RcOperationTemplateStep(
            template=tpl,
            sort_order=(i + 1) * 10,
            operation=s.operation,
            work_centre=s.work_centre or "",
            setup=s.setup or "",
            time=s.time or "",
            instruction_text=s.instruction_text or "",
            inspection=s.inspection or "",
            machine=s.machine or "",
            tool=s.tool or "",
            generates_output_serial=bool(s.generates_output_serial),
            requires_input_material=bool(s.requires_input_material),
            manual_operation=s.manual_operation is not False,
        )
    flush()
    return _template_out(tpl, include_steps=True)
