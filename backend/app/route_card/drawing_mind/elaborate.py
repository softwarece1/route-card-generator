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
