"""Local VLM DrawingMind — verbatim NOTE transcription + optional insight."""

from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from app.route_card.analyze_jobs import AnalysisCancelled, check_cancelled
from app.route_card.drawing_mind.base import DrawingMind
from app.route_card.drawing_mind.cpu_spatial import CpuSpatialMind
from app.route_card.drawing_mind.elaborate import (
    apply_grounded_elaboration,
    needs_stage_b_vision,
    note_is_enriched,
)
from app.route_card.drawing_mind.ollama_client import (
    OllamaError,
    chat_text,
    chat_vision,
    ollama_reachable,
    vlm_status,
)
from app.route_card.drawing_mind.page_images import (
    ocr_image_raw,
    render_note_bands,
    render_pdf_pages,
)
from app.route_card.drawing_mind.types import MindResult, PlacementFact, PcbLinkFact

SYSTEM_PROMPT = (
    "You are a manufacturing drawing note reader. "
    "Your only job is accurate verbatim transcription of instruction notes. "
    "Never invent, correct, simplify, or expand spelling, numbers, designators, or part numbers. "
    "Reply with JSON only — no markdown fences."
)

TRANSCRIBE_PROMPT = """You are viewing a crop of the NOTES / instruction area of an engineering GA drawing.

OCR transcript of the same crop (character authority — trust these characters; use the image only to recover a blank or garbled span):
-----
{ocr_text}
-----

Copy every numbered instruction line under NOTE, NOTE I, NOTE II, NOTES, ASSEMBLY INSTRUCTIONS, CTQ POINTS, CRITICAL TO QUALITY, REMARKS, or similar.
Keep the drawing spelling, punctuation, ranges, and part numbers exactly.
Do not simplify English. Do not "correct" words (RoHS, ENAMELED, BARE, FACIA, NYCOSOL, etc.).
Do not merge lines. Do not drop a line. Do not invent a component value, item, connector, or size.
If a glyph is unreadable after checking OCR and the image, write [unreadable] in that span.
Use title "CTQ POINTS" (not NOTE) for Critical-To-Quality / CTQ blocks so they stay quality checks.
CTQ lines are safety-critical: prefer OCR characters; never truncate mid-word; never append table/BOM bleed after the CTQ sentence.

Return JSON only (shape — no sample designators or part numbers):
{{
  "blocks": [
    {{
      "title": "NOTE I",
      "lines": ["1. …", "2. …"]
    }}
  ],
  "warnings": []
}}

If there are no instruction lines, return {{"blocks": [], "warnings": []}}.
"""

INSIGHT_PROMPT = """Verbatim drawing note (do not change this text):
{note_text}

If this note already cites a link (ITEM, P/N, FIGURE, SHEET, SEE, REFER, AS SHOWN, PS nnn), write one short insight sentence that only restates that existing link.
If there is nothing to add, return an empty insight.

Forbidden: new part numbers, new designators (X/R/TP/B lists), new hole sizes, rewritten shop steps, spelling changes.

Return JSON only:
{{
  "text": "exact copy of the verbatim note above",
  "insight": "",
  "warnings": []
}}
"""

STAGE_B_PROMPT = """You are viewing a GA assembly drawing page (views + balloons + dimensions).

Verbatim note that needs visual placement:
-----
{note_text}
-----

Items already cited on the note: {items_csv}

Return JSON only describing placement you can SEE (balloon numbers, surface labels, measured dims).
Do not invent part numbers, item numbers, or dimensions that are not visible.
If nothing useful is visible, return empty placements.

Surface rules (critical):
- Set "surface" ONLY when a clear mounting-face / port label is printed on the drawing
  (e.g. DC OUT, AC OUT, AC IN, MOUNTING FACE, FRONT FACE, REAR FACE).
- Do NOT use bare FRONT / REAR / view titles (FRONT VIEW, REAR VIEW, SIDE VIEW) as surface.
- If the face is unclear, leave "surface" as "".

{{
  "placements": [
    {{
      "itemNo": 2,
      "surface": "visible face label or empty",
      "offsets": [
        {{"from": "top", "value": 5.0, "unit": "mm"}},
        {{"from": "item", "value": 5.0, "unit": "mm", "relativeToItem": 2, "relation": "below"}}
      ],
      "confidence": 0.7
    }}
  ],
  "warnings": []
}}
"""

_JSON_FENCE = re.compile(r"```(?:json)?\s*([\s\S]*?)```", re.I)
_ITEM_NO = re.compile(
    r"(?:ITEMS?|ITMS?|IT\.?)\s*(?:NO\.?|NOS\.?|NUMBER|#)?\s*-?\s*(\d{1,3})",
    re.I,
)
_LINK_PHRASE = re.compile(
    r"\b(?:AS\s+SHOWN|AS\s+INDICATED|SEE|REFER|FIGURE|SHEET|ITEM|P/?N|PS\s*\d+)\b",
    re.I,
)
_LINE_START = re.compile(r"^\s*(\d{1,2})[\.\)]\s*(.*)$")
_NOTE_TITLE = re.compile(
    r"^\s*(NOTE(?:\s*[IVX]+)?|NOTES|ASSEMBLY\s+INSTRUCTIONS|"
    r"CTQ(?:\s+POINTS?)?|CRITICAL\s+TO\s+QUALITY(?:\s+POINTS?)?|REMARKS)\b.*$",
    re.I,
)
# Tokens that must match exactly between OCR and model (case-insensitive).
_TOKEN = re.compile(
    r"(?:"
    r"P/?N[—–\-\s]?[A-Z0-9]+|"
    r"[A-Z]{1,4}\d+(?:\.\d+)?|"  # X53.2, R66, B1, TP1, FL1, P2
    r"\d+[A-Z]{1,4}|"  # OCR glue: 5SI, 5S0
    r"\d+(?:\.\d+)?|"
    r"[A-Za-z]+"
    r")"
)
_STOP_TOKENS = {
    "A", "AN", "THE", "OF", "TO", "AND", "OR", "FOR", "ON", "IN", "BY", "WITH",
    "BE", "IS", "ARE", "AS", "PER", "NO", "NOS", "ITEM", "ITEMS", "USING",
}


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


