"""Parse BEL Parts List (PL) from PDF or legacy .xls into itemNo → part/description."""

from __future__ import annotations

import re
from io import BytesIO

from app.route_card.pdf_ingest import ingest_pdf, tables_to_tsv_lines

# Full BEL part no: 4 3 3 2 — may be glued to designation (…COATIN4585 116 802 83)
PART_NO_RE = re.compile(r"(\d{4}\s+\d{3}\s+\d{3}\s+\d{2})")
# Truncated / partial part nos common in poor PDF text layers: 4 3 1-3
PART_NO_FLEX = re.compile(r"(\d{4}\s+\d{3}\s+\d{1,3}(?:\s+\d{1,2})?)")
# item + designation letters glued to part digits, e.g. "0010 POWERSUP4579 229 8"
# BEL PL item nos are always 4 digits (0010, 0020, 0100, 0500).
GLUED_ROW = re.compile(
    r"^\s*(\d{4})\s+([A-Za-z][A-Za-z0-9 /().\-]{0,60}?)(\d{4}\s+\d{3}\s+\d{1,3}(?:\s+\d{1,2})?)\s*$"
)
# Line starts with 4-digit item no (space optional: 0010THERMAL…), then designation letter
LINE_START = re.compile(r"^\s*(\d{4})\s*([A-Za-z/(].*)$")
# Qty: integers and decimals (wire length 0.5 / .5 / 1.25 MTR)
_QTY_NUM = r"(\d+\.\d+|\.\d+|\d+)"
_QTY_UNIT = r"(NO|MM|EA|PCS|SET|MTR|KG|M|ST)"
QTY_RE = re.compile(rf"^{_QTY_NUM}\s*{_QTY_UNIT}?", re.I)
QTY_LINE = re.compile(rf"^\s*{_QTY_NUM}\s*{_QTY_UNIT}?\s*$", re.I)
# Qty with trailing circuit-ref junk: "6 NO ITEM002,,," or "0.5 MTR ,,"
QTY_LINE_LOOSE = re.compile(
    rf"^\s*{_QTY_NUM}\s*{_QTY_UNIT}?\b",
    re.I,
)
# Standalone BEL part-number line (pymupdf often puts each column on its own line)
PART_NO_LINE = re.compile(r"^\s*(\d{4}\s+\d{3}\s+\d{3}\s+\d{2})\s*$")
PART_NO_LINE_FLEX = re.compile(r"^\s*(\d{4}\s+\d{3}\s+\d{1,3}(?:\s+\d{1,2})?)\s*$")
# Item number alone: always 4 digits (0010 / 0020 / 0100 / 0500)
ITEM_ONLY_LINE = re.compile(r"^\s*(\d{4})\s*$")
# Bare 1–4 digit token (qty or unpadded next-item in messy PDF text)
BARE_NUM_LINE = re.compile(r"^\s*(\d{1,4})\s*$")
UNIT_ONLY_LINE = re.compile(r"^\s*(NO|MM|EA|PCS|SET|MTR|KG|M|ST)\s*$", re.I)
JUNK_LINE = re.compile(r"^[\s,]+$")

# BEL PL title block (end of each sheet) — skip entirely; only item rows matter.
_TB_STRONG = re.compile(
    r"(?i)^\s*(?:"
    r"BHARAT\s+ELECTRONICS|"
    r"THIS\s+DOCUMENT\s+IS\s+THE\s+PROPERTY|"
    r"BEL-PLM-|"
    r"DOC\s*TYPE\s*:?\s*PL\b|"
    r"HELD\s+IN\b|"
    r"ALT\s*BOM\b|"
    r"NO\.?\s*OF\s*SH\.?\b|"
    r"SHEET\s*NO\.?\b|"
    r"THIRD\s+ANGLE|"
    r"CHANGE\s*NO\.?\b"
    r")"
)
_TB_LABEL = re.compile(
    r"(?i)^\s*(?:"
    r"VER|VERSION|TITLE|DOC\s*TYPE|PART\s*NUMBER|PART\s*NO\.?|"
    r"HELD\s+IN|SHEET\s*NO\.?|NO\.?\s*OF\s*SH\.?|SHEETS?|"
    r"ALT\s*BOM|CHANGE\s*NO\.?|CHANGE|DATE|APVD|APPROVED|SCALE|"
    r"PROVISIONAL|ORIGINAL|REFER\s+ECR"
    r")\s*:?\s*$"
)
_TB_KV = re.compile(
    r"(?i)^\s*(?:"
    r"VER|VERSION|TITLE|DOC\s*TYPE|PART\s*NUMBER|PART\s*NO\.?|"
    r"HELD\s+IN|SHEET\s*NO\.?|NO\.?\s*OF\s*SH\.?|ALT\s*BOM|"
    r"CHANGE\s*NO\.?|DATE|APVD|APPROVED|SCALE"
    r")\s*[:.]?\s+\S+"
)
# Title-block VER values only (P1, 00–09). Never 4-digit item nos like 0010.
_TB_REV_TOKEN = re.compile(r"(?i)^\s*(?:P\d+|0\d)\s*$")
_TB_DATE = re.compile(r"^\s*\d{2}\.\d{2}\.\d{4}\s*$")
_TB_CHANGE_NO = re.compile(r"^\s*\d{10,}\s*$")
_TB_WINDOW_HINTS = re.compile(
    r"(?i)\b(?:"
    r"BHARAT\s+ELECTRONICS|DOC\s*TYPE|HELD\s+IN|ALT\s*BOM|"
    r"SHEET\s*NO|NO\.?\s*OF\s*SH|VERSION|CHANGE\s*NO|APVD|"
    r"BEL-PLM|PART\s*NUMBER|PROVISIONAL|THIRD\s+ANGLE"
    r")\b"
)
_PL_TABLE_HEADER = re.compile(
    r"(?i)\bITEM\b.*\b(?:DESIGNATION|PART\s*NO|PART\s*NUMBER|QTY|DESC)"
)
_TB_DESC_NOISE = re.compile(
    r"(?i)^\s*(?:"
    r"VER|VERSION|TITLE|DOC\s*TYPE|PART\s*NUMBER|PART\s*NO\.?|"
    r"HELD\s+IN|SHEET\s*NO\.?|NO\.?\s*OF\s*SH\.?|ALT\s*BOM|"
    r"CHANGE\s*NO\.?|CHANGE|DATE|APVD|APPROVED|SCALE|"
    r"BHARAT\s+ELECTRONICS|PROVISIONAL|ORIGINAL|REFER\s+ECR|"
    r"DESIGNATION|DESCRIPTION|DESC|ITEM|QTY|UNT|UNIT|CIRCUIT|REMARKS?"
    r")\s*:?\s*$"
)


