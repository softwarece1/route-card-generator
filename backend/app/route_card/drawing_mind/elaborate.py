"""Shared grounded note elaboration used by CPU and VLM minds."""

from __future__ import annotations

import re
from typing import Any

ITEM_APPEAR = re.compile(
    r"(?:ITEMS?|ITMS?|IT\.?)\s*(?:NO\.?|NOS\.?|NUMBER|#)?\s*-?\s*(\d{1,3})",
    re.I,
)

PLACEMENT_VERB = re.compile(
    r"\b(STICK|PASTE|GLUE|BOND|ADHERE|APPLY|MOUNT|PLACE|FIT|INSTALL|"
    r"ASSEMBLE|FIX|ENGAGE|MATE|TIGHTEN)\b",
    re.I,
)
AS_SHOWN = re.compile(r"\bAS\s+SHOWN\b", re.I)


def bom_index(ga_extraction: dict | None, parts_list: dict | None = None) -> dict[int, dict]:
    """Item number → description / part number from PL, then GA BOM."""
    out: dict[int, dict] = {}
    for src in (
        (parts_list or {}).get("items") or [],
        (ga_extraction or {}).get("bom_items") or [],
    ):
        for row in src:
            if not isinstance(row, dict):
                continue
            try:
                n = int(row.get("itemNo") or 0)
            except (TypeError, ValueError):
                continue
            if n <= 0 or n in out:
                continue
            desc = str(row.get("description") or row.get("designation") or "").strip()
            pn = str(row.get("partNumber") or "").strip()
            if desc or pn:
                out[n] = {"description": desc, "partNumber": pn}
    return out


def elaborate_note_cpu(note: dict, bom: dict[int, dict], unit: str = "mm") -> str:
    """Expand a GA note with PL names, torque, connectors — without inventing sizes."""
    del unit  # reserved for future size appendix; placement path owns measured mm
    raw = re.sub(r"\s+", " ", str(note.get("text") or "")).strip()
    base = re.sub(r"\s+", " ", str(note.get("elaboratedText") or "")).strip() or raw
    if not base:
        return ""
    extras: list[str] = []
    blob = base.upper()
    # Do not append "Parts: …" — item names/PNs are shown in the UI from the
    # items list / PL annotate preview; repeating them in instruction text is noise.
    _ = bom

    torques = [str(t).strip() for t in (note.get("torque") or []) if str(t).strip()]
    if torques and not any(t.upper() in blob for t in torques):
        extras.append("Torque: " + ", ".join(torques) + ".")

    conns: list[str] = []
    for c in note.get("connectors") or []:
        ref = str(c).strip().upper()
        if ref and ref not in blob and ref not in conns:
            conns.append(ref)
    if conns:
        extras.append("Connectors: " + ", ".join(conns) + ".")

    standards = [str(s).strip() for s in (note.get("standards") or []) if str(s).strip()]
    missing_std = [s for s in standards if s.upper() not in blob]
    if missing_std:
        extras.append("Standard: " + ", ".join(missing_std) + ".")

    # Relative placement without inventing mm (Stage B / CPU placement may already be in base)
    if note.get("placement") and "BELOW ITEM" not in blob and "ON THE" not in blob:
        rel_bits: list[str] = []
        for p in note.get("placement") or []:
            if not isinstance(p, dict):
                continue
            try:
                it = int(p.get("itemNo") or 0)
            except (TypeError, ValueError):
                continue
            if it <= 0:
                continue
            surf = str(p.get("surface") or "").strip()
            offs = p.get("offsets") or []
            rel = next((o for o in offs if isinstance(o, dict) and o.get("from") == "item"), None)
            if rel and rel.get("relativeToItem") is not None:
                relation = rel.get("relation") or "below"
                bit = f"Item {it} {relation} Item {rel['relativeToItem']}"
                if surf:
                    bit += f" on {surf}"
                if bit.upper() not in blob:
                    rel_bits.append(bit)
            elif surf and f"ITEM {it}" in blob and surf.upper() not in blob:
                rel_bits.append(f"Item {it} on {surf}")
        if rel_bits:
            extras.append("Placement: " + "; ".join(rel_bits) + ".")

    if not extras:
        # Keep prior grounded elaboration; otherwise leave blank when nothing added
        prior = re.sub(r"\s+", " ", str(note.get("elaboratedText") or "")).strip()
        if prior and prior != raw:
            return prior
        return prior or ""
    return f"{base} {' '.join(extras)}".strip()


def note_is_enriched(note: dict) -> bool:
    """True when elaboratedText adds grounded content beyond the raw drawing note."""
    raw = re.sub(r"\s+", " ", str(note.get("text") or "")).strip().lower()
    elab = re.sub(r"\s+", " ", str(note.get("elaboratedText") or "")).strip().lower()
    if not elab:
        return False
    if elab == raw:
        return False
    if raw and (raw in elab or raw[:80] in elab):
        return True
    return bool(note.get("placement") or note.get("viewRefs") or note.get("insight"))


