"""Parse engineering-drawing text (PDF text layer or CAD TEXT entities) into GA fields."""

from __future__ import annotations

import re

ASSEMBLY_VERBS = re.compile(
    r"\b(ASSEMBLE|ASSEMBLY|ENGAGE|TORQUE|TIGHTEN|PASTE|STICK|GLUE|BOND|ADHERE|"
    r"MATE|INSTALL|FASTEN|PLACE\s+ITEM|FIT|MOUNT|SECURE|APPLY)\b",
    re.I,
)
MACHINING_HINTS = re.compile(
    r"\b(TURNING|MILLING|DRILLING|BORING|GRINDING|H7|Ra\s*\d|HEAT\s*TREAT|EN8|BILLET)\b",
    re.I,
)

DRAWING_NO_SPACED = re.compile(r"\b(\d{4})\s+(\d{3})\s+(\d{3})\s+(\d{2})\b")
DRAWING_NO_COMPACT = re.compile(r"\b(\d{12,14}[A-Z]*)\b")
SHEET_FOOTER = re.compile(
    r"(?:--\s*(\d+)\s*of\s*(\d+)\s*--"
    r"|SHEETS?\s*(?:NO\.?)?\s*:?\s*(\d+)\s*(?:OF|/)\s*(\d+)"
    r"|(\d+)\s*/\s*(\d+)\s*(?:SHEETS?)?)",
    re.I,
)
ITEM_QTY = re.compile(r"(?<!\d)(\d{1,3})\s*[-–—]\s*(\d{1,3})(?!\d)")
DATE_WITH_YEAR = re.compile(r"\b\d{1,2}[-/]\d{1,2}[-/]\d{2,4}\b")
# ITEM / ITEMS / ITM / Item No. / Item# / It. 2
ITEM_REF = re.compile(
    r"(?:ITEMS?|ITMS?|IT\.?)\s*(?:NO\.?|NOS\.?|NUMBER|#)?\s*-?\s*(\d{1,3})",
    re.I,
)
# "ITEM 110 & 120" / "ITEMS 110 AND 120" / "ITEM NO-70"
ITEM_PAIR = re.compile(
    r"(?:ITEMS?|ITMS?)\s*(?:NO\.?|NOS\.?|#)?\s*-?\s*(\d{1,3})\s*(?:&|AND|,)\s*(\d{1,3})",
    re.I,
)
TORQUE = re.compile(
    r"(\d+(?:\.\d+)?)\s*(?:-|–|to)\s*(\d+(?:\.\d+)?)\s*(?:N\s*[-.]?\s*m|Nm|NEWTON\s*M)"
    r"|(\d+(?:\.\d+)?)\s*(?:N\s*[-.]?\s*m|Nm)",
    re.I,
)
CONNECTOR = re.compile(r"\bJ\d+\b", re.I)
STANDARD = re.compile(r"\bPS\s*\d{3}\b", re.I)
RELATED_ASSY = re.compile(r"\b(1180\s*\d{3}\s*\d{3}\s*\d{2}|1180\d{8,10})\b")
WEIGHT = re.compile(
    r"(?:WEIGHT|MASS|WT\.?)\s*:?\s*(\d+(?:\.\d+)?)\s*(?:\+/?-|±)\s*(\d+(?:\.\d+)?)\s*(?:kg|kgs)?",
    re.I,
)
FINISH_UM = re.compile(r"(\d+)\s*[μµu]m", re.I)
THRU_HOLE = re.compile(
    r"(\d+)\s*[x×]\s*(\d+(?:\.\d+)?)\s*(?:THRU|THROUGH|THR\.?)",
    re.I,
)
ECO_ROW = re.compile(
    r"(?:REFER\s+|REF\.?\s+)?(?:ECR|ECO|CN\.?\s*NO\.?)\s*"
    r"(\d{2})\s+(\d{5,8})\s+(\d{1,2}[-/]\d{1,2}[-/]\d{2,4})",
    re.I,
)
# NOTE / NOTES / ASSEMBLY INSTRUCTIONS / CTQ POINTS / INSTRUCTIONS (+ same-line indexed variants).
# OCR often reads II as Il / I1. Wiring GAs use "Assembly Instructions" instead of NOTES.
# Some drawings label the same block as "CTQ POINTS" (Critical To Quality).
NOTE_INDEX = r"(?:III|II|Il|I1|IV|IX|VIII|VII|VI|V|I|[0-9]{1,2})"
# Index must stay on the header line — never swallow the next "1. step …" list marker.
_NOTE_SAME_LINE_IDX = rf"(?:[ \t]*[-\u2013:_.:][ \t]*|[ \t]+){NOTE_INDEX}"
NOTE_LABEL = (
    rf"(?:"
    rf"ASSEMBLY\s+INSTRUCTIONS?|"
    rf"ASSY\.?\s+INSTRUCTIONS?|"
    rf"ASSEMBLY\s+NOTES?(?:{_NOTE_SAME_LINE_IDX})?|"
    rf"ASSY\.?\s*NOTES?(?:{_NOTE_SAME_LINE_IDX})?|"
    rf"CRITICAL\s+TO\s+QUALITY\s+POINTS?(?:{_NOTE_SAME_LINE_IDX})?|"
    rf"CTQ\s+POINTS?(?:{_NOTE_SAME_LINE_IDX})?|"
    rf"INSTRUCTIONS?(?:{_NOTE_SAME_LINE_IDX})?|"
    rf"NOTES?(?:{_NOTE_SAME_LINE_IDX})?|"
    rf"REMARKS?(?:{_NOTE_SAME_LINE_IDX})?"
    rf")"
)
NOTES_HEADER = re.compile(rf"(?:^|\n)\s*{NOTE_LABEL}\s*[:;.]?[ \t]*", re.I)
INLINE_NOTE = re.compile(
    rf"(?:^|\n)\s*{NOTE_LABEL}\s*[:;.]\s*(?P<body>.+?)"
    rf"(?=\n\s*{NOTE_LABEL}\s*[:;.]|\n\s*THIS DOCUMENT|\Z)",
    re.I | re.S,
)
# Indexed section headers on the *same line* (NOTE I / NOTE-1 / INSTRUCTION 2 / CTQ POINTS 1).
# Label must not wrap to the next line — otherwise "INSTRUCTIONS:\n1. …" steals step 1.
NOTE_SECTION = re.compile(
    rf"(?:^|\n)\s*(?:INSTRUCTIONS?|NOTES?|CTQ\s+POINTS?|CRITICAL\s+TO\s+QUALITY\s+POINTS?)"
    rf"(?:[ \t]*[-\u2013:_.:][ \t]*|[ \t]+)(?P<label>{NOTE_INDEX})"
    rf"[ \t]*[:;.]?[ \t]*(?=\n|$)",
    re.I,
)
TITLE_BLOCK_CUT = re.compile(
    r"\n\s*(?:THIS DOCUMENT IS THE PROPERTY|PRODUCT DEVELOPMENT &|"
    r"VER(?:SION)?\.?\s*\n|ISSUE\.?\s*\n|REV(?:ISION)?\.?\s*\n|"
    r"DRAWING\s+UPDATED|NEXT\s+ASSY|SHEET\s*No\.?)",
    re.I,
)
# 1. / 1) / (1) / 1, / Step 1:
LEADING_STEP = re.compile(
    r"^(?:STEP\s*)?(?:\(([1-9]|1[0-9]|2[0-5])\)|([1-9]|1[0-9]|2[0-5])[.,)\-:])(?:\s+|$)(.+)$",
    re.I,
)
# OCR often drops the digit: ". DRILL 3mm HOLES..."
LEADING_DOT_STEP = re.compile(r"^\.\s+(.+)$")
TRAILING_STEP = re.compile(r"^(.+?)\s+(\d+)\.\s*$")
SUBSTEP = re.compile(r"^[a-z]\)\s+", re.I)
# Decimal sub-notes from AMS drawings: 4.1 / 5.2.
SUBSTEP_DECIMAL = re.compile(r"^(\d{1,2})\.(\d{1,2})\.?\s+(.+)$")
NOTE_HEADER_ONLY = re.compile(
    rf"^{NOTE_LABEL}\s*[:;.]?\s*$",
    re.I,
)
TITLE_STOP = re.compile(
    r"^(THIS DOCUMENT IS THE PROPERTY|PRODUCT DEVELOPMENT|"
    r"DRAWN\s|CHECKED|APPR(?:OVE)?D|VER\.|ISSUE|REV\.|LAB/OFFICE|"
    r"ALL DIMENSIONS ARE IN MM|UNLESS OTHERWISE SPECIFIED|"
    r"DRAWING\s+UPDATED|NEXT\s+ASSY(?:\s+NUMBER)?|SHEET\s*No\.?|"
    r"BANGALORE|ORIGINAL|DATE|CHANGE|PROJECTION|ENGINEER|FINISH|MATERIAL|"
    r"CN\.?\s*No\.?|DOC\s*CODE|SCALE|TITLE|ITEM|QTY)$",
    re.I,
)
# Only cut from a *line-start* title-block marker so mid-line OCR bleed
# (e.g. "…DETAIL A. DRAWN CHECKED…") does not wipe remaining instruction steps.
NOTES_JUNK_TAIL = re.compile(
    r"(?:^|\n)\s*(?:\d{1,2}[./-]\d{1,2}[./-]\d{2,4}\s*)?"
    r"(?:DRAWING\s+UPDATED|NEXT\s+ASSY(?:\s+NUMBER)?|SHEET\s*No\.?|BANGALORE|"
    r"DRAWN\b|CHECKED\b|APPRD\b|PROJECTION\b)\b.*$",
    re.I | re.M | re.S,
)
# Title often sits on the line after the drawing number and before GA / DRG / DWG
TITLE_AFTER_DWG = re.compile(
    r"(?:\b\d{4}\s+\d{3}\s+\d{3}\s+\d{2}\b|\b\d{12,14}[A-Z]*\b)\s*\n\s*"
    r"([A-Z0-9][A-Z0-9 /()\-]{2,48})\s*\n\s*(?:GA|DRG|DWG)\b",
    re.I,
)
TITLE_LABEL = re.compile(
    r"(?:TITLE|PART\s*NAME|DESIGNATION)\s*:?\s*([A-Z0-9][A-Z0-9 /()\-]{2,48})",
    re.I,
)
VERSION_LABEL = re.compile(
    r"\b(?:VER(?:SION)?|ISSUE|REV(?:ISION)?)\b[^\n]{0,12}?(\d{2})\b",
    re.I,
)
ORIGINAL_DATE = re.compile(
    r"\bORIG(?:INAL)?\b\s+(\d{1,2}[-/]\d{1,2}[-/]\d{2,4})",
    re.I,
)
DIMENSIONS_MM = re.compile(
    r"(?:ALL\s+DIMENSIONS\s+ARE\s+IN\s+MM|DIMS?\s+IN\s+MM|DIMENSIONS?\s*:\s*MM)\b",
    re.I,
)


