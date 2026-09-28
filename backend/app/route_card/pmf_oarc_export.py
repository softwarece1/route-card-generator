"""Map route-card analysis payload → PMF CreateOrderModal / OARC JSON shape.

Fields that drawings cannot provide (Prod Order, Sale Order, WBS, Plant, Priority)
are left blank for the engineer to fill in Create Order.
"""

from __future__ import annotations

import re
from typing import Any


def _s(value: Any, default: str = "") -> str:
    if value is None:
        return default
    return str(value).strip()


def _num(value: Any, default: float | int | None = 0):
    if value is None or value == "":
        return default
    try:
        if isinstance(value, (int, float)):
            return value
        cleaned = re.sub(r"[^\d.\-]", "", str(value))
        if cleaned == "" or cleaned in {".", "-", "-."}:
            return default
        if "." in cleaned:
            return float(cleaned)
        return int(cleaned)
    except (TypeError, ValueError):
        return default


def _op_no(raw: Any, index: int) -> int:
    n = _num(raw, None)
    if isinstance(n, (int, float)) and n > 0:
        n = int(n)
        # PMF often uses 10, 20, 30 — keep if already multiple of 10
        if n % 10 == 0:
            return n
        return n * 10 if n < 10 else n
    return (index + 1) * 10


def _instruction_for_op(op: dict, notes: list[dict] | None) -> str:
    """Prefer instructionText; else match note by step / op number."""
    from app.route_card.extractor import break_instruction_points

    text = _s(op.get("instructionText") or op.get("reason"))
    if text:
        return break_instruction_points(text)
    op_no = _num(op.get("opNo"), None)
    for note in notes or []:
        step = _num(note.get("stepNo"), None)
        if op_no is not None and step is not None and int(op_no) == int(step):
            return break_instruction_points(_s(note.get("text")))
    return ""


def _raw_materials_from_payload(payload: dict, required_qty: float | int) -> list[dict]:
    items: list[dict] = []
    pl = payload.get("partsList") or {}
    pl_items = pl.get("items") if isinstance(pl, dict) else None
    if pl_items:
        source = pl_items
    else:
        source = payload.get("bomItems") or []

    for i, it in enumerate(source):
        if not isinstance(it, dict):
            continue
        qty = _num(it.get("qty") or it.get("quantity"), 1) or 1
        try:
            qty_f = float(qty)
        except (TypeError, ValueError):
            qty_f = 1.0
        req = float(required_qty or 1) or 1.0
        part_no = _s(it.get("partNumber") or it.get("part_number") or it.get("Child Part No"))
        desc = _s(it.get("description") or it.get("Description") or it.get("designation"))
        if not part_no and not desc:
            continue
        items.append(
            {
                "Sl.No": (i + 1) * 10,
                "Child Part No": part_no,
                "Description": desc,
                "Qty Per Set": qty_f,
                "UoM": _s(it.get("unit") or it.get("UoM") or "NO") or "NO",
                "Total Qty": qty_f * req,
            }
        )
    return items


def _operations_from_payload(payload: dict) -> list[dict]:
    ops = payload.get("routeOperations") or payload.get("suggestedOperations") or []
    notes = payload.get("notes") or []
    out: list[dict] = []
    for i, op in enumerate(ops):
        if not isinstance(op, dict):
            continue
        desc = _s(op.get("operation") or op.get("Operation"))
        if not desc:
            continue
        wc = _s(
            op.get("workCentre")
            or op.get("workCenter")
            or op.get("Wc/Plant")
            or op.get("work_center_code")
        )
        long_text = _instruction_for_op(op, notes)
        # Append torque / items hints into LongText when present
        extras: list[str] = []
        items = _s(op.get("items"))
        if items:
            extras.append(f"Items: {items}")
        torque = _s(op.get("torqueSpec"))
        if torque:
            extras.append(f"Torque: {torque}")
        ref = _s(op.get("reference"))
        if ref:
            extras.append(f"Ref: {ref}")
        if extras:
            long_text = (long_text + "\n" if long_text else "") + "\n".join(extras)

        setup = _num(op.get("setup"), 0) or 0
        per_pc = _num(op.get("time"), 0) or 0
        # setup/time in route-card are often strings like "1" not hours — keep numeric
        out.append(
            {
                "Oprn No": _op_no(op.get("opNo"), i),
                "Wc/Plant": wc,
                "Work Center": wc,
                "work_center_code": wc,
                "Operation": desc,
                "Setup Time": float(setup) if setup else 0,
                "Per Pc Time": float(per_pc) if per_pc else 0,
                "LongText": long_text,
                "Plant Number": "",
                "Jmp Qty": 0,
                "Tot Qty": 0,
                "Allowed Time": 0,
                "Confirm No": "",
                "generates_output_serial": False,
                "requires_input_material": False,
                "manual_operation": True,
            }
        )
    return out


def payload_to_pmf_oarc(
    payload: dict,
    *,
    required_qty: float | int | None = None,
    plant: str | int | None = None,
    production_order: str = "",
    sale_order: str = "",
    wbs: str = "",
    project_name: str = "",
) -> dict[str, Any]:
    """Build OARC-compatible dict for CreateOrderModal import."""
    info = payload.get("drawingInfo") or {}
    part_no = _s(
        info.get("partNumber")
        or info.get("drawingNumber")
        or info.get("part_number")
    )
    part_desc = _s(info.get("partName") or info.get("title") or info.get("part_description"))
    ops = _operations_from_payload(payload)
    req = required_qty if required_qty is not None else 1
    materials = _raw_materials_from_payload(payload, req)

    return {
        "source": "route-card-app",
        "Project Name": _s(project_name) or _s(part_desc) or "Route Card Import",
        "Sale Order": _s(sale_order),
        "Part No": part_no,
        "Part Desc": part_desc,
        "Required Qty": req,
        "Plant": plant if plant is not None else "",
        "WBS": _s(wbs),
        "Rtg Seq No": "0",
        "Sequence No": "0",
        "Launched Qty": req,
        "Prod Order No": _s(production_order),
        "Priority": "normal",
        "Total Operations": len(ops) or 1,
        "Operations": ops,
        "Raw Materials": materials,
        "Document Verification": {},
        # Helpful for engineers — not required by CreateOrderModal
        "_meta": {
            "routeCardId": payload.get("id"),
            "sessionId": payload.get("sessionId"),
            "drawingNumber": _s(info.get("drawingNumber")),
            "revision": _s(info.get("revision") or info.get("version")),
            "notesCount": len(payload.get("notes") or []),
            "warnings": list(payload.get("warnings") or [])[:20],
        },
    }
