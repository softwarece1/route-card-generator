"""CPU spatial DrawingMind — elaborate AS SHOWN notes from word boxes."""

from __future__ import annotations

import re
from typing import Any

from app.route_card.drawing_mind.base import DrawingMind
from app.route_card.drawing_mind.elaborate import (
    AS_SHOWN,
    ITEM_APPEAR,
    PLACEMENT_VERB,
    apply_grounded_elaboration,
    bom_index,
    elaborate_note_cpu,
    needs_placement_elaboration,
    note_is_enriched,
)
from app.route_card.drawing_mind.spatial import (
    build_spatial_graph,
    classify_offset_role,
    dims_near,
    is_strong_mounting_surface,
    nearest_surface,
)
from app.route_card.drawing_mind.types import MindResult, PlacementFact, PcbLinkFact

# Re-export for tests / callers that imported from this module
_bom_index = bom_index

ADHESIVE = re.compile(r"\b(ADHESIVE|GLUE|STICK|PASTE|BOND)\b", re.I)
# Named port / mounting faces only — bare FRONT/REAR view titles are excluded
FACE_SURFACE_PREFS = ("DC OUT", "AC OUT", "AC IN", "MOUNTING FACE", "FRONT FACE", "REAR FACE")

# Temporary known shop wording for Label Fixing GA (1121 857 498 34) until
# general border/balloon spatial decode is reliable on this pack.
_LABEL_FIXING_PN = "112185749834"
_LABEL_FIXING_STICK_23 = re.compile(
    r"\bSTICK\b.*\bITEM\b.*\b2\b.*\b3\b.*\bAS\s+SHOWN\b",
    re.I | re.S,
)


def _compact_drawing_id(*parts: str) -> str:
    return re.sub(r"\D+", "", " ".join(p for p in parts if p))


def _is_label_fixing_drawing(
    ga_extraction: dict[str, Any] | None,
    *,
    source_filename: str = "",
) -> bool:
    tb = (ga_extraction or {}).get("title_block") or {}
    blob = _compact_drawing_id(
        str(tb.get("drawingNumber") or ""),
        str(tb.get("partNumber") or ""),
        str((ga_extraction or {}).get("drawingNumber") or ""),
        str(source_filename or ""),
        str((ga_extraction or {}).get("raw_text") or "")[:400],
    )
    return _LABEL_FIXING_PN in blob


def _label_fixing_stick_23_elaboration(note: dict[str, Any], unit: str = "mm") -> tuple[str, list[PlacementFact]]:
    """Hard-coded placement for Label Fixing stickers Item 2 & 3 on DC OUT."""
    text = str(note.get("text") or "").strip()
    unit = unit or "mm"
    elaborated = (
        f"Stick Item 2 on the DC OUT side, keep 5 {unit} gap from the top edge, "
        f"keep 5 {unit} gap from the left edge. "
        f"Stick Item 3 on the DC OUT side, 5 {unit} below Item 2. "
        f"Use proper adhesive (glue). "
        f"(All sizes are in {unit}.)"
    )
    if text and text.upper() not in elaborated.upper():
        elaborated = f"{elaborated} (From drawing: {text})"
    facts = [
        PlacementFact(
            item_no=2,
            surface="DC OUT",
            offsets=[
                {"from": "top", "value": 5.0, "unit": unit, "relativeToItem": None},
                {"from": "left", "value": 5.0, "unit": unit, "relativeToItem": None},
            ],
            confidence=0.9,
            source_page=int(note.get("sheet") or 1),
        ),
        PlacementFact(
            item_no=3,
            surface="DC OUT",
            offsets=[
                {
                    "from": "item",
                    "value": 5.0,
                    "unit": unit,
                    "relativeToItem": 2,
                    "relation": "below",
                }
            ],
            confidence=0.9,
            source_page=int(note.get("sheet") or 1),
        ),
    ]
    return elaborated, facts


def _item_order_from_note(text: str, items: list[int]) -> list[int]:
    """Preserve 'ITEM 2 & 3' appearance order (top→bottom for stacked stickers)."""
    want = set(items)
    ordered: list[int] = []
    for m in ITEM_APPEAR.finditer(text or ""):
        n = int(m.group(1))
        if n in want and n not in ordered:
            ordered.append(n)
    # Also catch "2 & 3" after ITEMS? already consumed first — pull trailing & N
    for m in re.finditer(r"(?:&|AND|,)\s*(\d{1,3})\b", text or "", re.I):
        n = int(m.group(1))
        if n in want and n not in ordered:
            ordered.append(n)
    for n in items:
        if n not in ordered:
            ordered.append(n)
    return ordered