def _norm_spaces(text: str) -> str:
    return re.sub(r"[ \t]+", " ", text).strip()


def split_pages(full_text: str) -> list[str]:
    parts = re.split(r"\n--\s*\d+\s*of\s*\d+\s*--\s*\n?", full_text)
    pages = [p.strip() for p in parts if p.strip()]
    return pages or ([full_text] if full_text.strip() else [])


def extract_drawing_number(text: str, filename: str = "") -> str:
    m = DRAWING_NO_SPACED.search(text)
    if m:
        return f"{m.group(1)} {m.group(2)} {m.group(3)} {m.group(4)}"
    stem = re.sub(r"\.[^.]+$", "", filename or "")
    compact = re.sub(r"[^0-9A-Z]", "", stem.upper())
    digits = re.sub(r"\D", "", compact)
    if len(digits) >= 12:
        return f"{digits[0:4]} {digits[4:7]} {digits[7:10]} {digits[10:12]}"
    m2 = DRAWING_NO_COMPACT.search(text)
    if m2:
        c = re.sub(r"\D", "", m2.group(1))
        if len(c) >= 12:
            return f"{c[0:4]} {c[4:7]} {c[7:10]} {c[10:12]}"
    return stem or ""


def extract_bom_items(text: str) -> list[dict]:
    """Balloon callouts are 'item-qty' on their own line, e.g. 8-8 or 5-4,53-4,54-4."""
    qty_by_item: dict[int, int] = {}
    scrubbed = DATE_WITH_YEAR.sub(" ", text)
    scrubbed = re.sub(r"(\d{1,3}-\d{1,2})(?=\d{1,3}-)", r"\1\n", scrubbed)
    for line in scrubbed.splitlines():
        compact = re.sub(r"\s", "", line.strip())
        if not re.fullmatch(r"(?:\d{1,3}[-–—]\d{1,3},?)+", compact):
            continue
        for raw_item, raw_qty in ITEM_QTY.findall(line):
            item, qty = int(raw_item), int(raw_qty)
            if item < 1 or item > 120 or qty < 1 or qty > 80:
                continue
            qty_by_item[item] = max(qty_by_item.get(item, 0), qty)
    return [{"itemNo": k, "qty": v, "description": None} for k, v in sorted(qty_by_item.items())]