def apply_grounded_elaboration(
    notes: list[dict[str, Any]],
    *,
    ga_extraction: dict | None = None,
    parts_list: dict | None = None,
    unit: str = "mm",
    engine: str = "cpu_spatial",
) -> list[dict[str, Any]]:
    """Run torque/connector/placement enrichment on every note; set elaborated flag.

    Does not append Parts: lines (UI shows item names separately). Sanitizes
    elaboratedText for operator-facing chrome junk.
    """
    from app.route_card.extractor import sanitize_operator_instruction

    bom = bom_index(ga_extraction, parts_list)
    out: list[dict[str, Any]] = []
    for note in notes or []:
        nn = dict(note)
        raw = re.sub(r"\s+", " ", str(nn.get("text") or "")).strip()
        enriched = elaborate_note_cpu(nn, bom, unit)
        added = bool(enriched and enriched != raw)
        if added:
            nn["elaboratedText"] = enriched
            nn["mindEngine"] = nn.get("mindEngine") or engine
        elab = (nn.get("elaboratedText") or "").strip()
        if elab:
            cleaned = sanitize_operator_instruction(elab)
            if cleaned:
                nn["elaboratedText"] = cleaned
        # Mark before/after sanitize — sentence-case can rewrite ITEM→Item No.
        # and break raw⊂elab matching in note_is_enriched / generate_route.
        if added or note_is_enriched(nn) or (nn.get("insight") or "").strip():
            nn["elaborated"] = True
        out.append(nn)
    return out


def needs_placement_elaboration(text: str, items: list | None = None) -> bool:
    """Whether a note should get spatial / Stage-B placement treatment."""
    t = text or ""
    has_items = bool(items)
    return bool(PLACEMENT_VERB.search(t) and (AS_SHOWN.search(t) or has_items))


def needs_stage_b_vision(text: str) -> bool:
    """AS SHOWN / PLACE / DETAIL / isometric-style cues that benefit from full-page vision."""
    t = text or ""
    if AS_SHOWN.search(t):
        return True
    return bool(
        re.search(
            r"\b(AS\s+INDICATED|SEE\s+(?:DETAIL|VIEW|FIG)|PLACE|DETAIL|ISOMETRIC|AS\s+PER\s+VIEW)\b",
            t,
            re.I,
        )
    )


def placement_verb(text: str) -> str:
    """Operator verb from a drawing note (Stick / Place / …)."""
    m = PLACEMENT_VERB.search(text or "")
    if not m:
        return "Stick"
    raw = m.group(1).upper()
    mapping = {
        "STICK": "Stick",
        "PASTE": "Paste",
        "GLUE": "Glue",
        "BOND": "Bond",
        "ADHERE": "Adhere",
        "APPLY": "Apply",
        "MOUNT": "Mount",
        "PLACE": "Place",
        "FIT": "Fit",
        "INSTALL": "Install",
        "ASSEMBLE": "Assemble",
        "FIX": "Fix",
        "ENGAGE": "Engage",
        "MATE": "Mate",
        "TIGHTEN": "Tighten",
    }
    return mapping.get(raw, raw.title())


# Named port faces (DC OUT…) may print at moderate confidence; bare-ish FRONT/REAR
# face labels need a stronger hit so we do not invent a side from a view title.
_SURFACE_CONF_PORT = 0.55
_SURFACE_CONF_FRONT_REAR = 0.75
_FRONT_REAR_FACE = re.compile(r"\b(FRONT|REAR)\b", re.I)
_FIGURE_FALLBACK = "as indicated in the figure"


def surface_confidence_threshold(surface: str) -> float:
    """Minimum placement confidence required before naming this face in ops."""
    if _FRONT_REAR_FACE.search(surface or ""):
        return _SURFACE_CONF_FRONT_REAR
    return _SURFACE_CONF_PORT


def _surface_side_phrase(
    surface: str,
    *,
    confidence: float | None = None,
) -> str:
    """Operator face phrase only for strong labels at high enough confidence.

    Bare FRONT / REAR / view titles never print. FRONT FACE / REAR FACE need
    higher confidence than named ports (DC OUT, AC IN, …).
    """
    from app.route_card.drawing_mind.spatial import is_strong_mounting_surface

    surf = re.sub(r"\s+", " ", (surface or "").strip())
    if not surf or not is_strong_mounting_surface(surf):
        return ""
    conf = 1.0 if confidence is None else float(confidence)
    if conf < surface_confidence_threshold(surf):
        return ""
    if re.search(r"\b(SIDE|FACE|SURFACE|PANEL)\b", surf, re.I):
        return f"on the {surf}"
    return f"on the {surf} side"


def _figure_ref_phrase(view_used: str = "", view_refs: list[Any] | None = None) -> str:
    """Fallback location when no high-confidence face label is available."""
    label = re.sub(r"\s+", " ", (view_used or "").strip())
    if not label and view_refs:
        for ref in view_refs:
            if isinstance(ref, dict):
                label = str(
                    ref.get("label")
                    or ref.get("figure")
                    or ref.get("view")
                    or ref.get("name")
                    or ""
                ).strip()
            else:
                label = str(ref or "").strip()
            if label:
                break
    if label:
        # Avoid "figure FIGURE A" duplication
        if re.search(r"\b(figure|fig\.?|view|detail)\b", label, re.I):
            return f"as indicated in the {label}"
        return f"as indicated in the figure ({label})"
    return _FIGURE_FALLBACK


