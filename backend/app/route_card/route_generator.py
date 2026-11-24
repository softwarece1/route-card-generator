"""Deterministic route + inspection generation from extracted GA notes."""

from __future__ import annotations

import re

from app.route_card.extractor import is_ctq_note, sanitize_operator_instruction


def partition_notes_for_route(notes: list | None) -> tuple[list, list]:
    """Split notes into assembly (ops) vs CTQ (quality inspection)."""
    assembly: list = []
    ctq: list = []
    for n in notes or []:
        if not isinstance(n, dict):
            continue
        if is_ctq_note(n):
            ctq.append(n)
        else:
            assembly.append(n)
    return assembly, ctq


def _clean_ctq_dimension(text: str) -> str:
    """Tighten CTQ OCR for Quality tab: strip bullets, glue, and table bleed."""
    t = str(text or "")
    t = sanitize_operator_instruction(t) or t
    t = re.sub(r"^[\s•\-\*\u2022\u25CF]+", "", t)
    t = re.sub(r"\s+", " ", t).strip()
    # Drop trailing BOM / PL / revision junk often glued after the CTQ sentence
    t = re.sub(
        r"\s+(?:AD\s*[—\-].*|SES\s+\d.*|Qty[-–—]?\s*\d+\s*Nos?.*|"
        r"item\s*=\s*\d.*|PL[-–—]\s*\d{4}.*)$",
        "",
        t,
        flags=re.I,
    )
    # Collapse obvious OCR letter-runs stuck to words (e.g. "LOOM Li After" stays;
    # strip lone 1–2 letter garbage tokens mid-string only when surrounded by spaces)
    t = re.sub(r"\s+[a-z]{1,2}\s+(?=[A-Z])", " ", t)
    return t.strip(" :;,-•\u2022\u25CF*")[:240]


def ctq_notes_to_inspection(ctq_notes: list, *, start_idx: int = 1) -> list[dict]:
    """Map CTQ POINTS lines to Quality & Inspection characteristics."""
    rows: list[dict] = []
    idx = start_idx
    for n in ctq_notes or []:
        if not isinstance(n, dict):
            continue
        text = _clean_ctq_dimension(n.get("text") or "")
        if len(text) < 6:
            continue
        rows.append(
            {
                "id": f"ic-ctq-{idx}",
                "dimension": text,
                "nominal": "—",
                "tolerance": "—",
                "method": "Visual / as specified",
                "frequency": "100%",
                "criticality": "Critical",
                "source": "ctq",
            }
        )
        idx += 1
    return rows


def _work_centre(text: str, torque: list[str] | None = None) -> str:
    t = text.upper()
    if torque or "TORQUE" in t:
        return "Torque"
    if any(k in t for k in ("CLEAN", "PEEL OFF", "PASTE", "STICK", "GLUE", "BOND", "ADHERE", "APPLY", "MASK")):
        return "Bonding"
    if any(k in t for k in ("DRILL", "SOLDER", "TRANSFORMER", "SHORT", "ROHS", "LEAD-FREE", "BARE BOARD")):
        return "PCB Assembly"
    if any(k in t for k in ("INSPECT", "WEIGHT", "MASS", "VERIFY", "WARPAGE")):
        return "Quality"
    if "HEAT SINK" in t or "SFPDP" in t or "OPTICAL" in t:
        return "Special Assembly"
    return "Assembly"


def _tool(text: str, torque: list[str]) -> str:
    t = text.upper()
    if torque or "TORQUE" in t:
        return "Torque wrench"
    if "DRILL" in t:
        return "Drill"
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
        return "PCB drilling"
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
        return "Transformer mechanical mounting"
    if "TRANSFORMER" in t and "SOLDER" in t:
        return "Transformer soldering"
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