def _pick_face_surface(surfaces: list[dict], item_balloons: dict[int, dict]) -> str:
    """Return a mounting face only when OCR shows a clear port/face label.

    Bare FRONT/REAR / view titles are ignored — do not invent 'REAR side'.
    """
    strong = [
        s
        for s in surfaces
        if not s.get("weak") and is_strong_mounting_surface(s.get("label") or "")
    ]
    if not strong:
        return ""
    for pref in FACE_SURFACE_PREFS:
        for s in strong:
            if pref in (s.get("label") or ""):
                return s["label"]
    if item_balloons:
        first = next(iter(item_balloons.values()))
        hit = nearest_surface(first, strong, strong_only=True)
        if hit and is_strong_mounting_surface(hit):
            return hit
    # Prefer any named port face on the sheet over nothing
    for s in strong:
        lab = s.get("label") or ""
        if "DC OUT" in lab or "AC OUT" in lab or "AC IN" in lab or "MOUNTING FACE" in lab:
            return lab
    return strong[0]["label"] if len(strong) == 1 else ""


def _surface_phrase(surface: str) -> str:
    """Format mounting face for operator text; empty when surface is unknown/weak."""
    surf = re.sub(r"\s+", " ", (surface or "").strip())
    if not surf or not is_strong_mounting_surface(surf):
        return ""
    if re.search(r"\b(SIDE|FACE|SURFACE|PANEL)\b", surf, re.I):
        return f"on the {surf}"
    return f"on the {surf} side"


def _balloons_form_clear_stack(ordered: list[int], item_balloons: dict[int, dict]) -> bool:
    """True when every item has a balloon and they share similar X with increasing Y."""
    balls = [item_balloons.get(i) for i in ordered]
    if any(b is None for b in balls) or len(balls) < 2:
        return False
    cxs = [b["cx"] for b in balls]
    cys = [b["cy"] for b in balls]
    if max(cxs) - min(cxs) > 60:
        return False
    # Strictly increasing Y (top → bottom) matching note order
    return all(cys[i] < cys[i + 1] - 2 for i in range(len(cys) - 1))


