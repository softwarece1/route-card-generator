"""Balloon/callout assembly groups + LLM route generation helpers.

Stage C: extract GA balloon clusters like ``480, 230x4, 340x4`` into structured
assembly groups validated against the Parts List.

Stage D: ask the VLM for a full ordered route from NOTES + groups + PL.
"""

from __future__ import annotations

import json
import re
from typing import Any

from app.route_card.drawing_mind.ollama_client import chat_text, chat_vision

# 480 | 230x4 | 230×4 | 230 X4 | 230 x 4 | 230-4 | (460)
_CALLOUT_TOKEN = re.compile(
    r"\(\s*(\d{1,4})\s*\)|"
    r"(\d{1,4})(?:\s*[x×X]\s*(\d{1,4})|\s*-\s*(\d{1,4}))?"
)
# Standalone OCR bleed like "X4" / "×80" immediately after a bare item (handled via normalize)
_STANDALONE_QTY = re.compile(r"^\s*[x×X]\s*(\d{1,4})\s*$")
_JSON_FENCE = re.compile(r"```(?:json)?\s*([\s\S]*?)```", re.I)

STAGE_C_PROMPT = """You are viewing a GA assembly drawing page with balloon / item callouts.

Parts List item numbers that exist for this job (use ONLY these numbers):
{pl_items}

READING ORDER: the sheet is zoned like a drawing border.
Columns 1, 2, 3 … run left to right. Rows A, B, C … run top to bottom.
Scan zone A1, then across the top row, then row B left to right, and so on.
Return groups in that order. Do not skip a balloon because it is small.

Find every balloon/callout cluster on the page. Typical forms:
- 480, 230x4, 340x4, 350x4, 260x2  → parent 480; children 230×4, 340×4, 350×4, 260×2
- 40, 430x80, 380x80, 390x80  → parent 40; children with subscript qtys
- 50x4, 430x8, 380x8, 390x8  → parent 50 qty 4; children with subscript qtys
- 230-4  or  45-1, 13-2, 14-2  → hyphen item-qty (same meaning as xN)
- a balloon that is only one number, or only (460) / (470) → individual item.
  Assemble that item alone. children must be []. It is NOT the parent of a
  comma list printed nearby.
- comma-separated list → FIRST number is the item being made; every later
  number is a sub-item used to make that first item.

BALLOON POINTS (critical — stacked leaders are separate):
- Each leader/balloon on the drawing is its OWN group/point. If one balloon
  sits below another (e.g. 450/300/400/410 above, and 80/520/250/340/350 below),
  return TWO groups — never merge them just because they are vertically stacked.
- One leader may wrap to a second LINE of item numbers (line1 "450, 300x8" +
  line2 "400x8, 410x8"). Keep those lines on the SAME group (put both in
  rawText / children). Do not invent a separate group for the fastener-only
  second line alone (it would be dropped).

QUANTITY RULES (critical):
- Every non-parent balloon token MUST include its visible subscript/multiplier qty
  (forms: xN, ×N, XN, -N, or small stacked digits under the item number).
- Put those multipliers in BOTH children[].qty AND rawText (e.g. "40, 430x80, 380x80").
- Do NOT invent qty=1 unless the drawing literally shows 1 or has no multiplier.
- Do NOT drop subscripts from rawText.
- If the parent itself shows a multiplier (50x4 / 50-4), set parentQty.

Do NOT invent item numbers that are not visible. Do NOT invent PL rows.
If a cluster is ambiguous, lower confidence and still return the raw text with multipliers.

Return JSON only:
{{
  "groups": [
    {{
      "parentItemNo": 480,
      "children": [{{"itemNo": 230, "qty": 4}}, {{"itemNo": 340, "qty": 4}}],
      "rawText": "480, 230x4, 340x4, 350x4, 260x2",
      "confidence": 0.85
    }}
  ],
  "warnings": []
}}

If no callout clusters are visible, return {{"groups": [], "warnings": []}}.
"""

# One zone tile (row letter × column band). Subscripts are large enough to read.
ZONE_C_PROMPT = """You are reading ONE zone of a GA assembly drawing. This image is only that zone.

ZONE
- Row {row} — {row_hint}
  Rows are lettered A, B, C, D from the TOP of the sheet downward.
- Columns {col_lo}–{col_hi} — {col_hint}
  Columns are numbered 1, 2, 3 … from the LEFT of the sheet.
- Read every balloon in this crop from LEFT to RIGHT, then TOP to BOTTOM.
  Do not skip a callout. A short stack of item numbers on a leader still counts.

A balloon is a leader with item numbers. A small subscript sits under or beside
each number (x4, x8, x40, x80, x2, ×8, or 230-4). That subscript belongs ONLY
to the number it sits under. Never move it onto the neighbour.

GROUPING
1. One leader = one group. A separate leader below is a NEW group, even if the
   item numbers look similar.
2. SINGLE item — the balloon shows only one number, or only (470) / (460):
   individual item, no sub-items. Return children: [] and "individual": true.
   Assemble that item only. Do not pull numbers from a comma list next to it.
3. COMMA list — "480, 230, 340" or "50x4, 430x8, 380x8, 390x8":
   the FIRST number is the item being made. Every later number is a sub-item
   used to make that first item.
4. If the first number has its own subscript (50x4, 40x40, 80x4, 530x10),
   that value is parentQty (how many of the parent). Do not copy it onto children.
5. A second line on the SAME leader (same arrow, directly underneath) stays in
   that group. Example: "450, 300x8" with "400x8, 410x8" under it is ONE group,
   parent 450, children 300×8, 400×8, 410×8.
6. "(470)" or "(460)" printed near a comma list is its OWN single-item balloon.
   It is not the parent of the list above it.

QUANTITIES — copy every digit you see
- x40 is forty, never 4. x80 is eighty, never 8. x8 is eight, never 80 and never 4.
  x2 is two, never 4. x10 is ten, never 1.
- If no subscript is visible under an item, qty is 1. Do not invent 4 or 8.
- Write the same multipliers in rawText, e.g. "40x40, 430x80, 380x80, 390x80"
  or "480, 230x4, 340x4, 350x4, 260x2".

IGNORE notes, the title block, SECTION titles, dimensions, and anything that is
not a balloon. Do not invent item numbers that are not visible in this crop.
Parts List numbers (use only to reject a number you cannot see; do not add rows):
{pl_items}

Return JSON only, groups in left-to-right then top-to-bottom order:
{{
  "groups": [
    {{
      "parentItemNo": 50,
      "parentQty": 4,
      "individual": false,
      "children": [
        {{"itemNo": 430, "qty": 8}},
        {{"itemNo": 380, "qty": 8}},
        {{"itemNo": 390, "qty": 8}}
      ],
      "rawText": "50x4, 430x8, 380x8, 390x8",
      "confidence": 0.9
    }}
  ],
  "warnings": []
}}
If this zone has no balloons, return {{"groups": [], "warnings": []}}.
"""

_ROW_HINTS = {
    "A": "top band of the sheet",
    "B": "upper-middle band",
    "C": "lower-middle band",
    "D": "bottom band of the sheet",
}
_COL_HINTS = {
    (1, 4): "left side of the sheet",
    (5, 8): "middle of the sheet",
    (9, 12): "right side of the sheet",
}

QTY_REPAIR_PROMPT = """You are reading subscript / multiplier quantities next to balloon item numbers
on a GA assembly drawing page.

For EACH of these item numbers only, read the visible qty marker (xN, ×N, -N, or stacked digits).
If no multiplier is visible, use qty 1.

Item numbers: {item_nos}

Return JSON only:
{{
  "quantities": [{{"itemNo": 230, "qty": 4}}, {{"itemNo": 340, "qty": 4}}],
  "warnings": []
}}
"""

_FASTENER_RE = re.compile(
    r"\b(?:SCREW|BOLT|NUT|WASHER|FASTENER|STUD|RIVET|STANDOFF|PIN|CSK|HEX|SCR)\b",
    re.I,
)
_QTY_MARKER_RE = re.compile(
    r"\d{1,4}\s*[x×X]\s*\d{1,4}|\d{1,4}\s*-\s*\d{1,4}"
)

STAGE_D_PROMPT = """You are a manufacturing route-card planner for BEL-style GA + Parts List packs.

Build a complete ordered list of shop assembly operations that covers the Parts List
as fully as possible. Prefer drawing evidence (NOTES + balloon assembly groups).

NOTES (verbatim shop instructions):
-----
{notes_text}
-----

Balloon assembly groups (parent item + fastener/hardware children with qty):
-----
{groups_json}
-----

Parts List (itemNo | qty | description):
-----
{pl_text}
-----

PL items not yet cited in NOTES/groups (coverage gaps — try to cover when drawing evidence exists):
{pl_gaps}

Rules:
- Every itemsUsed.itemNo MUST appear on the Parts List above.
- Use balloon groups to create assemble steps (parent + children with qty).
- Keep NOTES / ASSEMBLY INSTRUCTIONS content as ops (do not drop bonding/leak/cable notes).
- Do NOT create shop ops from CTQ / Critical-To-Quality points — those are quality checks only (omitted from NOTES above).
- Do not invent part numbers or items.
- opNo: 10, 20, 30...
- instruction: clear operator bullets; cite Item No. and qty.

Return JSON only:
{{
  "operations": [
    {{
      "opNo": 10,
      "operation": "short name",
      "instruction": "• …",
      "itemsUsed": [{{"itemNo": 480, "qty": 1}}, {{"itemNo": 230, "qty": 4}}],
      "inspection": "Visual",
      "reference": ""
    }}
  ],
  "warnings": []
}}
"""