def _normalize_token(tok: str) -> str:
    t = (tok or "").upper().replace(" ", "")
    t = t.replace("P/N", "PN").replace("PN-", "PN").replace("PN—", "PN").replace("PN–", "PN")
    if t.startswith("PN") and len(t) > 2 and t[2:].isdigit():
        return t
    return t


def extract_significant_tokens(text: str) -> set[str]:
    """Words, numbers, designators, and P/N values (uppercased) for gate comparison."""
    out: set[str] = set()
    for m in _TOKEN.finditer(text or ""):
        tok = _normalize_token(m.group(0))
        if tok in _STOP_TOKENS:
            continue
        if len(tok) == 1 and tok.isalpha():
            continue
        out.add(tok)
        # Also index bare digit run for PN4851… ↔ 4851… comparisons.
        if tok.startswith("PN") and tok[2:].isdigit():
            out.add(tok[2:])
    return out


def _ocr_confusable_map(s: str) -> str:
    """Map common OCR lookalikes to a canonical form for comparison."""
    table = str.maketrans(
        {
            "I": "1",
            "L": "1",
            "|": "1",
            "O": "0",
            "Q": "0",
            "S": "5",
            "3": "5",  # 3/S/5 often swap on thin CAD fonts
            "B": "8",
            "Z": "2",
            "G": "6",
        }
    )
    return (s or "").upper().translate(table)


def tokens_are_ocr_confusable(ocr_tok: str, model_tok: str) -> bool:
    """
    True when the model token is a plausible OCR fix of the OCR token.

    Allows only tight confusions (I/1, S/5/3, one missing letter, glued ITEM NO-5SI→50).
    Does not allow inventing a wholly different part number or designator family.
    """
    a = _normalize_token(ocr_tok)
    b = _normalize_token(model_tok)
    if not a or not b or a == b:
        return a == b
    # PN4851… vs 4851…
    if a.startswith("PN") and a[2:] == b:
        return True
    if b.startswith("PN") and b[2:] == a:
        return True
    # Same letters after OCR digit/letter fold (Xi↔X1, TPS↔TP3, Ri↔R1).
    if _ocr_confusable_map(a) == _ocr_confusable_map(b):
        return True
    # ITEM NO-5SI / 5SI → 50 (digit stem + OCR letter glue).
    m_a = re.fullmatch(r"(\d+)[A-Z]+", a)
    if m_a and re.fullmatch(r"\d+", b):
        stem = m_a.group(1)
        if b == stem or b.startswith(stem) and len(b) <= len(stem) + 2:
            return True
        folded = _ocr_confusable_map(a)
        if re.fullmatch(r"\d+", folded) and (
            folded == b or b.startswith(stem) and len(b) <= len(stem) + 2
        ):
            return True
    m_b = re.fullmatch(r"(\d+)[A-Z]+", b)
    if m_b and re.fullmatch(r"\d+", a):
        stem = m_b.group(1)
        if a == stem or a.startswith(stem) and len(a) <= len(stem) + 2:
            return True
    # One-character edit for longer words (ENAMLED↔ENAMELED, CONNECTPRS↔CONNECTORS).
    if len(a) >= 4 and len(b) >= 4 and abs(len(a) - len(b)) <= 2:
        # Prefix must share at least 3 chars so P/Ns cannot freely morph.
        if a[:3] != b[:3] and _ocr_confusable_map(a)[:3] != _ocr_confusable_map(b)[:3]:
            return False
        if _edit_distance_le(a, b, 2):
            return True
    return False


def _edit_distance_le(a: str, b: str, limit: int) -> bool:
    if abs(len(a) - len(b)) > limit:
        return False
    # Banded Levenshtein — early exit above limit.
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        cur = [i]
        row_min = i
        for j, cb in enumerate(b, start=1):
            ins = cur[j - 1] + 1
            delete = prev[j] + 1
            sub = prev[j - 1] + (0 if ca == cb else 1)
            val = min(ins, delete, sub)
            cur.append(val)
            if val < row_min:
                row_min = val
        if row_min > limit:
            return False
        prev = cur
    return prev[-1] <= limit


def token_gate(ocr_line: str, model_line: str) -> tuple[bool, str | None]:
    """
    Return (ok, conflict_token).

    Model line must not add or drop significant tokens vs OCR (exact match).
    """
    ocr_toks = extract_significant_tokens(ocr_line)
    model_toks = extract_significant_tokens(model_line)
    if not ocr_toks:
        return True, None
    missing = ocr_toks - model_toks
    if missing:
        return False, sorted(missing)[0]
    extra = model_toks - ocr_toks
    if extra:
        return False, sorted(extra)[0]
    return True, None


