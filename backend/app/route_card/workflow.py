"""Clone, compare, favorites, recent, auto-template apply (Phases 2 & 4)."""

from __future__ import annotations

import re
from datetime import datetime

from fastapi import HTTPException
from pony.orm import commit, db_session, desc, select

from app.route_card import audit
from app.route_card.models import (
    RcInspectionChar,
    RcOperation,
    RcOperationTemplate,
    RcRouteCard,
    RcSession,
    RcUser,
    RcUserFavorite,
)


def _op_snapshot(o: RcOperation) -> dict:
    return {
        "opNo": o.op_no,
        "operation": o.operation or "",
        "workCentre": o.work_centre or "",
        "machine": o.machine or "",
        "tool": o.tool or "",
        "itemsUsed": o.items_used or [],
        "torqueSpec": o.torque_spec or "",
        "reference": o.reference or "",
        "setup": o.setup or "",
        "time": o.time or "",
        "inspection": o.inspection or "",
        "instructionText": o.instruction_text or "",
        "status": o.status or "Planned",
    }


@db_session
def clone_route_onto_session(
    session_id: int,
    from_route_card_id: int,
    user: dict,
) -> dict:
    from app.route_card import service

    session = RcSession.get(id=session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    service._assert_session_access(session, user, write=True)
    source = RcRouteCard.get(id=from_route_card_id)
    if not source:
        raise HTTPException(404, "Source route card not found")
    drawings = list(sorted(session.drawings, key=lambda x: x.id))
    if not drawings:
        raise HTTPException(400, "Upload a drawing to the session before cloning a route")
    primary = drawings[-1]
    existing = primary.route_cards.select().order_by(desc(RcRouteCard.created_at)).first()
    generated = {
        "operations": [_op_snapshot(o) for o in sorted(source.operations, key=lambda x: x.op_no)],
        "inspection": [
            {
                "dimension": c.characteristic,
                "nominal": c.nominal,
                "tolerance": c.tolerance,
                "method": c.method,
                "frequency": c.frequency,
                "criticality": c.criticality,
            }
            for c in source.inspection_chars
        ],
    }
    card = service.persist_route(primary, generated, existing)
    card.status = "draft"
    commit()
    audit.record_audit(
        action="clone_route",
        user=user,
        route_card_id=card.id,
        session_id=session_id,
        detail={"fromRouteCardId": from_route_card_id},
        comment=f"Cloned from route {from_route_card_id}",
    )
    from app.route_card.models import RcExtraction

    extraction = primary.extractions.select().order_by(desc(RcExtraction.created_at)).first()
    return service.build_payload(primary, extraction, card)


@db_session
def compare_route_cards(a_id: int, b_id: int) -> dict:
    a = RcRouteCard.get(id=a_id)
    b = RcRouteCard.get(id=b_id)
    if not a or not b:
        raise HTTPException(404, "Route card not found")
    a_ops = {_op_key(o): _op_snapshot(o) for o in a.operations}
    b_ops = {_op_key(o): _op_snapshot(o) for o in b.operations}
    added = [b_ops[k] for k in b_ops if k not in a_ops]
    removed = [a_ops[k] for k in a_ops if k not in b_ops]
    changed = []
    for k in a_ops:
        if k in b_ops and a_ops[k] != b_ops[k]:
            changed.append({"before": a_ops[k], "after": b_ops[k]})
    return {
        "a": {"id": a.id, "status": a.status, "opCount": len(a_ops)},
        "b": {"id": b.id, "status": b.status, "opCount": len(b_ops)},
        "added": added,
        "removed": removed,
        "changed": changed,
    }


def _op_key(o: RcOperation) -> str:
    return f"{o.op_no}|{(o.work_centre or '').strip()}|{(o.operation or '').strip()[:80]}"


@db_session
def list_favorites(user: dict) -> list[dict]:
    uid = user.get("id")
    rows = select(f for f in RcUserFavorite if f.user.id == uid).order_by(
        desc(RcUserFavorite.created_at)
    )[:50]
    return [
        {
            "id": f.id,
            "partNumber": f.part_number or "",
            "label": f.label or "",
            "sessionId": f.session_id,
            "routeCardId": f.route_card_id,
            "createdAt": f.created_at.isoformat() + "Z" if f.created_at else None,
        }
        for f in rows
    ]


@db_session
def add_favorite(user: dict, body: dict) -> dict:
    u = RcUser.get(id=user["id"])
    if not u:
        raise HTTPException(401, "User not found")
    f = RcUserFavorite(
        user=u,
        part_number=(body.get("partNumber") or "").strip(),
        label=(body.get("label") or "").strip(),
        session_id=body.get("sessionId"),
        route_card_id=body.get("routeCardId"),
    )
    commit()
    return {
        "id": f.id,
        "partNumber": f.part_number,
        "label": f.label,
        "sessionId": f.session_id,
        "routeCardId": f.route_card_id,
    }


@db_session
def delete_favorite(fav_id: int, user: dict) -> dict:
    f = RcUserFavorite.get(id=fav_id)
    if not f or f.user.id != user.get("id"):
        raise HTTPException(404, "Favorite not found")
    f.delete()
    commit()
    return {"ok": True}


@db_session
def list_recent(user: dict, limit: int = 8) -> list[dict]:
    from app.route_card import service

    items = service.list_my_extractions(user)
    # list_my_extractions returns {items: [...]} or list
    rows = items.get("items") if isinstance(items, dict) else items
    out = []
    for row in (rows or [])[:limit]:
        out.append(
            {
                "sessionId": row.get("sessionId") or row.get("id"),
                "partNumber": row.get("partNumber") or row.get("drawingNumber") or "",
                "status": row.get("status"),
                "updatedAt": row.get("updatedAt") or row.get("createdAt"),
                "routeCardId": row.get("routeCardId"),
            }
        )
    return out


def apply_auto_templates(
    operations: list[dict],
    *,
    dept: str | None,
    title_block: dict | None,
    notes: list | None,
) -> list[dict]:
    """Insert dept auto-template steps (pre/post) when keywords match."""
    from app.route_card.dept_config import get_dept_rules

    if not dept:
        return operations
    rules_wrap = get_dept_rules(dept)
    rules = rules_wrap.get("rules") or {}
    auto_ids = rules.get("autoTemplateIds") or []
    keywords = [str(k).lower() for k in (rules.get("keywords") or []) if k]
    blob = " ".join(
        [
            str((title_block or {}).get("partNumber") or ""),
            str((title_block or {}).get("title") or ""),
            " ".join(
                (n.get("text") if isinstance(n, dict) else str(n)) or ""
                for n in (notes or [])
            ),
        ]
    ).lower()
    if keywords and not any(k in blob for k in keywords):
        return operations

    pre_ops: list[dict] = []
    post_ops: list[dict] = []
    for tid in auto_ids:
        try:
            tpl = RcOperationTemplate.get(id=int(tid))
        except (TypeError, ValueError):
            continue
        if not tpl or not tpl.is_active:
            continue
        if (tpl.dept or "").strip() != (dept or "").strip() and dept:
            continue
        steps = sorted(tpl.steps, key=lambda s: s.sort_order)
        mapped = [
            {
                "opNo": 0,
                "operation": s.operation,
                "workCentre": s.work_centre or "",
                "machine": s.machine or "",
                "tool": s.tool or "",
                "itemsUsed": [],
                "setup": s.setup or "1",
                "time": s.time or "",
                "inspection": s.inspection or "",
                "instructionText": s.instruction_text or "",
                "status": "Planned",
                "reference": f"template:{tpl.id}",
            }
            for s in steps
        ]
        if (tpl.placement or "any") == "pre":
            pre_ops.extend(mapped)
        else:
            post_ops.extend(mapped)

    combined = pre_ops + list(operations or []) + post_ops
    n = 10
    for op in combined:
        op["opNo"] = n
        n += 10
    aliases = rules.get("wcAliases") or {}
    if aliases:
        for op in combined:
            wc = op.get("workCentre") or ""
            if wc in aliases:
                op["workCentre"] = aliases[wc]
    return combined


def suggest_vlm_pages(raw_text: str, page_count: int | None) -> list[int]:
    """Heuristic: pages mentioning NOTES / AS SHOWN / INSTRUCTION."""
    if not page_count or page_count < 1:
        return [1]
    prefer = []
    if page_count >= 1:
        prefer.append(1)
    for i in range(max(1, page_count - 2), page_count + 1):
        if i not in prefer:
            prefer.append(i)
    text = (raw_text or "").lower()
    if re.search(r"as\s*shown|assembly\s+note|instruction", text):
        return prefer[:4]
    return list(range(1, min(page_count, 3) + 1))