def _final_inspection_op(extraction: dict, notes: list, op_no: int, title: dict) -> dict:
    torques = extraction.get("torque_specs") or []
    checks = []
    tools = []
    if torques:
        checks.append("torque points")
        tools.append("Torque verifier")
    has_connectors = any(n.get("connectors") for n in notes if isinstance(n, dict))
    if has_connectors:
        checks.append("connector engagement")
    if title.get("weight"):
        checks.append("weight")
        tools.append("scale")
    if title.get("surfaceFinish"):
        checks.append("mounting-surface finish")
    if extraction.get("dimensions"):
        checks.append("critical dimensions")
        tools.append("caliper / gauge")
    tools.append("visual")
    tool_label = " / ".join(dict.fromkeys(tools))
    if checks:
        inspection_ops_text = f"Verify {', '.join(checks)}."
    else:
        inspection_ops_text = "Final visual and assembly inspection."
    return {
        "id": f"op-{op_no}",
        "opNo": op_no,
        "operation": "Final inspection",
        "workCentre": "Quality",
        "machine": "Inspection bench",
        "tool": tool_label,
        "items": "",
        "itemsUsed": [],
        "torqueSpec": ", ".join(torques) if torques else "",
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


def generate_route(extraction: dict) -> dict:
    notes = list(extraction.get("notes") or [])
    bom = extraction.get("bom_items") or []
    bom_lookup = {int(b["itemNo"]): int(b.get("qty") or 0) for b in bom}
    title = extraction.get("title_block") or {}
    drawing_type = extraction.get("drawing_type") or title.get("drawingType") or "unknown"
    assembly_notes, ctq_notes = partition_notes_for_route(notes)

    # Prefer LLM Stage D route when present and non-empty
    llm_ops = extraction.get("llmRouteOps") or extraction.get("llm_route_ops") or []
    if isinstance(llm_ops, list) and len(llm_ops) >= 1:
        ctq_norm = {
            re.sub(r"\s+", " ", str(n.get("text") or "")).strip().lower()[:120]
            for n in ctq_notes
            if isinstance(n, dict) and (n.get("text") or "").strip()
        }
        operations = []
        for op in llm_ops:
            if not isinstance(op, dict):
                continue
            instr_probe = re.sub(
                r"\s+",
                " ",
                str(op.get("instructionText") or op.get("instruction") or ""),
            ).strip().lower()[:120]
            # Drop Stage D echoes of CTQ lines (Quality tab owns those).
            if instr_probe and any(
                instr_probe == c or instr_probe in c or c in instr_probe
                for c in ctq_norm
                if len(c) >= 12
            ):
                continue
            o = dict(op)
            items_used = []
            for it in o.get("itemsUsed") or []:
                if not isinstance(it, dict):
                    continue
                try:
                    ino = int(it.get("itemNo"))
                except (TypeError, ValueError):
                    continue
                qty = it.get("qty")
                if qty is None:
                    qty = bom_lookup.get(ino)
                items_used.append(
                    {
                        "itemNo": ino,
                        "qty": qty,
                        "description": it.get("description"),
                    }
                )
            instr = sanitize_operator_instruction(
                o.get("instructionText") or o.get("instruction") or ""
            ) or (o.get("instructionText") or o.get("instruction") or "")
            o["instructionText"] = instr
            o["itemsUsed"] = items_used
            o["items"] = ", ".join(
                f"#{u['itemNo']}" + (f"×{u['qty']}" if u.get("qty") else "")
                for u in items_used
            )
            o["features"] = [f"ITM-{u['itemNo']}" for u in items_used]
            o["source"] = o.get("source") or "llm_route"
            operations.append(o)
        if operations:
            operations.sort(key=lambda x: int(x.get("opNo") or 0))
            for i, o in enumerate(operations):
                op_no = (i + 1) * 10
                o["opNo"] = op_no
                o["id"] = f"op-{op_no}"
            max_op = max(int(o.get("opNo") or 0) for o in operations)
            operations.append(
                _final_inspection_op(extraction, assembly_notes, max_op + 10, title)
            )
            return _route_payload(
                extraction,
                assembly_notes,
                bom,
                operations,
                drawing_type,
                title,
                ctq_notes=ctq_notes,
            )

    # Milestone 1: ensure balloon assembly groups become notes if not already merged
    groups = extraction.get("assemblyGroups") or extraction.get("assembly_groups") or []
    if groups:
        try:
            from app.route_card.drawing_mind.assembly_groups import (
                groups_to_synthetic_notes,
                merge_notes_with_balloon_notes,
            )

            balloon_notes = groups_to_synthetic_notes(
                groups, parts_list={"items": bom}
            )
            notes = merge_notes_with_balloon_notes(notes, balloon_notes)
            assembly_notes, ctq_notes = partition_notes_for_route(notes)
        except Exception:
            pass

    operations = []
    op_no = 10
    for note in assembly_notes:
        text = note.get("text") or ""
        # Keep the drawing wording. CPU/view elaboration is used only when it
        # still contains that wording (never a free rewrite that drops the note).
        insight = (note.get("insight") or "").strip()
        raw = str(text or "").strip()
        elab = re.sub(r"\s+", " ", str(note.get("elaboratedText") or "")).strip()
        raw_norm = re.sub(r"\s+", " ", raw).lower()
        elab_norm = re.sub(r"\s+", " ", elab).lower()
        head = raw_norm[:80]
        use_elab = bool(
            elab_norm
            and raw_norm
            and elab_norm != raw_norm
            and (
                raw_norm in elab_norm
                or (head and head in elab_norm and "->" in elab_norm)
                or bool(note.get("elaborated"))
            )
        )
        instruction_src = elab if use_elab else raw
        instruction_clean = sanitize_operator_instruction(instruction_src) or instruction_src
        insight_clean = sanitize_operator_instruction(insight) if insight else ""
        torque = note.get("torque") or []
        items = note.get("items") or []
        refs = list(note.get("standards") or []) + list(note.get("references") or [])
        # Prefer elaborated text for naming/WC hints when it carries grounding
        hint_text = instruction_src or text
        name = _op_name(hint_text, note.get("stepNo") or 1)
        wc = _work_centre(hint_text, torque)
        if note.get("itemsUsed"):
            items_used = []
            for it in note.get("itemsUsed") or []:
                if not isinstance(it, dict):
                    continue
                try:
                    ino = int(it.get("itemNo"))
                except (TypeError, ValueError):
                    continue
                qty = it.get("qty")
                if qty is None:
                    qty = bom_lookup.get(ino)
                items_used.append(
                    {
                        "itemNo": ino,
                        "qty": qty,
                        "description": it.get("description"),
                    }
                )
        else:
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
        drawing_zone = ""
        if note.get("assemblyGroup"):
            dz = str(note.get("drawingZone") or "").strip()
            if re.fullmatch(r"[A-Ha-h]-\d{1,2}", dz):
                drawing_zone = f"{dz[0].upper()}{dz[1:]}"
        op_row: dict = {
            "id": f"op-{op_no}",
            "opNo": op_no,
            "operation": name,
            "workCentre": wc,
            "machine": "Assembly station",
            "tool": _tool(hint_text, torque),
            "items": items_label,
            "itemsUsed": items_used,
            "torqueSpec": ", ".join(torque),
            "reference": ", ".join(dict.fromkeys(refs)),
            "setup": "1",
            "time": "",
            "inspection": _inspection_for_step(hint_text, torque),
            "instructionText": instruction_clean,
            "insight": insight_clean or insight,
            "status": "Planned",
            "type": wc,
            "reason": instruction_clean[:240],
            "features": [f"ITM-{i}" for i in items],
            "elaborated": bool(insight) or use_elab or bool(note.get("elaborated")),
            "verbatimText": raw,
            "needsReview": bool(note.get("needsReview")),
            "sourceDrawingId": note.get("sourceDrawingId"),
            "placement": note.get("placement") or [],
            "viewRefs": note.get("viewRefs") or [],
        }
        if drawing_zone:
            op_row["drawingZone"] = drawing_zone
        operations.append(op_row)
        op_no += 10

    operations.append(_final_inspection_op(extraction, assembly_notes, op_no, title))
    return _route_payload(
        extraction,
        assembly_notes,
        bom,
        operations,
        drawing_type,
        title,
        ctq_notes=ctq_notes,
    )


def _route_payload(
    extraction: dict,
    notes: list,
    bom: list,
    operations: list,
    drawing_type: str,
    title: dict,
    ctq_notes: list | None = None,
) -> dict:
    torques = extraction.get("torque_specs") or []
    inspection = []
    idx = 1
    for tq in torques:
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
                    "frequency": "100% fasteners" if ("902" in std or torques) else "Process audit",
                    "criticality": "Important",
                }
            )
            idx += 1

    # CTQ POINTS from GA → Quality & Inspection (not Manufacturing ops)
    ctq_rows = ctq_notes_to_inspection(
        ctq_notes if ctq_notes is not None else [],
        start_idx=idx,
    )
    if not ctq_rows:
        # Fallback: classify from extraction notes if caller did not pass ctq_notes
        _, inferred_ctq = partition_notes_for_route(extraction.get("notes") or [])
        ctq_rows = ctq_notes_to_inspection(inferred_ctq, start_idx=idx)
    for row in ctq_rows:
        inspection.append(row)
        idx += 1

    # Dynamic fastener count
    fastener_kws = ("SCREW", "BOLT", "NUT", "WASHER", "FASTENER", "STUD", "RIVET", "STANDOFF", "PIN", "CSK", "HEX")
    fastener_count = 0
    for b in bom:
        desc = (b.get("description") or "").upper()
        pno = (b.get("partNumber") or "").upper()
        if any(k in desc or k in pno for k in fastener_kws):
            fastener_count += 1
    if fastener_count == 0:
        fastener_count = sum(
            1 for n in notes
            if any(k in (n.get("text") or "").upper() for k in ("SCREW", "FASTENER", "BOLT", "NUT", "WASHER"))
        )

    # Dynamic hole count from dimensions
    hole_count = 0
    for d in extraction.get("dimensions") or []:
        val = d.get("value") or ""
        lbl = (d.get("label") or "").lower()
        if "hole" in lbl or "thru" in val.lower():
            m = re.search(r"(\d+)\s*[xX×]", val)
            if m:
                hole_count += int(m.group(1))
            else:
                hole_count += 1

    counts = [
        {"key": "items", "label": "BOM items", "count": len(bom)},
        {"key": "ops", "label": "Assembly steps", "count": max(len(operations) - 1, 0)},
        {"key": "fasteners", "label": "Fastener callouts", "count": fastener_count},
        {"key": "connectors", "label": "Connector refs", "count": len({c for n in notes for c in n.get("connectors") or []})},
        {"key": "torques", "label": "Torque specs", "count": len(torques)},
        {"key": "holes", "label": "Mounting holes", "count": hole_count},
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
    for tq in torques:
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