def reconcile_ocr_with_model(ocr_line: str, model_line: str) -> tuple[str, bool, str | None]:
    """
    Prefer OCR text, but accept model tokens that are OCR confusable fixes.

    Returns (text, needs_review, conflict_or_none).
    - Exact token match → OCR text, needs_review=False
    - Only confusable diffs → OCR text with those tokens replaced by model forms, needs_review=True
    - Any non-confusable invent/drop → OCR text unchanged, needs_review=True, conflict set
    """
    ocr_line = (ocr_line or "").strip()
    model_line = (model_line or "").strip()
    if not model_line:
        return ocr_line, False, None

    ok, conflict = token_gate(ocr_line, model_line)
    if ok:
        return ocr_line, False, None

    ocr_matches = list(_TOKEN.finditer(ocr_line))
    model_toks = [_normalize_token(m.group(0)) for m in _TOKEN.finditer(model_line)]
    model_toks = [
        t
        for t in model_toks
        if t not in _STOP_TOKENS and not (len(t) == 1 and t.isalpha())
    ]
    unused_model = list(model_toks)
    replacements: list[tuple[int, int, str]] = []  # start, end, new_text
    hard_conflict: str | None = None

    for m in ocr_matches:
        raw = m.group(0)
        ocr_tok = _normalize_token(raw)
        if ocr_tok in _STOP_TOKENS or (len(ocr_tok) == 1 and ocr_tok.isalpha()):
            continue
        # Exact presence in model (including PN↔digits expansion).
        if ocr_tok in unused_model:
            unused_model.remove(ocr_tok)
            continue
        if ocr_tok.startswith("PN") and ocr_tok[2:] in unused_model:
            unused_model.remove(ocr_tok[2:])
            continue
        if ocr_tok.isdigit() and f"PN{ocr_tok}" in unused_model:
            unused_model.remove(f"PN{ocr_tok}")
            continue

        # Find a confusable model token.
        matched_j = -1
        for j, mt in enumerate(unused_model):
            if tokens_are_ocr_confusable(ocr_tok, mt):
                matched_j = j
                break
        if matched_j < 0:
            hard_conflict = ocr_tok
            break
        mt = unused_model.pop(matched_j)
        # Replace the OCR span with the model spelling (preserve PN-/P/N style lightly).
        repl = mt
        if raw.upper().startswith("P/N") or raw.upper().startswith("PN"):
            digits = mt[2:] if mt.startswith("PN") else mt
            repl = f"P/N-{digits}" if digits.isdigit() else mt
        replacements.append((m.start(), m.end(), repl))

    if hard_conflict:
        return ocr_line, True, hard_conflict

    # Remaining unused model tokens must each map to something already covered,
    # or be a soft expansion of an OCR token we already replaced. Drop leftovers
    # that are ordinary words; hard-fail on new designators / long numbers.
    for mt in unused_model:
        if mt in _STOP_TOKENS:
            continue
        if re.fullmatch(r"[A-Z]{1,4}\d+(?:\.\d+)?", mt) or re.fullmatch(r"\d{4,}", mt) or (
            mt.startswith("PN") and len(mt) > 4
        ):
            # Already handled via OCR side? If still here, model invented it.
            return ocr_line, True, mt

    if not replacements:
        return ocr_line, True, conflict

    # Apply replacements right-to-left so spans stay valid.
    text = ocr_line
    for start, end, repl in sorted(replacements, key=lambda x: x[0], reverse=True):
        text = text[:start] + repl + text[end:]
    text = re.sub(r"\s+", " ", text).strip()
    # Confusable fixes always need human review.
    return text, True, None


def strip_leading_step_number(text: str, label: str = "") -> str:
    """Remove a duplicated leading 'N.' / 'N)' from note body when label already carries it."""
    t = (text or "").strip()
    m = _LINE_START.match(t)
    if not m:
        return t
    if label and m.group(1) != str(label).strip():
        return t
    return (m.group(2) or "").strip() or t


def insight_is_safe(note_text: str, insight: str) -> bool:
    """Insight must not introduce numbers / designators / part numbers absent from the note."""
    insight = (insight or "").strip()
    if not insight:
        return True
    note_toks = extract_significant_tokens(note_text)
    insight_toks = extract_significant_tokens(insight)
    # Allow ordinary English words in insight even if not in note; block new numbers/designators/PN.
    for tok in insight_toks:
        if tok in note_toks:
            continue
        if re.fullmatch(r"\d+(?:\.\d+)?", tok):
            return False
        if re.fullmatch(r"[A-Z]{1,4}\d+(?:\.\d+)?", tok):
            return False
        if tok.startswith("PN") and len(tok) > 3:
            return False
        if re.fullmatch(r"[A-Z]*\d{6,}", tok):
            return False
    return True