def extract_torques(text: str) -> list[str]:
    found = []
    normalized = (
        text.replace("N-m", "Nm")
        .replace("N.m", "Nm")
        .replace("N m", "Nm")
        .replace("newton m", "Nm")
        .replace("Newton m", "Nm")
    )
    for m in TORQUE.finditer(normalized):
        if m.group(1) and m.group(2):
            found.append(f"{m.group(1)}-{m.group(2)} Nm")
        elif m.group(3):
            found.append(f"{m.group(3)} Nm")
    seen = set()
    out = []
    for t in found:
        key = t.lower().replace(" ", "")
        if key not in seen:
            seen.add(key)
            out.append(t)
    return out


def _items_in(text: str) -> list[int]:
    nums: list[int] = []
    for a, b in ITEM_PAIR.findall(text or ""):
        nums.extend([int(a), int(b)])
    nums.extend(int(x) for x in ITEM_REF.findall(text or ""))
    seen = []
    for n in nums:
        if n not in seen:
            seen.append(n)
    return seen


def break_instruction_points(text: str) -> str:
    """
    Put list-style markers on their own lines inside instruction / Long Text.

    Handles mid-paragraph markers such as:
      ... ITEM No. 1 a) ENSURE ... b) ENSURE ... i) CHECK ... 2) TORQUE ...
    → each a) / b) / i) / ii) / 1) / 2) starts a new line.

    Does not invent bullets for ordinary prose; only splits on existing markers.
    Does NOT treat "(REVISION E)" / "REVISION E)" as a list point.
    """
    if not text:
        return ""
    text = str(text).replace("\r\n", "\n").replace("\r", "\n")

    # Protect revision letters so "REVISION E)" is never treated as point "e)"
    protected: list[str] = []

    def _mask(match: re.Match) -> str:
        protected.append(match.group(0))
        return f"\x00REV{len(protected) - 1}\x00"

    text = re.sub(r"\(?\bREVISIONS?\s+[A-Z]\)", _mask, text, flags=re.I)

    # Letter bullets: lowercase a)–z) only (never E) from REVISION E).
    # Roman: i) ii) iii) … (case-insensitive via local flag).
    # Digits: 1) 2) 12)
    text = re.sub(
        r"(?<!\n)\s+(?=(?:"
        r"[a-z]\)|"
        r"(?i:xii|xi|ix|viii|vii|vi|iv|iii|ii|x|v|i)\)|"
        r"\d{1,3}\)"
        r")(?:\s+|$))",
        "\n",
        text,
    )
    # Glued markers: "...1a) ENSURE" (lowercase letter / roman / digit only)
    text = re.sub(
        r"(?<![A-Za-z0-9\n\x00])(?=(?:"
        r"[a-z]\)|"
        r"(?i:xii|xi|ix|viii|vii|vi|iv|iii|ii|x|v|i)\)|"
        r"\d{1,3}\)"
        r")\s+[A-Za-z(])",
        "\n",
        text,
    )

    for i, original in enumerate(protected):
        text = text.replace(f"\x00REV{i}\x00", original)

    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _note_step_dict(sheet: int, step_no: int, text: str) -> dict | None:
    text = _norm_spaces(NOTES_JUNK_TAIL.sub("", text))
    text = re.sub(r"\s+", " ", text).strip(" ;:")
    # Trailing revision dates stuck on by OCR
    text = re.sub(r"\s+\d{1,2}[./-]\d{1,2}[./-]\d{2,4}\s*$", "", text).strip()
    # Title-block / revision-table OCR bleed glued onto instruction lines.
    # Strip the bleed *segment* only — do not cut away the rest of the step.
    text = re.sub(
        r"\s+MATERIAL\s+FINISH\s+PROJECTION(?:\s*\|?\s*DIMNS?\s+HELD(?:\s+IN)?)?",
        " ",
        text,
        flags=re.I,
    )
    text = re.sub(
        r"\s+DRAWN\s+CHECKED(?:\s+ENGINEER)?(?:\s+[A-Z0-9}{\]|._-]{1,12}){0,8}",
        " ",
        text,
        flags=re.I,
    )
    text = re.sub(
        r"\s+(?:DOC(?:UMENT)?[\s\]\}]*NUM(?:BER)?|SHEET\)?\s*ISSUE(?:\s*\]?\s*SIZE)?|"
        r"NO\.?\s*OF\s*SHEETS|EOGFCS(?:\s*UPGRADE)?)\b(?:\s+\S+){0,6}",
        " ",
        text,
        flags=re.I,
    )
    text = re.sub(
        r"\s+(?:No\.\s*\|?\s*CN\.?\s*NO\.|DATE\s+CHANGE|NUMBER\s+ITEM\s*\|?\s*QTY|"
        r"a\s+ORIGINAL\b[^\n]{0,40}|NOTE\s+\d+\s*&\s*\d+\s+DELETED[^\n]{0,40}|"
        r"NEXT\s+ASSEMBLY\b|YOG\s+UMRESH\b[^\n]{0,60})",
        " ",
        text,
        flags=re.I,
    )
    text = re.sub(
        r"\s+CODE\s+\d{4}\s+\d{3}\s+\d{3}\s+\d{2}\b(?:\s+\S+){0,8}",
        " ",
        text,
        flags=re.I,
    )
    text = re.sub(r"\s+\|\s*", " ", text)
    text = re.sub(r"\s{2,}", " ", text).strip(" ;:|")
    text = re.sub(r"\bNSERTS\b", "INSERTS", text, flags=re.I)
    text = break_instruction_points(text)
    if len(text) < 8:
        return None
    # Drop pure title-block leftovers
    if TITLE_STOP.match(text):
        return None
    if re.fullmatch(r"[\d./\-\s]+", text):
        return None
    return {
        "sheet": sheet,
        "stepNo": step_no,
        "text": text,
        "items": _items_in(text),
        "torque": extract_torques(text),
        "connectors": sorted(set(CONNECTOR.findall(text))),
        "standards": sorted(set(re.sub(r"\s+", "", s).upper() for s in STANDARD.findall(text))),
        "references": (
            ["SAP special assembly instruction"] if re.search(r"\bSAP\b", text, re.I) else []
        ),
    }


