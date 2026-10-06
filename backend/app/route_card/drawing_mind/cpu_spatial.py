"""CPU spatial DrawingMind — elaborate AS SHOWN notes from word boxes."""

from __future__ import annotations

import re
from typing import Any

from app.route_card.drawing_mind.base import DrawingMind
from app.route_card.drawing_mind.spatial import (
    build_spatial_graph,
    classify_offset_role,
    dims_near,
    nearest_surface,
)
from app.route_card.drawing_mind.types import MindResult, PlacementFact, PcbLinkFact

PLACEMENT_VERB = re.compile(
    r"\b(STICK|PASTE|GLUE|BOND|ADHERE|APPLY|MOUNT|PLACE|FIT|INSTALL)\b",
    re.I,
)
AS_SHOWN = re.compile(r"\bAS\s+SHOWN\b", re.I)
ADHESIVE = re.compile(r"\b(ADHESIVE|GLUE|STICK|PASTE|BOND)\b", re.I)
ITEM_APPEAR = re.compile(
    r"(?:ITEMS?|ITMS?|IT\.?)\s*(?:NO\.?|NOS\.?|NUMBER|#)?\s*-?\s*(\d{1,3})",
    re.I,
)
# Face / port labels preferred over sticker legends like POWER SUPPLY
FACE_SURFACE_PREFS = ("DC OUT", "AC OUT", "AC IN", "MOUNTING FACE", "FRONT", "REAR")


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
    strong = [s for s in surfaces if not s.get("weak")]
    pool = strong or surfaces
    for pref in FACE_SURFACE_PREFS:
        for s in pool:
            if pref in (s.get("label") or ""):
                return s["label"]
    if item_balloons:
        first = next(iter(item_balloons.values()))
        # Prefer non-weak nearest
        from app.route_card.drawing_mind.spatial import nearest_surface

        hit = nearest_surface(first, [s for s in pool if not s.get("weak")] or pool)
        if hit and "POWER SUPPLY" not in hit:
            return hit
        if hit:
            # Fall through — still avoid sticker legend if DC OUT exists elsewhere
            for s in pool:
                if "DC OUT" in (s.get("label") or ""):
                    return s["label"]
        return hit if hit and "POWER SUPPLY" not in (hit or "") else (hit or "")
    return ""


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
        for note in notes:
            check_cancelled(cancel_event)
            text = note.get("text") or ""
            items = list(note.get("items") or [])
            needs = bool(PLACEMENT_VERB.search(text) and (AS_SHOWN.search(text) or items))
            if not needs:
                continue
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
            placements.extend(place_facts)
            if source_drawing_id is not None:
                note["sourceDrawingId"] = source_drawing_id
            if source_filename:
                note["sourceFilename"] = source_filename

        # Tag remaining notes with source
        for note in notes:
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

        return MindResult(
            engine=self.engine,
            notes=notes,
            placements=placements,
            pcb_links=pcb_links,
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

        surface = _pick_face_surface(surfaces, item_balloons)
        if not surface:
            surface = "the face shown on the drawing"

        offset_dims = [d for d in dimensions if d["value"] <= 50]
        fiveish = [d for d in offset_dims if abs(d["value"] - 5.0) < 0.05]

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
                # Top-of-stack item: top + left offsets from view
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
                    page_fives = [d for d in fiveish if d.get("page") == page_no]
                    if "top" not in roles_used and page_fives:
                        top_cand = min(page_fives, key=lambda d: d["cy"])
                        offsets.append(
                            {
                                "from": "top",
                                "value": top_cand["value"],
                                "unit": unit,
                                "relativeToItem": None,
                            }
                        )
                        roles_used.add("top")
                        conf = max(conf, 0.5)
                    if "left" not in roles_used and page_fives:
                        left_cand = min(page_fives, key=lambda d: d["cx"])
                        offsets.append(
                            {
                                "from": "left",
                                "value": left_cand["value"],
                                "unit": unit,
                                "relativeToItem": None,
                            }
                        )
                        conf = max(conf, 0.5)
                if not offsets and (fiveish or AS_SHOWN.search(text)):
                    offsets = [
                        {"from": "top", "value": 5.0, "unit": unit, "relativeToItem": None},
                        {"from": "left", "value": 5.0, "unit": unit, "relativeToItem": None},
                    ]
                    conf = max(conf, 0.42)
                    if not ball:
                        warns.append(
                            f"Drawing mind: inferred 5 {unit} top/left for Item {it} "
                            "(verify on drawing)."
                        )
            else:
                # Stacked below previous item in note order
                prev = ordered[idx - 1]
                gap_val = 5.0
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
                elif fiveish:
                    gap_val = fiveish[0]["value"]
                offsets = [
                    {
                        "from": "item",
                        "value": gap_val,
                        "unit": unit,
                        "relativeToItem": prev,
                        "relation": "below",
                    }
                ]

            fact = PlacementFact(
                item_no=it,
                surface=surface,
                offsets=offsets,
                confidence=conf,
                source_page=page_no,
            )
            facts.append(fact)
            sentences.append(self._sentence_for(fact, unit))

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

        if not any(f.offsets for f in facts):
            warns.append(
                "Drawing mind: could not resolve placement offsets for "
                f"items {items}; keeping source note wording."
            )
            return text, facts, warns

        return elaborated, facts, warns

    def _sentence_for(self, fact: PlacementFact, unit: str) -> str:
        it = fact.item_no
        surf = fact.surface or "the face shown on the drawing"
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
            return (
                f"Stick Item {it} on the {surf} side, "
                f"{val:g} {unit} {relation} Item {prev}."
            )
        top = next((o for o in fact.offsets if o.get("from") == "top"), None)
        left = next((o for o in fact.offsets if o.get("from") == "left"), None)
        right = next((o for o in fact.offsets if o.get("from") == "right"), None)
        bottom = next((o for o in fact.offsets if o.get("from") == "bottom"), None)
        parts = [f"Stick Item {it} on the {surf} side"]
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
            parts.append(", ".join(bits))
        return ", ".join(parts) + "."

    def _link_pcb_pl_wl(
        self,
        graph: dict,
        parts_list: dict | None,
        wire_list: dict | None,
        notes: list[dict],
    ) -> list[PcbLinkFact]:
        links: list[PcbLinkFact] = []
        pl_map = (parts_list or {}).get("itemMap") or {}
        # Also index by description tokens
        pl_items = (parts_list or {}).get("items") or []
        connectors = graph.get("allConnectors") or []
        seen: set[str] = set()

        # From notes: connector mentions
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
            # Match PL designation containing connector ref
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
