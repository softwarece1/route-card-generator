"""Local VLM DrawingMind — Ollama vision for instruction discovery + AS SHOWN elaboration."""

from __future__ import annotations

import json
import re
from typing import Any

from app.route_card.analyze_jobs import AnalysisCancelled, check_cancelled
from app.route_card.drawing_mind.base import DrawingMind
from app.route_card.drawing_mind.cpu_spatial import CpuSpatialMind
from app.route_card.drawing_mind.ollama_client import OllamaError, chat_vision, ollama_reachable
from app.route_card.drawing_mind.page_images import render_pdf_pages
from app.route_card.drawing_mind.types import MindResult, PlacementFact, PcbLinkFact

SYSTEM_PROMPT = (
    "You are a manufacturing drawing reader for the shop floor. "
    "Operators have ITI / Diploma background — write short, simple English "
    "that a layman can follow (no jargon, no long sentences). "
    "Match NOTES with balloons, faces, connectors, and size marks on the drawing. "
    "Never invent item numbers or sizes that are not visible. "
    "Reply with JSON only — no markdown fences."
)

PAGE_PROMPT = """You are viewing one sheet of an engineering GA / assembly drawing.

TASK A — Find instruction steps
Find ANY manufacturing / assembly / process instruction block, regardless of heading
(NOTE, NOTES, ASSEMBLY INSTRUCTIONS, INSTRUCTIONS, CTQ, REMARKS, or unlabeled numbered steps).
Ignore title-block fields, revision tables, company stamps, and BOM tables (except item numbers referenced by a step).

TASK B — Match each step with the drawing views
For steps that say AS SHOWN / AS INDICATED / stick|paste|glue|bond|mount|place:
1. Identify which VIEW shows the work (side / front / top / bottom / isometric / detail / section).
2. Name the FACE using visible labels when present (e.g. "DC OUT face", "AC IN face", "CONTROL panel", "front face").
   Do NOT say "the indicated face" or "the specified surface" — use a concrete name from the drawing.
3. Read nearby size marks (e.g. 5 mm from left/top, gap between items) and map them to each item balloon.
4. Use isometric/other views only to confirm the same face/side.

Return JSON exactly:
{
  "instructionBlockTitle": "string or null",
  "steps": [
    {
      "step": "1",
      "text": "raw instruction text from the drawing",
      "items": [2, 3],
      "needsVisualElaboration": true,
      "viewUsed": "side / lateral view (confirmed by isometric)",
      "elaboratedText": "Simple shop steps: how to stick/fix, which face, item order, and every readable mm gap",
      "confidence": 0.0,
      "placement": [
        {
          "itemNo": 2,
          "surface": "DC OUT face (side)",
          "offsets": [
            {"from": "left", "value": 5.0, "unit": "mm"},
            {"from": "top", "value": 5.0, "unit": "mm"}
          ],
          "confidence": 0.85
        },
        {
          "itemNo": 3,
          "surface": "DC OUT face (side)",
          "offsets": [
            {"from": "left", "value": 5.0, "unit": "mm"},
            {"from": "item", "value": 5.0, "unit": "mm", "relativeToItem": 2, "relation": "below"}
          ],
          "confidence": 0.85
        }
      ]
    }
  ],
  "warnings": []
}

Rules:
- Do NOT invent item numbers or sizes. Omit gaps you cannot read.
- offset.from must be one of: left, right, top, bottom, item.
- relation (when from=item): above, below, left_of, right_of.
- needsVisualElaboration=true for AS SHOWN / placement / stick-paste-mount without fully written offsets in the note text.
- elaboratedText MUST use simple everyday English for shop operators (ITI / Diploma). Short sentences. Prefer words like stick, paste, put, keep gap, below, above, left, right, face, side, glue. Avoid jargon (affix, correlate, orthographic, as indicated, specified surface).
- elaboratedText MUST include: glue/method if stated, named face, which view, item order (e.g. Item 2 above Item 3), and sizes in mm.
- Example style: "Use proper adhesive (glue). Stick Item 2 on the DC OUT face (side view). Keep 5 mm gap from top and 5 mm from left. Stick Item 3 below Item 2 with 5 mm gap."
- If the view is unclear, set confidence low and add a warning — still avoid vague phrases like "as shown" / "indicated face" alone.
- If no instruction steps, return {"instructionBlockTitle": null, "steps": [], "warnings": []}.
"""