def _is_title_block_line(raw: str) -> bool:
    """True for BEL end-of-sheet title-block labels/values (not PL item rows)."""
    s = re.sub(r"[ \t]+", " ", (raw or "")).strip()
    if not s:
        return False
    if _TB_STRONG.match(s) or _TB_LABEL.match(s) or _TB_KV.match(s):
        return True
    if _TB_DATE.match(s) or _TB_CHANGE_NO.match(s) or _TB_REV_TOKEN.match(s):
        return True
    return False


def _is_title_block_desc(desc: str) -> bool:
    s = re.sub(r"[ \t]+", " ", (desc or "")).strip()
    if not s:
        return True
    if _TB_DESC_NOISE.match(s) or _TB_STRONG.match(s) or _TB_KV.match(s):
        return True
    return False


def _tb_window_score(blob: str) -> int:
    return len(_TB_WINDOW_HINTS.findall(blob or ""))


def _looks_like_title_block_start(lines: list[str], i: int) -> bool:
    raw = re.sub(r"[ \t]+", " ", (lines[i] if 0 <= i < len(lines) else "")).strip()
    if not raw:
        return False
    if _TB_STRONG.match(raw):
        return True
    if _TB_LABEL.match(raw) or _TB_KV.match(raw) or _TB_REV_TOKEN.match(raw):
        window = " ".join(
            re.sub(r"[ \t]+", " ", lines[k]).strip()
            for k in range(i, min(i + 14, len(lines)))
        )
        if _tb_window_score(window) >= 2:
            return True
    return False


def _is_pl_table_header_line(raw: str) -> bool:
    s = re.sub(r"[ \t]+", " ", (raw or "")).strip()
    if _PL_TABLE_HEADER.search(s):
        return True
    up = s.upper()
    return up in {"ITEM", "DESIGNATION", "PART NO", "PART NUMBER", "QTY", "UNT", "UNIT"}


def _title_block_end(lines: list[str], start: int) -> int:
    """Index just past the end-of-sheet title block starting at ``start``."""
    i = start
    last_tb = start
    while i < len(lines):
        raw = re.sub(r"[ \t]+", " ", lines[i]).strip()
        if not raw or JUNK_LINE.match(raw):
            i += 1
            # Long blank run after TB content → block finished
            if i - last_tb > 6:
                break
            continue
        # Next sheet resumes with a 4-digit item row — stop (do not consume it)
        if ITEM_ONLY_LINE.match(raw) or (
            LINE_START.match(raw)
            and not _is_title_block_desc(LINE_START.match(raw).group(2))
        ):
            break
        if _is_pl_table_header_line(raw) and i > start:
            break
        if _is_title_block_line(raw) or _TB_STRONG.search(raw):
            last_tb = i
            i += 1
            continue
        # Title / assembly name / doc PN sitting inside the block
        if i <= last_tb + 12 and (
            _part_no_from_line(raw)
            or re.match(r"[A-Za-z]", raw)
            or _TB_KV.match(raw)
        ):
            last_tb = i
            i += 1
            continue
        # Anything else → past the title block
        break
    return max(i, start + 1)


def _strip_bel_pl_title_blocks(text: str) -> str:
    """Remove BEL title blocks that repeat at the end of each PL sheet."""
    if not text:
        return ""
    lines = text.splitlines()
    keep: list[str] = []
    i = 0
    while i < len(lines):
        if _looks_like_title_block_start(lines, i):
            i = _title_block_end(lines, i)
            # Preserve a blank separator so sheet boundaries stay readable
            if keep and keep[-1].strip():
                keep.append("")
            continue
        keep.append(lines[i])
        i += 1
    return "\n".join(keep)


def _extract_pl_doc_part_number(text: str) -> str:
    """Part number from the PL title block (document identity, not a BOM line)."""
    if not text:
        return ""
    m = re.search(
        r"(?i)(?:PART\s*NUMBER|PART\s*NO\.?)\s*:?\s*"
        r"(\d{4}\s+\d{3}\s+\d{3}\s+\d{2})",
        text,
    )
    if m:
        return _norm_part_no(m.group(1))
    return ""


def _norm_item_no(raw) -> int | None:
    """Parse BEL 4-digit item no (``0010`` → 10). Reject non-numeric / empty."""
    if raw is None or raw == "":
        return None
    try:
        s = str(raw).strip()
        if not re.fullmatch(r"\d{1,4}", s):
            return None
        n = int(s)
        return n if n > 0 else None
    except (TypeError, ValueError):
        return None


def format_item_no(item_no: int | str | None) -> str:
    """PL display form: always 4 digits (``10`` → ``0010``).

    GA drawings call the same item ``10`` / ``60`` / ``450`` (no padding).
    Matching must use the integer value; only PL tables show the padded form.
    """
    try:
        n = int(item_no)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return ""
    if n <= 0:
        return ""
    return f"{n:04d}"