def split_ocr_note_lines(ocr_text: str) -> list[dict[str, str]]:
    """
    Split OCR note-band text into {title, label, text} lines.

    Continuations of a numbered line are joined until the next number or title.
    """
    lines_out: list[dict[str, str]] = []
    current_title = ""
    current: dict[str, str] | None = None

    def flush() -> None:
        nonlocal current
        if current and (current.get("text") or "").strip():
            current["text"] = re.sub(r"\s+", " ", current["text"]).strip()
            lines_out.append(current)
        current = None

    for raw in (ocr_text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        if _NOTE_TITLE.match(line):
            flush()
            current_title = re.sub(r"\s+", " ", line)
            # Keep long NOTE II intros that include the first sentence after the colon.
            if ":" in current_title and len(current_title) > 40:
                title_part, rest = current_title.split(":", 1)
                current_title = title_part.strip()
                rest = rest.strip()
                if rest:
                    current = {"title": current_title, "label": "", "text": rest}
            continue
        m = _LINE_START.match(line)
        if m:
            flush()
            current = {
                "title": current_title,
                "label": m.group(1),
                "text": (m.group(2) or "").strip(),
            }
            continue
        if current is not None:
            current["text"] = f"{current['text']} {line}".strip()
        elif current_title and not lines_out:
            # Preamble under a title before first number.
            current = {"title": current_title, "label": "", "text": line}
    flush()
    return lines_out


def flatten_model_blocks(data: dict[str, Any]) -> list[dict[str, str]]:
    """Flatten VLM {blocks:[{title, lines}]} into {title, label, text}."""
    out: list[dict[str, str]] = []
    blocks = data.get("blocks")
    if not isinstance(blocks, list):
        # Legacy shape support
        steps = data.get("steps")
        if isinstance(steps, list):
            for step in steps:
                if not isinstance(step, dict):
                    continue
                text = str(step.get("text") or "").strip()
                if not text:
                    continue
                out.append(
                    {
                        "title": str(data.get("instructionBlockTitle") or ""),
                        "label": str(step.get("step") or ""),
                        "text": text,
                    }
                )
        return out

    for block in blocks:
        if not isinstance(block, dict):
            continue
        title = str(block.get("title") or "").strip()
        lines = block.get("lines") or []
        if not isinstance(lines, list):
            continue
        for line in lines:
            if isinstance(line, dict):
                text = str(line.get("text") or "").strip()
                label = str(line.get("step") or line.get("label") or "").strip()
            else:
                text = str(line or "").strip()
                label = ""
                m = _LINE_START.match(text)
                if m:
                    label = m.group(1)
                    text = (m.group(2) or "").strip() or text
            if not text:
                continue
            # Strip leading "1. " if still present after label parse
            m2 = _LINE_START.match(text)
            if m2 and not label:
                label = m2.group(1)
                text = (m2.group(2) or "").strip()
            out.append({"title": title, "label": label, "text": text})
    return out


def align_model_to_ocr(
    ocr_lines: list[dict[str, str]],
    model_lines: list[dict[str, str]],
) -> list[dict[str, Any]]:
    """
    Build notes from OCR lines; gate / reconcile against best-matching model line.

    Exact match → OCR text. Confusable OCR errors → model spelling, needsReview.
    Hard invent/drop → OCR text kept, needsReview + gateConflict.
    """
    used: set[int] = set()
    notes: list[dict[str, Any]] = []

    def best_model(ocr_text: str) -> tuple[int, str]:
        ocr_toks = extract_significant_tokens(ocr_text)
        best_i = -1
        best_score = 0
        for i, ml in enumerate(model_lines):
            if i in used:
                continue
            mt = extract_significant_tokens(ml.get("text") or "")
            score = len(ocr_toks & mt) if ocr_toks else 0
            # Soft score for confusable overlaps (Xi vs X1).
            if score == 0 and ocr_toks and mt:
                soft = 0
                for ot in ocr_toks:
                    if any(tokens_are_ocr_confusable(ot, m) for m in mt):
                        soft += 1
                score = soft
            if score > best_score:
                best_score = score
                best_i = i
        if best_i < 0:
            return -1, ""
        return best_i, model_lines[best_i].get("text") or ""

    if ocr_lines:
        for idx, ol in enumerate(ocr_lines):
            label = str(ol.get("label") or idx + 1).strip() or str(idx + 1)
            ocr_text = strip_leading_step_number((ol.get("text") or "").strip(), label)
            if not ocr_text:
                continue
            mi, model_text = best_model(ocr_text)
            needs_review = False
            conflict: str | None = None
            final_text = ocr_text
            if mi >= 0 and model_text:
                used.add(mi)
                model_body = strip_leading_step_number(model_text, label)
                final_text, needs_review, conflict = reconcile_ocr_with_model(
                    ocr_text, model_body
                )
            elif "[unreadable]" in ocr_text.lower():
                needs_review = True
            title = str(ol.get("title") or "").strip()
            if mi >= 0 and not title:
                title = str(model_lines[mi].get("title") or "").strip()
            note: dict[str, Any] = {
                "label": label,
                "text": final_text,
                "blockTitle": title,
                "needsReview": needs_review,
                "insight": "",
                "items": _coerce_items(None, final_text),
            }
            if conflict:
                note["gateConflict"] = conflict
            notes.append(note)
        return notes

    # No OCR lines — keep model text but force review (OCR is character authority).
    for idx, ml in enumerate(model_lines):
        text = (ml.get("text") or "").strip()
        if not text:
            continue
        label = str(ml.get("label") or idx + 1).strip() or str(idx + 1)
        text = strip_leading_step_number(text, label)
        notes.append(
            {
                "label": label,
                "text": text,
                "blockTitle": str(ml.get("title") or "").strip(),
                "needsReview": True,
                "insight": "",
                "items": _coerce_items(None, text),
                "gateConflict": "ocr_empty",
            }
        )
    return notes


def _note_needs_insight(text: str) -> bool:
    return bool(_LINK_PHRASE.search(text or ""))


def _build_note_dict(
    *,
    sheet: int,
    step_no: int,
    label: str,
    text: str,
    items: list[int],
    block_title: str,
    insight: str,
    needs_review: bool,
    source_drawing_id: int | None,
    source_filename: str,
    mind_confidence: float,
) -> dict[str, Any]:
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
        # Shop instruction stays verbatim; insight is separate.
        "elaboratedText": "",
        "insight": insight or "",
        "placement": [],
        "viewRefs": [],
        "viewUsed": "",
        "mindEngine": "local_vlm",
        "mindConfidence": mind_confidence,
        "needsVisualElaboration": False,
        "needsReview": bool(needs_review),
    }
    if block_title:
        out["blockTitle"] = block_title
        try:
            from app.route_card.extractor import is_ctq_header_text

            if is_ctq_header_text(block_title):
                out["noteKind"] = "ctq"
                out["noteSection"] = "CTQ POINTS"
            else:
                out.setdefault("noteKind", "note")
                out.setdefault("noteSection", block_title)
        except Exception:
            out.setdefault("noteKind", "note")
    else:
        out.setdefault("noteKind", "note")
    if source_drawing_id is not None:
        out["sourceDrawingId"] = source_drawing_id
    if source_filename:
        out["sourceFilename"] = source_filename
    return out


# --- Legacy helpers kept for older unit tests / CPU merge paths -------------

