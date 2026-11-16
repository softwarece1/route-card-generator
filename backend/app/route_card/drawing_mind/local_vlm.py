"""Local VLM DrawingMind — verbatim NOTE transcription + optional insight."""

from __future__ import annotations

import json
import re
from typing import Any

from app.route_card.analyze_jobs import AnalysisCancelled, check_cancelled
from app.route_card.drawing_mind.base import DrawingMind
from app.route_card.drawing_mind.cpu_spatial import CpuSpatialMind
from app.route_card.drawing_mind.ollama_client import (
    OllamaError,
    chat_text,
    chat_vision,
    ollama_reachable,
)
from app.route_card.drawing_mind.page_images import ocr_image_raw, render_note_bands
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

Copy every numbered instruction line under NOTE, NOTE I, NOTE II, NOTES, ASSEMBLY INSTRUCTIONS, CTQ, REMARKS, or similar.
Keep the drawing spelling, punctuation, ranges, and part numbers exactly.
Do not simplify English. Do not "correct" words (RoHS, ENAMELED, BARE, FACIA, etc.).
Do not merge lines. Do not drop a line. Do not invent a component value, item, connector, or size.
If a glyph is unreadable after checking OCR and the image, write [unreadable] in that span.

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
_NOTE_TITLE = re.compile(r"^\s*(NOTE(?:\s*[IVX]+)?|NOTES|ASSEMBLY\s+INSTRUCTIONS|CTQ|REMARKS)\b.*$", re.I)
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
    for p in placements:
        item = p.get("itemNo")
        offs = p.get("offsets") or []
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
        elif surface:
            parts.append(f"Item {item}: stick on {surface}.")
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


def _merge_elaboration_onto_ocr(
    ocr_notes: list[dict[str, Any]],
    vlm_notes: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Keep OCR notes; attach insight when texts roughly match (fallback path)."""
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
                score = len(set(body.split()) & set(vb.split()))
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
    if any((f.surface and not _WEAK_SURFACE.match(f.surface)) or f.offsets for f in vlm_facts):
        return vlm_facts
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

        base_url = getattr(settings, "OLLAMA_BASE_URL", "http://172.195.132.152:8010")
        model = getattr(settings, "OLLAMA_VLM_MODEL", "google/gemma-4-E4B-it")
        timeout = float(getattr(settings, "OLLAMA_TIMEOUT_SEC", 600) or 600)
        max_pages = int(getattr(settings, "OLLAMA_VLM_MAX_PAGES", 6) or 6)
        note_dpi = int(getattr(settings, "OLLAMA_VLM_NOTE_DPI", 300) or 300)
        note_max_edge = int(getattr(settings, "OLLAMA_VLM_NOTE_MAX_EDGE", 2400) or 2400)

        if not ollama_reachable(base_url, timeout=min(5.0, timeout)):
            warnings.append(
                f"Drawing mind (local_vlm): vision server not reachable at {base_url} — using CPU spatial fallback."
            )
            return MindResult(
                engine="local_vlm_fallback_cpu",
                notes=ocr_notes,
                placements=cpu_placements,
                pcb_links=pcb_links,
                warnings=warnings,
            )

        try:
            bands = render_note_bands(
                pdf_bytes,
                dpi=note_dpi,
                max_pages=max_pages,
                max_edge=note_max_edge,
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
                warnings=warnings,
            )

        if not bands:
            warnings.append("Drawing mind (local_vlm): no note bands rendered — CPU fallback.")
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

        for band in bands:
            check_cancelled(cancel_event)
            page_no = int(band.get("page") or 1)
            ocr_text = ocr_image_raw(band.get("raw") or b"")
            if not ocr_text.strip():
                page_warns.append(
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

            ocr_lines = split_ocr_note_lines(ocr_text)
            model_lines = flatten_model_blocks(data)
            aligned = align_model_to_ocr(ocr_lines, model_lines)

            for row in aligned:
                step_counter += 1
                text = str(row.get("text") or "").strip()
                if len(text) < 3:
                    step_counter -= 1
                    continue
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
            notes = vlm_notes
            engine = self.engine
            warnings.append(
                f"Drawing mind (local_vlm): extracted {len(notes)} verbatim note line(s) "
                f"from {len(bands)} note-band image(s)."
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

        placements = _prefer_vlm_placements(cpu_placements, [])

        for note in notes:
            if source_drawing_id is not None and "sourceDrawingId" not in note:
                note["sourceDrawingId"] = source_drawing_id
            if source_filename and not note.get("sourceFilename"):
                note["sourceFilename"] = source_filename

        return MindResult(
            engine=engine,
            notes=notes,
            placements=placements,
            pcb_links=pcb_links,
            warnings=warnings,
        )