def _norm_pl_text(raw: str) -> str:
    """PL designations are uppercase; collapse whitespace."""
    return re.sub(r"\s+", " ", str(raw or "")).strip().upper()[:200]


def _qty_value(raw: str) -> int | float:
    """Parse qty; keep decimals (0.5 / .5 m braid) as float, whole numbers as int."""
    s = str(raw).strip()
    if s.startswith("."):
        s = "0" + s
    val = float(s)
    if val.is_integer():
        return int(val)
    return val


def _coerce_pl_qty(raw) -> int | float | None:
    """Normalize a PL qty cell (int/float/str like ``1`` or ``1 NO``)."""
    if raw is None or raw == "":
        return None
    if isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        try:
            return _qty_value(str(raw))
        except (TypeError, ValueError):
            return None
    s = str(raw).strip()
    if not s:
        return None
    qm = QTY_RE.match(s) or QTY_LINE_LOOSE.match(s)
    if not qm:
        return None
    try:
        return _qty_value(qm.group(1))
    except (TypeError, ValueError):
        return None


def _looks_like_designation(line: str) -> bool:
    """True for a PL designation, including digit-leading ones (``24 SLOT…``)."""
    s = re.sub(r"[ \t]+", " ", (line or "")).strip()
    if not s or not re.search(r"[A-Za-z]", s):
        return False
    if ITEM_ONLY_LINE.match(s) or _part_no_from_line(s) or UNIT_ONLY_LINE.match(s):
        return False
    if QTY_LINE.match(s) and not re.search(r"[A-Za-z]", s):
        return False
    if _is_title_block_desc(s) or _is_title_block_line(s):
        return False
    upper = s.upper()
    if upper.startswith(
        (
            "DESIGNATION",
            "PART NO",
            "PART NUMBER",
            "DESCRIPTION",
            "DESC",
            "ITEM",
            "QTY",
            "UNT",
            "UNIT",
            "CIRCUIT",
            "REMARK",
            "VERSION",
            "VER ",
            "SHEET",
            "HELD IN",
            "DOC TYPE",
            "ALT BOM",
            "TITLE",
            "REFER ECR",
            "ORIGINAL",
            "PROVISIONAL",
        )
    ) or upper == "VER":
        return False
    # Letter-first, or "24 SLOT…" / "12 SLOT…" style
    return bool(re.match(r"(?:[A-Za-z/(]|\d{1,4}\s+[A-Za-z])", s))


def _bare_number_is_next_item(lines: list[str], idx: int) -> bool:
    """True when ``lines[idx]`` is a bare item no that starts the next PL row.

    Stacked PDF text often looks like::

        <part no>
        20          ← next ITEM (sometimes unpadded), not qty
        DESIGNATION…
        <part no>
        1
        NO          ← qty + unit on separate lines

    Consuming bare ``20`` / ``560`` as qty is the classic PL-qty bug.
    """
    if idx < 0 or idx >= len(lines):
        return False
    raw = re.sub(r"[ \t]+", " ", lines[idx]).strip()
    # 4-digit PL item, or short bare number that starts the next row
    if not (ITEM_ONLY_LINE.match(raw) or BARE_NUM_LINE.match(raw)):
        return False
    j = _next_nonempty(lines, idx + 1)
    if j < 0:
        return False  # trailing bare number after last PN → qty
    nxt = re.sub(r"[ \t]+", " ", lines[j]).strip()
    # Qty then unit on the next line: "1" / "NO"
    if UNIT_ONLY_LINE.match(nxt):
        return False
    if ITEM_ONLY_LINE.match(nxt) or BARE_NUM_LINE.match(nxt) or _part_no_from_line(nxt):
        return False
    if QTY_LINE.match(nxt) and not re.search(r"[A-Za-z]", nxt):
        return False
    return _looks_like_designation(nxt)


def _parse_qty_at(lines: list[str], idx: int) -> tuple[int | float, str, int] | None:
    """Parse qty(+unit) at ``idx``.

    Returns ``(qty, unit, end_idx)`` so a following standalone ``NO`` line is
    consumed as the unit. Refuses bare numbers that start the next item.
    """
    if idx < 0 or idx >= len(lines):
        return None
    qty_raw = re.sub(r"[ \t]+", " ", lines[idx]).strip()
    if not qty_raw or JUNK_LINE.match(qty_raw):
        return None
    if _bare_number_is_next_item(lines, idx):
        return None
    qm = QTY_LINE.match(qty_raw) or QTY_LINE_LOOSE.match(qty_raw)
    if not qm:
        return None
    rest_after_num = qty_raw[len(qm.group(1)) :].lstrip()
    is_decimal = "." in qm.group(1)
    next_itemish = (
        not is_decimal
        and LINE_START.match(qty_raw)
        and rest_after_num
        and not rest_after_num.upper().startswith(
            ("NO", "MM", "EA", "PCS", "SET", "MTR", "KG", "M", "ST")
        )
    )
    unit_ok = bool(qm.group(2)) or (not rest_after_num) or is_decimal
    if not unit_ok or next_itemish:
        return None
    qty = _qty_value(qm.group(1))
    unit = (qm.group(2) or "").upper()
    end_idx = idx
    if not unit:
        # BEL tables often put UNT on the next line after QTY
        n = _next_nonempty(lines, idx + 1)
        if n >= 0 and UNIT_ONLY_LINE.match(re.sub(r"[ \t]+", " ", lines[n]).strip()):
            unit = UNIT_ONLY_LINE.match(re.sub(r"[ \t]+", " ", lines[n]).strip()).group(1).upper()
            end_idx = n
        else:
            unit = "NO"
    return qty, unit, end_idx


def _next_nonempty(lines: list[str], start: int) -> int:
    j = start
    while j < len(lines):
        raw = lines[j].strip()
        if raw and not JUNK_LINE.match(raw):
            return j
        j += 1
    return -1


