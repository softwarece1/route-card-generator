"""Merge multi-GA extractions and resolve drawing cross-references."""

from __future__ import annotations

import re
from typing import Any

from app.route_card.drawing_mind.types import CrossRefFact
from app.route_card.drawing_mind.view_refs import resolve_view_refs_for_notes

DRAWING_NO_SPACED = re.compile(r"\b(\d{4})\s+(\d{3})\s+(\d{3})\s+(\d{2})\b")
DRAWING_NO_COMPACT = re.compile(r"\b(\d{12,14})\b")
REFER_GA = re.compile(
    r"(?:REFER|SEE|REF\.?)\s+(?:GA|DRG|DWG|DRAWING)?\s*"
    r"(?:NO\.?|#)?\s*:?\s*(\d{4}\s*\d{3}\s*\d{3}\s*\d{2}|\d{12,14})",
    re.I,
)


def normalize_drawing_no(raw: str) -> str:
    digits = re.sub(r"\D", "", raw or "")
    if len(digits) >= 12:
        return f"{digits[0:4]} {digits[4:7]} {digits[7:10]} {digits[10:12]}"
    return re.sub(r"\s+", " ", (raw or "").strip())


def extract_referenced_drawing_nos(text: str, self_no: str = "") -> list[str]:
    found: list[str] = []
    self_norm = normalize_drawing_no(self_no)
    for m in REFER_GA.finditer(text or ""):
        n = normalize_drawing_no(m.group(1))
        if n and n != self_norm and n not in found:
            found.append(n)
    for m in DRAWING_NO_SPACED.finditer(text or ""):
        n = f"{m.group(1)} {m.group(2)} {m.group(3)} {m.group(4)}"
        if n != self_norm and n not in found:
            # Skip if it's clearly in a title-block-only context without REFER — keep spaced hits
            # that appear near REFER/SEE/GA language in a window
            start = max(0, m.start() - 40)
            window = (text or "")[start : m.end() + 10].upper()
            if any(k in window for k in ("REFER", "SEE ", "REF.", "GA ", "NEXT ASSY", "RELATED")):
                found.append(n)
    return found


def resolve_cross_refs(
    ga_results: list[dict[str, Any]],
) -> list[CrossRefFact]:
    """
    ga_results: [{ drawingId, filename, drawingNumber, references, rawText, notes }]
    """
    by_no: dict[str, dict] = {}
    for g in ga_results:
        dn = normalize_drawing_no(
            g.get("drawingNumber") or (g.get("title_block") or {}).get("drawingNumber") or ""
        )
        if dn:
            by_no[dn] = g
            by_no[re.sub(r"\s+", "", dn)] = g

    facts: list[CrossRefFact] = []
    seen: set[tuple[str, int | None]] = set()
    for g in ga_results:
        self_no = normalize_drawing_no(
            g.get("drawingNumber") or (g.get("title_block") or {}).get("drawingNumber") or ""
        )
        blob_parts = [
            g.get("rawText") or "",
            " ".join(str(r) for r in (g.get("references") or [])),
            " ".join((n.get("text") or "") for n in (g.get("notes") or [])),
        ]
        blob = "\n".join(blob_parts)
        refs = extract_referenced_drawing_nos(blob, self_no)
        # Also from structured references list
        for r in g.get("references") or []:
            n = normalize_drawing_no(str(r))
            if n and n != self_no and n not in refs and re.search(r"\d{4}", n):
                refs.append(n)

        src_id = g.get("drawingId")
        for ref in refs:
            key = (ref, src_id)
            if key in seen:
                continue
            seen.add(key)
            match = by_no.get(ref) or by_no.get(re.sub(r"\s+", "", ref))
            if match:
                facts.append(
                    CrossRefFact(
                        drawing_number=ref,
                        status="resolved",
                        source_drawing_id=src_id,
                        matched_drawing_id=match.get("drawingId"),
                        matched_filename=match.get("filename") or "",
                    )
                )
            else:
                facts.append(
                    CrossRefFact(
                        drawing_number=ref,
                        status="missing",
                        source_drawing_id=src_id,
                    )
                )
    return facts


