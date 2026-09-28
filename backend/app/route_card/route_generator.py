"""Deterministic route + inspection generation from extracted GA notes."""

from __future__ import annotations

import re

from app.route_card.extractor import break_instruction_points


def _work_centre(text: str) -> str:
    t = text.upper()
    if any(k in t for k in ("CLEAN", "PEEL OFF", "PASTE", "STICK", "GLUE", "BOND", "ADHERE", "APPLY", "MASK")):
        return "Bonding"
    if any(k in t for k in ("TORQUE", "TIGHTEN", "JAMNUT", "FASTEN", "SECURE")):
        return "Torque"
    if any(k in t for k in ("DRILL", "SOLDER", "TRANSFORMER", "SHORT", "ROHS", "LEAD-FREE", "BARE BOARD")):
        return "PCB Assembly"
    if any(k in t for k in ("INSPECT", "WEIGHT", "MASS", "VERIFY", "WARPAGE")):
        return "Quality"
    if "HEAT SINK" in t or "SFPDP" in t or "OPTICAL" in t:
        return "Special Assembly"
    return "Assembly"


def _tool(text: str, torque: list[str]) -> str:
    t = text.upper()
    if torque or "TORQUE" in t or "TIGHTEN" in t:
        return "Torque wrench"
    if "DRILL" in t:
        return "Drill / 4-40 UNC inserts"
    if "SOLDER" in t:
        return "Soldering station"
    if "MASK" in t:
        return "Masking tape"
    if any(k in t for k in ("PEEL", "PASTE", "STICK", "GLUE", "BOND", "ADHERE", "APPLY")):
        return "Applicator"
    if "CLEAN" in t:
        return "IPA / lint-free cloth"
    return "Assembly tools"


def _op_name(text: str, step_no: int) -> str:
    t = text.upper()
    if "CLEAN" in t:
        return "Surface preparation"
    if "PEEL OFF" in t and ("PASTE" in t or "STICK" in t):
        return "Adhesive pad application"
    if any(k in t for k in ("STICK", "GLUE", "BOND", "ADHERE", "ADHESIVE")):
        return "Adhesive / bonding"
    if "MASK" in t or "CONFORMAL" in t:
        return "Masking before conformal coating"
    if "DRILL" in t:
        return "PCB drilling for inserts"
    if "WARPAGE" in t and "TRANSFORMER" not in t:
        return "Board warpage check"
    if "SOLDER FILL" in t or "UN-USED HOLES" in t or "UNUSED HOLES" in t:
        return "Solder-fill unused holes"
    if "DO NOT SHORT" in t:
        return "Do not short specified connector pins"
    if "DO NOT MOUNT" in t:
        return "Do not mount specified items"
    if "BARE BOARD" in t or "ENAMEL" in t:
        return "Bare-board wire shorting"
    if "SHORT" in t and ("PIN" in t or re.search(r"\bX\d+", t)):
        return "Short connector pins"
    if "TRANSFORMER" in t and ("MOUNT" in t or "MECHANICAL" in t):
        return "Beta transformer mechanical mounting"
    if "TRANSFORMER" in t and "SOLDER" in t:
        return "Beta transformer soldering"
    if "LEAD-FREE" in t or "ROHS" in t:
        return "RoHS / lead-free component callout"
    if "FACIA" in t:
        return "Facia panel assembly"
    if "TEST POINT" in t:
        return "Mask / protect test points"
    if "CONNECTOR" in t and ("MASK" in t or "X1" in t or "P1" in t or "PL," in t or "P2" in t):
        return "Mask connectors"
    if "TIN PLATED" in t or "SIDE EDGE" in t:
        return "Mask PCB tin-plated edge"
    if "JAMNUT" in t or "O-RING" in t or "O RING" in t:
        return "Connector jam-nut and O-ring fitment"
    if "HEAT SINK" in t:
        return "Heat-sink assembly"
    if "SFPDP" in t or "OPTICAL" in t:
        return "SFPDP / optical interface"
    if "WEIGHT" in t or "MASS" in t or ("MOUNT" in t and "FLOOR" in t):
        return "Installation / mounting"
    if "ENGAGE" in t and "CONNECTOR" in t:
        return "Connector engagement"
    if any(k in t for k in ("ASSEMBLE", "ASSEMBLY", "INSTALL", "FIT", "PLACE ITEM", "MOUNT")):
        first = text.split(".")[0]
        if len(first) < 80:
            return first[:72].title() if first[:1].islower() else first[:72]
        return f"Assembly step {step_no}"
    return f"Assembly step {step_no}"