def _part_no_from_line(line: str) -> re.Match | None:
    """Return a match if the line is (mostly) a BEL part number alone."""
    s = line.strip()
    m = PART_NO_LINE.match(s) or PART_NO_LINE_FLEX.match(s)
    if m:
        return m
    # Part no with trailing whitespace/junk but nothing before it
    m = PART_NO_RE.search(s) or PART_NO_FLEX.search(s)
    if m and not s[: m.start()].strip():
        return m
    return None


def _item_from_stacked_columns(lines: list[str], i: int) -> tuple[dict, int] | None:
    """
    Stitch column-per-line PL rows where ITEM is alone on its line:

        10
        CONN CIRS TSTC PL 13-35 CRP 22 P N
        4615 010 027 12
        1

    (Also used when qty is decimal, e.g. 0.5 for braid / sleeve metres.)
    """
    raw = lines[i].strip()
    im = ITEM_ONLY_LINE.match(raw)
    if not im:
        return None
    # 4-digit item nos only; title-block VER "02" is 2 digits and never matches here
    item_no = int(im.group(1))
    if item_no <= 0:
        return None
    # Do not stitch a row if the previous line was a title-block label
    if i > 0:
        p = i - 1
        while p >= 0 and (not lines[p].strip() or JUNK_LINE.match(lines[p].strip())):
            p -= 1
        if p >= 0 and _is_title_block_line(lines[p]):
            return None

    j = _next_nonempty(lines, i + 1)
    if j < 0:
        return None
    desc_line = re.sub(r"[ \t]+", " ", lines[j]).strip()
    if not _looks_like_designation(desc_line):
        return None
    # Absorb wrapped designation lines until the part-number column
    desc_chunks = [desc_line]
    desc_end = j
    while True:
        n = _next_nonempty(lines, desc_end + 1)
        if n < 0:
            break
        cont = re.sub(r"[ \t]+", " ", lines[n]).strip()
        if _part_no_from_line(cont) or ITEM_ONLY_LINE.match(cont):
            break
        if UNIT_ONLY_LINE.match(cont):
            break
        if QTY_LINE.match(cont) and not re.search(r"[A-Za-z]", cont):
            break
        if not _looks_like_designation(cont):
            break
        desc_chunks.append(cont)
        desc_end = n
    desc = re.sub(r"\s+", " ", " ".join(desc_chunks)).strip()[:200]

    k = _next_nonempty(lines, desc_end + 1)
    if k < 0:
        return None
    pn_m = _part_no_from_line(lines[k])
    if not pn_m:
        return None

    qty: int | float = 1
    unit = "NO"
    consumed_end = k
    m = _next_nonempty(lines, k + 1)
    if m >= 0:
        parsed_qty = _parse_qty_at(lines, m)
        if parsed_qty:
            qty, unit, consumed_end = parsed_qty

    hit = {
        "itemNo": item_no,
        "partNumber": _norm_part_no(pn_m.group(1)),
        "description": desc,
        "qty": qty,
        "unit": unit.upper(),
    }
    return hit, consumed_end - i + 1


def _item_from_multiline(lines: list[str], i: int) -> tuple[dict, int] | None:
    """
    Stitch pymupdf column-per-line PL rows:

        1 MECHANICAL ASSY_MFR_PSPU
        1180 005 096 03
        1 NO
        ,,,
    """
    raw = re.sub(r"[ \t]+", " ", lines[i]).strip()
    start = LINE_START.match(raw)
    if not start:
        return None
    item_no = int(start.group(1))
    rest = start.group(2)
    upper = rest.upper()
    if (
        upper.startswith("DESIGNATION")
        or upper.startswith("PART NO")
        or upper.startswith("PART NUMBER")
        or upper.startswith("DESCRIPTION")
        or upper.startswith("DESC")
        or upper.startswith("VERSION")
        or upper.startswith("VER ")
        or upper == "VER"
        or upper.startswith("SHEET")
        or upper.startswith("HELD IN")
        or upper.startswith("DOC TYPE")
        or upper.startswith("ALT BOM")
        or upper.startswith("TITLE")
    ):
        return None
    if _is_title_block_desc(rest):
        return None
    # Same-line part no belongs to _item_from_text_line
    if PART_NO_RE.search(rest) or PART_NO_FLEX.search(rest):
        return None
    desc = re.sub(r"\s+", " ", rest).strip()[:200]
    if not desc or not _looks_like_designation(desc):
        return None

    j = _next_nonempty(lines, i + 1)
    if j < 0:
        return None
    pn_m = _part_no_from_line(lines[j])
    if not pn_m:
        return None

    qty: int | float = 1
    unit = "NO"
    consumed_end = j
    k = _next_nonempty(lines, j + 1)
    if k >= 0:
        parsed_qty = _parse_qty_at(lines, k)
        if parsed_qty:
            qty, unit, consumed_end = parsed_qty

    hit = {
        "itemNo": item_no,
        "partNumber": _norm_part_no(pn_m.group(1)),
        "description": desc,
        "qty": qty,
        "unit": unit.upper(),
    }
    return hit, consumed_end - i + 1