_AS_SHOWNISH = re.compile(
    r"\b(AS\s+SHOWN|AS\s+INDICATED|SEE\s+(?:DETAIL|VIEW|FIG)|STICK|PASTE|GLUE|BOND|ADHERE|MOUNT|PLACE|FIT)\b",
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


def _sanitize_surface_label(surface: str) -> str:
    """Keep only clear mounting-face labels; drop FRONT/REAR view titles and vague fillers."""
    from app.route_card.drawing_mind.spatial import (
        is_strong_mounting_surface,
        is_weak_surface_label,
    )

    surf = re.sub(r"\s+", " ", (surface or "").strip())
    if not surf:
        return ""
    if _WEAK_SURFACE.match(surf) or is_weak_surface_label(surf):
        return ""
    if not is_strong_mounting_surface(surf):
        return ""
    return surf


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
        surface = _sanitize_surface_label(str(p.get("surface") or ""))
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
    surface = _sanitize_surface_label(
        next((str(p.get("surface") or "") for p in placements if p.get("surface")), "")
    )
    view_bit = f" ({view_used})" if view_used else ""
    if surface:
        parts.append(f"Stick these parts on the {surface}{view_bit}.")
    else:
        parts.append(f"Stick these parts as marked on the drawing{view_bit}.")
    for p in placements:
        item = p.get("itemNo")
        offs = p.get("offsets") or []
        item_surface = _sanitize_surface_label(str(p.get("surface") or "")) or surface
        bits: list[str] = []
        for o in offs:
            frm = o.get("from")
            val = o.get("value")
            unit = o.get("unit") or "mm"
            if frm == "item" and o.get("relativeToItem") is not None:
                if val is not None:
                    bits.append(f"keep {val:g} {unit} relative to Item {o['relativeToItem']}")
            elif val is not None and frm in {"left", "right", "top", "bottom"}:
                bits.append(f"keep {val:g} {unit} from {frm}")
        if bits:
            parts.append(f"Item {item}: " + "; ".join(bits) + ".")
        elif item_surface:
            parts.append(f"Item {item}: stick on {item_surface}.")
    return " ".join(parts).strip()


def _normalize_step(step: dict[str, Any], *, sheet: int, step_no: int) -> dict[str, Any] | None:
    """Legacy step normalizer (tests). New path uses align_model_to_ocr."""
    text = str(step.get("text") or "").strip()
    if not text or len(text) < 3:
        return None
    needs = bool(step.get("needsVisualElaboration"))
    if not needs and _AS_SHOWNISH.search(text):
        needs = True
    items = _coerce_items(step.get("items"), text)
    label = str(step.get("step") or step_no).strip() or str(step_no)
    return {
        "sheet": sheet,
        "stepNo": step_no,
        "label": label,
        "text": text,
        "items": items,
        "torque": [],
        "connectors": [],
        "standards": [],
        "references": [],
        "elaboratedText": "",
        "insight": str(step.get("insight") or "").strip(),
        "placement": _normalize_placement(step.get("placement"), source_page=sheet),
        "viewRefs": [],
        "viewUsed": str(step.get("viewUsed") or "").strip(),
        "mindEngine": "local_vlm",
        "mindConfidence": 0.7,
        "needsVisualElaboration": needs,
        "needsReview": bool(step.get("needsReview")),
    }


def _vlm_notes_usable(notes: list[dict[str, Any]]) -> bool:
    if not notes:
        return False
    return any(len((n.get("text") or "").strip()) >= 8 for n in notes)


def _note_match_score(a: str, b: str) -> int:
    body = re.sub(r"\s+", " ", (a or "")).upper()[:120]
    vb = re.sub(r"\s+", " ", (b or "")).upper()[:120]
    if not body or not vb:
        return 0
    if body in vb or vb in body:
        return min(len(body), len(vb))
    return len(set(body.split()) & set(vb.split()))


def _merge_cpu_enrichment_onto_vlm(
    vlm_notes: list[dict[str, Any]],
    cpu_notes: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Keep VLM verbatim text; never wipe CPU elaboratedText / placement / viewRefs."""
    out = [dict(n) for n in vlm_notes]
    used: set[int] = set()
    for note in out:
        best_i = -1
        best_score = 0
        for i, cn in enumerate(cpu_notes):
            if i in used:
                continue
            score = _note_match_score(note.get("text") or "", cn.get("text") or "")
            if score > best_score:
                best_score = score
                best_i = i
        if best_i < 0 or best_score < 3:
            continue
        used.add(best_i)
        cn = cpu_notes[best_i]
        # Preserve CPU grounding when VLM left fields empty
        if not (note.get("elaboratedText") or "").strip() and (cn.get("elaboratedText") or "").strip():
            note["elaboratedText"] = cn["elaboratedText"]
        if not (note.get("placement") or []) and (cn.get("placement") or []):
            note["placement"] = list(cn.get("placement") or [])
        if not (note.get("viewRefs") or []) and (cn.get("viewRefs") or []):
            note["viewRefs"] = list(cn.get("viewRefs") or [])
        if not (note.get("insight") or "").strip() and (cn.get("insight") or "").strip():
            note["insight"] = cn["insight"]
        for key in ("items", "torque", "connectors", "standards", "references"):
            if not note.get(key) and cn.get(key):
                note[key] = list(cn.get(key) or [])
        if cn.get("elaborated") or note_is_enriched(note):
            note["elaborated"] = True
        # Prefer higher confidence engine tag but keep enrichment
        if cn.get("mindConfidence") and not note.get("mindConfidence"):
            note["mindConfidence"] = cn.get("mindConfidence")
    return out


def _merge_elaboration_onto_ocr(
    ocr_notes: list[dict[str, Any]],
    vlm_notes: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Keep OCR notes; attach insight when texts roughly match (fallback path)."""
    out = [dict(n) for n in ocr_notes]
    used: set[int] = set()
    for note in out:
        best_i = -1
        best_score = 0
        for i, vn in enumerate(vlm_notes):
            if i in used:
                continue
            score = _note_match_score(note.get("text") or "", vn.get("text") or "")
            if score > best_score:
                best_score = score
                best_i = i
        if best_i < 0 or best_score < 3:
            continue
        used.add(best_i)
        vn = vlm_notes[best_i]
        insight = (vn.get("insight") or "").strip()
        if insight and insight_is_safe(note.get("text") or "", insight):
            note["insight"] = insight
        note["mindEngine"] = "local_vlm"
        note["mindConfidence"] = vn.get("mindConfidence")
        if vn.get("needsReview"):
            note["needsReview"] = True
    return out


def _stage_b_grounded_placements(
    raw: dict[str, Any],
    *,
    allowed_items: set[int],
    note_text: str,
) -> list[dict[str, Any]]:
    """Accept Stage B placements only when item nos are cited and offsets are numeric."""
    del note_text
    out: list[dict[str, Any]] = []
    for p in raw.get("placements") or []:
        if not isinstance(p, dict):
            continue
        try:
            item = int(p.get("itemNo") or 0)
        except (TypeError, ValueError):
            continue
        if item <= 0:
            continue
        if allowed_items and item not in allowed_items:
            continue
        offsets = _normalize_offsets(p.get("offsets"))
        surface = _sanitize_surface_label(str(p.get("surface") or ""))
        if not offsets and not surface:
            continue
        conf = _coerce_float(p.get("confidence")) or 0.55
        out.append(
            {
                "itemNo": item,
                "surface": surface,
                "offsets": offsets,
                "confidence": max(0.0, min(conf, 0.95)),
            }
        )
    return out


def _adaptive_note_dpi(band_count: int, configured: int) -> int:
    """Lower DPI when many note bands to keep vision latency reasonable."""
    base = max(120, min(int(configured or 300), 400))
    if band_count >= 6:
        return min(base, 220)
    if band_count >= 4:
        return min(base, 280)
    return base


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
    vlm_facts = _placement_facts(vlm_placements)
    if not vlm_facts:
        return cpu_placements
    if any((_sanitize_surface_label(f.surface) or f.offsets) for f in vlm_facts):
        # Drop weak FRONT/REAR surfaces the model may still emit
        cleaned: list[PlacementFact] = []
        for f in vlm_facts:
            cleaned.append(
                PlacementFact(
                    item_no=f.item_no,
                    surface=_sanitize_surface_label(f.surface),
                    offsets=list(f.offsets or []),
                    confidence=f.confidence,
                    source_page=f.source_page,
                )
            )
        return cleaned
    return cpu_placements


class LocalVlmMind(DrawingMind):
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
        cpu_groups: list[dict[str, Any]] = list(cpu_result.assembly_groups or [])
        ocr_notes = [dict(n) for n in (cpu_result.notes or ga_extraction.get("notes") or [])]

        if not pdf_bytes:
            warnings.append("Drawing mind (local_vlm): no PDF bytes — using CPU spatial only.")
            return MindResult(
                engine="local_vlm_fallback_cpu",
                notes=ocr_notes,
                placements=cpu_placements,
                pcb_links=pcb_links,
                assembly_groups=cpu_groups,
                warnings=warnings,
            )

        base_url = getattr(settings, "OLLAMA_BASE_URL", "http://172.195.132.152:8010")
        model = getattr(settings, "OLLAMA_VLM_MODEL", "google/gemma-4-E4B-it")
        timeout = float(getattr(settings, "OLLAMA_TIMEOUT_SEC", 600) or 600)
        max_pages = int(getattr(settings, "OLLAMA_VLM_MAX_PAGES", 6) or 6)
        note_dpi_cfg = int(getattr(settings, "OLLAMA_VLM_NOTE_DPI", 300) or 300)
        note_max_edge = int(getattr(settings, "OLLAMA_VLM_NOTE_MAX_EDGE", 2400) or 2400)
        page_dpi = int(getattr(settings, "OLLAMA_VLM_DPI", 160) or 160)
        page_max_edge = int(getattr(settings, "OLLAMA_VLM_MAX_IMAGE_EDGE", 1600) or 1600)
        transcribe_max_tokens = min(
            1024, int(getattr(settings, "OLLAMA_VLM_MAX_TOKENS", 2048) or 2048)
        )

        ok, status_err = vlm_status(base_url, model=model, timeout=min(5.0, timeout))
        if not ok and not ollama_reachable(base_url, timeout=min(5.0, timeout)):
            warnings.append(
                f"Drawing mind (local_vlm): vision server not reachable at {base_url}"
                + (f" ({status_err})" if status_err else "")
                + " — using CPU spatial fallback."
            )
            return MindResult(
                engine="local_vlm_fallback_cpu",
                notes=ocr_notes,
                placements=cpu_placements,
                pcb_links=pcb_links,
                assembly_groups=cpu_groups,
                warnings=warnings,
            )
        if not ok:
            warnings.append(
                f"Drawing mind (local_vlm): vision server not ready at {base_url}"
                + (f" ({status_err})" if status_err else "")
                + " — using CPU spatial fallback."
            )
            return MindResult(
                engine="local_vlm_fallback_cpu",
                notes=ocr_notes,
                placements=cpu_placements,
                pcb_links=pcb_links,
                assembly_groups=cpu_groups,
                warnings=warnings,
            )

        # Probe band count at moderate DPI first for adaptive sizing
        try:
            probe_bands = render_note_bands(
                pdf_bytes,
                dpi=min(note_dpi_cfg, 200),
                max_pages=max_pages,
                max_edge=min(note_max_edge, 1600),
                page_indexes=page_indexes,
                cancel_event=cancel_event,
            )
        except AnalysisCancelled:
            raise
        except Exception as exc:
            warnings.append(f"Drawing mind (local_vlm): note-band render failed ({exc}) — CPU fallback.")
            return MindResult(
                engine="local_vlm_fallback_cpu",
                notes=ocr_notes,
                placements=cpu_placements,
                pcb_links=pcb_links,
                assembly_groups=cpu_groups,
                warnings=warnings,
            )

        if not probe_bands:
            warnings.append("Drawing mind (local_vlm): no note bands rendered — CPU fallback.")
            return MindResult(
                engine="local_vlm_fallback_cpu",
                notes=ocr_notes,
                placements=cpu_placements,
                pcb_links=pcb_links,
                assembly_groups=cpu_groups,
                warnings=warnings,
            )

        note_dpi = _adaptive_note_dpi(len(probe_bands), note_dpi_cfg)
        if note_dpi != min(note_dpi_cfg, 200):
            try:
                bands = render_note_bands(
                    pdf_bytes,
                    dpi=note_dpi,
                    max_pages=max_pages,
                    max_edge=note_max_edge if note_dpi >= 280 else min(note_max_edge, 2000),
                    page_indexes=page_indexes,
                    cancel_event=cancel_event,
                )
            except AnalysisCancelled:
                raise
            except Exception:
                bands = probe_bands
        else:
            bands = probe_bands

        if not bands:
            bands = probe_bands

        system_prompt = SYSTEM_PROMPT
        if prompt_addendum and str(prompt_addendum).strip():
            system_prompt = SYSTEM_PROMPT + "\n\n" + str(prompt_addendum).strip()

        page_warns: list[str] = []

        def _transcribe_band(band: dict[str, Any]) -> tuple[int, list[dict[str, Any]], list[str]]:
            """One vision call per note-band page; returns (page, aligned rows, warns)."""
            local_warns: list[str] = []
            page_no = int(band.get("page") or 1)
            check_cancelled(cancel_event)
            ocr_text = ocr_image_raw(band.get("raw") or b"")
            if not ocr_text.strip():
                local_warns.append(
                    f"Drawing mind (local_vlm): page {page_no} note-band OCR empty — model lines will need review."
                )
            prompt = TRANSCRIBE_PROMPT.format(ocr_text=ocr_text or "(no OCR text)")
            try:
                raw = chat_vision(
                    prompt=prompt,
                    images_b64=[band["b64"]],
                    model=model,
                    base_url=base_url,
                    timeout=timeout,
                    temperature=0.0,
                    system=system_prompt,
                    cancel_event=cancel_event,
                    image_mime=str(band.get("mime") or "image/jpeg"),
                    max_tokens=transcribe_max_tokens,
                )
                data = _parse_vlm_json(raw)
            except AnalysisCancelled:
                raise
            except (OllamaError, ValueError, json.JSONDecodeError) as exc:
                local_warns.append(f"VLM page {page_no}: {exc}")
                return page_no, [], local_warns

            for w in data.get("warnings") or []:
                if isinstance(w, str) and w.strip():
                    local_warns.append(f"VLM page {page_no}: {w.strip()}")

            ocr_lines = split_ocr_note_lines(ocr_text)
            model_lines = flatten_model_blocks(data)
            aligned = align_model_to_ocr(ocr_lines, model_lines)
            rows: list[dict[str, Any]] = []
            for row in aligned:
                text = str(row.get("text") or "").strip()
                if len(text) < 3:
                    continue
                rows.append({**row, "_page": page_no, "_ocr": ocr_text})
            return page_no, rows, local_warns

        # Limited parallelism (2-way) across note-band pages
        band_results: list[tuple[int, list[dict[str, Any]], list[str]]] = []
        workers = min(2, len(bands))
        if workers <= 1:
            for band in bands:
                band_results.append(_transcribe_band(band))
        else:
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futures = [pool.submit(_transcribe_band, b) for b in bands]
                for fut in as_completed(futures):
                    check_cancelled(cancel_event)
                    band_results.append(fut.result())
        band_results.sort(key=lambda t: t[0])

        vlm_notes: list[dict[str, Any]] = []
        step_counter = 0
        for page_no, rows, local_warns in band_results:
            page_warns.extend(local_warns)
            for row in rows:
                step_counter += 1
                text = str(row.get("text") or "").strip()
                needs_review = bool(row.get("needsReview"))
                if row.get("gateConflict"):
                    page_warns.append(
                        f"VLM page {page_no} step {step_counter}: token gate conflict "
                        f"'{row.get('gateConflict')}' — kept OCR text."
                    )
                elif row.get("needsReview"):
                    page_warns.append(
                        f"VLM page {page_no} step {step_counter}: OCR confusable fix "
                        f"applied — needs review."
                    )
                if "[unreadable]" in text.lower():
                    needs_review = True

                insight = ""
                if _note_needs_insight(text) and not needs_review:
                    try:
                        insight_raw = chat_text(
                            prompt=INSIGHT_PROMPT.format(note_text=text),
                            model=model,
                            base_url=base_url,
                            timeout=timeout,
                            temperature=0.0,
                            system=system_prompt,
                            cancel_event=cancel_event,
                            max_tokens=256,
                        )
                        insight_data = _parse_vlm_json(insight_raw)
                        candidate = str(insight_data.get("insight") or "").strip()
                        if candidate and insight_is_safe(text, candidate):
                            insight = candidate
                        elif candidate:
                            page_warns.append(
                                f"VLM page {page_no} step {step_counter}: insight dropped (new tokens)."
                            )
                    except AnalysisCancelled:
                        raise
                    except (OllamaError, ValueError, json.JSONDecodeError) as exc:
                        page_warns.append(f"VLM insight step {step_counter}: {exc}")

                conf = 0.95 if not needs_review else 0.4
                vlm_notes.append(
                    _build_note_dict(
                        sheet=page_no,
                        step_no=step_counter,
                        label=str(row.get("label") or step_counter),
                        text=text,
                        items=list(row.get("items") or []),
                        block_title=str(row.get("blockTitle") or ""),
                        insight=insight,
                        needs_review=needs_review,
                        source_drawing_id=source_drawing_id,
                        source_filename=source_filename,
                        mind_confidence=conf,
                    )
                )

        warnings.extend(page_warns)

        if _vlm_notes_usable(vlm_notes):
            notes = _merge_cpu_enrichment_onto_vlm(vlm_notes, ocr_notes)
            engine = self.engine
            warnings.append(
                f"Drawing mind (local_vlm): extracted {len(notes)} verbatim note line(s) "
                f"from {len(bands)} note-band image(s); CPU enrichment merged."
            )
        else:
            notes = _merge_elaboration_onto_ocr(ocr_notes, vlm_notes)
            engine = "local_vlm_partial" if vlm_notes else "local_vlm_fallback_cpu"
            if not vlm_notes:
                warnings.append(
                    "Drawing mind (local_vlm): no usable instruction steps from vision — kept OCR/CPU notes."
                )
            else:
                warnings.append(
                    "Drawing mind (local_vlm): vision steps sparse — merged onto OCR notes."
                )

        # Stage B: full-page vision for AS SHOWN / DETAIL cues (additive)
        stage_b_placements: list[dict[str, Any]] = []
        stage_b_notes = [n for n in notes if needs_stage_b_vision(n.get("text") or "")]
        if stage_b_notes and pdf_bytes:
            try:
                pages_needed = sorted(
                    {
                        int(n.get("sheet") or 1)
                        for n in stage_b_notes
                        if int(n.get("sheet") or 1) > 0
                    }
                )[:max_pages]
                page_imgs = render_pdf_pages(
                    pdf_bytes,
                    dpi=page_dpi,
                    max_pages=max_pages,
                    max_edge=page_max_edge,
                    page_indexes=pages_needed or page_indexes,
                    cancel_event=cancel_event,
                )
                by_page = {int(p["page"]): p for p in page_imgs}
                for note in stage_b_notes:
                    check_cancelled(cancel_event)
                    if note.get("placement"):
                        continue  # CPU already grounded placement
                    page_no = int(note.get("sheet") or 1)
                    img = by_page.get(page_no)
                    if not img:
                        continue
                    items = [int(i) for i in (note.get("items") or []) if str(i).isdigit() or isinstance(i, int)]
                    try:
                        raw_b = chat_vision(
                            prompt=STAGE_B_PROMPT.format(
                                note_text=note.get("text") or "",
                                items_csv=", ".join(str(i) for i in items) or "(none)",
                            ),
                            images_b64=[img["b64"]],
                            model=model,
                            base_url=base_url,
                            timeout=timeout,
                            temperature=0.0,
                            system=system_prompt,
                            cancel_event=cancel_event,
                            image_mime=str(img.get("mime") or "image/jpeg"),
                            max_tokens=512,
                        )
                        data_b = _parse_vlm_json(raw_b)
                    except AnalysisCancelled:
                        raise
                    except (OllamaError, ValueError, json.JSONDecodeError) as exc:
                        warnings.append(f"VLM Stage B page {page_no}: {exc}")
                        continue
                    placed = _stage_b_grounded_placements(
                        data_b,
                        allowed_items=set(items),
                        note_text=str(note.get("text") or ""),
                    )
                    if placed:
                        for p in placed:
                            p["sourcePage"] = page_no
                        note["placement"] = placed
                        note["needsVisualElaboration"] = False
                        stage_b_placements.extend(placed)
                        composed = _compose_elaboration_from_placement(
                            note.get("text") or "", placed
                        )
                        if composed and not _is_weak_elaboration(composed):
                            # Placement elaboration only — no "(From drawing: …)" suffix
                            # (verbatim stays in note["text"]; route gen uses elaborated flag).
                            note["elaboratedText"] = composed
                            note["elaborated"] = True
                if stage_b_placements:
                    warnings.append(
                        f"Drawing mind (local_vlm): Stage B grounded {len(stage_b_placements)} placement(s)."
                    )
            except AnalysisCancelled:
                raise
            except Exception as exc:
                warnings.append(f"Drawing mind (local_vlm): Stage B skipped ({exc}).")

        # Stage C: balloon / callout assembly groups (full-page vision + PL gate)
        assembly_groups: list[dict[str, Any]] = list(cpu_groups)
        try:
            from app.route_card.drawing_mind.assembly_groups import (
                dedupe_groups,
                extract_assembly_groups_from_page,
                filter_weak_groups,
                groups_to_synthetic_notes,
                merge_continuation_groups,
                merge_notes_with_balloon_notes,
                scan_text_for_clusters,
                validate_assembly_group,
                pl_item_set,
            )

            pl_nos = pl_item_set(parts_list)
            stage_c_tokens = min(
                2048, int(getattr(settings, "OLLAMA_VLM_MAX_TOKENS", 2048) or 2048)
            )
            page_imgs_c = render_pdf_pages(
                pdf_bytes,
                dpi=page_dpi,
                max_pages=max_pages,
                max_edge=page_max_edge,
                page_indexes=page_indexes,
                cancel_event=cancel_event,
            )
            vlm_groups: list[dict[str, Any]] = []
            for img in page_imgs_c:
                check_cancelled(cancel_event)
                page_no = int(img.get("page") or 1)
                try:
                    groups_page, c_warns = extract_assembly_groups_from_page(
                        image_b64=img["b64"],
                        image_mime=str(img.get("mime") or "image/jpeg"),
                        parts_list=parts_list,
                        page_no=page_no,
                        model=model,
                        base_url=base_url,
                        timeout=timeout,
                        max_tokens=stage_c_tokens,
                        cancel_event=cancel_event,
                        source_drawing_id=source_drawing_id,
                        source_filename=source_filename,
                        system=system_prompt,
                    )
                    vlm_groups.extend(groups_page)
                    warnings.extend(
                        f"VLM Stage C page {page_no}: {w}" for w in c_warns if w
                    )
                except AnalysisCancelled:
                    raise
                except (OllamaError, ValueError, json.JSONDecodeError) as exc:
                    warnings.append(f"VLM Stage C page {page_no}: {exc}")

            # OCR/raw-text salvage — always run; dedupe unions children with VLM
            blob = (ga_extraction.get("raw_text") or "") + "\n" + "\n".join(
                str(n.get("text") or "") for n in notes
            )
            for g in scan_text_for_clusters(blob, parts_list=parts_list):
                ng = validate_assembly_group(
                    g,
                    pl_nos,
                    source_page=int(g.get("sourcePage") or 1),
                    source_drawing_id=source_drawing_id,
                    source_filename=source_filename,
                )
                if ng:
                    ng.pop("warnings", None)
                    vlm_groups.append(ng)

            assembly_groups = dedupe_groups(list(cpu_groups) + vlm_groups)
            assembly_groups, mwarns = merge_continuation_groups(
                assembly_groups, parts_list=parts_list
            )
            warnings.extend(f"VLM Stage C: {w}" for w in mwarns if w)
            assembly_groups, fwarns = filter_weak_groups(
                assembly_groups, parts_list=parts_list
            )
            warnings.extend(f"VLM Stage C: {w}" for w in fwarns if w)
            if assembly_groups:
                balloon_notes = groups_to_synthetic_notes(
                    assembly_groups, parts_list=parts_list
                )
                notes = merge_notes_with_balloon_notes(notes, balloon_notes)
                warnings.append(
                    f"Drawing mind (local_vlm): Stage C found {len(assembly_groups)} "
                    f"balloon assembly group(s)."
                )
        except AnalysisCancelled:
            raise
        except Exception as exc:
            warnings.append(f"Drawing mind (local_vlm): Stage C skipped ({exc}).")
            assembly_groups = list(cpu_groups)

        unit = (ga_extraction.get("title_block") or {}).get("unit") or "mm"
        notes = apply_grounded_elaboration(
            notes,
            ga_extraction=ga_extraction,
            parts_list=parts_list,
            unit=unit,
            engine=engine,
        )

        placements = _prefer_vlm_placements(cpu_placements, stage_b_placements)

        for note in notes:
            if note_is_enriched(note):
                note["elaborated"] = True
            if source_drawing_id is not None and "sourceDrawingId" not in note:
                note["sourceDrawingId"] = source_drawing_id
            if source_filename and not note.get("sourceFilename"):
                note["sourceFilename"] = source_filename

        return MindResult(
            engine=engine,
            notes=notes,
            placements=placements,
            pcb_links=pcb_links,
            assembly_groups=assembly_groups,
            warnings=warnings,
        )