def merge_ga_extractions(
    ga_results: list[dict[str, Any]],
) -> dict[str, Any]:
    """Merge notes/BOM/dims/refs from multiple GA parses into one extraction dict."""
    if not ga_results:
        return {
            "title_block": {},
            "notes": [],
            "bom_items": [],
            "revisions": [],
            "torque_specs": [],
            "dimensions": [],
            "references": [],
            "warnings": [],
            "raw_text": "",
            "pages": 0,
            "drawing_type": "unknown",
        }

    # Prefer the GA with most notes / assembly type as primary title
    primary = max(
        ga_results,
        key=lambda g: (
            1 if (g.get("drawing_type") == "assembly") else 0,
            len(g.get("notes") or []),
            len(g.get("raw_text") or ""),
        ),
    )
    title = dict(primary.get("title_block") or {})
    notes: list[dict] = []
    bom_by_item: dict[int, dict] = {}
    revisions: list[dict] = []
    torques: list[str] = []
    dimensions: list[dict] = []
    references: list[str] = []
    warnings: list[str] = []
    raw_parts: list[str] = []
    pages = 0
    drawing_type = primary.get("drawing_type") or "unknown"

    for g in ga_results:
        src_id = g.get("drawingId")
        src_fn = g.get("filename") or ""
        pages += int(g.get("pages") or 0)
        for n in g.get("notes") or []:
            nn = dict(n)
            nn.setdefault("sourceDrawingId", src_id)
            nn.setdefault("sourceFilename", src_fn)
            notes.append(nn)
        for b in g.get("bom_items") or []:
            try:
                ino = int(b.get("itemNo"))
            except (TypeError, ValueError):
                continue
            prev = bom_by_item.get(ino)
            if not prev or (b.get("description") and not prev.get("description")):
                bb = dict(b)
                bb["sourceDrawingId"] = src_id
                bom_by_item[ino] = bb
            elif prev and b.get("qty"):
                prev["qty"] = max(int(prev.get("qty") or 0), int(b.get("qty") or 0))
        for r in g.get("revisions") or []:
            if r not in revisions:
                revisions.append(r)
        for t in g.get("torque_specs") or []:
            if t not in torques:
                torques.append(t)
        for d in g.get("dimensions") or []:
            if d not in dimensions:
                dimensions.append(d)
        for r in g.get("references") or []:
            if r not in references:
                references.append(r)
        warnings.extend(g.get("warnings") or [])
        if g.get("raw_text"):
            raw_parts.append(f"--- GA {src_fn or src_id} ---\n{g['raw_text']}")
        if g.get("drawing_type") == "assembly":
            drawing_type = "assembly"

    cross = resolve_cross_refs(ga_results)
    for c in cross:
        if c.status == "missing":
            warnings.append(
                f"Referenced drawing {c.drawing_number} is not uploaded in this session "
                f"(referenced from drawing id {c.source_drawing_id})."
            )

    # FIGURE / SHEET / TABLE / DETAIL pointers across the GA set
    notes, view_facts, view_warns = resolve_view_refs_for_notes(notes, ga_results)
    warnings.extend(view_warns)

    # Index sheet numbers on gaSources for UI
    from app.route_card.drawing_mind.view_refs import catalog_sheet

    ga_sources = []
    for g in ga_results:
        cat = catalog_sheet(g)
        ga_sources.append(
            {
                "drawingId": g.get("drawingId"),
                "filename": g.get("filename"),
                "drawingNumber": normalize_drawing_no(
                    g.get("drawingNumber")
                    or (g.get("title_block") or {}).get("drawingNumber")
                    or ""
                ),
                "notesCount": len(g.get("notes") or []),
                "sheetNo": cat.sheet_no,
                "figures": sorted(cat.figures),
                "tables": sorted(cat.tables),
                "details": sorted(cat.details),
                "namedBlocks": sorted(cat.named),
            }
        )

    return {
        "title_block": title,
        "notes": notes,
        "bom_items": [bom_by_item[k] for k in sorted(bom_by_item)],
        "revisions": revisions,
        "torque_specs": torques,
        "dimensions": dimensions,
        "references": references,
        "warnings": list(dict.fromkeys(warnings)),
        "raw_text": "\n\n".join(raw_parts)[:200000],
        "pages": pages or primary.get("pages") or 1,
        "drawing_type": drawing_type,
        "crossRefs": [c.to_dict() for c in cross],
        "viewRefs": [v.to_dict() for v in view_facts],
        "gaSources": ga_sources,
    }