def _parse_pl_line_items(text: str) -> list[dict]:
    items: list[dict] = []
    # Drop end-of-sheet BEL title blocks (VERSION/VER/SHEET NO/…) before row parse
    lines = _strip_bel_pl_title_blocks(text or "").splitlines()
    i = 0
    while i < len(lines):
        raw_line = lines[i]
        if not raw_line.strip():
            i += 1
            continue
        if _is_title_block_line(raw_line) or _is_pl_table_header_line(raw_line):
            i += 1
            continue
        if "\t" in raw_line:
            cells = [c.strip() for c in raw_line.split("\t") if str(c).strip()]
            hit = _item_from_cells(cells)
            if hit:
                # qty may be on next line: "1 NO" (never bare next-item numbers)
                parsed_qty = _parse_qty_at(lines, i + 1) if i + 1 < len(lines) else None
                if parsed_qty:
                    hit["qty"], hit["unit"], end_idx = parsed_qty
                    i = end_idx
                items.append(hit)
                i += 1
                continue
        hit = _item_from_text_line(raw_line)
        if hit:
            parsed_qty = _parse_qty_at(lines, i + 1) if i + 1 < len(lines) else None
            if parsed_qty:
                hit["qty"], hit["unit"], end_idx = parsed_qty
                i = end_idx
            items.append(hit)
            i += 1
            continue
        # Prefer stacked "item / desc / pn / qty" (wiring PLs) before same-line item+desc
        stacked = _item_from_stacked_columns(lines, i)
        if stacked:
            hit, consumed = stacked
            items.append(hit)
            i += max(consumed, 1)
            continue
        multi = _item_from_multiline(lines, i)
        if multi:
            hit, consumed = multi
            items.append(hit)
            i += max(consumed, 1)
            continue
        i += 1
    return items


def _norm_part_no(raw: str) -> str:
    raw = re.sub(r"\s+", " ", str(raw or "")).strip()
    digits = re.sub(r"\D", "", raw)
    if len(digits) == 12:
        return f"{digits[0:4]} {digits[4:7]} {digits[7:10]} {digits[10:12]}"
    if len(digits) >= 8:
        # Keep readable spacing for partial numbers from broken PDF text
        return raw
    return raw


def _part_number_from_filename(filename: str) -> str:
    digits = re.sub(r"\D", "", filename or "")
    if len(digits) >= 12:
        return f"{digits[0:4]} {digits[4:7]} {digits[7:10]} {digits[10:12]}"
    return ""


def _finalize(items: list[dict], filename: str, warnings: list[str], raw_text: str = "") -> dict:
    doc_pn = _extract_pl_doc_part_number(raw_text) or _part_number_from_filename(filename)
    doc_pn_digits = re.sub(r"\D", "", doc_pn or "")
    by_no: dict[int, dict] = {}
    for it in items:
        row = dict(it)
        try:
            ino = int(row.get("itemNo"))
        except (TypeError, ValueError):
            continue
        row["itemNo"] = ino
        row["itemNoDisplay"] = format_item_no(ino)
        row["description"] = _norm_pl_text(row.get("description") or "")
        if row.get("unit"):
            row["unit"] = str(row["unit"]).strip().upper()
        if _is_title_block_desc(row.get("description") or ""):
            continue
        # Title-block document PN is not a BOM line item
        if doc_pn_digits and len(doc_pn_digits) >= 12:
            it_digits = re.sub(r"\D", "", str(row.get("partNumber") or ""))
            if it_digits == doc_pn_digits:
                continue
        # Keep first designation when duplicate item numbers appear (e.g. alt RAM)
        if ino not in by_no:
            by_no[ino] = row
        else:
            existing = by_no[ino]
            if row.get("description") and len(row["description"]) > len(existing.get("description") or ""):
                by_no[ino] = row
    items = [by_no[k] for k in sorted(by_no)]
    if not items:
        warnings.append(
            "Parts List uploaded but no item rows matched yet. "
            "Expected columns: ITEM | DESIGNATION | PART NO | QTY."
        )
    # Index by both GA short form ("60") and PL padded form ("0060")
    item_map: dict[str, dict] = {}
    for it in items:
        ino = int(it["itemNo"])
        item_map[str(ino)] = it
        item_map[format_item_no(ino)] = it
    return {
        "docType": "PL",
        "partNumber": doc_pn or _part_number_from_filename(filename),
        "title": filename,
        "items": items,
        "itemMap": item_map,
        "warnings": warnings,
        "raw_text": raw_text[:50000],
    }


def _item_from_cells(cells: list[str]) -> dict | None:
    if len(cells) < 3:
        return None
    item_raw = cells[0].strip()
    if not re.fullmatch(r"\d{4}", item_raw):
        return None
    item_no = int(item_raw)
    pn_idx = next(
        (i for i, c in enumerate(cells[1:], 1) if PART_NO_RE.search(c) or PART_NO_FLEX.search(c)),
        None,
    )
    if pn_idx is None:
        return None
    pn_m = PART_NO_RE.search(cells[pn_idx]) or PART_NO_FLEX.search(cells[pn_idx])
    if not pn_m:
        return None
    desc_parts: list[str] = []
    qty: int | float = 1
    unit = "NO"
    seen_qty = False
    for i, c in enumerate(cells[1:], 1):
        if i == pn_idx:
            continue
        cell = c.strip()
        if not cell or JUNK_LINE.match(cell) or re.fullmatch(r"[,.\s]+", cell):
            continue
        if UNIT_ONLY_LINE.match(cell):
            unit = UNIT_ONLY_LINE.match(cell).group(1).upper()
            continue
        qm = QTY_RE.fullmatch(cell)
        if qm:
            qty = _qty_value(qm.group(1))
            if qm.group(2):
                unit = qm.group(2).upper()
            seen_qty = True
            continue
        if PART_NO_RE.search(cell) or PART_NO_FLEX.search(cell):
            continue
        up = cell.upper()
        if up in {"CIRCUIT REFERENCE", "REMARKS", "ENV REL", "GR", "UNT", "UNIT", "UOM"}:
            continue
        # After QTY/UNT, remaining cells are circuit refs — keep out of designation
        if seen_qty or i > pn_idx:
            continue
        if not _looks_like_designation(cell) and not re.search(r"[A-Za-z]", cell):
            continue
        desc_parts.append(cell)
    desc = re.sub(r"\s+", " ", " ".join(desc_parts)).strip()[:200]
    if not desc:
        return None
    return {
        "itemNo": item_no,
        "partNumber": _norm_part_no(pn_m.group(1)),
        "description": desc,
        "qty": qty,
        "unit": unit.upper(),
    }


