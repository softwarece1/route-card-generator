"""Parse BEL Parts List (PL) from PDF or legacy .xls into itemNo → part/description."""

from __future__ import annotations

import re
from io import BytesIO

from app.route_card.pdf_ingest import ingest_pdf, tables_to_tsv_lines

# Full BEL part no: 4 3 3 2 — may be glued to designation (…COATIN4585 116 802 83)
PART_NO_RE = re.compile(r"(\d{4}\s+\d{3}\s+\d{3}\s+\d{2})")
# Truncated / partial part nos common in poor PDF text layers: 4 3 1-3
PART_NO_FLEX = re.compile(r"(\d{4}\s+\d{3}\s+\d{1,3}(?:\s+\d{1,2})?)")
# item + designation letters glued to part digits, e.g. "1 POWERSUP4579 229 8"
GLUED_ROW = re.compile(
    r"^\s*(\d{1,4})\s+([A-Za-z][A-Za-z0-9 /().\-]{0,60}?)(\d{4}\s+\d{3}\s+\d{1,3}(?:\s+\d{1,2})?)\s*$"
)
# Line starts with item no (space optional: 10THERMAL…), then designation letter
LINE_START = re.compile(r"^\s*(\d{1,4})\s*([A-Za-z/(].*)$")
QTY_RE = re.compile(r"^(\d+(?:\.\d+)?)\s*(NO|MM|EA|PCS|SET|MTR|KG|M|ST)?", re.I)
QTY_LINE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*(NO|MM|EA|PCS|SET|MTR|KG|M|ST)?\s*$", re.I)
# Qty with trailing circuit-ref junk: "6 NO ITEM002,,," or "1 NO ,,,"
QTY_LINE_LOOSE = re.compile(
    r"^\s*(\d+(?:\.\d+)?)\s*(NO|MM|EA|PCS|SET|MTR|KG|M|ST)?\b",
    re.I,
)
# Standalone BEL part-number line (pymupdf often puts each column on its own line)
PART_NO_LINE = re.compile(r"^\s*(\d{4}\s+\d{3}\s+\d{3}\s+\d{2})\s*$")
PART_NO_LINE_FLEX = re.compile(r"^\s*(\d{4}\s+\d{3}\s+\d{1,3}(?:\s+\d{1,2})?)\s*$")
# Item number alone on its own line (common on wiring / cable PLs)
ITEM_ONLY_LINE = re.compile(r"^\s*(\d{1,4})\s*$")
JUNK_LINE = re.compile(r"^[\s,]+$")


def _qty_value(raw: str) -> int | float:
    """Parse qty; keep decimals (0.5 m braid) as float, whole numbers as int."""
    val = float(raw)
    if val.is_integer():
        return int(val)
    return val


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
    item_no = int(im.group(1))
    if item_no <= 0:
        return None

    j = _next_nonempty(lines, i + 1)
    if j < 0:
        return None
    desc_line = re.sub(r"[ \t]+", " ", lines[j]).strip()
    # Must look like a designation, not another item / part no / qty
    if ITEM_ONLY_LINE.match(desc_line) or _part_no_from_line(desc_line):
        return None
    if QTY_LINE.match(desc_line) and not re.search(r"[A-Za-z]", desc_line):
        return None
    upper = desc_line.upper()
    if (
        upper.startswith("DESIGNATION")
        or upper.startswith("PART NO")
        or upper.startswith("PART NUMBER")
        or upper.startswith("DESCRIPTION")
        or upper.startswith("DESC")
        or upper.startswith("ITEM")
        or upper.startswith("QTY")
        or upper.startswith("UNT")
        or upper.startswith("UNIT")
        or upper.startswith("CIRCUIT")
        or upper.startswith("REMARK")
    ):
        return None
    if not re.match(r"[A-Za-z/(]", desc_line):
        return None
    desc = desc_line[:200]

    k = _next_nonempty(lines, j + 1)
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
        qty_raw = re.sub(r"[ \t]+", " ", lines[m]).strip()
        qm = QTY_LINE.match(qty_raw) or QTY_LINE_LOOSE.match(qty_raw)
        if qm:
            rest_after_num = qty_raw[len(qm.group(1)) :].lstrip()
            # Decimal qty like "0.5" is never an item number; bare "1"/"10" after
            # a part no is qty when it does not start a designation.
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
            if unit_ok and not next_itemish:
                qty = _qty_value(qm.group(1))
                unit = (qm.group(2) or unit).upper()
                consumed_end = m

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
    ):
        return None
    # Same-line part no belongs to _item_from_text_line
    if PART_NO_RE.search(rest) or PART_NO_FLEX.search(rest):
        return None
    desc = re.sub(r"\s+", " ", rest).strip()[:200]
    if not desc or not re.match(r"[A-Za-z/(]", desc):
        return None

    j = _next_nonempty(lines, i + 1)
    if j < 0:
        return None
    pn_m = _part_no_from_line(lines[j])
    if not pn_m:
        return None

    qty = 1
    unit = "NO"
    consumed_end = j
    k = _next_nonempty(lines, j + 1)
    if k >= 0:
        qty_raw = re.sub(r"[ \t]+", " ", lines[k]).strip()
        # "6 NO ITEM002,,," is qty; "6 CARD MOUNT…" is the next item row
        qm = QTY_LINE.match(qty_raw) or QTY_LINE_LOOSE.match(qty_raw)
        if qm:
            after = qty_raw[qm.end() :].strip()
            rest_after_num = qty_raw[len(qm.group(1)) :].lstrip()
            unit_ok = bool(qm.group(2)) or (not rest_after_num)
            # If digits are followed by a designation (not a unit), it's the next item
            next_item = LINE_START.match(qty_raw) and not (
                rest_after_num.upper().startswith("NO")
                or rest_after_num.upper().startswith("MM")
                or rest_after_num.upper().startswith("EA")
                or rest_after_num.upper().startswith("PCS")
                or rest_after_num.upper().startswith("SET")
                or rest_after_num.upper().startswith("MTR")
                or rest_after_num.upper().startswith("KG")
                or not rest_after_num
            )
            if unit_ok and not next_item:
                qty = _qty_value(qm.group(1))
                unit = (qm.group(2) or unit).upper()
                consumed_end = k
                _ = after  # circuit-ref junk ignored

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
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        raw_line = lines[i]
        if not raw_line.strip():
            i += 1
            continue
        if "\t" in raw_line:
            cells = [c.strip() for c in raw_line.split("\t") if str(c).strip()]
            hit = _item_from_cells(cells)
            if hit:
                # qty may be on next line: "1 NO"
                if i + 1 < len(lines):
                    qm = QTY_LINE.match(lines[i + 1]) or QTY_LINE_LOOSE.match(lines[i + 1])
                    if qm and not LINE_START.match(re.sub(r"[ \t]+", " ", lines[i + 1])):
                        hit["qty"] = _qty_value(qm.group(1))
                        hit["unit"] = (qm.group(2) or hit.get("unit") or "NO").upper()
                        i += 1
                items.append(hit)
                i += 1
                continue
        hit = _item_from_text_line(raw_line)
        if hit:
            if i + 1 < len(lines):
                qm = QTY_LINE.match(lines[i + 1])
                if qm:
                    hit["qty"] = _qty_value(qm.group(1))
                    hit["unit"] = (qm.group(2) or hit.get("unit") or "NO").upper()
                    i += 1
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
    by_no: dict[int, dict] = {}
    for it in items:
        # Keep first designation when duplicate item numbers appear (e.g. alt RAM)
        if it["itemNo"] not in by_no:
            by_no[it["itemNo"]] = it
        else:
            # Prefer longer description / keep both part nos lightly
            existing = by_no[it["itemNo"]]
            if it.get("description") and len(it["description"]) > len(existing.get("description") or ""):
                by_no[it["itemNo"]] = it
    items = [by_no[k] for k in sorted(by_no)]
    if not items:
        warnings.append(
            "Parts List uploaded but no item rows matched yet. "
            "Expected columns: ITEM | DESIGNATION | PART NO | QTY."
        )
    return {
        "docType": "PL",
        "partNumber": _part_number_from_filename(filename),
        "title": filename,
        "items": items,
        "itemMap": {str(it["itemNo"]): it for it in items},
        "warnings": warnings,
        "raw_text": raw_text[:50000],
    }