ELABORATE_PROMPT = """This drawing page has an instruction that needs a clear shop-floor explanation.

RAW NOTE:
{raw_note}

ITEMS MENTIONED: {items}

Look at the views (side/front/top/isometric/detail). Match balloons for these items with faces and size marks.

Return JSON only:
{{
  "viewUsed": "which view(s) you used",
  "elaboratedText": "simple steps: glue/method + named face + item order + all readable mm gaps",
  "confidence": 0.0,
  "placement": [
    {{
      "itemNo": 2,
      "surface": "concrete face name from drawing labels",
      "offsets": [
        {{"from": "left", "value": 5.0, "unit": "mm"}},
        {{"from": "top", "value": 5.0, "unit": "mm"}}
      ],
      "confidence": 0.85
    }}
  ],
  "warnings": []
}}

Write elaboratedText in short, simple English for ITI / Diploma shop operators. Use everyday words (stick, paste, put, keep gap, below, face, glue). No jargon.
Do not use vague wording like "the indicated face" or "the specified surface". Prefer face labels on the drawing (e.g. DC OUT).
Example: "Use proper adhesive (glue). Stick Item 2 on the DC OUT face. Keep 5 mm from top and 5 mm from left. Stick Item 3 below Item 2 with 5 mm gap."
"""

_JSON_FENCE = re.compile(r"```(?:json)?\s*([\s\S]*?)```", re.I)
_AS_SHOWNISH = re.compile(
    r"\b(AS\s+SHOWN|AS\s+INDICATED|SEE\s+(?:DETAIL|VIEW|FIG)|STICK|PASTE|GLUE|BOND|ADHERE|MOUNT|PLACE|FIT)\b",
    re.I,
)
_ITEM_NO = re.compile(
    r"(?:ITEMS?|ITMS?|IT\.?)\s*(?:NO\.?|NOS\.?|NUMBER|#)?\s*-?\s*(\d{1,3})",
    re.I,
)
_WEAK_SURFACE = re.compile(
    r"^(the\s+)?(indicated|specified|shown|relevant|appropriate|given)\s+(face|surface|side|area)\.?$",
    re.I,
)
_WEAK_ELAB = re.compile(
    r"\b(specified surface|indicated face|as shown|as indicated)\b",
    re.I,
)


def _strip_json_payload(raw: str) -> str:
    text = (raw or "").strip()
    m = _JSON_FENCE.search(text)
    if m:
        return m.group(1).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        return text[start : end + 1]
    return text


def _parse_vlm_json(raw: str) -> dict[str, Any]:
    payload = _strip_json_payload(raw)
    data = json.loads(payload)
    if not isinstance(data, dict):
        raise ValueError("VLM JSON root must be an object")
    return data


def _coerce_items(value: Any, text: str) -> list[int]:
    items: list[int] = []
    if isinstance(value, list):
        for v in value:
            try:
                n = int(v)
            except (TypeError, ValueError):
                continue
            if 1 <= n <= 999 and n not in items:
                items.append(n)
    if not items and text:
        for m in _ITEM_NO.finditer(text):
            n = int(m.group(1))
            if n not in items:
                items.append(n)
    return items