def _item_from_text_line(line: str) -> dict | None:
    line = re.sub(r"[ \t]+", " ", line).strip()
    glued = GLUED_ROW.match(line)
    if glued:
        desc = re.sub(r"\s+", " ", glued.group(2)).strip(" -")[:200]
        if not desc:
            return None
        return {
            "itemNo": int(glued.group(1)),
            "partNumber": _norm_part_no(glued.group(3)),
            "description": desc,
            "qty": 1,
            "unit": "NO",
        }
    start = LINE_START.match(line)
    if not start:
        return None
    item_no = int(start.group(1))
    rest = start.group(2)
    up = rest.upper()
    if (
        up.startswith("DESIGNATION")
        or up.startswith("PART NO")
        or up.startswith("PART NUMBER")
        or up.startswith("DESCRIPTION")
        or up.startswith("DESC")
        or up.startswith("VERSION")
        or up.startswith("VER ")
        or up == "VER"
        or up.startswith("SHEET")
        or up.startswith("HELD IN")
        or up.startswith("DOC TYPE")
        or up.startswith("ALT BOM")
        or up.startswith("TITLE")
        or _is_title_block_desc(rest)
    ):
        return None
    pn = PART_NO_RE.search(rest) or PART_NO_FLEX.search(rest)
    if not pn:
        return None
    desc = re.sub(r"\s+", " ", rest[: pn.start()]).strip()[:200]
    if not desc:
        # designation glued into part start: POWERSUP4579…
        glued2 = re.match(r"^([A-Za-z][A-Za-z /()-]{1,40}?)(\d{4}\b.*)$", rest)
        if glued2:
            desc = glued2.group(1).strip()
            pn = PART_NO_RE.search(glued2.group(2)) or PART_NO_FLEX.search(glued2.group(2))
            if not pn or not desc:
                return None
        else:
            return None
    after = rest[pn.end() :].strip() if pn else ""
    qm = QTY_RE.match(after)
    qty = _qty_value(qm.group(1)) if qm else 1
    unit = (qm.group(2) if qm and qm.lastindex and qm.group(2) else "") or "NO"
    return {
        "itemNo": item_no,
        "partNumber": _norm_part_no(pn.group(1)),
        "description": desc,
        "qty": qty,
        "unit": unit.upper(),
    }


def parse_partslist_pdf(data: bytes, filename: str = "", *, format_aliases: dict | None = None) -> dict:
    warnings: list[str] = []
    result = ingest_pdf(data, want_tables=True)
    warnings.extend(result.warnings)
    if result.method == "ocr":
        warnings.append("Parts List used offline OCR (Tesseract).")

    text = result.text
    if format_aliases:
        from app.route_card.format_templates import apply_aliases_to_text

        text = apply_aliases_to_text(text, format_aliases, doc_type="PL")

    tsv = tables_to_tsv_lines(result.tables)
    if tsv and format_aliases:
        from app.route_card.format_templates import apply_aliases_to_text

        tsv = apply_aliases_to_text(tsv, format_aliases, doc_type="PL")

    items: list[dict] = []
    # Prefer embedded tables (ITEM/QTY/UNT columns) — more accurate than stacked text
    tsv_items: list[dict] = []
    if tsv and len(tsv.strip()) >= 40 and re.search(r"(?i)\bITEM\b", tsv):
        tsv_items = _parse_pl_line_items(tsv)
    text_items = (
        _parse_pl_line_items(text) if text and len(text.strip()) >= 40 else []
    )
    if tsv_items:
        items.extend(tsv_items)
        have = {it["itemNo"] for it in tsv_items}
        for it in text_items:
            if it["itemNo"] not in have:
                items.append(it)
    else:
        items.extend(text_items)

    if not items and len((text or "").strip()) < 40:
        warnings.append("Parts List PDF has little/no text layer.")

    out = _finalize(items, filename, warnings, text or tsv or "")
    out["ingest_method"] = result.method
    out["tableCount"] = len(result.tables)
    return out