def _parse_json(raw: str) -> dict[str, Any]:
    text = (raw or "").strip()
    m = _JSON_FENCE.search(text)
    if m:
        text = m.group(1).strip()
    # Trim leading chatter before first {
    brace = text.find("{")
    if brace > 0:
        text = text[brace:]
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("JSON root must be an object")
    return data


def pl_item_set(parts_list: dict[str, Any] | None) -> set[int]:
    nos: set[int] = set()
    if not parts_list:
        return nos
    for it in parts_list.get("items") or []:
        try:
            nos.add(int(it.get("itemNo") or it.get("item_no") or it.get("no")))
        except (TypeError, ValueError):
            continue
    for k in parts_list.get("itemMap") or {}:
        try:
            nos.add(int(k))
        except (TypeError, ValueError):
            continue
    return nos


def format_pl_for_prompt(parts_list: dict[str, Any] | None, *, limit: int = 120) -> str:
    rows: list[str] = []
    items = list((parts_list or {}).get("items") or [])
    for it in items[:limit]:
        try:
            ino = int(it.get("itemNo") or it.get("item_no") or 0)
        except (TypeError, ValueError):
            continue
        if not ino:
            continue
        qty = it.get("qty") or ""
        desc = re.sub(r"\s+", " ", str(it.get("description") or ""))[:60]
        rows.append(f"{ino} | {qty} | {desc}")
    return "\n".join(rows) if rows else "(no parts list)"


def format_pl_ids_csv(parts_list: dict[str, Any] | None, *, limit: int = 160) -> str:
    nos = sorted(pl_item_set(parts_list))[:limit]
    return ", ".join(str(n) for n in nos) if nos else "(none)"


def raw_has_qty_markers(raw: str) -> bool:
    return bool(_QTY_MARKER_RE.search(str(raw or "")))


_CALLOUT_LINE_RE = re.compile(
    r"^[\s,]*\(?\d{1,4}\)?(?:\s*[x×X\-]\s*\d{1,4})?"
    r"(?:\s*,\s*\(?\d{1,4}\)?(?:\s*[x×X\-]\s*\d{1,4})?)*[\s,]*$"
)
_QTY_ONLY_LINE_RE = re.compile(r"^(?:\s*[x×X]\s*\d{1,4}\s*,?\s*)+$", re.I)


def _is_qty_only_line(ln: str) -> bool:
    s = (ln or "").strip()
    if not s:
        return False
    if _QTY_ONLY_LINE_RE.match(s) or _STANDALONE_QTY.match(s):
        return True
    parts = [p.strip() for p in re.split(r"\s*,\s*", s) if p.strip()]
    return bool(parts) and all(_STANDALONE_QTY.match(p) for p in parts)


def _apply_qty_row_to_tokens(tokens: list[str], qty_line: str) -> None:
    """Map a stacked ``x4, x8, x8`` row onto the trailing bare item run (L→R)."""
    qtys = [m.group(1) for m in re.finditer(r"[x×X]\s*(\d{1,4})", qty_line)]
    if not qtys or not tokens:
        return
    run: list[int] = []
    for j in range(len(tokens) - 1, -1, -1):
        if re.fullmatch(r"\(?\d{1,4}\)?", tokens[j]):
            run.append(j)
        else:
            break
    run.reverse()
    # Fewer qtys than items → align right (subscripts sit under trailing numbers)
    if len(qtys) < len(run):
        run = run[-len(qtys) :]
    for idx, q in zip(run, qtys):
        tokens[idx] = f"{tokens[idx]}x{q}"


def _tokens_from_item_line(ln: str) -> list[str]:
    return [p.strip() for p in re.split(r"\s*,\s*", (ln or "").strip()) if p.strip()]


def _line_is_continuation(
    tokens: list[str],
    *,
    pl_lookup: dict[int, dict[str, Any]] | None = None,
) -> bool:
    """True when this line continues the balloon above (fastener row), not a new point.

    Stacked leaders are separate points — e.g. the ``80,520,250`` balloon below
    ``450,300`` must NOT merge into it. Continuation lines are typically short
    washer/screw rows (``400x8, 410x8`` / ``340x8, 350x8``).
    """
    if not tokens:
        return False
    items: list[int] = []
    for t in tokens:
        m = re.match(r"\(?(\d{1,4})\)?", t)
        if m:
            try:
                items.append(int(m.group(1)))
            except ValueError:
                continue
    if not items:
        return False
    if pl_lookup:
        return all(_is_fastener_like(i, pl_lookup) for i in items)
    # No PL: continuation = short all-qty row (washer pair). A new balloon often
    # starts with a bare parent (450, 300x8) or a longer qty row (80x4, 520x8, 250x8).
    first = tokens[0]
    if re.fullmatch(r"\(?\d{1,4}\)?", first):
        return False
    if len(tokens) <= 2 and all(raw_has_qty_markers(t) or re.search(r"[x×X\-]\d", t) for t in tokens):
        return True
    return False


def _materialize_callout_point_lines(
    text: str,
) -> list[list[str]]:
    """OCR lines → list of token-rows (each drawing line = one point row).

    Applies a following ``x4, x8`` qty-only row onto the item line above it.
    Does not merge separate balloons.
    """
    lines = [ln.strip() for ln in re.split(r"[\n;]+", str(text or "")) if ln.strip()]
    point_rows: list[list[str]] = []
    pending: list[str] | None = None

    def flush() -> None:
        nonlocal pending
        if pending:
            point_rows.append(pending)
            pending = None

    for ln in lines:
        if _is_qty_only_line(ln):
            if pending is not None:
                _apply_qty_row_to_tokens(pending, ln)
            continue
        if _CALLOUT_LINE_RE.match(ln):
            flush()
            pending = _tokens_from_item_line(ln)
            continue
        flush()
    flush()
    return point_rows