def _coerce_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _normalize_offsets(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    allowed_from = {"left", "right", "top", "bottom", "item"}
    out: list[dict[str, Any]] = []
    for off in raw:
        if not isinstance(off, dict):
            continue
        frm = str(off.get("from") or "").strip().lower()
        if frm not in allowed_from:
            continue
        val = _coerce_float(off.get("value"))
        if val is None:
            continue
        unit = str(off.get("unit") or "mm").strip() or "mm"
        entry: dict[str, Any] = {"from": frm, "value": val, "unit": unit, "relativeToItem": None}
        rel = off.get("relativeToItem")
        if rel is not None:
            try:
                entry["relativeToItem"] = int(rel)
            except (TypeError, ValueError):
                entry["relativeToItem"] = None
        relation = str(off.get("relation") or "").strip().lower()
        if relation in {"above", "below", "left_of", "right_of"}:
            entry["relation"] = relation
        out.append(entry)
    return out


def _normalize_placement(raw: Any, *, source_page: int) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for p in raw:
        if not isinstance(p, dict):
            continue
        try:
            item_no = int(p.get("itemNo"))
        except (TypeError, ValueError):
            continue
        if item_no < 1:
            continue
        surface = str(p.get("surface") or "").strip()
        if _WEAK_SURFACE.match(surface):
            surface = ""
        conf = _coerce_float(p.get("confidence"))
        if conf is None:
            conf = 0.7 if surface else 0.45
        conf = max(0.0, min(conf, 1.0))
        out.append(
            {
                "itemNo": item_no,
                "surface": surface,
                "offsets": _normalize_offsets(p.get("offsets")),
                "confidence": conf,
                "sourcePage": source_page,
            }
        )
    return out


def _is_weak_elaboration(text: str, raw_note: str = "") -> bool:
    t = (text or "").strip()
    if not t:
        return True
    if _WEAK_ELAB.search(t) and not re.search(r"\b\d+(?:\.\d+)?\s*mm\b", t, re.I):
        return True
    # Nearly identical to raw note → not really elaborated
    a = re.sub(r"\s+", " ", t.upper())
    b = re.sub(r"\s+", " ", (raw_note or "").upper())
    if a and b and (a == b or a in b or b in a) and "DC OUT" not in a and "MM" not in a:
        return True
    return False


def _compose_elaboration_from_placement(
    raw_note: str,
    placements: list[dict[str, Any]],
    *,
    view_used: str = "",
) -> str:
    if not placements:
        return ""
    parts: list[str] = []
    if re.search(r"adhesive|glue|stick|paste|bond", raw_note or "", re.I):
        parts.append("Use proper adhesive (glue).")
    surface = next((p.get("surface") for p in placements if p.get("surface")), "")
    view_bit = f" ({view_used})" if view_used else ""
    if surface:
        parts.append(f"Stick these parts on the {surface}{view_bit}.")
    else:
        parts.append(f"Stick these parts as marked on the drawing{view_bit}.")

    rel_words = {
        "below": "below",
        "above": "above",
        "left_of": "to the left of",
        "right_of": "to the right of",
    }
    for p in placements:
        item = p.get("itemNo")
        offs = p.get("offsets") or []
        bits: list[str] = []
        for o in offs:
            frm = o.get("from")
            val = o.get("value")
            unit = o.get("unit") or "mm"
            if frm == "item" and o.get("relativeToItem") is not None:
                rel = rel_words.get(o.get("relation") or "below", "below")
                bits.append(f"keep {val:g} {unit} {rel} Item {o['relativeToItem']}")
            elif frm in {"left", "right", "top", "bottom"}:
                bits.append(f"keep {val:g} {unit} from {frm}")
            elif frm:
                bits.append(f"keep {val:g} {unit} from {frm}")
        if bits:
            parts.append(f"Item {item}: " + "; ".join(bits) + ".")
        elif surface:
            parts.append(f"Item {item}: stick on {surface}.")
    return " ".join(parts).strip()


def _placement_facts(placements: list[dict[str, Any]]) -> list[PlacementFact]:
    facts: list[PlacementFact] = []
    for p in placements:
        facts.append(
            PlacementFact(
                item_no=int(p["itemNo"]),
                surface=str(p.get("surface") or ""),
                offsets=list(p.get("offsets") or []),
                confidence=float(p.get("confidence") or 0.0),
                source_page=int(p.get("sourcePage") or 1),
            )
        )
    return facts


def _prefer_vlm_placements(
    cpu_placements: list[PlacementFact],
    vlm_placements: list[dict[str, Any]],
) -> list[PlacementFact]:
    """Prefer VLM placements when they name a surface or carry offsets."""
    vlm_facts = _placement_facts(vlm_placements)
    if not vlm_facts:
        return cpu_placements
    if any((f.surface and not _WEAK_SURFACE.match(f.surface)) or f.offsets for f in vlm_facts):
        return vlm_facts
    # Merge: keep CPU offsets if VLM has surface only, etc.
    by_item = {f.item_no: f for f in cpu_placements}
    for vf in vlm_facts:
        cur = by_item.get(vf.item_no)
        if not cur:
            by_item[vf.item_no] = vf
            continue
        surface = vf.surface or cur.surface
        if surface and _WEAK_SURFACE.match(surface):
            surface = cur.surface if cur.surface and not _WEAK_SURFACE.match(cur.surface) else surface
        offsets = vf.offsets or cur.offsets
        conf = max(vf.confidence, cur.confidence)
        by_item[vf.item_no] = PlacementFact(
            item_no=vf.item_no,
            surface=surface or "",
            offsets=offsets,
            confidence=conf,
            source_page=vf.source_page or cur.source_page,
        )
    return list(by_item.values())


def _normalize_step(step: dict[str, Any], *, sheet: int, step_no: int) -> dict[str, Any] | None:
    text = str(step.get("text") or "").strip()
    if not text or len(text) < 3:
        return None
    elaborated = str(step.get("elaboratedText") or "").strip()
    needs = bool(step.get("needsVisualElaboration"))
    if not needs and _AS_SHOWNISH.search(text):
        needs = True
    view_used = str(step.get("viewUsed") or "").strip()
    placement = _normalize_placement(step.get("placement"), source_page=sheet)
    if needs and _is_weak_elaboration(elaborated, text):
        composed = _compose_elaboration_from_placement(text, placement, view_used=view_used)
        if composed:
            elaborated = composed
    if needs and not elaborated:
        elaborated = text
    if elaborated and elaborated.upper() == text.upper() and not needs:
        elaborated = ""

    conf_raw = step.get("confidence")
    try:
        confidence = float(conf_raw) if conf_raw is not None else (0.7 if elaborated else 0.55)
    except (TypeError, ValueError):
        confidence = 0.55
    confidence = max(0.0, min(confidence, 1.0))

    items = _coerce_items(step.get("items"), text)
    label = str(step.get("step") or step_no).strip() or str(step_no)

    out: dict[str, Any] = {
        "sheet": sheet,
        "stepNo": step_no,
        "label": label,
        "text": text,
        "items": items,
        "torque": [],
        "connectors": [],
        "standards": [],
        "references": [],
        "elaboratedText": elaborated,
        "placement": placement,
        "viewRefs": [],
        "viewUsed": view_used,
        "mindEngine": "local_vlm",
        "mindConfidence": confidence,
        "needsVisualElaboration": needs,
    }
    return out


def _vlm_notes_usable(notes: list[dict[str, Any]]) -> bool:
    if not notes:
        return False
    return any(len((n.get("text") or "").strip()) >= 8 for n in notes)


def _merge_elaboration_onto_ocr(
    ocr_notes: list[dict[str, Any]],
    vlm_notes: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Keep OCR notes; attach VLM elaborations / placements when texts roughly match."""
    out = [dict(n) for n in ocr_notes]
    used: set[int] = set()
    for note in out:
        body = re.sub(r"\s+", " ", (note.get("text") or "")).upper()[:120]
        if not body:
            continue
        best_i = -1
        best_score = 0
        for i, vn in enumerate(vlm_notes):
            if i in used:
                continue
            vb = re.sub(r"\s+", " ", (vn.get("text") or "")).upper()[:120]
            if not vb:
                continue
            if body in vb or vb in body:
                score = min(len(body), len(vb))
            else:
                bt = set(body.split())
                vt = set(vb.split())
                score = len(bt & vt)
            if score > best_score:
                best_score = score
                best_i = i
        if best_i < 0 or best_score < 3:
            continue
        used.add(best_i)
        vn = vlm_notes[best_i]
        elab = (vn.get("elaboratedText") or "").strip()
        if elab and not _is_weak_elaboration(elab, note.get("text") or ""):
            note["elaboratedText"] = elab
        elif vn.get("placement"):
            composed = _compose_elaboration_from_placement(
                note.get("text") or "",
                vn.get("placement") or [],
                view_used=str(vn.get("viewUsed") or ""),
            )
            if composed:
                note["elaboratedText"] = composed
        if vn.get("placement"):
            note["placement"] = list(vn.get("placement") or [])
        note["mindEngine"] = "local_vlm"
        note["mindConfidence"] = vn.get("mindConfidence")
        note["needsVisualElaboration"] = vn.get("needsVisualElaboration")
        if vn.get("viewUsed"):
            note["viewUsed"] = vn.get("viewUsed")
    return out


def _needs_second_pass(note: dict[str, Any]) -> bool:
    if not note.get("needsVisualElaboration"):
        return False
    if _is_weak_elaboration(note.get("elaboratedText") or "", note.get("text") or ""):
        return True
    placements = note.get("placement") or []
    if not placements:
        return True
    if all(not (p.get("surface") or "").strip() for p in placements):
        return True
    return False


class LocalVlmMind(DrawingMind):
    """Vision-first instruction discovery with CPU spatial fallback."""

    engine = "local_vlm"

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
        from app.config.settings import settings

        check_cancelled(cancel_event)

        cpu = CpuSpatialMind()
        cpu_result = cpu.understand(
            pdf_bytes=pdf_bytes,
            ga_extraction=ga_extraction,
            spatial_pages=spatial_pages,
            parts_list=parts_list,
            wire_list=wire_list,
            source_drawing_id=source_drawing_id,
            source_filename=source_filename,
            cancel_event=cancel_event,
        )

        warnings = list(cpu_result.warnings)
        cpu_placements: list[PlacementFact] = list(cpu_result.placements)
        pcb_links: list[PcbLinkFact] = list(cpu_result.pcb_links)
        ocr_notes = [dict(n) for n in (cpu_result.notes or ga_extraction.get("notes") or [])]

        if not pdf_bytes:
            warnings.append("Drawing mind (local_vlm): no PDF bytes — using CPU spatial only.")
            return MindResult(
                engine="local_vlm_fallback_cpu",
                notes=ocr_notes,
                placements=cpu_placements,
                pcb_links=pcb_links,
                warnings=warnings,
            )

        base_url = getattr(settings, "OLLAMA_BASE_URL", "http://127.0.0.1:11434")
        model = getattr(settings, "OLLAMA_VLM_MODEL", "qwen3.8-27b-vl:latest")
        timeout = float(getattr(settings, "OLLAMA_TIMEOUT_SEC", 600) or 600)
        dpi = int(getattr(settings, "OLLAMA_VLM_DPI", 160) or 160)
        max_pages = int(getattr(settings, "OLLAMA_VLM_MAX_PAGES", 6) or 6)
        max_edge = int(getattr(settings, "OLLAMA_VLM_MAX_IMAGE_EDGE", 1600) or 1600)

        if not ollama_reachable(base_url, timeout=min(5.0, timeout)):
            warnings.append(
                f"Drawing mind (local_vlm): Ollama not reachable at {base_url} — using CPU spatial fallback."
            )
            return MindResult(
                engine="local_vlm_fallback_cpu",
                notes=ocr_notes,
                placements=cpu_placements,
                pcb_links=pcb_links,
                warnings=warnings,
            )

        try:
            pages = render_pdf_pages(
                pdf_bytes,
                dpi=dpi,
                max_pages=max_pages,
                max_edge=max_edge,
                page_indexes=page_indexes,
                cancel_event=cancel_event,
            )
        except AnalysisCancelled:
            raise
        except Exception as exc:
            warnings.append(f"Drawing mind (local_vlm): page render failed ({exc}) — CPU fallback.")
            return MindResult(
                engine="local_vlm_fallback_cpu",
                notes=ocr_notes,
                placements=cpu_placements,
                pcb_links=pcb_links,
                warnings=warnings,
            )

        if not pages:
            warnings.append("Drawing mind (local_vlm): no pages rendered — CPU fallback.")
            return MindResult(
                engine="local_vlm_fallback_cpu",
                notes=ocr_notes,
                placements=cpu_placements,
                pcb_links=pcb_links,
                warnings=warnings,
            )

        system_prompt = SYSTEM_PROMPT
        if prompt_addendum and str(prompt_addendum).strip():
            system_prompt = SYSTEM_PROMPT + "\n\n" + str(prompt_addendum).strip()

        vlm_notes: list[dict[str, Any]] = []
        page_warns: list[str] = []
        step_counter = 0
        pages_by_no = {int(p["page"]): p for p in pages}

        for page in pages:
            check_cancelled(cancel_event)
            page_no = int(page.get("page") or 1)
            try:
                raw = chat_vision(
                    prompt=PAGE_PROMPT,
                    images_b64=[page["b64"]],
                    model=model,
                    base_url=base_url,
                    timeout=timeout,
                    temperature=0.1,
                    system=system_prompt,
                    cancel_event=cancel_event,
                )
                data = _parse_vlm_json(raw)
            except AnalysisCancelled:
                raise
            except (OllamaError, ValueError, json.JSONDecodeError) as exc:
                page_warns.append(f"VLM page {page_no}: {exc}")
                continue

            for w in data.get("warnings") or []:
                if isinstance(w, str) and w.strip():
                    page_warns.append(f"VLM page {page_no}: {w.strip()}")

            title = data.get("instructionBlockTitle")
            steps = data.get("steps") or []
            if not isinstance(steps, list):
                continue
            for step in steps:
                if not isinstance(step, dict):
                    continue
                step_counter += 1
                normalized = _normalize_step(step, sheet=page_no, step_no=step_counter)
                if not normalized:
                    step_counter -= 1
                    continue
                if isinstance(title, str) and title.strip():
                    normalized["blockTitle"] = title.strip()
                if source_drawing_id is not None:
                    normalized["sourceDrawingId"] = source_drawing_id
                if source_filename:
                    normalized["sourceFilename"] = source_filename
                vlm_notes.append(normalized)

        # Second pass: refine weak AS SHOWN / placement elaborations with a focused prompt
        for note in vlm_notes:
            if not _needs_second_pass(note):
                continue
            check_cancelled(cancel_event)
            page = pages_by_no.get(int(note.get("sheet") or 1))
            if not page:
                continue
            prompt = ELABORATE_PROMPT.format(
                raw_note=note.get("text") or "",
                items=", ".join(str(i) for i in (note.get("items") or [])) or "(none listed)",
            )
            try:
                raw = chat_vision(
                    prompt=prompt,
                    images_b64=[page["b64"]],
                    model=model,
                    base_url=base_url,
                    timeout=timeout,
                    temperature=0.1,
                    system=system_prompt,
                    cancel_event=cancel_event,
                )
                data = _parse_vlm_json(raw)
            except AnalysisCancelled:
                raise
            except (OllamaError, ValueError, json.JSONDecodeError) as exc:
                page_warns.append(f"VLM elaborate step {note.get('stepNo')}: {exc}")
                continue
            for w in data.get("warnings") or []:
                if isinstance(w, str) and w.strip():
                    page_warns.append(f"VLM elaborate: {w.strip()}")
            view_used = str(data.get("viewUsed") or note.get("viewUsed") or "").strip()
            placement = _normalize_placement(
                data.get("placement"),
                source_page=int(note.get("sheet") or 1),
            )
            elab = str(data.get("elaboratedText") or "").strip()
            if placement:
                note["placement"] = placement
            if view_used:
                note["viewUsed"] = view_used
            if elab and not _is_weak_elaboration(elab, note.get("text") or ""):
                note["elaboratedText"] = elab
            elif placement:
                composed = _compose_elaboration_from_placement(
                    note.get("text") or "",
                    placement,
                    view_used=view_used,
                )
                if composed:
                    note["elaboratedText"] = composed
            conf = _coerce_float(data.get("confidence"))
            if conf is not None:
                note["mindConfidence"] = max(0.0, min(conf, 1.0))

        warnings.extend(page_warns)

        vlm_placement_dicts: list[dict[str, Any]] = []
        for n in vlm_notes:
            vlm_placement_dicts.extend(n.get("placement") or [])

        if _vlm_notes_usable(vlm_notes):
            notes = vlm_notes
            # Fill empty VLM placement from matching CPU note only if VLM has none
            ocr_by_key = {
                re.sub(r"\s+", " ", (n.get("text") or "")).upper()[:100]: n for n in ocr_notes
            }
            for note in notes:
                key = re.sub(r"\s+", " ", (note.get("text") or "")).upper()[:100]
                src = ocr_by_key.get(key)
                if src and src.get("placement") and not note.get("placement"):
                    note["placement"] = list(src.get("placement") or [])
                    vlm_placement_dicts.extend(note["placement"])
            engine = self.engine
            warnings.append(
                f"Drawing mind (local_vlm): extracted {len(notes)} instruction step(s) from {len(pages)} page image(s)."
            )
        else:
            notes = _merge_elaboration_onto_ocr(ocr_notes, vlm_notes)
            for n in notes:
                vlm_placement_dicts.extend(n.get("placement") or [])
            engine = "local_vlm_partial" if vlm_notes else "local_vlm_fallback_cpu"
            if not vlm_notes:
                warnings.append(
                    "Drawing mind (local_vlm): no usable instruction steps from vision — kept OCR/CPU notes."
                )
            else:
                warnings.append(
                    "Drawing mind (local_vlm): vision steps sparse — merged elaborations onto OCR notes."
                )

        placements = _prefer_vlm_placements(cpu_placements, vlm_placement_dicts)

        for note in notes:
            if source_drawing_id is not None and "sourceDrawingId" not in note:
                note["sourceDrawingId"] = source_drawing_id
            if source_filename and "sourceFilename" not in note:
                note["sourceFilename"] = source_filename
            # If note still has weak surface in placement, overlay preferred facts by item
            if note.get("placement"):
                by_item = {f.item_no: f for f in placements}
                refreshed: list[dict[str, Any]] = []
                for p in note["placement"]:
                    fact = by_item.get(int(p.get("itemNo") or 0))
                    if fact:
                        refreshed.append(fact.to_dict())
                    else:
                        refreshed.append(p)
                note["placement"] = refreshed

        return MindResult(
            engine=engine,
            notes=notes,
            placements=placements,
            pcb_links=pcb_links,
            warnings=list(dict.fromkeys(warnings)),
        )