def parse_partslist_xls(data: bytes, filename: str = "") -> dict:
    warnings: list[str] = []
    # Some "PL.xls" exports are actually TSV/CSV text with an .xls extension
    head = data[:64]
    if b"ITEM" in head.upper() and (b"\t" in head or b"," in head) and not head.startswith(b"\xd0\xcf"):
        try:
            text = data.decode("utf-8", errors="ignore")
        except Exception:
            text = data.decode("latin-1", errors="ignore")
        items = _parse_pl_line_items(text)
        if items:
            return _finalize(items, filename, ["Parts List .xls was plain text/TSV; parsed as table text."], text)
    try:
        import xlrd
    except ImportError:
        return _finalize(
            [],
            filename,
            ["xlrd is not installed on the server; cannot parse .xls. Use the PDF Parts List."],
        )

    try:
        book = xlrd.open_workbook(file_contents=data)
    except Exception as exc:
        # Fallback: try as tab/CSV text when xlrd rejects the file
        try:
            text = data.decode("utf-8", errors="ignore")
        except Exception:
            text = data.decode("latin-1", errors="ignore")
        items = _parse_pl_line_items(text)
        if items:
            return _finalize(
                items,
                filename,
                [f"Could not open as Excel ({exc}); parsed as plain text instead."],
                text,
            )
        return _finalize([], filename, [f"Could not open .xls: {exc}"])

    items = []
    for si in range(book.nsheets):
        sheet = book.sheet_by_index(si)
        # Find header row
        header_row = 0
        col_map = {"item": 0, "designation": 1, "part": 2, "qty": 3, "unit": 4}
        for r in range(min(5, sheet.nrows)):
            cells = [str(sheet.cell_value(r, c)).strip().upper() for c in range(min(sheet.ncols, 8))]
            joined = " ".join(cells)
            if "ITEM" in joined and (
                "DESIGNATION" in joined
                or "PART" in joined
                or "DESC" in joined
                or "DESCRIPTION" in joined
            ):
                header_row = r
                for c, label in enumerate(cells):
                    if label.startswith("ITEM") or label in {"ITM", "SL", "S.NO", "SNO"}:
                        col_map["item"] = c
                    elif "DESIGN" in label or label.startswith("DESC") or "NAME" in label:
                        col_map["designation"] = c
                    elif "PART" in label or label in {"P/N", "PN", "PNO"}:
                        col_map["part"] = c
                    elif label.startswith("QTY") or label in {"QTY", "QUANTITY", "QTY."}:
                        col_map["qty"] = c
                    elif label.startswith("UNT") or label.startswith("UNIT") or label == "UOM":
                        col_map["unit"] = c
                break

        for r in range(header_row + 1, sheet.nrows):
            try:
                raw_item = sheet.cell_value(r, col_map["item"])
                if raw_item in ("", None):
                    continue
                item_no = int(float(raw_item))
            except (ValueError, TypeError, IndexError):
                continue
            try:
                desc = str(sheet.cell_value(r, col_map["designation"])).strip()
                part_no = _norm_part_no(sheet.cell_value(r, col_map["part"]))
                qty_raw = sheet.cell_value(r, col_map["qty"])
                if qty_raw in ("", None):
                    qty: int | float = 1
                else:
                    qty = _qty_value(str(qty_raw).strip())
                unit = ""
                if col_map["unit"] < sheet.ncols:
                    unit = str(sheet.cell_value(r, col_map["unit"])).strip()
            except (ValueError, TypeError, IndexError):
                continue
            if not desc and not part_no:
                continue
            items.append(
                {
                    "itemNo": item_no,
                    "partNumber": part_no,
                    "description": re.sub(r"\s+", " ", desc)[:200],
                    "qty": qty,
                    "unit": unit or "NO",
                }
            )

    return _finalize(items, filename, warnings)


def parse_partslist_xlsx(data: bytes, filename: str = "") -> dict:
    warnings: list[str] = []
    try:
        from openpyxl import load_workbook
    except ImportError:
        return _finalize(
            [],
            filename,
            ["openpyxl is not installed on the server; cannot parse .xlsx. Use PDF or .xls."],
        )
    try:
        book = load_workbook(BytesIO(data), read_only=True, data_only=True)
    except Exception as exc:
        return _finalize([], filename, [f"Could not open .xlsx: {exc}"])

    items: list[dict] = []
    try:
        for sheet in book.worksheets:
            rows = list(sheet.iter_rows(values_only=True))
            if not rows:
                continue
            header_row = 0
            col_map = {"item": 0, "designation": 1, "part": 2, "qty": 3, "unit": 4}
            for r, row in enumerate(rows[:5]):
                cells = [str(c or "").strip().upper() for c in (row or [])[:8]]
                joined = " ".join(cells)
                if "ITEM" in joined and (
                    "DESIGNATION" in joined
                    or "PART" in joined
                    or "DESC" in joined
                    or "DESCRIPTION" in joined
                ):
                    header_row = r
                    for c, label in enumerate(cells):
                        if label.startswith("ITEM") or label in {"ITM", "SL", "S.NO", "SNO"}:
                            col_map["item"] = c
                        elif "DESIGN" in label or label.startswith("DESC") or "NAME" in label:
                            col_map["designation"] = c
                        elif "PART" in label or label in {"P/N", "PN", "PNO"}:
                            col_map["part"] = c
                        elif label.startswith("QTY") or label in {"QTY", "QUANTITY", "QTY."}:
                            col_map["qty"] = c
                        elif label.startswith("UNT") or label.startswith("UNIT") or label == "UOM":
                            col_map["unit"] = c
                    break

            for row in rows[header_row + 1 :]:
                cells = list(row or [])
                try:
                    raw_item = cells[col_map["item"]] if col_map["item"] < len(cells) else None
                    if raw_item in ("", None):
                        continue
                    item_no = int(float(raw_item))
                except (ValueError, TypeError, IndexError):
                    continue
                try:
                    desc = str(cells[col_map["designation"]] if col_map["designation"] < len(cells) else "").strip()
                    part_no = _norm_part_no(cells[col_map["part"]] if col_map["part"] < len(cells) else "")
                    qty_raw = cells[col_map["qty"]] if col_map["qty"] < len(cells) else None
                    qty: int | float = 1 if qty_raw in ("", None) else _qty_value(str(qty_raw).strip())
                    unit = ""
                    if col_map["unit"] < len(cells):
                        unit = str(cells[col_map["unit"]] or "").strip()
                except (ValueError, TypeError, IndexError):
                    continue
                if not desc and not part_no:
                    continue
                items.append(
                    {
                        "itemNo": item_no,
                        "partNumber": part_no,
                        "description": re.sub(r"\s+", " ", desc)[:200],
                        "qty": qty,
                        "unit": unit or "NO",
                    }
                )
    finally:
        book.close()
    return _finalize(items, filename, warnings)


def parse_partslist_bytes(data: bytes, filename: str = "", *, format_aliases: dict | None = None) -> dict:
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext == "pdf":
        return parse_partslist_pdf(data, filename, format_aliases=format_aliases)
    if ext == "xls":
        return parse_partslist_xls(data, filename)
    if ext == "xlsx":
        return parse_partslist_xlsx(data, filename)
    return _finalize(
        [],
        filename,
        [f"Unsupported Parts List type .{ext or 'unknown'}. Use PDF or Excel (.xls / .xlsx)."],
    )


