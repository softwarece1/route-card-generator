"""CPU spatial DrawingMind — elaborate AS SHOWN notes from word boxes."""

from __future__ import annotations

import re
from typing import Any

from app.route_card.drawing_mind.base import DrawingMind
from app.route_card.drawing_mind.elaborate import (
    ITEM_APPEAR,
    apply_grounded_elaboration,
    bom_index,
    compose_placement_elaboration,
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

# Named port / mounting faces only — bare FRONT/REAR view titles are excluded
FACE_SURFACE_PREFS = ("DC OUT", "AC OUT", "AC IN", "MOUNTING FACE", "FRONT FACE", "REAR FACE")


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


def _single_item_groups_from_graph(
    graph: dict[str, Any],
    *,
    pl_nos: set[int] | None = None,
    source_drawing_id: int | None = None,
    source_filename: str = "",
) -> list[dict[str, Any]]:
    """Promote lone spatial balloons into assembly groups for clubbing / host pick."""
    balloons = graph.get("allBalloons") or []
    seen: set[int] = set()
    groups: list[dict[str, Any]] = []
    for b in balloons:
        try:
            ino = int(b.get("itemNo"))
        except (TypeError, ValueError, AttributeError):
            continue
        if ino <= 0 or ino in seen:
            continue
        if pl_nos and ino not in pl_nos:
            continue
        seen.add(ino)
        groups.append(
            {
                "parentItemNo": ino,
                "parentQty": 1,
                "children": [],
                "rawText": str(ino),
                "confidence": 0.65,
                "sourcePage": int(b.get("page") or 1),
                "sourceDrawingId": source_drawing_id,
                "sourceFilename": source_filename or "",
                "source": "spatial_balloon",
            }
        )
    return groups


def _infer_host_item_no(
    note: dict[str, Any],
    graph: dict[str, Any],
    ordered: list[int],
) -> int | None:
    """Pick an uncited body balloon near stickers (e.g. Item 1 under labels 2 & 3)."""
    existing = note.get("hostItemNo")
    if existing is not None:
        try:
            h = int(existing)
            if h > 0:
                return h
        except (TypeError, ValueError):
            pass
    cited = set(ordered)
    balloons = graph.get("allBalloons") or []
    sticker_balls = [b for b in balloons if b.get("itemNo") in cited]
    if not sticker_balls:
        return None
    page = int(sticker_balls[0].get("page") or 1)
    sx = sum(float(b["cx"]) for b in sticker_balls) / len(sticker_balls)
    sy = sum(float(b["cy"]) for b in sticker_balls) / len(sticker_balls)
    candidates: list[tuple[float, int]] = []
    for b in balloons:
        try:
            ino = int(b.get("itemNo"))
        except (TypeError, ValueError):
            continue
        if ino in cited or ino <= 0:
            continue
        if int(b.get("page") or 1) != page:
            continue
        # Prefer balloons near the sticker cluster (same view)
        dist = abs(float(b["cx"]) - sx) + abs(float(b["cy"]) - sy)
        if dist > 280:
            continue
        candidates.append((dist, ino))
    if not candidates:
        return None
    candidates.sort()
    # Only claim a host when a single nearby uncited balloon stands out
    best_dist, best = candidates[0]
    if len(candidates) > 1 and candidates[1][0] < best_dist + 40:
        return None
    return best


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

        # Soft balloon-cluster salvage first — club overlapping callouts into NOTES
        # before placement elaboration so stick/place notes absorb measured balloons.
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
            # Also promote lone balloons from the spatial graph so stick notes can
            # club shared items and pick a host body (e.g. Item 1 under stickers).
            assembly_groups.extend(
                _single_item_groups_from_graph(
                    graph,
                    pl_nos=pl_nos,
                    source_drawing_id=source_drawing_id,
                    source_filename=source_filename,
                )
            )
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

        placements: list[PlacementFact] = []
        for note in notes:
            check_cancelled(cancel_event)
            text = note.get("text") or ""
            items = list(note.get("items") or [])
            if note.get("assemblyGroup"):
                continue
            if not needs_placement_elaboration(text, items):
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
        # Prefer left-side balloons; when duplicates exist, keep note-order stack
        # (later items should sit below earlier ones).
        prev_cy: float | None = None
        for it in items:
            cands = [b for b in balloons if b["itemNo"] == it]
            if not cands:
                continue
            cands.sort(key=lambda b: (b["cx"], b["cy"]))
            pick = cands[0]
            if prev_cy is not None and len(cands) > 1:
                below = [b for b in cands if float(b["cy"]) > prev_cy + 2]
                if below:
                    below.sort(key=lambda b: (b["cx"], b["cy"]))
                    pick = below[0]
            item_balloons[it] = pick
            prev_cy = float(pick["cy"])

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

        for idx, it in enumerate(ordered):
            ball = item_balloons.get(it)
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
                if ball and prev in item_balloons:
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
                    elif use_balloon_stack:
                        conf = 0.5
                entry: dict = {
                    "from": "item",
                    "unit": unit,
                    "relativeToItem": prev,
                    "relation": "below",
                }
                if gap_val is not None:
                    entry["value"] = gap_val
                # Same-X stack → left-aligned stickers
                if (
                    ball
                    and prev in item_balloons
                    and abs(float(ball["cx"]) - float(item_balloons[prev]["cx"])) < 25
                ):
                    entry["alignedLeft"] = True
                offsets = [entry]

            fact = PlacementFact(
                item_no=it,
                surface=surface,
                offsets=offsets,
                confidence=conf,
                source_page=page_no,
            )
            facts.append(fact)

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

        host = _infer_host_item_no(note, graph, ordered)
        if host is not None:
            note["hostItemNo"] = host

        elaborated = compose_placement_elaboration(
            text,
            [f.to_dict() for f in facts],
            host_item_no=host,
            unit=unit,
            view_used=str(note.get("viewUsed") or ""),
            view_refs=list(note.get("viewRefs") or []),
        )
        # Attach original note for traceability when composition adds grounding
        if elaborated and text and text.upper() not in elaborated.upper():
            elaborated = f"{elaborated} (From drawing: {text})"
        if not elaborated:
            return "", facts, warns

        return elaborated, facts, warns

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