def _item_from_cells(cells: list[str]) -> dict | None:
    if len(cells) < 3:
        return None
    item_raw = cells[0].strip()
    if not re.fullmatch(r"\d{1,4}", item_raw):
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
    unit_only = re.compile(r"^(NO|MM|EA|PCS|SET|MTR|KG|M|ST)$", re.I)
    for i, c in enumerate(cells[1:], 1):
        if i == pn_idx:
            continue
        cell = c.strip()
        if not cell or JUNK_LINE.match(cell) or re.fullmatch(r"[,.\s]+", cell):
            continue
        if unit_only.fullmatch(cell):
            unit = cell.upper()
            continue
        qm = QTY_RE.fullmatch(cell)
        if qm:
            qty = _qty_value(qm.group(1))
            if qm.group(2):
                unit = qm.group(2).upper()
            continue
        if PART_NO_RE.search(cell) or PART_NO_FLEX.search(cell):
            continue
        # Skip obvious non-description columns (circuit ref / remarks headers)
        up = cell.upper()
        if up in {"CIRCUIT REFERENCE", "REMARKS", "ENV REL", "GR", "UNT", "UNIT", "UOM"}:
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
    if rest.upper().startswith("DESIGNATION") or rest.upper().startswith("PART NO") or rest.upper().startswith(
        "PART NUMBER"
    ) or rest.upper().startswith("DESCRIPTION") or rest.upper().startswith("DESC"):
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

    blobs = [text]
    tsv = tables_to_tsv_lines(result.tables)
    if tsv:
        if format_aliases:
            from app.route_card.format_templates import apply_aliases_to_text

            tsv = apply_aliases_to_text(tsv, format_aliases, doc_type="PL")
        blobs.append(tsv)

    items: list[dict] = []
    for blob in blobs:
        if len((blob or "").strip()) < 40:
            continue
        items.extend(_parse_pl_line_items(blob))

    if not items and len((text or "").strip()) < 40:
        warnings.append("Parts List PDF has little/no text layer.")

    out = _finalize(items, filename, warnings, text)
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


def enrich_bom_with_pl(bom_items: list[dict], pl: dict) -> list[dict]:
    item_map = pl.get("itemMap") or {}
    out = []
    for b in bom_items or []:
        row = dict(b)
        key = str(row.get("itemNo"))
        hit = item_map.get(key)
        if hit:
            row["description"] = hit.get("description") or row.get("description")
            row["partNumber"] = hit.get("partNumber")
            if hit.get("qty") is not None:
                row["qty"] = hit["qty"]
        out.append(row)
    return out


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