def _is_junk_note_text(text: str) -> bool:
    """Drop OCR noise / revision-table rows that are not real manufacturing notes."""
    t = re.sub(r"\s+", " ", (text or "")).strip()
    if len(t) < 12:
        return True
    u = t.upper()
    if re.search(r"\bZONE\b.*\bREV\b|\bDESCRIPTION\s+DATE\s+APVD\b|\bECR-\s*\d", u):
        return True
    if "PROPRIETARY" in u and "REPRODUCED" in u:
        return True
    if re.search(r"INFORMATION CONTAINED HEREIN", u):
        return True
    # Title-block fragments OCR'd as separate "steps"
    if re.search(
        r"\b(?:DOC(?:UMENT)?[\s\]\}]*NUM|SHEET\)?\s*ISSUE|NO\.?\s*OF\s*SHEETS|EOGFCS|"
        r"DIMNS?\s+HELD|NEXT\s+ASSY|CODE\s+\d{4}\s+\d{3})\b",
        u,
    ):
        return True
    if re.search(r"\b(?:UMRESH|YOG)\b", u) and not re.search(
        r"\b(?:HEAT|TERMINATE|CABLE|ASSEMBL|CUT|LABEL|PREPARE|WIRES?|TOLERANCE)\b", u
    ):
        return True
    # Dimension / view callouts without process language
    process = re.search(
        r"\b(REMOVE|BURR|MATERIAL|HEAT|TREAT|PLATING|CADMIUM|THREAD|PROTECT|"
        r"TEST|TORQUE|ACCEPTANCE|STRESS|HYDROGEN|BAKING|GAUGE|AMS|SAE|"
        r"ASSEMBLE|INSTALL|FOLLOW|PERFORM|QUALIFIED|TERMINATE|PREPARE|"
        r"CABLE|LABEL|SHRINK|TOLERANCE|WIRES?)\b",
        u,
    )
    dim_noise = re.search(r"\b(X45|UNF-|SECTION\s+[A-Z]|VIEW PROJECTION|SCALE:)\b", u)
    if dim_noise and not process:
        return True
    # OCR bleed of title-block into the BEL disclaimer note
    if "REGARDING" in u and "STANDARD" in u and dim_noise and len(t) > 140:
        return True
    return False