def _placement_dict(p: Any) -> dict[str, Any] | None:
    if isinstance(p, dict):
        return p
    if hasattr(p, "to_dict"):
        try:
            d = p.to_dict()
            return d if isinstance(d, dict) else None
        except Exception:
            return None
    return None


def _sentence_for_placement(
    placement: dict[str, Any],
    *,
    verb: str = "Stick",
    unit: str = "mm",
    host_item_no: int | None = None,
    view_used: str = "",
    view_refs: list[Any] | None = None,
) -> str:
    """One operator line from a grounded placement fact (no invented sizes)."""
    try:
        it = int(placement.get("itemNo") or 0)
    except (TypeError, ValueError):
        return ""
    if it <= 0:
        return ""
    action = (verb or "Stick").capitalize()
    try:
        conf = float(placement.get("confidence")) if placement.get("confidence") is not None else None
    except (TypeError, ValueError):
        conf = None
    face = _surface_side_phrase(str(placement.get("surface") or ""), confidence=conf)
    figure = "" if face else _figure_ref_phrase(view_used, view_refs)
    offsets = [o for o in (placement.get("offsets") or []) if isinstance(o, dict)]
    host_bit = f", on item {host_item_no}" if host_item_no else ""
    rel_words = {
        "below": "below",
        "above": "above",
        "left_of": "to the left of",
        "right_of": "to the right of",
    }

    def _head() -> str:
        h = f"{action} Item {it}"
        if face:
            return f"{h} {face}"
        if figure:
            return f"{h} {figure}"
        return h

    rel = next((o for o in offsets if o.get("from") == "item"), None)
    if rel:
        prev = rel.get("relativeToItem")
        val = rel.get("value")
        relation = rel_words.get(str(rel.get("relation") or "below").lower(), "below")
        head = _head()
        align = ""
        if rel.get("alignedLeft") or any(o.get("from") == "left" for o in offsets):
            align = ", left-aligned"
        if val is not None:
            body = f"{val:g} {unit} {relation} Item {prev}{align}"
        else:
            body = f"{relation} Item {prev}{align}"
        return f"{head}, {body}{host_bit}."
    top = next((o for o in offsets if o.get("from") == "top"), None)
    left = next((o for o in offsets if o.get("from") == "left"), None)
    right = next((o for o in offsets if o.get("from") == "right"), None)
    bottom = next((o for o in offsets if o.get("from") == "bottom"), None)
    head = _head()
    bits: list[str] = []
    if top and top.get("value") is not None:
        bits.append(f"keep {top['value']:g} {unit} gap from the top edge")
    if bottom and bottom.get("value") is not None:
        bits.append(f"keep {bottom['value']:g} {unit} gap from the bottom edge")
    if left and left.get("value") is not None:
        bits.append(f"keep {left['value']:g} {unit} gap from the left edge")
    if right and right.get("value") is not None:
        bits.append(f"keep {right['value']:g} {unit} gap from the right edge")
    if bits:
        return f"{head}, " + ", ".join(bits) + f"{host_bit}."
    if face or figure:
        return f"{head}{host_bit}."
    return f"{head} {_FIGURE_FALLBACK}{host_bit}."


def compose_placement_elaboration(
    raw_note: str,
    placements: list[Any] | None,
    *,
    host_item_no: int | None = None,
    unit: str = "mm",
    view_used: str = "",
    view_refs: list[Any] | None = None,
) -> str:
    """Club note verb + measured placements (+ optional host body) into operator text."""
    rows: list[dict[str, Any]] = []
    for p in placements or []:
        d = _placement_dict(p)
        if d:
            rows.append(d)
    if not rows:
        return ""
    verb = placement_verb(raw_note)
    try:
        host = int(host_item_no) if host_item_no is not None else None
    except (TypeError, ValueError):
        host = None
    if host is not None and host <= 0:
        host = None
    unit = unit or "mm"
    refs = list(view_refs or [])
    sentences = [
        _sentence_for_placement(
            p,
            verb=verb,
            unit=unit,
            host_item_no=host,
            view_used=view_used,
            view_refs=refs,
        )
        for p in rows
    ]
    sentences = [s for s in sentences if s]
    if not sentences:
        return ""
    parts = list(sentences)
    if re.search(r"adhesive|glue|stick|paste|bond", raw_note or "", re.I):
        adhesive = "Use proper adhesive (glue)."
        if adhesive.lower() not in " ".join(parts).lower():
            parts.append(adhesive)
    text = " ".join(parts).strip()
    if unit and "size" not in text.lower() and "dimension" not in text.lower():
        text = f"{text} (All sizes are in {unit}.)"
    return text.strip()