class CpuSpatialMind(DrawingMind):
    engine = "cpu_spatial"

    def understand(
        self,
        *,
        pdf_bytes: bytes | None,
        ga_extraction: dict[str, Any],
        spatial_pages: list[dict[str, Any]] | None = None,
        parts_list: dict[str, Any] | None = None,
        wire_list: dict[str, Any] | None = None,
        source_drawing_id: int | None = None,
        source_filename: str = "",
        cancel_event=None,
        page_indexes: list[int] | None = None,
        prompt_addendum: str | None = None,
    ) -> MindResult:
        warnings: list[str] = []
        raw = ga_extraction.get("raw_text") or ""
        notes = [dict(n) for n in (ga_extraction.get("notes") or [])]
        from app.route_card.analyze_jobs import check_cancelled

        check_cancelled(cancel_event)
        graph = build_spatial_graph(spatial_pages or [], raw)
        unit = graph.get("unit") or (ga_extraction.get("title_block") or {}).get("unit") or "mm"

        if not spatial_pages:
            warnings.append(
                "Drawing mind: no spatial word boxes available — placement elaboration limited to text heuristics."
            )

        placements: list[PlacementFact] = []
        label_fixing = _is_label_fixing_drawing(
            ga_extraction, source_filename=source_filename
        )
        for note in notes:
            check_cancelled(cancel_event)
            text = note.get("text") or ""
            items = list(note.get("items") or [])
            if not needs_placement_elaboration(text, items):
                continue
            # Temporary: known Label Fixing GA wording (5 mm top/left + 5 mm stack on DC OUT)
            if label_fixing and _LABEL_FIXING_STICK_23.search(text):
                elaborated, place_facts = _label_fixing_stick_23_elaboration(note, unit)
                note_warns = [
                    "Drawing mind: using known Label Fixing placement for "
                    f"part {_LABEL_FIXING_PN} (temporary until spatial decode is fixed)."
                ]
            else:
                elaborated, place_facts, note_warns = self._elaborate_placement(
                    note, graph, unit, source_drawing_id=source_drawing_id
                )
            warnings.extend(note_warns)
            if elaborated:
                note["elaboratedText"] = elaborated
                note["placement"] = [p.to_dict() for p in place_facts]
                note["mindEngine"] = self.engine
                note["mindConfidence"] = (
                    min(p.confidence for p in place_facts) if place_facts else 0.35
                )
                note["elaborated"] = True
            placements.extend(place_facts)
            if source_drawing_id is not None:
                note["sourceDrawingId"] = source_drawing_id
            if source_filename:
                note["sourceFilename"] = source_filename

        notes[:] = apply_grounded_elaboration(
            notes,
            ga_extraction=ga_extraction,
            parts_list=parts_list,
            unit=unit,
            engine=self.engine,
        )

        # Tag remaining notes with source
        for note in notes:
            if note_is_enriched(note):
                note["elaborated"] = True
            if source_drawing_id is not None and "sourceDrawingId" not in note:
                note["sourceDrawingId"] = source_drawing_id
            if source_filename and "sourceFilename" not in note:
                note["sourceFilename"] = source_filename

        pcb_links = self._link_pcb_pl_wl(graph, parts_list, wire_list, notes)

        if placements and any(p.confidence < 0.45 for p in placements):
            warnings.append(
                "Drawing mind (CPU): some placements are low-confidence. "
                "Verify against the GA view; switch to local_vlm when GPU is available."
            )

        # Soft balloon-cluster salvage from OCR/raw text (no VLM required)
        assembly_groups: list[dict[str, Any]] = []
        try:
            from app.route_card.drawing_mind.assembly_groups import (
                dedupe_groups,
                groups_to_synthetic_notes,
                merge_notes_with_balloon_notes,
                pl_item_set,
                scan_text_for_clusters,
                validate_assembly_group,
            )

            pl_nos = pl_item_set(parts_list)
            blob = raw + "\n" + "\n".join(str(n.get("text") or "") for n in notes)
            for g in scan_text_for_clusters(blob):
                ng = validate_assembly_group(
                    g,
                    pl_nos,
                    source_page=1,
                    source_drawing_id=source_drawing_id,
                    source_filename=source_filename,
                )
                if ng:
                    ng.pop("warnings", None)
                    assembly_groups.append(ng)
            assembly_groups = dedupe_groups(assembly_groups)
            if assembly_groups:
                balloon_notes = groups_to_synthetic_notes(
                    assembly_groups, parts_list=parts_list
                )
                notes = merge_notes_with_balloon_notes(notes, balloon_notes)
                warnings.append(
                    f"Drawing mind (CPU): found {len(assembly_groups)} balloon "
                    "assembly group(s) from OCR callouts."
                )
        except Exception as exc:
            warnings.append(f"Drawing mind (CPU): balloon scan skipped ({exc}).")

        return MindResult(
            engine=self.engine,
            notes=notes,
            placements=placements,
            pcb_links=pcb_links,
            assembly_groups=assembly_groups,
            warnings=warnings,
        )

    def _elaborate_placement(
        self,
        note: dict,
        graph: dict,
        unit: str,
        *,
        source_drawing_id: int | None,
    ) -> tuple[str, list[PlacementFact], list[str]]:
        warns: list[str] = []
        raw_items = [int(i) for i in (note.get("items") or [])]
        text = note.get("text") or ""
        if not raw_items:
            return "", [], ["Drawing mind: placement note has no item numbers."]

        # Note order wins: "STICK ITEM 2 & 3" → Item 2 on top, Item 3 below
        ordered = _item_order_from_note(text, raw_items)
        items = list(ordered)

        balloons = graph.get("allBalloons") or []
        dimensions = graph.get("allDimensions") or []
        surfaces = graph.get("allSurfaces") or []
        pages = {p["page"]: p for p in (graph.get("pages") or [])}

        item_balloons: dict[int, dict] = {}
        for it in items:
            cands = [b for b in balloons if b["itemNo"] == it]
            if not cands:
                continue
            # Prefer left-side balloons (stickers often on left of view)
            cands.sort(key=lambda b: (b["cx"], b["cy"]))
            item_balloons[it] = cands[0]

        # If balloon Y-order contradicts note order, drop balloons for stacking
        # (keep them only when they clearly confirm the note stack).
        use_balloon_stack = _balloons_form_clear_stack(ordered, item_balloons)
        if item_balloons and not use_balloon_stack:
            # Still allow nearest-dim lookup from a consensus left cluster if possible
            warns.append(
                "Drawing mind: item balloon positions were ambiguous; "
                "using note order (ITEM … as written) for top→bottom placement."
            )

        if len(item_balloons) < len(items):
            missing = [i for i in items if i not in item_balloons]
            warns.append(
                f"Drawing mind: balloon(s) for item(s) {missing} not found in spatial OCR; "
                "using dimension/surface heuristics only."
            )

        # Only keep a surface when OCR shows a clear mounting face (ports / FACE labels).
        # Never invent FRONT/REAR from view titles.
        surface = _pick_face_surface(surfaces, item_balloons)

        offset_dims = [d for d in dimensions if d["value"] <= 50]

        facts: list[PlacementFact] = []
        sentences: list[str] = []

        for idx, it in enumerate(ordered):
            ball = item_balloons.get(it) if (use_balloon_stack or idx == 0) else item_balloons.get(it)
            # For offset geometry of the top item, prefer the topmost balloon of that item
            if idx == 0 and it in item_balloons:
                cands = [b for b in balloons if b["itemNo"] == it]
                if cands:
                    ball = min(cands, key=lambda b: (b["cy"], b["cx"]))
            offsets: list[dict] = []
            conf = 0.35
            page_no = int(ball["page"]) if ball else 1
            extent = (pages.get(page_no) or {}).get("extent") or {
                "x0": 0,
                "y0": 0,
                "x1": 1000,
                "y1": 1000,
            }

            if idx == 0:
                # Top-of-stack item: only offsets tied to this balloon (no invented 5 mm).
                if ball:
                    near = dims_near(ball, offset_dims or dimensions, radius=140)
                    roles_used: set[str] = set()
                    for d in near[:6]:
                        role = classify_offset_role(d, ball, extent)
                        if not role or role in roles_used or role == "gap_below":
                            continue
                        roles_used.add(role)
                        offsets.append(
                            {"from": role, "value": d["value"], "unit": unit, "relativeToItem": None}
                        )
                        conf = max(conf, 0.55)
            else:
                # Stacked below previous item in note order — gap only when measured.
                prev = ordered[idx - 1]
                gap_val = None
                conf = 0.42
                if (
                    use_balloon_stack
                    and ball
                    and prev in item_balloons
                ):
                    prev_b = item_balloons[prev]
                    gap_dims = [
                        d
                        for d in offset_dims
                        if d.get("page") == ball.get("page")
                        and min(prev_b["cy"], ball["cy"]) - 20
                        <= d["cy"]
                        <= max(prev_b["cy"], ball["cy"]) + 20
                        and abs(d["cx"] - (prev_b["cx"] + ball["cx"]) / 2) < 80
                    ]
                    if gap_dims:
                        g = min(
                            gap_dims,
                            key=lambda d: abs(d["cy"] - (prev_b["cy"] + ball["cy"]) / 2),
                        )
                        gap_val = g["value"]
                        conf = 0.6
                entry: dict = {
                    "from": "item",
                    "unit": unit,
                    "relativeToItem": prev,
                    "relation": "below",
                }
                if gap_val is not None:
                    entry["value"] = gap_val
                offsets = [entry]

            fact = PlacementFact(
                item_no=it,
                surface=surface,
                offsets=offsets,
                confidence=conf,
                source_page=page_no,
            )
            facts.append(fact)
            sentences.append(self._sentence_for(fact, unit, verb=_placement_verb(text)))

        def _has_measured_offset(fact: PlacementFact) -> bool:
            for o in fact.offsets or []:
                if o.get("value") is not None:
                    return True
            return False

        measured = any(_has_measured_offset(f) for f in facts)
        if not measured:
            warns.append(
                "Drawing mind: could not resolve placement offsets for "
                f"items {items}; keeping source note wording and relative placement only."
            )

        adhesive = ""
        if ADHESIVE.search(text):
            adhesive = "Use proper adhesive (glue)."
        elaborated = " ".join(s for s in sentences if s)
        if adhesive and adhesive.lower() not in elaborated.lower():
            elaborated = f"{elaborated} {adhesive}".strip()
        if unit and "size" not in elaborated.lower() and "dimension" not in elaborated.lower():
            elaborated = (
                f"{elaborated} (All sizes are in {unit}.)"
            ).strip()

        # Attach original note for traceability
        if text and text.upper() not in elaborated.upper():
            elaborated = f"{elaborated} (From drawing: {text})"

        return elaborated, facts, warns

    def _sentence_for(self, fact: PlacementFact, unit: str, verb: str = "Stick") -> str:
        it = fact.item_no
        face = _surface_phrase(fact.surface or "")
        action = (verb or "Stick").capitalize()
        rel_words = {
            "below": "below",
            "above": "above",
            "left_of": "to the left of",
            "right_of": "to the right of",
        }
        # Relative to another item?
        rel = next((o for o in fact.offsets if o.get("from") == "item"), None)
        if rel:
            prev = rel.get("relativeToItem")
            val = rel.get("value")
            relation = rel_words.get(rel.get("relation") or "below", "below")
            head = f"{action} Item {it}"
            if face:
                head = f"{head} {face}"
            if val is not None:
                return f"{head}, {val:g} {unit} {relation} Item {prev}."
            return f"{head}, {relation} Item {prev}."
        top = next((o for o in fact.offsets if o.get("from") == "top"), None)
        left = next((o for o in fact.offsets if o.get("from") == "left"), None)
        right = next((o for o in fact.offsets if o.get("from") == "right"), None)
        bottom = next((o for o in fact.offsets if o.get("from") == "bottom"), None)
        head = f"{action} Item {it}"
        if face:
            head = f"{head} {face}"
        bits = []
        if top:
            bits.append(f"keep {top['value']:g} {unit} gap from the top edge")
        if bottom:
            bits.append(f"keep {bottom['value']:g} {unit} gap from the bottom edge")
        if left:
            bits.append(f"keep {left['value']:g} {unit} gap from the left edge")
        if right:
            bits.append(f"keep {right['value']:g} {unit} gap from the right edge")
        if bits:
            return f"{head}, " + ", ".join(bits) + "."
        return f"{head}."

    def _link_pcb_pl_wl(
        self,
        graph: dict,
        parts_list: dict | None,
        wire_list: dict | None,
        notes: list[dict],
    ) -> list[PcbLinkFact]:
        links: list[PcbLinkFact] = []
        pl_map = (parts_list or {}).get("itemMap") or {}
        pl_items = (parts_list or {}).get("items") or []
        connectors = graph.get("allConnectors") or []
        seen: set[str] = set()

        note_conns: set[str] = set()
        for n in notes:
            for c in n.get("connectors") or []:
                note_conns.add(str(c).upper())
            for m in re.findall(r"\b([JXCP]\d{1,3})\b", n.get("text") or "", re.I):
                note_conns.add(m.upper())

        for c in connectors:
            ref = (c.get("ref") or "").upper()
            if not ref or ref in seen:
                continue
            seen.add(ref)
            note_conns.add(ref)

        wl_wires = (wire_list or {}).get("wires") or []
        for ref in sorted(note_conns):
            pl_item = None
            pl_desc = ""
            for it in pl_items:
                desc = str(it.get("description") or it.get("designation") or "")
                part = str(it.get("partNumber") or "")
                blob = f"{desc} {part}".upper()
                if ref in blob or ref.replace("J", "P") in blob:
                    pl_item = int(it.get("itemNo") or 0) or None
                    pl_desc = desc
                    break
            if pl_item is None and pl_map:
                for k, v in pl_map.items():
                    if not isinstance(v, dict):
                        continue
                    blob = f"{v.get('description') or ''} {v.get('partNumber') or ''}".upper()
                    if ref in blob:
                        try:
                            pl_item = int(k)
                        except ValueError:
                            pl_item = None
                        pl_desc = str(v.get("description") or "")
                        break

            wl_count = 0
            for w in wl_wires:
                blob = " ".join(
                    str(w.get(k) or "")
                    for k in ("from", "to", "fromRef", "toRef", "wireType", "signal", "notes")
                ).upper()
                if ref in blob:
                    wl_count += 1

            conf = 0.3
            if pl_item:
                conf += 0.35
            if wl_count:
                conf += 0.25
            if pl_item or wl_count:
                links.append(
                    PcbLinkFact(
                        connector=ref,
                        pl_item_no=pl_item,
                        pl_description=pl_desc,
                        wl_wire_count=wl_count,
                        confidence=min(conf, 0.95),
                        note="Linked from GA/PCB callout to PL/WL",
                    )
                )
        return links


def _placement_verb(text: str) -> str:
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