def _inspection_for_step(text: str, torque: list[str]) -> str:
    if torque:
        return f"Torque {', '.join(torque)}"
    t = text.upper()
    if "ENGAGE" in t:
        return "Visual — connector fully mated"
    if any(k in t for k in ("PEEL", "PASTE", "STICK", "GLUE", "BOND", "ADHESIVE")):
        return "Visual — liner removed, pad seated"
    if "CLEAN" in t:
        return "Visual — hatched surfaces clean"
    return "Visual"


def _items_payload(item_nos: list[int], bom_lookup: dict[int, int]) -> list[dict]:
    return [{"itemNo": n, "qty": bom_lookup.get(n), "description": None} for n in item_nos]


def generate_route(extraction: dict) -> dict:
    notes = extraction.get("notes") or []
    bom = extraction.get("bom_items") or []
    bom_lookup = {int(b["itemNo"]): int(b.get("qty") or 0) for b in bom}
    title = extraction.get("title_block") or {}
    drawing_type = extraction.get("drawing_type") or title.get("drawingType") or "unknown"

    operations = []
    op_no = 10
    for note in notes:
        text = note.get("text") or ""
        elaborated = (note.get("elaboratedText") or "").strip()
        instruction_src = elaborated or text
        if re.match(r"^INSTALLATION TORQUE FOR ALL", text, re.I) and len(text) < 120:
            # fold generic PS902 reminder into following ops rather than a lone op
            continue
        torque = note.get("torque") or []
        items = note.get("items") or []
        refs = list(note.get("standards") or []) + list(note.get("references") or [])
        name = _op_name(text, note.get("stepNo") or 1)
        wc = _work_centre(text)
        items_used = _items_payload(items, bom_lookup)
        items_label = ", ".join(f"#{i['itemNo']}" + (f"×{i['qty']}" if i.get("qty") else "") for i in items_used)
        src_ref = note.get("sourceFilename") or ""
        if src_ref and src_ref not in refs:
            refs.append(src_ref)
        for vr in note.get("viewRefs") or []:
            if isinstance(vr, dict):
                fn = vr.get("matchedFilename") or ""
                if fn and fn not in refs:
                    refs.append(fn)
                lab = vr.get("label") or ""
                if lab and lab not in refs:
                    refs.append(lab)
        for r in note.get("references") or []:
            if r and r not in refs:
                refs.append(r)
        operations.append(
            {
                "id": f"op-{op_no}",
                "opNo": op_no,
                "operation": name,
                "workCentre": wc,
                "machine": "Assembly station",
                "tool": _tool(text, torque),
                "items": items_label,
                "itemsUsed": items_used,
                "torqueSpec": ", ".join(torque),
                "reference": ", ".join(dict.fromkeys(refs)),
                "setup": "1",
                "time": "",
                "inspection": _inspection_for_step(text, torque),
                "instructionText": break_instruction_points(instruction_src),
                "status": "Planned",
                "type": wc,
                "reason": break_instruction_points(instruction_src)[:240],
                "features": [f"ITM-{i}" for i in items],
                "elaborated": bool(elaborated),
                "sourceDrawingId": note.get("sourceDrawingId"),
                "placement": note.get("placement") or [],
                "viewRefs": note.get("viewRefs") or [],
            }
        )
        op_no += 10

    # Always close with inspection
    inspection_ops_text = "Verify torque points, connector engagement, weight and mounting-surface finish."
    operations.append(
        {
            "id": f"op-{op_no}",
            "opNo": op_no,
            "operation": "Final inspection",
            "workCentre": "Quality",
            "machine": "Inspection bench",
            "tool": "Torque verifier / scale / visual",
            "items": "",
            "itemsUsed": [],
            "torqueSpec": ", ".join(extraction.get("torque_specs") or []),
            "reference": ", ".join(extraction.get("references") or []),
            "setup": "—",
            "time": "",
            "inspection": "100% derived checklist",
            "instructionText": inspection_ops_text,
            "status": "Planned",
            "type": "Quality",
            "reason": inspection_ops_text,
            "features": [],
        }
    )

    inspection = []
    idx = 1
    for tq in extraction.get("torque_specs") or []:
        inspection.append(
            {
                "id": f"ic-{idx}",
                "dimension": f"Fastener / connector torque {tq}",
                "nominal": tq,
                "tolerance": tq,
                "method": "Calibrated torque wrench",
                "frequency": "100%",
                "criticality": "Critical",
            }
        )
        idx += 1
    for dim in extraction.get("dimensions") or []:
        level = dim.get("level") or "Standard"
        if level == "Standard" and "pitch" in (dim.get("label") or "").lower():
            continue
        inspection.append(
            {
                "id": f"ic-{idx}",
                "dimension": dim.get("label") or "Dimension",
                "nominal": dim.get("value") or "",
                "tolerance": "",
                "method": "CMM / scale / visual" if "Mass" in (dim.get("label") or "") else "Visual / gauge",
                "frequency": "100%" if level == "Critical" else "First piece",
                "criticality": level,
            }
        )
        idx += 1
    for std in extraction.get("references") or []:
        if std.upper().startswith("PS"):
            inspection.append(
                {
                    "id": f"ic-{idx}",
                    "dimension": f"Compliance {std}",
                    "nominal": std,
                    "tolerance": "—",
                    "method": "Process audit",
                    "frequency": "100% fasteners",
                    "criticality": "Important",
                }
            )
            idx += 1

    counts = [
        {"key": "items", "label": "BOM items", "count": len(bom)},
        {"key": "ops", "label": "Assembly steps", "count": max(len(operations) - 1, 0)},
        {"key": "fasteners", "label": "Fastener callouts", "count": sum(1 for b in bom if b["itemNo"] in {3, 5, 8, 23, 26, 27, 29, 30, 31, 32, 33, 36, 37, 38, 44, 50, 53, 54, 55, 56})},
        {"key": "connectors", "label": "Connector refs", "count": len({c for n in notes for c in n.get("connectors") or []})},
        {"key": "torques", "label": "Torque specs", "count": len(extraction.get("torque_specs") or [])},
        {"key": "holes", "label": "Mounting holes", "count": 8 if any("Mounting holes" in (d.get("label") or "") for d in extraction.get("dimensions") or []) else 0},
        {"key": "docs", "label": "Referenced docs", "count": len(extraction.get("references") or [])},
        {"key": "critical", "label": "Critical checks", "count": sum(1 for i in inspection if i.get("criticality") == "Critical")},
    ]

    features = []
    for i, b in enumerate(bom[:40], start=1):
        features.append(
            {
                "id": f"ITM-{b['itemNo']}",
                "type": f"Item {b['itemNo']}",
                "dimension": f"Qty {b['qty']}",
                "tolerance": "—",
                "operation": "Assembly",
                "category": "Assembly",
            }
        )

    requirements = []
    for ref in extraction.get("references") or []:
        requirements.append({"label": "Referenced document", "value": ref, "level": "Important"})
    for tq in extraction.get("torque_specs") or []:
        requirements.append({"label": "Torque requirement", "value": tq, "level": "Critical"})
    if title.get("weight"):
        requirements.append({"label": "Mass", "value": title["weight"], "level": "Critical"})
    if title.get("surfaceFinish"):
        requirements.append({"label": "Surface finish", "value": title["surfaceFinish"], "level": "Important"})

    return {
        "drawing_type": drawing_type,
        "operations": operations,
        "inspection": inspection,
        "feature_counts": counts,
        "manufacturing_features": features,
        "intelligence_dimensions": extraction.get("dimensions") or [],
        "intelligence_requirements": requirements,
        "referenced_documents": extraction.get("references") or [],
    }