def rebuild_bom_from_pl(
    pl: dict | None,
    *,
    existing_bom: list[dict] | None = None,
    extracted_by_item: dict[int, int] | None = None,
) -> list[dict]:
    """Build the BOM table as the Parts List in item-no order.

    - Every PL row is included (PN, description, unit, PL qty).
    - ``extractedQty`` / GA presence come from balloon callouts (and prior BOM).
    - Items on the PL but not on the GA are marked ``gaPresence=not_present``.
    - GA-only callouts (not on PL) are appended at the end.
    """
    if not pl:
        return [dict(b) for b in (existing_bom or []) if isinstance(b, dict)]

    extracted: dict[int, int | float] = {}
    for k, v in (extracted_by_item or {}).items():
        try:
            extracted[int(k)] = int(v) if float(v) == int(v) else float(v)
        except (TypeError, ValueError):
            continue

    ga_refs: set[int] = set(extracted.keys())
    prior_meta: dict[int, dict] = {}
    for b in existing_bom or []:
        if not isinstance(b, dict):
            continue
        try:
            ino = int(b.get("itemNo") or b.get("item_no") or 0)
        except (TypeError, ValueError):
            continue
        if not ino:
            continue
        prior_meta[ino] = b
        ext = b.get("extractedQty")
        if ext is not None and str(ext).strip() != "":
            try:
                extracted.setdefault(ino, int(ext) if float(ext) == int(float(ext)) else float(ext))
                ga_refs.add(ino)
            except (TypeError, ValueError):
                pass
        elif b.get("onDrawing") or b.get("gaPresence") == "present":
            ga_refs.add(ino)
        elif str(b.get("source") or "").lower() in {"balloon", "ga", "drawing"}:
            # Prior GA/balloon row without extractedQty — still counts as on drawing.
            ga_refs.add(ino)
            if ino not in extracted and b.get("qty") not in (None, ""):
                try:
                    extracted[ino] = int(b.get("qty") or 0) or 0
                except (TypeError, ValueError):
                    pass

    # Collect PL items (items[] preferred; fill gaps from itemMap)
    by_no: dict[int, dict] = {}
    for it in pl.get("items") or []:
        if not isinstance(it, dict):
            continue
        try:
            ino = int(it.get("itemNo") or it.get("item_no") or it.get("no"))
        except (TypeError, ValueError):
            continue
        if ino > 0:
            by_no[ino] = it
    for k, v in (pl.get("itemMap") or {}).items():
        if not isinstance(v, dict):
            continue
        try:
            ino = int(k)
        except (TypeError, ValueError):
            continue
        if ino > 0:
            by_no.setdefault(ino, v)

    out: list[dict] = []
    pl_nos: set[int] = set()
    for ino in sorted(by_no):
        it = by_no[ino]
        pl_nos.add(ino)
        pl_qty = _coerce_pl_qty(it.get("qty"))
        if pl_qty is None:
            pl_qty = 1
        on_ga = ino in ga_refs or ino in extracted
        ext = extracted.get(ino) if on_ga else None
        qty_match = None
        if on_ga and ext is not None:
            try:
                qty_match = float(ext) == float(pl_qty)
            except (TypeError, ValueError):
                qty_match = None
        prior = prior_meta.get(ino) or {}
        out.append(
            {
                "itemNo": ino,
                "itemNoDisplay": format_item_no(ino),
                "qty": pl_qty,
                "extractedQty": ext,
                "partNumber": it.get("partNumber")
                or it.get("part_number")
                or prior.get("partNumber")
                or "",
                "description": _norm_pl_text(
                    it.get("description") or prior.get("description") or ""
                ),
                "unit": str(it.get("unit") or prior.get("unit") or "NO").strip().upper(),
                "source": "pl",
                "onDrawing": on_ga,
                "gaPresence": "present" if on_ga else "not_present",
                "qtyMatch": qty_match,
            }
        )

    # GA / balloon callouts that never appear on the PL
    for ino in sorted(set(extracted.keys()) | ga_refs):
        if ino in pl_nos:
            continue
        prior = prior_meta.get(ino) or {}
        ext = extracted.get(ino)
        out.append(
            {
                "itemNo": ino,
                "itemNoDisplay": format_item_no(ino),
                "qty": None,
                "extractedQty": ext,
                "partNumber": prior.get("partNumber") or prior.get("part_number") or "",
                "description": _norm_pl_text(prior.get("description") or ""),
                "unit": str(prior.get("unit") or "").strip().upper(),
                "source": prior.get("source") or "ga",
                "onDrawing": True,
                "gaPresence": "ga_only",
                "qtyMatch": None,
            }
        )
    return out


def enrich_bom_with_pl(
    bom_items: list[dict],
    pl: dict,
    *,
    extracted_by_item: dict[int, int] | None = None,
) -> list[dict]:
    """PL-ordered BOM with authoritative PL qty (wrapper around ``rebuild_bom_from_pl``)."""
    return rebuild_bom_from_pl(
        pl,
        existing_bom=bom_items,
        extracted_by_item=extracted_by_item,
    )


def enrich_ops_items(operations: list[dict], pl: dict) -> list[dict]:
    item_map = pl.get("itemMap") or {}
    out = []
    for op in operations or []:
        row = dict(op)
        used = []
        for it in row.get("itemsUsed") or []:
            u = dict(it)
            key = str(u.get("itemNo")) if u.get("itemNo") is not None else ""
            hit = item_map.get(key)
            if hit:
                u["description"] = hit.get("description")
                u["partNumber"] = hit.get("partNumber")
            used.append(u)
        row["itemsUsed"] = used
        if used:
            row["items"] = ", ".join(
                f"#{i.get('itemNo')}"
                + (f" {i.get('description')}" if i.get("description") else "")
                + (f"×{i.get('qty')}" if i.get("qty") else "")
                for i in used
                if i.get("itemNo") is not None
            )
        out.append(row)
    return out