def split_stacked_balloon_clusters(
    text: str,
    *,
    parts_list: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Split OCR into distinct balloon points (stacked leaders stay separate).

    Within one leader, line-2 fastener rows stay with that balloon. A new
    assembly line below starts a new point — never merge ``80…`` into ``450…``.

    Returns ``[{rawText, lines: [lineStr, …]}, …]``.
    """
    pl_lookup = _pl_lookup(parts_list) if parts_list else {}
    rows = _materialize_callout_point_lines(text)
    if not rows:
        raw = str(text or "").strip()
        return [{"rawText": raw, "lines": [raw]}] if raw else []

    balloons: list[dict[str, Any]] = []
    cur_lines: list[str] = []

    def flush() -> None:
        nonlocal cur_lines
        if not cur_lines:
            return
        balloons.append(
            {
                "rawText": ", ".join(cur_lines),
                "lines": list(cur_lines),
            }
        )
        cur_lines = []

    for tokens in rows:
        line_str = ", ".join(tokens)
        if not cur_lines:
            cur_lines.append(line_str)
            continue
        if _line_is_continuation(tokens, pl_lookup=pl_lookup or None):
            cur_lines.append(line_str)
        else:
            flush()
            cur_lines.append(line_str)
    flush()
    return balloons


def _glue_multiline_callout(text: str) -> str:
    """Join lines that belong to ONE balloon (qty rows + wrap).

    For page OCR that may contain several stacked balloons, prefer
    ``split_stacked_balloon_clusters`` first. This helper only flattens a
    single already-scoped cluster (or a lone multi-line rawText).
    """
    clusters = split_stacked_balloon_clusters(text)
    if not clusters:
        return str(text or "")
    # If caller passed a single balloon, flatten its lines; if several slipped
    # in, keep the first only here — scan_text expands all clusters.
    return clusters[0]["rawText"]


def _attach_standalone_qtys(parts: list[str]) -> list[str]:
    """Attach bare xN / ×N tokens to the nearest preceding item that lacks a qty."""
    fixed: list[str] = []
    for p in parts:
        p = p.strip()
        if not p:
            continue
        mq = _STANDALONE_QTY.match(p)
        if mq:
            attached = False
            for i in range(len(fixed) - 1, -1, -1):
                tok = fixed[i]
                if re.fullmatch(r"\(?\d{1,4}\)?", tok):
                    fixed[i] = f"{tok}x{mq.group(1)}"
                    attached = True
                    break
            if not attached:
                fixed.append(p)
            continue
        fixed.append(p)
    return fixed


def _normalize_callout_raw(raw: str) -> str:
    """Normalize OCR qty bleed (unicode ×, spaced x, multiline wrap, trailing bare XN)."""
    text = _glue_multiline_callout(raw)
    # If glue left multiple non-callout lines, normalize only the callout-ish spans
    text = text.replace("×", "x").replace("Ｘ", "x")
    text = re.sub(r"([xX])\s+(\d{1,4})", r"\1\2", text)
    # Prefer the densest callout span when extra prose remains
    if "\n" in text:
        best = ""
        for chunk in text.splitlines():
            if _CALLOUT_LINE_RE.match(chunk.strip()) and len(chunk) > len(best):
                best = chunk.strip()
        if best:
            text = best
    parts = re.split(r"\s*,\s*", text)
    fixed = _attach_standalone_qtys(parts)
    return re.sub(r"\s+", " ", ", ".join(fixed)).strip(" ,;")


def parse_callout_cluster(raw: str) -> dict[str, Any] | None:
    """Parse a single callout cluster string into parent/children/references.

    Supports ``230x4``, ``230×4``, ``230-4``, multiline wraps, and parent qty
    (``50x4, 430x8…`` or hyphen ``45-1, 13-2…``).
    """
    text = _normalize_callout_raw(raw)
    if not text:
        return None
    parent: int | None = None
    parent_qty: int | None = None
    children: list[dict[str, Any]] = []
    references: list[int] = []
    seen_child: set[int] = set()

    tokens: list[tuple[str, int, int | None]] = []
    for m in _CALLOUT_TOKEN.finditer(text):
        if m.group(1):  # parenthetical
            try:
                references.append(int(m.group(1)))
            except ValueError:
                continue
            continue
        try:
            item = int(m.group(2))
        except (TypeError, ValueError):
            continue
        qty_s = m.group(3) or m.group(4)
        qty: int | None = None
        if qty_s:
            try:
                qty = int(qty_s)
            except ValueError:
                qty = 1
        tokens.append(("item", item, qty))

    def _add_child(item: int, qty: int) -> None:
        if item == parent:
            return
        if item not in seen_child:
            children.append({"itemNo": item, "qty": qty})
            seen_child.add(item)
            return
        for ch in children:
            if int(ch["itemNo"]) == item and qty > int(ch.get("qty") or 1):
                ch["qty"] = qty

    for kind, item, qty in tokens:
        if kind != "item":
            continue
        if qty is not None:
            if parent is None and not children:
                # First token carries qty → parent with parentQty (50x4 / 45-1 style)
                parent = item
                parent_qty = qty if qty >= 1 else 1
            else:
                _add_child(item, qty if qty >= 1 else 1)
        else:
            if parent is None:
                parent = item
            else:
                _add_child(item, 1)

    if parent is None and not children and not references:
        return None
    # All-qty tokens with no bare parent: first became parent above.
    # Legacy path if somehow only children (should not happen with new rule).
    if parent is None and children:
        first = children.pop(0)
        parent = int(first["itemNo"])
        try:
            parent_qty = int(first.get("qty") or 1)
        except (TypeError, ValueError):
            parent_qty = 1
    if parent is None and references:
        return {
            "parentItemNo": None,
            "parentQty": None,
            "children": [],
            "references": references,
            "rawText": text,
            "confidence": 0.55,
            "referenceOnly": True,
        }
    if parent is None:
        return None
    out: dict[str, Any] = {
        "parentItemNo": parent,
        "children": children,
        "references": references,
        "rawText": text,
        "confidence": 0.7,
        "referenceOnly": False,
    }
    if parent_qty is not None:
        out["parentQty"] = parent_qty
    return out


def _pl_lookup(parts_list: dict[str, Any] | None) -> dict[int, dict[str, Any]]:
    lookup: dict[int, dict[str, Any]] = {}
    if not parts_list:
        return lookup
    for it in parts_list.get("items") or []:
        if not isinstance(it, dict):
            continue
        try:
            lookup[int(it.get("itemNo") or it.get("item_no") or it.get("no"))] = it
        except (TypeError, ValueError):
            continue
    for k, v in (parts_list.get("itemMap") or {}).items():
        try:
            ik = int(k)
        except (TypeError, ValueError):
            continue
        if isinstance(v, dict):
            lookup.setdefault(ik, v)
    return lookup


def _is_fastener_like(item_no: int, pl_lookup: dict[int, dict[str, Any]]) -> bool:
    hit = pl_lookup.get(int(item_no)) or {}
    desc = str(hit.get("description") or "")
    pno = str(hit.get("partNumber") or "")
    return bool(_FASTENER_RE.search(desc) or _FASTENER_RE.search(pno))


def _merge_children_prefer_parsed_qty(
    model_children: list[dict[str, Any]] | None,
    parsed_children: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    """Prefer qty from rawText parse when higher / when model defaulted to 1."""
    by_no: dict[int, dict[str, Any]] = {}
    for src in (model_children or [], parsed_children or []):
        for ch in src:
            if not isinstance(ch, dict):
                continue
            try:
                ino = int(ch.get("itemNo"))
                qty = int(ch.get("qty") or 1)
            except (TypeError, ValueError):
                continue
            if qty < 1:
                qty = 1
            prev = by_no.get(ino)
            if not prev or qty > int(prev.get("qty") or 1):
                by_no[ino] = {"itemNo": ino, "qty": qty}
    return [by_no[k] for k in sorted(by_no)]


def needs_qty_repair(group: dict[str, Any]) -> bool:
    children = group.get("children") or []
    if not children:
        return False
    if raw_has_qty_markers(str(group.get("rawText") or "")):
        return False
    if float(group.get("confidence") or 0) < 0.55:
        return False
    return all(int(c.get("qty") or 1) == 1 for c in children if isinstance(c, dict))


def apply_rawtext_qty_preference(group: dict[str, Any]) -> dict[str, Any]:
    """If rawText has qty markers, re-parse and prefer those qtys over model children."""
    if not isinstance(group, dict):
        return group
    raw = str(group.get("rawText") or "")
    if not raw_has_qty_markers(raw) and "\n" not in raw:
        return group
    parsed = parse_callout_cluster(raw)
    if not parsed or not (parsed.get("children") or parsed.get("parentItemNo")):
        return group
    out = dict(group)
    if out.get("parentItemNo") is None and parsed.get("parentItemNo") is not None:
        out["parentItemNo"] = parsed["parentItemNo"]
    if parsed.get("parentQty") is not None:
        out["parentQty"] = parsed["parentQty"]
    out["children"] = _merge_children_prefer_parsed_qty(
        out.get("children"), parsed.get("children")
    )
    if parsed.get("rawText"):
        out["rawText"] = parsed["rawText"]
    if parsed.get("references") and not out.get("references"):
        out["references"] = list(parsed.get("references") or [])
    return out


def scan_text_for_clusters(
    blob: str,
    *,
    parts_list: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Heuristic scan of OCR/raw text for callout clusters.

    Each stacked leader is its own point. Line-2 fastener rows stay with that
    leader only — never merge a balloon that sits below another.
    """
    found: list[dict[str, Any]] = []
    seen: set[str] = set()
    for cluster in split_stacked_balloon_clusters(blob or "", parts_list=parts_list):
        raw = str(cluster.get("rawText") or "").strip()
        if not raw:
            continue
        if not re.search(r"\d{1,4}\s*[x×X\-]\s*\d{1,4}", raw):
            if not re.search(r"\d{1,4}\s*,\s*\d{1,4}", raw):
                continue
        key = re.sub(r"\s+", "", raw.lower())
        if key in seen:
            continue
        g = parse_callout_cluster(raw)
        if not g or g.get("referenceOnly"):
            continue
        if not g.get("children") and g.get("parentQty") is None:
            continue
        seen.add(key)
        lines = cluster.get("lines") or []
        if lines:
            g["calloutLines"] = list(lines)
        g["confidence"] = min(float(g.get("confidence") or 0.6), 0.65)
        g["source"] = "ocr_scan"
        found.append(g)
    return found


def _merge_child_lists(
    a: list[dict[str, Any]] | None,
    b: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    return _merge_children_prefer_parsed_qty(a, b)


def _fold_orphan_into_target(
    target: dict[str, Any],
    orphan: dict[str, Any],
) -> None:
    """Attach a fastener-only / continuation orphan into an assembly parent group."""
    children = [c for c in (orphan.get("children") or []) if isinstance(c, dict)]
    parent = orphan.get("parentItemNo")
    fold_children = list(children)
    if parent is not None:
        try:
            pq = int(orphan.get("parentQty") or 0)
        except (TypeError, ValueError):
            pq = 0
        if pq < 1:
            parsed = parse_callout_cluster(str(orphan.get("rawText") or ""))
            if parsed:
                try:
                    pq = int(parsed.get("parentQty") or 0)
                except (TypeError, ValueError):
                    pq = 0
                if pq < 1:
                    for ch in parsed.get("children") or []:
                        try:
                            if int(ch.get("itemNo")) == int(parent):
                                pq = int(ch.get("qty") or 0)
                                break
                        except (TypeError, ValueError):
                            continue
        fold_children = [{"itemNo": int(parent), "qty": max(pq, 1)}] + fold_children
    target["children"] = _merge_child_lists(target.get("children"), fold_children)
    raw_a = str(target.get("rawText") or "").strip()
    raw_b = str(orphan.get("rawText") or "").strip()
    if raw_b and raw_b not in raw_a:
        target["rawText"] = f"{raw_a}, {raw_b}".strip(" ,") if raw_a else raw_b
    lines_a = list(target.get("calloutLines") or [])
    lines_b = list(orphan.get("calloutLines") or [])
    if raw_b and raw_b not in lines_a and raw_b not in lines_b:
        lines_b = lines_b + [raw_b]
    if lines_b:
        merged_lines = list(lines_a)
        for ln in lines_b:
            if ln not in merged_lines:
                merged_lines.append(ln)
        target["calloutLines"] = merged_lines


def merge_continuation_groups(
    groups: list[dict[str, Any]],
    *,
    parts_list: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Fold fastener-only / continuation clusters into the nearest assembly parent.

    VLM often emits line2 ``400x8, 410x8`` as its own group (sometimes *before*
    the parent in JSON). Attach to the nearest same-page non-fastener parent
    (prefer previous), so filter_weak does not drop the line.
    """
    pl_lookup = _pl_lookup(parts_list)
    warns: list[str] = []
    items = [g for g in (groups or []) if isinstance(g, dict)]

    def _is_fastener_orphan(g: dict[str, Any]) -> bool:
        # A lone balloon is an assemble step, not a continuation line.
        if g.get("individual"):
            return False
        parent = g.get("parentItemNo")
        children = [c for c in (g.get("children") or []) if isinstance(c, dict)]
        if parent is None:
            return False
        if not children and parent is not None:
            # Bare single callout — only fold if fastener-like
            if not pl_lookup:
                return False
            try:
                return _is_fastener_like(int(parent), pl_lookup)
            except (TypeError, ValueError):
                return False
        if not pl_lookup:
            # No PL: treat short all-qty rows as orphans (washer pairs)
            raw = str(g.get("rawText") or "")
            toks = [t.strip() for t in raw.split(",") if t.strip()]
            if len(toks) <= 2 and raw_has_qty_markers(raw):
                return True
            return False
        try:
            p = int(parent)
        except (TypeError, ValueError):
            return False
        if not _is_fastener_like(p, pl_lookup):
            return False
        return all(
            _is_fastener_like(int(c["itemNo"]), pl_lookup)
            for c in children
            if c.get("itemNo") is not None
        )

    def _is_assembly_parent(g: dict[str, Any]) -> bool:
        if _is_fastener_orphan(g):
            return False
        if g.get("parentItemNo") is None:
            return False
        if not (g.get("children") or []):
            return False
        if pl_lookup:
            try:
                return not _is_fastener_like(int(g["parentItemNo"]), pl_lookup)
            except (TypeError, ValueError):
                return True
        return True

    assembly_idxs = [i for i, g in enumerate(items) if _is_assembly_parent(g)]
    absorbed: set[int] = set()
    _SIZE_RE = re.compile(r"M\d+(?:\.\d+)?", re.I)

    def _item_sizes(ino: int) -> set[str]:
        hit = pl_lookup.get(int(ino)) or {}
        text = f"{hit.get('description') or ''} {hit.get('partNumber') or ''}"
        return {m.group(0).upper() for m in _SIZE_RE.finditer(text)}

    def _orphan_item_nos(g: dict[str, Any]) -> set[int]:
        nos: set[int] = set()
        try:
            if g.get("parentItemNo") is not None:
                nos.add(int(g["parentItemNo"]))
        except (TypeError, ValueError):
            pass
        for ch in g.get("children") or []:
            if isinstance(ch, dict) and ch.get("itemNo") is not None:
                try:
                    nos.add(int(ch["itemNo"]))
                except (TypeError, ValueError):
                    continue
        return nos

    def _child_nos(g: dict[str, Any]) -> set[int]:
        nos: set[int] = set()
        for ch in g.get("children") or []:
            if isinstance(ch, dict) and ch.get("itemNo") is not None:
                try:
                    nos.add(int(ch["itemNo"]))
                except (TypeError, ValueError):
                    continue
        return nos

    for i, g in enumerate(items):
        if not _is_fastener_orphan(g):
            continue
        page = g.get("sourcePage")
        orphan_nos = _orphan_item_nos(g)
        orphan_sizes: set[str] = set()
        for n in orphan_nos:
            orphan_sizes |= _item_sizes(n)
        cands: list[tuple[int, int, int, int, int]] = []
        for j in assembly_idxs:
            ag = items[j]
            ap = ag.get("sourcePage")
            if page is not None and ap is not None and ap != page:
                continue
            child_nos = _child_nos(ag)
            # Prefer parents that do not already list these fasteners (true continuation)
            already = 1 if (orphan_nos & child_nos) else 0
            # Prefer fastener-size family match (M3 washers → parent with M3 screws)
            child_sizes: set[str] = set()
            for n in child_nos:
                child_sizes |= _item_sizes(n)
            size_miss = 0 if (orphan_sizes and child_sizes and (orphan_sizes & child_sizes)) else 1
            if not orphan_sizes or not child_sizes:
                size_miss = 0  # no signal — don't penalize
            prefer_prev = 0 if j < i else 1
            cands.append((already, size_miss, prefer_prev, abs(j - i), j))
        if not cands:
            continue
        cands.sort()
        j = cands[0][4]
        _fold_orphan_into_target(items[j], g)
        absorbed.add(i)
        warns.append(
            f"merged continuation callout into parent={items[j].get('parentItemNo')} "
            f"from orphan parent={g.get('parentItemNo')}"
        )

    out = [g for i, g in enumerate(items) if i not in absorbed]
    return out, warns


def validate_assembly_group(
    group: dict[str, Any],
    pl_nos: set[int],
    *,
    source_page: int | None = None,
    source_drawing_id: int | None = None,
    source_filename: str = "",
) -> dict[str, Any] | None:
    """Keep only PL-known item numbers; drop empty / invalid groups."""
    if not isinstance(group, dict):
        return None
    warnings: list[str] = []
    parent_raw = group.get("parentItemNo")
    parent: int | None
    try:
        parent = int(parent_raw) if parent_raw is not None and str(parent_raw).strip() != "" else None
    except (TypeError, ValueError):
        parent = None

    if parent is not None and pl_nos and parent not in pl_nos:
        warnings.append(f"parent {parent} not on PL — dropped")
        parent = None

    children: list[dict[str, Any]] = []
    for ch in group.get("children") or []:
        if not isinstance(ch, dict):
            continue
        try:
            ino = int(ch.get("itemNo"))
            qty = int(ch.get("qty") or 1)
        except (TypeError, ValueError):
            continue
        if qty < 1:
            qty = 1
        if pl_nos and ino not in pl_nos:
            warnings.append(f"child {ino} not on PL — dropped")
            continue
        children.append({"itemNo": ino, "qty": qty})

    refs: list[int] = []
    for r in group.get("references") or []:
        try:
            ri = int(r)
        except (TypeError, ValueError):
            continue
        if pl_nos and ri not in pl_nos:
            continue
        refs.append(ri)

    if parent is None and not children:
        return None

    # Promote first child if parent missing after PL filter
    if parent is None and children:
        first = children.pop(0)
        parent = int(first["itemNo"])

    conf = float(group.get("confidence") or 0.7)
    out = {
        "parentItemNo": parent,
        "children": children,
        "references": refs,
        "rawText": str(group.get("rawText") or "").strip(),
        "confidence": round(min(0.99, max(0.1, conf)), 3),
        "referenceOnly": False,
        "sourcePage": int(source_page or group.get("sourcePage") or 1),
        "sourceDrawingId": source_drawing_id
        if source_drawing_id is not None
        else group.get("sourceDrawingId"),
        "sourceFilename": source_filename or group.get("sourceFilename") or "",
        "source": group.get("source") or "vlm",
        "warnings": warnings,
    }
    pq_raw = group.get("parentQty")
    if pq_raw is not None:
        try:
            pq = int(pq_raw)
            if pq >= 1:
                out["parentQty"] = pq
        except (TypeError, ValueError):
            pass
    # Single-item balloon: assemble that item, no sub-items.
    if children:
        out["individual"] = False
    elif group.get("individual"):
        out["individual"] = True
    if group.get("zone"):
        out["zone"] = str(group.get("zone"))
    if group.get("readOrder") is not None:
        try:
            out["readOrder"] = int(group.get("readOrder"))
        except (TypeError, ValueError):
            pass
    return out


def normalize_vlm_groups(
    data: dict[str, Any],
    pl_nos: set[int],
    *,
    source_page: int,
    source_drawing_id: int | None = None,
    source_filename: str = "",
    parts_list: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    warns: list[str] = []
    for w in data.get("warnings") or []:
        if isinstance(w, str) and w.strip():
            warns.append(w.strip())
    out: list[dict[str, Any]] = []
    for g in data.get("groups") or []:
        if not isinstance(g, dict):
            continue
        raw = str(g.get("rawText") or "")
        # Prefer rawText qty markers / multiline wraps over model children
        if raw_has_qty_markers(raw) or "\n" in raw or ";" in raw:
            g = apply_rawtext_qty_preference(g)
        elif not g.get("children") and raw:
            parsed = parse_callout_cluster(raw)
            if parsed:
                g = {**parsed, **{k: v for k, v in g.items() if v not in (None, "", [])}}
        ng = validate_assembly_group(
            g,
            pl_nos,
            source_page=source_page,
            source_drawing_id=source_drawing_id,
            source_filename=source_filename,
        )
        if ng:
            out.append(ng)
            warns.extend(ng.pop("warnings", []) or [])
    out, mwarns = merge_continuation_groups(out, parts_list=parts_list)
    warns.extend(mwarns)
    out, fwarns = filter_weak_groups(out, parts_list=parts_list)
    warns.extend(fwarns)
    return out, warns


def filter_weak_groups(
    groups: list[dict[str, Any]],
    *,
    parts_list: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Drop bare parent-only groups and leftover fastener-only washer/screw pairs.

    Prefer ``merge_continuation_groups`` first so next-line fastener rows attach
    to the real assembly parent instead of being discarded.
    """
    pl_lookup = _pl_lookup(parts_list)
    out: list[dict[str, Any]] = []
    warns: list[str] = []
    for g in groups or []:
        if not isinstance(g, dict):
            continue
        children = [c for c in (g.get("children") or []) if isinstance(c, dict)]
        parent = g.get("parentItemNo")
        if not children:
            if g.get("individual"):
                out.append(g)
                continue
            warns.append(f"dropped weak group parent={parent} (no children)")
            continue
        if parent is not None and pl_lookup:
            try:
                p = int(parent)
            except (TypeError, ValueError):
                p = None
            if p is not None and _is_fastener_like(p, pl_lookup):
                if all(
                    _is_fastener_like(int(c["itemNo"]), pl_lookup)
                    for c in children
                    if c.get("itemNo") is not None
                ):
                    warns.append(
                        f"dropped fastener-only group parent={p} "
                        f"children={[c.get('itemNo') for c in children]}"
                    )
                    continue
        out.append(g)
    return out, warns


def repair_group_quantities(
    groups: list[dict[str, Any]],
    *,
    image_b64: str,
    image_mime: str,
    model: str,
    base_url: str,
    timeout: float,
    max_tokens: int,
    cancel_event=None,
    system: str | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Vision pass: recover subscript qtys when model left all children at qty=1."""
    warns: list[str] = []
    need = [g for g in groups if needs_qty_repair(g)]
    if not need or not image_b64:
        return groups, warns

    item_nos: list[int] = []
    seen: set[int] = set()
    for g in need:
        for ch in g.get("children") or []:
            try:
                ino = int(ch.get("itemNo"))
            except (TypeError, ValueError):
                continue
            if ino not in seen:
                seen.add(ino)
                item_nos.append(ino)
    if not item_nos:
        return groups, warns

    prompt = QTY_REPAIR_PROMPT.format(
        item_nos=", ".join(str(n) for n in item_nos[:80])
    )
    try:
        raw = chat_vision(
            prompt=prompt,
            images_b64=[image_b64],
            model=model,
            base_url=base_url,
            timeout=timeout,
            temperature=0.0,
            system=system
            or (
                "You read balloon subscript quantities from GA drawings. "
                "Reply with JSON only — no markdown fences."
            ),
            cancel_event=cancel_event,
            image_mime=image_mime or "image/jpeg",
            max_tokens=max_tokens,
        )
        data = _parse_json(raw)
    except Exception as exc:  # soft-fail
        warns.append(f"qty-repair skipped: {exc}")
        return groups, warns

    qty_map: dict[int, int] = {}
    for row in data.get("quantities") or []:
        if not isinstance(row, dict):
            continue
        try:
            ino = int(row.get("itemNo"))
            qty = int(row.get("qty") or 1)
        except (TypeError, ValueError):
            continue
        if qty < 1:
            qty = 1
        prev = qty_map.get(ino)
        if prev is None or qty > prev:
            qty_map[ino] = qty
    for w in data.get("warnings") or []:
        if isinstance(w, str) and w.strip():
            warns.append(w.strip())
    if not qty_map:
        return groups, warns

    out: list[dict[str, Any]] = []
    for g in groups:
        if not needs_qty_repair(g):
            out.append(g)
            continue
        ng = dict(g)
        kids = []
        changed = False
        for ch in ng.get("children") or []:
            if not isinstance(ch, dict):
                continue
            try:
                ino = int(ch.get("itemNo"))
                old = int(ch.get("qty") or 1)
            except (TypeError, ValueError):
                continue
            new_qty = qty_map.get(ino, old)
            if new_qty > old:
                changed = True
            kids.append({"itemNo": ino, "qty": new_qty})
        ng["children"] = kids
        if changed:
            # Reflect recovered markers in rawText for downstream parse preference
            bits = [str(ng.get("parentItemNo") or "")]
            bits.extend(f"{c['itemNo']}x{c['qty']}" for c in kids)
            ng["rawText"] = ", ".join(b for b in bits if b)
        out.append(ng)
    return out, warns


def callout_qty_totals(groups: list[dict[str, Any]] | None) -> dict[int, int]:
    """Sum balloon callout qtys per itemNo across all assembly groups."""
    totals: dict[int, int] = {}
    for g in groups or []:
        if not isinstance(g, dict) or g.get("referenceOnly"):
            continue
        parent = g.get("parentItemNo")
        if parent is not None:
            try:
                p = int(parent)
                try:
                    pq = int(g.get("parentQty") or 1)
                except (TypeError, ValueError):
                    pq = 1
                if pq < 1:
                    pq = 1
                totals[p] = totals.get(p, 0) + pq
            except (TypeError, ValueError):
                pass
        for ch in g.get("children") or []:
            if not isinstance(ch, dict):
                continue
            try:
                ino = int(ch.get("itemNo"))
                qty = int(ch.get("qty") or 1)
            except (TypeError, ValueError):
                continue
            if qty < 1:
                qty = 1
            totals[ino] = totals.get(ino, 0) + qty
    return totals


def bom_items_from_assembly_groups(
    groups: list[dict[str, Any]],
    parts_list: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Flatten assembly groups into BOM rows.

    Display ``qty`` comes from the Parts List when present (authoritative).
    ``extractedQty`` is the summed balloon callout qty for PL cross-check.
    """
    pl_lookup = _pl_lookup(parts_list)
    extracted = callout_qty_totals(groups)
    by_no: dict[int, dict[str, Any]] = {}

    for ino, ext_qty in extracted.items():
        hit = pl_lookup.get(ino) or {}
        pl_qty = None
        if hit.get("qty") is not None:
            try:
                raw_q = hit.get("qty")
                pl_qty = int(raw_q) if float(raw_q) == int(float(raw_q)) else float(raw_q)
            except (TypeError, ValueError):
                pl_qty = None
        on_pl = bool(hit)
        by_no[ino] = {
            "itemNo": ino,
            # Never fall back display qty to balloon totals — that caused PL 1 → 20.
            "qty": pl_qty,
            "extractedQty": ext_qty,
            "partNumber": hit.get("partNumber") or hit.get("part_number") or "",
            "description": hit.get("description") or "",
            "source": "balloon",
            "onDrawing": True,
            "gaPresence": "present" if on_pl else "ga_only",
            "qtyMatch": (pl_qty == ext_qty) if pl_qty is not None else None,
        }
    return [by_no[k] for k in sorted(by_no)]


def merge_bom_with_balloon_items(
    ga_bom: list[dict[str, Any]] | None,
    balloon_bom: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    """Union GA BOM rows with balloon-derived rows; keep extractedQty for PL check."""
    by_no: dict[int, dict[str, Any]] = {}
    order: list[int] = []

    def _ingest(row: dict[str, Any]) -> None:
        if not isinstance(row, dict):
            return
        try:
            ino = int(row.get("itemNo") or row.get("item_no") or 0)
        except (TypeError, ValueError):
            return
        if not ino:
            return
        try:
            qty = int(row.get("qty") or 0) or 0
        except (TypeError, ValueError):
            qty = 0
        try:
            ext = row.get("extractedQty")
            extracted = int(ext) if ext is not None and str(ext).strip() != "" else None
        except (TypeError, ValueError):
            extracted = None
        prev = by_no.get(ino)
        if prev is None:
            by_no[ino] = {
                "itemNo": ino,
                "qty": qty if qty else 1,
                "extractedQty": extracted if extracted is not None else (qty if qty else 1),
                "partNumber": row.get("partNumber") or row.get("part_number") or "",
                "description": row.get("description") or "",
                "source": row.get("source") or "ga",
                "qtyMatch": row.get("qtyMatch"),
            }
            order.append(ino)
            return
        # Keep PL/display qty if already set; bump extractedQty when balloon has more signal
        if extracted is not None:
            try:
                old_ext = int(prev.get("extractedQty") or 0)
            except (TypeError, ValueError):
                old_ext = 0
            if extracted > old_ext:
                prev["extractedQty"] = extracted
        if not prev.get("partNumber") and (row.get("partNumber") or row.get("part_number")):
            prev["partNumber"] = row.get("partNumber") or row.get("part_number")
        if not prev.get("description") and row.get("description"):
            prev["description"] = row.get("description")
        if row.get("source") == "balloon":
            prev["source"] = "balloon"
        if row.get("qtyMatch") is not None:
            prev["qtyMatch"] = row.get("qtyMatch")

    for r in ga_bom or []:
        _ingest(r if isinstance(r, dict) else {})
    for r in balloon_bom or []:
        _ingest(r if isinstance(r, dict) else {})
    return [by_no[i] for i in order]


def _is_zone_reading(g: dict[str, Any]) -> bool:
    return str(g.get("source") or "") == "zone_vlm"


def _qty_marker_count(g: dict[str, Any]) -> int:
    return len(_QTY_MARKER_RE.findall(str(g.get("rawText") or "")))


def _prefer_group_reading(prev: dict[str, Any], nxt: dict[str, Any]) -> dict[str, Any]:
    """Pick one consistent balloon reading.

    A zone-scan reading wins over OCR/full-page text, and two zone readings
    are not mixed item-by-item (that is how x40 and x8 collapse into 4 and 80
    on different children of the same parent).
    """
    prev_zone = _is_zone_reading(prev)
    nxt_zone = _is_zone_reading(nxt)
    if prev_zone != nxt_zone:
        return dict(prev if prev_zone else nxt)
    if prev_zone and nxt_zone:
        prev_kids = prev.get("children") or []
        nxt_kids = nxt.get("children") or []
        # A comma group beats a lone balloon of the same item.
        if prev_kids and not nxt_kids:
            return dict(prev)
        if nxt_kids and not prev_kids:
            return dict(nxt)
        prev_score = (_qty_marker_count(prev), float(prev.get("confidence") or 0))
        nxt_score = (_qty_marker_count(nxt), float(nxt.get("confidence") or 0))
        return dict(prev if prev_score >= nxt_score else nxt)

    merged = dict(prev)
    merged["children"] = _merge_child_lists(prev.get("children"), nxt.get("children"))
    try:
        pq_g = int(nxt.get("parentQty") or 0)
        pq_p = int(prev.get("parentQty") or 0)
        if pq_g > pq_p:
            merged["parentQty"] = pq_g
    except (TypeError, ValueError):
        pass
    raw_g = str(nxt.get("rawText") or "")
    raw_p = str(prev.get("rawText") or "")
    if raw_has_qty_markers(raw_g) and (
        not raw_has_qty_markers(raw_p) or len(raw_g) > len(raw_p)
    ):
        merged["rawText"] = raw_g
    elif len(raw_g) > len(raw_p):
        merged["rawText"] = raw_g
    if float(nxt.get("confidence") or 0) > float(prev.get("confidence") or 0):
        merged["confidence"] = nxt.get("confidence")
    lines: list[str] = []
    for src in (prev.get("calloutLines") or [], nxt.get("calloutLines") or []):
        for ln in src:
            if ln and ln not in lines:
                lines.append(ln)
    if lines:
        merged["calloutLines"] = lines
    # Keep confirmed border cell when present on either reading
    for src in (nxt, prev):
        dz = str(src.get("drawingZone") or "").strip()
        if re.fullmatch(r"[A-Ha-h]-\d{1,2}", dz):
            merged["drawingZone"] = f"{dz[0].upper()}{dz[1:]}"
            break
    return merged


def dedupe_groups(groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep one group per parent.

    Zone readings stay intact. Other sources still union children and prefer
    the richer rawText / qty.
    """
    best: dict[int, dict[str, Any]] = {}
    for g in groups:
        if not isinstance(g, dict):
            continue
        parent = g.get("parentItemNo")
        if parent is None:
            continue
        try:
            key = int(parent)
        except (TypeError, ValueError):
            continue
        prev = best.get(key)
        if not prev:
            best[key] = dict(g)
            continue
        best[key] = _prefer_group_reading(prev, g)
    return [best[k] for k in sorted(best)]


def sort_groups_reading_order(groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Zone order: row A→D, column 1→12, then the order returned inside the tile."""

    def _key(g: dict[str, Any]) -> tuple:
        zone = str(g.get("zone") or "")
        m = re.match(r"([A-Z])(\d+)$", zone)
        try:
            parent = int(g.get("parentItemNo") or 0)
        except (TypeError, ValueError):
            parent = 0
        try:
            order = int(g.get("readOrder") or 0)
        except (TypeError, ValueError):
            order = 0
        if m:
            return (0, m.group(1), int(m.group(2)), order, parent)
        return (1, "Z", 0, order, parent)

    return sorted([g for g in groups if isinstance(g, dict)], key=_key)


def group_to_instruction(group: dict[str, Any], pl_lookup: dict[int, dict] | None = None) -> str:
    parent = group.get("parentItemNo")
    pl_lookup = pl_lookup or {}
    parent_desc = ""
    if parent is not None and pl_lookup.get(int(parent)):
        parent_desc = pl_lookup[int(parent)].get("description") or ""
    parent_bit = f"Item No. {parent}"
    if parent_desc:
        parent_bit += f" ({parent_desc[:48]})"
    try:
        pq = int(group.get("parentQty") or 0)
    except (TypeError, ValueError):
        pq = 0
    if pq > 1:
        parent_bit = f"{pq} × {parent_bit}"
    sheet = f" (sheet {group.get('sourcePage')})." if group.get("sourcePage") else "."
    parts = []
    for ch in group.get("children") or []:
        ino = ch.get("itemNo")
        qty = ch.get("qty") or 1
        desc = ""
        if ino is not None and pl_lookup.get(int(ino)):
            desc = pl_lookup[int(ino)].get("description") or ""
        bit = f"Item No. {ino}×{qty}"
        if desc:
            bit += f" ({desc[:40]})"
        parts.append(bit)
    if not parts:
        return (
            f"Assemble {parent_bit} as indicated by the single-item balloon "
            f"on the drawing{sheet}"
        )
    child_bit = ", ".join(parts)
    return (
        f"Assemble {parent_bit} using {child_bit} as indicated by the balloon "
        f"callout on the drawing{sheet}"
    )


def groups_to_synthetic_notes(
    groups: list[dict[str, Any]],
    *,
    parts_list: dict[str, Any] | None = None,
    start_step: int = 1,
) -> list[dict[str, Any]]:
    pl_lookup: dict[int, dict] = {}
    for it in (parts_list or {}).get("items") or []:
        try:
            pl_lookup[int(it.get("itemNo"))] = it
        except (TypeError, ValueError):
            continue
    notes: list[dict[str, Any]] = []
    step = start_step
    for g in groups:
        if g.get("referenceOnly") or g.get("parentItemNo") is None:
            continue
        if float(g.get("confidence") or 0) < 0.55:
            continue
        parent = int(g["parentItemNo"])
        items = [parent] + [int(c["itemNo"]) for c in (g.get("children") or [])]
        parent_qty = 1
        if pl_lookup.get(parent) and pl_lookup[parent].get("qty"):
            try:
                parent_qty = int(pl_lookup[parent].get("qty") or 1) or 1
            except (TypeError, ValueError):
                parent_qty = 1
        items_used = [
            {
                "itemNo": parent,
                "qty": parent_qty,
                "description": (pl_lookup.get(parent) or {}).get("description"),
            }
        ]
        for c in g.get("children") or []:
            ino = int(c["itemNo"])
            items_used.append(
                {
                    "itemNo": ino,
                    "qty": int(c.get("qty") or 1),
                    "description": (pl_lookup.get(ino) or {}).get("description"),
                }
            )
        text = group_to_instruction(g, pl_lookup)
        refs = [g.get("sourceFilename")] if g.get("sourceFilename") else []
        dz_raw = str(g.get("drawingZone") or "").strip()
        # Confirmed border cell only (e.g. A-8) — never Stage C tile ids
        drawing_zone = ""
        if re.fullmatch(r"[A-Ha-h]-\d{1,2}", dz_raw):
            drawing_zone = f"{dz_raw[0].upper()}{dz_raw[1:]}"
        note: dict[str, Any] = {
            "sheet": int(g.get("sourcePage") or 1),
            "stepNo": step,
            "text": text,
            "items": items,
            "itemsUsed": items_used,
            "torque": [],
            "connectors": [],
            "standards": [],
            "references": refs,
            "sourceDrawingId": g.get("sourceDrawingId"),
            "sourceFilename": g.get("sourceFilename") or "",
            "assemblyGroup": True,
            "balloonRaw": g.get("rawText") or "",
            "mindEngine": "local_vlm_stage_c",
            "mindConfidence": float(g.get("confidence") or 0.7),
            "elaborated": False,
        }
        if drawing_zone:
            note["drawingZone"] = drawing_zone
        notes.append(note)
        step += 1
    return notes


def _note_item_set(note: dict[str, Any]) -> set[int]:
    out: set[int] = set()
    for i in note.get("items") or []:
        try:
            out.add(int(i))
        except (TypeError, ValueError):
            continue
    return out


def _balloon_item_list(note: dict[str, Any]) -> list[int]:
    items: list[int] = []
    for i in note.get("items") or []:
        try:
            n = int(i)
        except (TypeError, ValueError):
            continue
        if n not in items:
            items.append(n)
    return items


def _is_drawing_placement_note(note: dict[str, Any]) -> bool:
    """True for shop NOTES (stick/place as shown) — not synthetic balloon assemble lines."""
    if note.get("assemblyGroup"):
        return False
    from app.route_card.drawing_mind.elaborate import needs_placement_elaboration

    return needs_placement_elaboration(str(note.get("text") or ""), list(note.get("items") or []))


def _attach_balloon_group(note: dict[str, Any], bn: dict[str, Any]) -> None:
    groups = note.setdefault("balloonGroups", [])
    if not isinstance(groups, list):
        groups = []
        note["balloonGroups"] = groups
    payload = {
        "rawText": bn.get("balloonRaw") or bn.get("text") or "",
        "items": _balloon_item_list(bn),
        "sourceFilename": bn.get("sourceFilename") or "",
        "sourcePage": bn.get("sheet"),
        "drawingZone": bn.get("drawingZone") or "",
    }
    groups.append(payload)
    used = note.setdefault("itemsUsed", [])
    if not isinstance(used, list):
        used = []
        note["itemsUsed"] = used
    seen = set()
    for u in used:
        if isinstance(u, dict) and u.get("itemNo") is not None:
            try:
                seen.add(int(u["itemNo"]))
            except (TypeError, ValueError):
                continue
    for u in bn.get("itemsUsed") or []:
        if not isinstance(u, dict):
            continue
        try:
            ino = int(u.get("itemNo"))
        except (TypeError, ValueError):
            continue
        if ino in seen:
            continue
        used.append(dict(u))
        seen.add(ino)


def merge_notes_with_balloon_notes(
    notes: list[dict[str, Any]],
    balloon_notes: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Club overlapping balloon callouts into NOTES; keep disjoint balloons separate.

    - Shared item numbers → attach the balloon group onto the drawing note and do
      not emit a synthetic ``Assemble Item N…`` step for those items.
    - Single-item balloon not cited by a stick/place note on the same sheet, while
      that note already clubs other balloons → treat as ``hostItemNo`` (body) and
      suppress its assemble line.
    - No shared items → append the balloon note as its own step (fastener clusters).
    """
    out = [dict(n) for n in (notes or [])]
    covered: set[int] = set()
    for n in out:
        covered |= _note_item_set(n)

    next_step = max((int(n.get("stepNo") or 0) for n in out), default=0) + 1
    host_candidates: list[tuple[dict[str, Any], list[int]]] = []

    for bn_raw in balloon_notes or []:
        bn = dict(bn_raw)
        items = _balloon_item_list(bn)
        if not items:
            continue
        item_set = set(items)
        # Prefer a drawing note that shares items with this callout
        matched: dict[str, Any] | None = None
        for n in out:
            if n.get("assemblyGroup"):
                continue
            shared = _note_item_set(n) & item_set
            if shared:
                matched = n
                break
        if matched is not None:
            _attach_balloon_group(matched, bn)
            covered |= item_set
            continue

        # Lone balloon with no note overlap — maybe the host body of a stick note
        if len(items) == 1 and not (bn.get("itemsUsed") and len(bn.get("itemsUsed") or []) > 1):
            # children would make items longer; also check empty children via itemsUsed
            children = [
                u
                for u in (bn.get("itemsUsed") or [])
                if isinstance(u, dict)
                and u.get("itemNo") is not None
                and int(u["itemNo"]) != items[0]
            ]
            if not children:
                host_candidates.append((bn, items))
                continue

        # Fully covered already (e.g. items already clubbed via another note)
        if item_set <= covered:
            continue
        bn["stepNo"] = next_step
        next_step += 1
        out.append(bn)
        covered |= item_set

    for bn, items in host_candidates:
        parent = items[0]
        if parent in covered:
            continue
        host_note: dict[str, Any] | None = None
        for n in out:
            if not _is_drawing_placement_note(n):
                continue
            n_items = _note_item_set(n)
            if parent in n_items:
                continue
            sheet_n = int(n.get("sheet") or 1)
            sheet_b = int(bn.get("sheet") or 1)
            if sheet_n != sheet_b:
                continue
            # Prefer notes that already clubbed sticker balloons on this sheet
            if n.get("balloonGroups") or n_items:
                if n.get("hostItemNo") is None:
                    host_note = n
                    break
        if host_note is not None:
            host_note["hostItemNo"] = parent
            covered.add(parent)
            continue
        # Not a host — keep as its own assemble step
        bn = dict(bn)
        bn["stepNo"] = next_step
        next_step += 1
        out.append(bn)
        covered.update(items)

    return out


def group_item_nos(groups: list[dict[str, Any]]) -> set[str]:
    nos: set[str] = set()
    for g in groups or []:
        if g.get("parentItemNo") is not None:
            nos.add(str(int(g["parentItemNo"])))
        for ch in g.get("children") or []:
            try:
                nos.add(str(int(ch.get("itemNo"))))
            except (TypeError, ValueError):
                continue
        for r in g.get("references") or []:
            try:
                nos.add(str(int(r)))
            except (TypeError, ValueError):
                continue
    return nos


def _zone_prompt(tile: dict[str, Any], parts_list: dict[str, Any] | None) -> str:
    row = str(tile.get("row") or "A")
    col_lo = int(tile.get("colFrom") or 1)
    col_hi = int(tile.get("colTo") or col_lo)
    return ZONE_C_PROMPT.format(
        row=row,
        row_hint=_ROW_HINTS.get(row, f"row {row} from the top"),
        col_lo=col_lo,
        col_hi=col_hi,
        col_hint=_COL_HINTS.get((col_lo, col_hi), f"columns {col_lo}–{col_hi}"),
        pl_items=format_pl_ids_csv(parts_list),
    )


def extract_assembly_groups_by_zone(
    *,
    pdf_bytes: bytes,
    page_no: int,
    parts_list: dict[str, Any] | None,
    model: str,
    base_url: str,
    timeout: float,
    max_tokens: int,
    cancel_event=None,
    source_drawing_id: int | None = None,
    source_filename: str = "",
    system: str | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Vision-read balloons zone by zone (row A→D, columns 1→12).

    Each tile is a tight crop so subscript digits (40, 80, 8, 2) stay legible.
    Groups come back in that reading order. A single-item balloon is kept.
    """
    from app.route_card.analyze_jobs import check_cancelled
    from app.route_card.drawing_mind.page_images import render_callout_zones

    warns: list[str] = []
    pl_nos = pl_item_set(parts_list)
    try:
        tiles = render_callout_zones(pdf_bytes, page_no, cancel_event=cancel_event)
    except Exception as exc:
        return [], [f"zone render skipped: {exc}"]
    if not tiles:
        return [], ["zone scan found no ink tiles"]

    system_prompt = system or (
        "You read balloon callouts inside one drawing zone. "
        "Copy subscript quantities digit-for-digit (x40 is 40, x80 is 80, x8 is 8, x2 is 2). "
        "A single item is assembled alone. A comma list: the first item is made from the rest. "
        "Reply with JSON only — no markdown fences."
    )
    groups: list[dict[str, Any]] = []
    for tile_i, tile in enumerate(tiles):
        check_cancelled(cancel_event)
        zone = str(tile.get("zone") or "")
        label = f"{tile.get('row')}{tile.get('colFrom')}-{tile.get('colTo')}"
        try:
            raw = chat_vision(
                prompt=_zone_prompt(tile, parts_list),
                images_b64=[tile["b64"]],
                model=model,
                base_url=base_url,
                timeout=timeout,
                temperature=0.0,
                system=system_prompt,
                cancel_event=cancel_event,
                image_mime=str(tile.get("mime") or "image/jpeg"),
                max_tokens=max_tokens,
            )
            data = _parse_json(raw)
        except Exception as exc:
            warns.append(f"zone {label} skipped: {exc}")
            continue
        for w in data.get("warnings") or []:
            if isinstance(w, str) and w.strip():
                warns.append(f"zone {label}: {w.strip()}")
        tile_groups: list[dict[str, Any]] = []
        for gi, g in enumerate(data.get("groups") or []):
            if not isinstance(g, dict):
                continue
            g = dict(g)
            g["zone"] = zone
            g["readOrder"] = tile_i * 100 + gi
            g["source"] = "zone_vlm"
            raw_text = str(g.get("rawText") or "")
            kids = g.get("children") or []
            # Model flag, or a raw string that is only one item / (item).
            if g.get("individual") or (
                not kids and re.fullmatch(r"\(?\d{1,4}\)?", raw_text.strip())
            ):
                g["individual"] = True
                g["children"] = []
            elif raw_has_qty_markers(raw_text) or "\n" in raw_text or ";" in raw_text:
                g = apply_rawtext_qty_preference(g)
                g["zone"] = zone
                g["readOrder"] = tile_i * 100 + gi
                g["source"] = "zone_vlm"
            ng = validate_assembly_group(
                g,
                pl_nos,
                source_page=page_no,
                source_drawing_id=source_drawing_id,
                source_filename=source_filename,
            )
            if not ng:
                continue
            warns.extend(ng.pop("warnings", []) or [])
            ng["source"] = "zone_vlm"
            ng["zone"] = zone
            ng["readOrder"] = tile_i * 100 + gi
            tile_groups.append(ng)
        # Wrap-lines inside this tile only (450 with 400/410). Do not reach
        # into another zone.
        tile_groups, mwarns = merge_continuation_groups(
            tile_groups, parts_list=parts_list
        )
        warns.extend(f"zone {label}: {w}" for w in mwarns if w)
        groups.extend(tile_groups)

    groups, fwarns = filter_weak_groups(groups, parts_list=parts_list)
    warns.extend(fwarns)
    groups = sort_groups_reading_order(groups)
    if groups:
        warns.append(
            f"zone scan page {page_no}: {len(tiles)} tile(s), {len(groups)} balloon(s)"
        )
    return groups, warns


def extract_assembly_groups_from_page(
    *,
    image_b64: str,
    image_mime: str,
    parts_list: dict[str, Any] | None,
    page_no: int,
    model: str,
    base_url: str,
    timeout: float,
    max_tokens: int,
    cancel_event=None,
    source_drawing_id: int | None = None,
    source_filename: str = "",
    system: str | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    pl_nos = pl_item_set(parts_list)
    prompt = STAGE_C_PROMPT.format(pl_items=format_pl_ids_csv(parts_list))
    raw = chat_vision(
        prompt=prompt,
        images_b64=[image_b64],
        model=model,
        base_url=base_url,
        timeout=timeout,
        temperature=0.0,
        system=system
        or (
            "You extract balloon callout clusters from GA drawings. "
            "Preserve subscript quantities (xN / ×N / -N) in rawText and children. "
            "Reply with JSON only — no markdown fences."
        ),
        cancel_event=cancel_event,
        image_mime=image_mime or "image/jpeg",
        max_tokens=max_tokens,
    )
    data = _parse_json(raw)
    groups, warns = normalize_vlm_groups(
        data,
        pl_nos,
        source_page=page_no,
        source_drawing_id=source_drawing_id,
        source_filename=source_filename,
        parts_list=parts_list,
    )
    if any(needs_qty_repair(g) for g in groups):
        groups, rwarns = repair_group_quantities(
            groups,
            image_b64=image_b64,
            image_mime=image_mime or "image/jpeg",
            model=model,
            base_url=base_url,
            timeout=timeout,
            max_tokens=min(1024, max_tokens),
            cancel_event=cancel_event,
            system=system,
        )
        warns.extend(rwarns)
    return groups, warns


def generate_llm_route_ops(
    *,
    notes: list[dict[str, Any]],
    assembly_groups: list[dict[str, Any]],
    parts_list: dict[str, Any] | None,
    model: str,
    base_url: str,
    timeout: float,
    max_tokens: int,
    cancel_event=None,
    pl_gaps: list[str] | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    pl_nos = pl_item_set(parts_list)
    notes_lines = []
    try:
        from app.route_card.extractor import is_ctq_note
    except Exception:
        is_ctq_note = lambda _n: False  # noqa: E731
    for n in notes:
        if n.get("assemblyGroup"):
            continue  # groups passed separately
        if is_ctq_note(n):
            continue  # CTQ → Quality inspection, not Stage D shop ops
        t = (n.get("text") or "").strip()
        if t:
            notes_lines.append(f"{n.get('stepNo') or '-'}. {t}")
    notes_text = "\n".join(notes_lines) if notes_lines else "(none)"
    groups_json = json.dumps(assembly_groups[:40], ensure_ascii=False)
    pl_text = format_pl_for_prompt(parts_list)
    gaps = pl_gaps
    if gaps is None:
        cited = set()
        for n in notes:
            for i in n.get("items") or []:
                try:
                    cited.add(int(i))
                except (TypeError, ValueError):
                    pass
        cited |= {int(x) for x in group_item_nos(assembly_groups) if str(x).isdigit()}
        gaps = [str(n) for n in sorted(pl_nos - cited)]
    prompt = STAGE_D_PROMPT.format(
        notes_text=notes_text[:8000],
        groups_json=groups_json[:6000],
        pl_text=pl_text[:6000],
        pl_gaps=", ".join(gaps[:80]) if gaps else "(none)",
    )
    raw = chat_text(
        prompt=prompt,
        model=model,
        base_url=base_url,
        timeout=timeout,
        temperature=0.0,
        system=(
            "You write complete shop route cards from GA notes, balloon groups, "
            "and Parts List. JSON only — no markdown fences."
        ),
        cancel_event=cancel_event,
        max_tokens=max_tokens,
    )
    data = _parse_json(raw)
    warns = [w for w in (data.get("warnings") or []) if isinstance(w, str) and w.strip()]
    ops = validate_llm_route_ops(data.get("operations") or [], pl_nos, parts_list)
    if not ops:
        warns.append("LLM route returned no valid operations")
    return ops, warns


def validate_llm_route_ops(
    ops: list[Any],
    pl_nos: set[int],
    parts_list: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    pl_lookup: dict[int, dict] = {}
    for it in (parts_list or {}).get("items") or []:
        try:
            pl_lookup[int(it.get("itemNo"))] = it
        except (TypeError, ValueError):
            continue
    out: list[dict[str, Any]] = []
    for i, op in enumerate(ops):
        if not isinstance(op, dict):
            continue
        instr = str(op.get("instruction") or op.get("instructionText") or "").strip()
        if len(instr) < 3:
            continue
        try:
            op_no = int(op.get("opNo") or (i + 1) * 10)
        except (TypeError, ValueError):
            op_no = (i + 1) * 10
        items_used: list[dict[str, Any]] = []
        for it in op.get("itemsUsed") or []:
            if not isinstance(it, dict):
                continue
            try:
                ino = int(it.get("itemNo"))
            except (TypeError, ValueError):
                continue
            if pl_nos and ino not in pl_nos:
                continue
            try:
                qty = int(it.get("qty") or 0) or None
            except (TypeError, ValueError):
                qty = None
            if qty is None and pl_lookup.get(ino):
                try:
                    qty = int(pl_lookup[ino].get("qty") or 0) or None
                except (TypeError, ValueError):
                    qty = None
            desc = None
            if pl_lookup.get(ino):
                desc = pl_lookup[ino].get("description")
            items_used.append({"itemNo": ino, "qty": qty, "description": desc})
        name = str(op.get("operation") or "").strip() or f"Assembly step {i + 1}"
        out.append(
            {
                "id": f"op-{op_no}",
                "opNo": op_no,
                "operation": name[:80],
                "workCentre": "Assembly",
                "machine": "Assembly station",
                "tool": "Assembly tools",
                "items": ", ".join(
                    f"#{u['itemNo']}" + (f"×{u['qty']}" if u.get("qty") else "")
                    for u in items_used
                ),
                "itemsUsed": items_used,
                "torqueSpec": "",
                "reference": str(op.get("reference") or ""),
                "setup": "",
                "time": "",
                "inspection": str(op.get("inspection") or "Visual"),
                "instructionText": instr,
                "insight": "",
                "status": "Planned",
                "type": "Assembly",
                "reason": instr[:240],
                "features": [f"ITM-{u['itemNo']}" for u in items_used],
                "elaborated": True,
                "verbatimText": instr,
                "needsReview": False,
                "source": "llm_route",
                "placement": [],
                "viewRefs": [],
            }
        )
    # Stable sort / renumber
    out.sort(key=lambda o: int(o.get("opNo") or 0))
    for i, o in enumerate(out):
        op_no = (i + 1) * 10
        o["opNo"] = op_no
        o["id"] = f"op-{op_no}"
    return out