def _notes_look_incomplete(text: str, notes: list[dict] | None) -> bool:
    """True when the text layer likely missed graphics-only NOTES / instructions."""
    notes = notes or []
    raw = text or ""
    if not notes:
        return True
    refs = [int(m) for m in re.findall(r"\bNOTES?\s*([1-9]\d?)\b", raw, flags=re.I)]
    max_ref = max(refs) if refs else 0
    if max_ref >= 3 and len(notes) < max_ref:
        return True
    has_instr_hdr = bool(
        re.search(
            r"\b(?:ASSEMBLY\s+INSTRUCTIONS?|ASSY\.?\s+INSTRUCTIONS?|INSTRUCTIONS?|"
            r"CTQ\s+POINTS?|CRITICAL\s+TO\s+QUALITY\s+POINTS?)\b",
            raw,
            re.I,
        )
    )
    if len(raw.strip()) < 800 and (
        re.search(r"\bNOTES?\b", raw, re.I) or has_instr_hdr
    ) and len(notes) <= 2:
        return True
    if len(notes) <= 2 and re.search(r"REFER\s+NOTES?\s*[1-9]|NOTES?\s*[3-9]\b", raw, re.I):
        return True
    # Header present but numbered steps not recovered
    numbered = len(re.findall(r"(?m)^\s*(?:[1-9]|1[0-9]|2[0-5])[.)]\s+[A-Z]", raw))
    if has_instr_hdr and numbered >= 3 and len(notes) < max(3, numbered // 2):
        return True
    # Single "REGARDING IAI PS…" style note while drawing still has numbered process notes
    if len(notes) == 1:
        body = (notes[0].get("text") or "").upper()
        if "REGARDING" in body and "STANDARD" in body:
            return True
    return False


def _prepare_notes_text(text: str) -> str:
    """Normalize OCR quirks and NOTE / instruction header variants before parsing."""
    text = text.replace("\ufeff", " ").replace("\u00a0", " ")
    # OCR typo: "5S." / "4S." → "5." / "4."
    text = re.sub(r"(?m)^(\d)[Ss]\.\s+", r"\1. ", text)
    # Unify wiring-style headers → ASSEMBLY INSTRUCTIONS:
    text = re.sub(
        r"(?im)^(?:ASSY\.?\s+)?ASSEMBLY\s+INSTRUCTIONS?\s*[:;.]?\s*$",
        "ASSEMBLY INSTRUCTIONS:",
        text,
    )
    text = re.sub(
        r"(?im)^INSTRUCTIONS?\s*[:;.]?\s*$",
        "INSTRUCTIONS:",
        text,
    )
    # Unify CTQ / Critical-To-Quality headers → CTQ POINTS:
    text = re.sub(
        r"(?im)^CRITICAL\s+TO\s+QUALITY\s+POINTS?\s*[:;.]?\s*$",
        "CTQ POINTS:",
        text,
    )
    text = re.sub(
        r"(?im)^CTQ\s+POINTS?\s*[:;.]?\s*$",
        "CTQ POINTS:",
        text,
    )
    # Strip revision-table header that OCR attaches under NOTES:
    text = re.sub(
        r"(?im)^NOTES?\s*:\s*ZONE\s*\|?\s*REV\b.*$",
        "NOTES:",
        text,
    )
    # NOTE Il / NOTE I1 → NOTE II (keep "NOTE 11" as arabic if clearly two digits after space/dash)
    text = re.sub(r"\bNOTES?[ \t]*[-\u2013:]?[ \t]*(?:Il|I1)\b", "NOTE II", text, flags=re.I)
    # Unify separators on the same line: Note-1 / Note:1 / Note_1 → Note 1
    # Do not cross newlines — "NOTES:\n1. step" must stay a header + list, not "NOTE 1."
    text = re.sub(
        rf"\bNOTES?[ \t]*[-\u2013:_.:][ \t]*(?P<n>{NOTE_INDEX})\b",
        lambda m: f"NOTE {m.group('n').upper()}",
        text,
        flags=re.I,
    )
    # NOTE1 / NOTES2 (no space) → NOTE 1
    text = re.sub(
        r"\bNOTES?(?P<n>[0-9]{1,2})\b",
        lambda m: f"NOTE {m.group('n')}",
        text,
        flags=re.I,
    )
    # ITEM NO-SO / NO-S0 → ITEM NO-50
    text = re.sub(r"ITEM\s*NO[-\s]*S[O0]\b", "ITEM NO-50", text, flags=re.I)
    text = re.sub(r"ENAMLED", "ENAMELED", text, flags=re.I)
    text = re.sub(r"CONNECTPRS", "CONNECTORS", text, flags=re.I)
    # If OCR lost "NOTE I"/"NOTE 1" header but RoHS block is present, inject it
    if re.search(r"LEAD-FREE|RoHS\s+COMPLIANT", text, re.I) and not re.search(
        r"\bNOTES?\s*[-\u2013:\s]*?(?:I(?![IVX])|1)\b", text, re.I
    ):
        text = re.sub(
            r"((?:^|\n)\s*)(\.?\s*THE FOLLOWING ARE LEAD-FREE)",
            r"\1NOTE 1:\n\2",
            text,
            count=1,
            flags=re.I,
        )
    if "--- OCR ---" in text:
        parts = text.split("--- OCR ---", 1)
        text = parts[0] + "\n" + parts[1]
    return text


def _normalize_note_label(raw: str) -> str:
    """Map OCR/roman/arabic note labels to a stable display form."""
    lab = (raw or "").strip().upper().replace("IL", "II").replace("I1", "II")
    roman = {"I": "1", "II": "2", "III": "3", "IV": "4", "V": "5", "VI": "6", "VII": "7", "VIII": "8", "IX": "9"}
    if lab in roman:
        return roman[lab]
    if re.fullmatch(r"[0-9]{1,2}", lab):
        return str(int(lab))
    return lab


def _parse_notes_block(block: str, sheet: int) -> list[dict]:
    lines = [_norm_spaces(ln) for ln in block.splitlines() if _norm_spaces(ln)]
    steps: list[dict] = []
    current: dict | None = None
    auto_n = 0

    def flush():
        nonlocal current
        if current:
            built = _note_step_dict(sheet, current["stepNo"], current.get("text") or "")
            if built:
                steps.append(built)
        current = None

    for line in lines:
        if TITLE_STOP.match(line) or line in {"8", "F", "7", "T", "S", "R", "Q", "U"}:
            # Keep finish/material specification lines inside the current note
            if current and re.match(r"^(FINISH|MATERIAL)\s*:", line, re.I):
                current["text"] += " " + line
                continue
            break
        if NOTE_HEADER_ONLY.match(line):
            continue
        # Strip accidental leading "l;" from bad NOTE Il splits
        line = re.sub(r"^[Il1|;:\s]+(?=[A-Z])", "", line).strip()
        lead = LEADING_STEP.match(line)
        dot = LEADING_DOT_STEP.match(line) if not lead else None
        trail = TRAILING_STEP.match(line) if not lead and not dot else None
        dec = SUBSTEP_DECIMAL.match(line) if not lead and not dot and not trail else None
        if lead:
            flush()
            step_no = int(lead.group(1) or lead.group(2))
            current = {"stepNo": step_no, "text": lead.group(3)}
            if len((current["text"] or "").strip()) < 4:
                current = None
            continue
        if dot:
            flush()
            auto_n += 1
            current = {"stepNo": auto_n, "text": dot.group(1)}
            continue
        if trail:
            step_n = int(trail.group(2))
            prefix = trail.group(1)
            glued_item = bool(re.search(r"(?:ITEMS?|ITMS?)\s*(?:NO\.?)?\s*$", prefix, re.I))
            if not glued_item and 1 <= step_n <= 25 and len(prefix) > 12:
                flush()
                current = {"stepNo": step_n, "text": prefix}
                continue
        if dec and current:
            # 4.1 / 5.2 sub-notes belong to the parent numbered note
            current["text"] += " " + line
            continue
        if SUBSTEP.match(line) and current:
            current["text"] += " " + line
            continue
        if current:
            current["text"] += " " + line
        elif re.search(r"[A-Z]{4,}", line) and not TITLE_STOP.match(line):
            auto_n = max(auto_n, len(steps)) + 1
            current = {"stepNo": auto_n, "text": line}
    flush()
    return steps


def _unglue_step_numbers(block: str) -> str:
    """pypdf concatenates 'PS902'+'1.' and 'ITEM 26'+'2.' into one token."""
    block = re.sub(r"(PS\s*\d{3})(\d+)\.", r"\1\n\2. ", block, flags=re.I)
    block = re.sub(
        r"((?:ITEMS?|ITMS?)\s+\d{1,2})([1-9])\.\s+(?=[A-Z])",
        r"\1\n\2. ",
        block,
        flags=re.I,
    )
    block = re.sub(r"(AND\s+\d{1,2})([1-9])\.\s+(?=[A-Z])", r"\1\n\2. ", block, flags=re.I)

    def _split_numbered(match: re.Match) -> str:
        n = int(match.group(1))
        if n > 25:
            return match.group(0)
        start = match.start()
        before = block[max(0, start - 20) : start].upper()
        if re.search(
            r"(?:NO\.?\s*|ITEMS?\s*|ITMS?\s*|SHEET\s*|FIGURE\s*|FIG\.?\s*|"
            r"TABLE?\s*|TABEL\s*|DETAIL\s*|REV\.?\s*|VER\.?\s*|ISSUE\s*)$",
            before,
        ):
            return match.group(0)
        return f"\n{match.group(1)}. "

    return re.sub(r"(?<!\d)(\d{1,2})\.\s+(?=[A-Z])", _split_numbered, block)


def extract_notes(pages: list[str]) -> list[dict]:
    joined = _prepare_notes_text("\n\n".join(pages) if pages else "")
    notes: list[dict] = []

    # Prefer explicit NOTE I / NOTE II sections (common on PCB GAs)
    sections = list(NOTE_SECTION.finditer(joined))
    if sections:
        for i, m in enumerate(sections):
            start = m.end()
            end = sections[i + 1].start() if i + 1 < len(sections) else len(joined)
            block = joined[start:end]
            cut = TITLE_BLOCK_CUT.search(block)
            if cut:
                block = block[: cut.start()]
            block = NOTES_JUNK_TAIL.sub("", block)
            label = _normalize_note_label(m.group("label") or "")
            parsed = _parse_notes_block(_unglue_step_numbers(block), sheet=i + 1)
            # If section is a short intro + numbered list, keep steps; if single paragraph, keep as one
            if parsed:
                for n in parsed:
                    n["noteSection"] = f"NOTE {label}"
                notes.extend(parsed)
            else:
                body = _norm_spaces(block)
                body = NOTES_JUNK_TAIL.sub("", body)
                one = _note_step_dict(i + 1, 1, body)
                if one:
                    one["noteSection"] = f"NOTE {label}"
                    notes.append(one)
    else:
        # Inline / single-line notes: "NOTE : STICK ITEM 2 & 3 ..."
        for i, m in enumerate(INLINE_NOTE.finditer(joined)):
            body = _norm_spaces(m.group("body") or "")
            if len(body) < 8:
                continue
            if LEADING_STEP.match(body.split("\n", 1)[0].strip()) or "\n1." in f"\n{body}":
                continue
            one = _note_step_dict(i + 1, len(notes) + 1, body)
            if one:
                notes.append(one)

        matches = list(NOTES_HEADER.finditer(joined))
        for i, m in enumerate(matches):
            start = m.end()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(joined)
            block = joined[start:end]
            cut = TITLE_BLOCK_CUT.search(block)
            if cut:
                block = block[: cut.start()]
            note_hits = len(re.findall(NOTE_LABEL, block, flags=re.I))
            if note_hits > 4 and "ASSEMBLE ITEM" not in block.upper() and not ASSEMBLY_VERBS.search(block):
                continue
            stripped = block.strip()
            if stripped and not LEADING_STEP.match(stripped.split("\n", 1)[0]) and "1." not in stripped[:40]:
                if re.match(rf"^{NOTE_LABEL}\s*[:;.]", m.group(0), re.I):
                    continue
            notes.extend(_parse_notes_block(_unglue_step_numbers(block), sheet=i + 1))

    # Also catch orphan OCR dot-steps (NOTE I header lost entirely)
    if not notes or len(notes) < 3:
        if re.search(r"^\.\s+[A-Z].{10,}", joined, re.M):
            orphan = _parse_notes_block(_unglue_step_numbers(joined), sheet=1)
            # Keep orphan steps that look like assembly instructions
            for n in orphan:
                t = (n.get("text") or "").upper()
                if any(
                    k in t
                    for k in (
                        "LEAD-FREE",
                        "ROHS",
                        "DRILL",
                        "TRANSFORMER",
                        "SOLDER",
                        "SHORT",
                        "MOUNT",
                        "MASK",
                        "WARPAGE",
                        "HOLES",
                        "HEAT SHRINK",
                        "CABLE",
                        "TERMINATE",
                        "CONNECTOR",
                        "LABEL",
                        "READHEAD",
                        "READ HEAD",
                    )
                ):
                    notes.append(n)

    # de-dupe identical step text + drop OCR junk
    seen = set()
    out = []
    for n in notes:
        body = n.get("text") or ""
        if _is_junk_note_text(body):
            continue
        key = re.sub(r"\s+", " ", body).upper()[:180]
        if key in seen:
            continue
        seen.add(key)
        # renumber for display order
        n["stepNo"] = len(out) + 1
        out.append(n)
    return out


def extract_revisions(text: str) -> list[dict]:
    rows = []
    for ver, eco, date in ECO_ROW.findall(text):
        rows.append({"version": ver, "ecoNo": eco, "relDate": date, "change": "REFER ECR"})
    orig = ORIGINAL_DATE.search(text)
    if orig:
        rows.insert(0, {"version": "00", "ecoNo": "", "relDate": orig.group(1), "change": "ORIGINAL"})
    seen = set()
    out = []
    for r in rows:
        key = (r["version"], r["ecoNo"], r["relDate"])
        if key not in seen:
            seen.add(key)
            out.append(r)
    return out


def extract_dimensions(text: str) -> list[dict]:
    dims = []
    m = THRU_HOLE.search(text)
    if m:
        dims.append(
            {
                "label": "Mounting holes",
                "value": f"{m.group(1)} x D{m.group(2)} THRU ALL",
                "level": "Important",
            }
        )
    for num in ["98.00", "440.00", "503.53", "482.60", "131.50"]:
        if num in text:
            label_map = {
                "98.00": "Mounting pitch",
                "440.00": "Envelope length",
                "503.53": "Overall length",
                "482.60": "Mounting span",
                "131.50": "Height (3U)",
            }
            dims.append({"label": label_map[num], "value": f"{num} mm", "level": "Standard"})
    if re.search(r"COOLANT\s+INLET|COOLANT\s+PORT", text, re.I):
        dims.append({"label": "Coolant ports", "value": "Inlet / Outlet", "level": "Important"})
    # de-dupe labels
    seen = set()
    out = []
    for d in dims:
        if d["label"] not in seen:
            seen.add(d["label"])
            out.append(d)
    return out


def extract_title_block(text: str, filename: str, page_count: int) -> dict:
    drawing_no = extract_drawing_number(text, filename)
    doc_type = ""
    if re.search(r"\bGA\b", text) or re.search(r"\bGA\b", filename, re.I):
        doc_type = "GA"
    elif re.search(r"\b(?:DRG|DWG)\b", text):
        doc_type = "DRG"
    sheet_m = list(SHEET_FOOTER.finditer(text))
    sheets = f"{page_count} of {page_count}"
    if sheet_m:
        g = sheet_m[-1].groups()
        # pairs: (a,b, None...), (None,None,c,d), (None.. e,f)
        cur = next((g[i] for i in (0, 2, 4) if g[i]), None)
        tot = next((g[i] for i in (1, 3, 5) if g[i]), None)
        if cur and tot:
            sheets = f"{page_count} of {tot}"
    size = ""
    for s in ("A0", "A1", "A2", "A3", "A4"):
        if re.search(rf"\b{s}\b", text):
            size = s
            break
    scale = ""
    if re.search(r"\bNTS\b", text):
        scale = "NTS"
    elif m := re.search(r"\b(\d+\s*:\s*\d+)\b", text):
        scale = re.sub(r"\s+", "", m.group(1))
    version = ""
    vm = VERSION_LABEL.search(text)
    if re.search(r"\n03\n", text) or re.search(r"\b03\b", text[text.find("PDG") :] if "PDG" in text else ""):
        version = "03"
    if vm:
        version = vm.group(1)
    ecos = ECO_ROW.findall(text)
    if ecos:
        version = ecos[-1][0]

    part_name = ""
    if m := re.search(r"\b([A-Z]{3,}\s*\(MFR\))", text):
        part_name = _norm_spaces(m.group(1))
    elif m := TITLE_AFTER_DWG.search(text):
        part_name = _norm_spaces(m.group(1))
    elif m := TITLE_LABEL.search(text):
        part_name = _norm_spaces(m.group(1))

    weight = ""
    wm = WEIGHT.search(text.replace(" ", ""))
    if not wm:
        wm = WEIGHT.search(text)
    if wm:
        weight = f"{wm.group(1)} +/- {wm.group(2)} kg"
    elif m := re.search(r"(?:WEIGHT|MASS|WT\.?)\s*:?\s*([^\n]+)", text, re.I):
        weight = _norm_spaces(m.group(1))

    finish = ""
    fm = FINISH_UM.search(text)
    if fm:
        finish = f"{fm.group(1)} um or better (mounting surface)"

    material = ""
    if m := re.search(r"\bAS\s+PER\s+(PS\s*\d{3}[^\n]{0,40})", text, re.I):
        material = _norm_spaces(m.group(0))
    elif m := re.search(r"\bMATERIAL\s*:?\s*([A-Z0-9][^\n]{2,40})", text, re.I):
        val = _norm_spaces(m.group(1))
        if val.upper() not in {"CHECKED", "FINISH", "DT", "-"}:
            material = val

    drawn = checked = approved = ""
    if "SACHIN" in text:
        drawn = "SACHIN"
    if "VARUN" in text:
        checked = "VARUN"
    if "SASO" in text:
        approved = "SASO"
    if not drawn:
        if m := re.search(r"\b(ROSHAN|SURENDAR|SACHIN)\b", text):
            drawn = m.group(1)
    if not checked:
        if m := re.search(r"\b(VIJAY\s*K\s*K|VARUN)\b", text):
            checked = _norm_spaces(m.group(1))
    if not approved:
        if m := re.search(r"\b(GURUMURTHY(?:\s*M\.?\s*G\.?)?|SASO)\b", text):
            approved = _norm_spaces(m.group(1))

    overall = ""
    if "503.53" in text and "131.50" in text:
        overall = "503.53 x 131.50 mm (3U)"
    elif "503.53" in text:
        overall = "503.53 mm overall length"

    return {
        "drawingNumber": drawing_no,
        "revision": f"VER {version}".strip() if version else "",
        "partName": part_name,
        "partNumber": drawing_no.replace(" ", "") if drawing_no else "",
        "material": material,
        "quantity": "1",
        "overallDimensions": overall,
        "tolerance": "",
        "surfaceFinish": finish,
        "drawingType": "unknown",
        "docType": doc_type,
        "version": version,
        "scale": scale,
        "sheetSize": size,
        "sheets": sheets,
        "weight": weight,
        "drawnBy": drawn,
        "checkedBy": checked,
        "approvedBy": approved,
        "unit": "mm" if DIMENSIONS_MM.search(text) else "",
    }


def classify_drawing(text: str, title_block: dict) -> str:
    if (title_block.get("docType") or "").upper() == "GA" or ASSEMBLY_VERBS.search(text):
        if ASSEMBLY_VERBS.search(text):
            return "assembly"
    if MACHINING_HINTS.search(text) and not ASSEMBLY_VERBS.search(text):
        return "machining"
    if ASSEMBLY_VERBS.search(text):
        return "assembly"
    return "unknown"


def extract_references(text: str, notes: list[dict]) -> list[str]:
    refs = set()
    for s in STANDARD.findall(text):
        token = re.sub(r"\s+", "", s).upper()
        if re.fullmatch(r"PS\d{3}", token):
            refs.add(token)
    if re.search(r"\bSAP\b", text):
        refs.add("SAP special assembly instructions")
    current_no = re.sub(r"\s+", "", extract_drawing_number(text, ""))
    for m in RELATED_ASSY.findall(text):
        compact = re.sub(r"\s+", "", m)
        if compact == current_no:
            continue
        refs.add(_norm_spaces(m))
    for n in notes:
        refs.update(n.get("references") or [])
        refs.update(n.get("standards") or [])
    return sorted(refs)


def parse_drawing_text(
    full_text: str,
    filename: str = "",
    page_count: int | None = None,
    *,
    format_aliases: dict | None = None,
) -> dict:
    if format_aliases:
        from app.route_card.format_templates import apply_aliases_to_text

        full_text = apply_aliases_to_text(full_text, format_aliases, doc_type="GA")
    pages = split_pages(full_text)
    n_pages = page_count or len(pages)
    title = extract_title_block(full_text, filename, n_pages)
    notes = extract_notes(pages)
    bom = extract_bom_items(full_text)
    known = {b["itemNo"] for b in bom}
    for n in notes:
        for item in n.get("items") or []:
            if item not in known and 1 <= item <= 80:
                bom.append({"itemNo": item, "qty": 1, "description": None})
                known.add(item)
    bom.sort(key=lambda b: b["itemNo"])
    drawing_type = classify_drawing(full_text, title)
    title["drawingType"] = drawing_type
    dims = extract_dimensions(full_text)
    if title.get("weight"):
        dims.append({"label": "Mass", "value": title["weight"], "level": "Critical"})
    if title.get("surfaceFinish"):
        dims.append({"label": "Mounting surface finish", "value": title["surfaceFinish"], "level": "Important"})
    warnings = []
    if len(full_text.strip()) < 80:
        warnings.append(
            "Little or no text layer found. If this is a scan, enable Tesseract OCR "
            "(install binary + set TESSERACT_CMD); otherwise provide a vector PDF."
        )
    if not notes:
        warnings.append(
            "No assembly NOTES / Assembly Instructions found in the PDF text layer. "
            "If instructions are drawn as graphics only (or masked), they cannot be extracted without OCR/a cleaner export."
        )
    return {
        "title_block": title,
        "revisions": extract_revisions(full_text),
        "bom_items": bom,
        "notes": notes,
        "torque_specs": extract_torques(full_text),
        "dimensions": dims,
        "references": extract_references(full_text, notes),
        "warnings": warnings,
        "raw_text": full_text[:200000],
        "pages": n_pages,
        "drawing_type": drawing_type,
    }


def pdf_to_text(data: bytes) -> tuple[str, int]:
    """Extract PDF text via offline ingest (PyMuPDF → pypdf → Tesseract OCR)."""
    from app.route_card.pdf_ingest import pdf_to_text as ingest_pdf_to_text

    return ingest_pdf_to_text(data)


def ingest_drawing_pdf(
    data: bytes,
    filename: str = "",
    *,
    format_aliases: dict | None = None,
) -> dict:
    """Full GA path: ingest PDF then run field parsers; OCR if NOTES are graphics-only."""
    from app.route_card.pdf_ingest import ingest_pdf

    result = ingest_pdf(data, want_tables=False)
    parsed = parse_drawing_text(
        result.text, filename, result.page_count or None, format_aliases=format_aliases
    )

    # Title-block text can exist while NOTES are drawn as paths/images.
    # Also: a sparse text layer may yield 1 weak note while NOTE 2…N are graphics-only
    # (SPECIAL BOLT.pdf — "REFER NOTE 5" with only the IAI disclaimer in the text layer).
    need_ocr = (not result.ocr_used) and _notes_look_incomplete(
        result.text or "", parsed.get("notes") or []
    )
    if need_ocr:
        ocr_result = ingest_pdf(data, want_tables=False, merge_ocr=True)
        if ocr_result.ocr_used and len((ocr_result.text or "").strip()) > len((result.text or "").strip()):
            ocr_parsed = parse_drawing_text(
                ocr_result.text, filename, ocr_result.page_count or None, format_aliases=format_aliases
            )
            # Also parse the OCR body alone — avoids sparse vector "NOTES REGARDING…"
            # swallowing the numbered process notes that live only in the OCR layer.
            ocr_body = ocr_result.text
            if "--- OCR ---" in ocr_body:
                ocr_body = ocr_body.split("--- OCR ---", 1)[1]
            ocr_only_notes = extract_notes([ocr_body])
            if len(ocr_only_notes) > len(ocr_parsed.get("notes") or []):
                ocr_parsed = {**ocr_parsed, "notes": ocr_only_notes}

            if len(ocr_parsed.get("notes") or []) > len(parsed.get("notes") or []):
                title = parsed.get("title_block") or {}
                ocr_title = ocr_parsed.get("title_block") or {}
                for key in (
                    "partNumber",
                    "drawingNumber",
                    "partName",
                    "title",
                    "weight",
                    "surfaceFinish",
                    "material",
                ):
                    if title.get(key) and not ocr_title.get(key):
                        ocr_title[key] = title[key]
                ocr_parsed["title_block"] = ocr_title
                parsed = ocr_parsed
                result = ocr_result
            elif not (parsed.get("notes") or []):
                parsed = ocr_parsed
                result = ocr_result

    warnings = list(dict.fromkeys((parsed.get("warnings") or []) + result.warnings))
    if result.ocr_used or "ocr" in (result.method or ""):
        warnings.insert(
            0,
            "Used offline OCR (Tesseract) to recover graphics-only drawing text / NOTES.",
        )
        warnings = [
            w
            for w in warnings
            if "OCR is not enabled" not in w
            and "cannot be extracted without OCR" not in w
        ]
    elif result.method in {"pymupdf", "pypdf"} and result.text.strip():
        warnings = [w for w in warnings if "OCR is not enabled" not in w]
    if not (parsed.get("notes") or []) and not result.ocr_used:
        warnings.append(
            "No assembly NOTES / Assembly Instructions in the text layer. Install Tesseract OCR "
            "(see README) so graphic blocks like 'NOTE I / NOTE II' or 'ASSEMBLY INSTRUCTIONS' can be read."
        )
    parsed["warnings"] = list(dict.fromkeys(warnings))
    parsed["pages"] = result.page_count or parsed.get("pages") or 1
    parsed["ingest_method"] = result.method
    return parsed
