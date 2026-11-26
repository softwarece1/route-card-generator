"""BEL-structure validation for GA / PL / WL uploads.

Hard gate: a file that fails validation is rejected before it is stored.
Non-blocking notes are returned as ``warnings`` and saved on the document.

Each role checks its own required signals, and each role rejects content that
looks like another role (for example a Parts List uploaded as a GA drawing).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from app.route_card.partslist_parser import parse_partslist_bytes
from app.route_card.pdf_ingest import ingest_pdf, ocr_image_bytes
from app.route_card.wirelist_parser import _excel_to_tsv_text, parse_wirelist_bytes

logger = logging.getLogger(__name__)

ROLE_LABEL = {
    "drawing": "GA drawing",
    "partslist": "Parts List",
    "wirelist": "Wire List",
}

# BEL drawing / part number: 4-3-3-2 digit groups, spaces optional (OCR / PDF spacing).
BEL_PN_RE = re.compile(r"\b\d{4}\s?\d{3}\s?\d{3}\s?\d{2}\b")

GA_CUES: dict[str, re.Pattern[str]] = {
    "GENERAL ASSEMBLY": re.compile(r"\bGENERAL\s+ASSEMBLY\b", re.I),
    "ASSEMBLY": re.compile(r"\bASSEMBLY\b", re.I),
    "TITLE BLOCK": re.compile(r"\bTITLE\s*BLOCK\b|\bDOC\s*TYPE\b", re.I),
    "SHEET": re.compile(r"\bSHEET\b", re.I),
    "SCALE": re.compile(r"\bSCALE\b", re.I),
    "NOTES": re.compile(r"\bNOTES?\b", re.I),
    "BILL OF MATERIAL": re.compile(r"\bBILL\s+OF\s+MATERIAL\b", re.I),
    "ITEM CALLOUT": re.compile(r"\bITEM\s*\d{1,3}\b", re.I),
}

PL_HEADER_TOKENS: dict[str, re.Pattern[str]] = {
    "ITEM": re.compile(r"\bITEM\b", re.I),
    "PART NO": re.compile(r"\bPART\s*(?:NO|NUMBER)\b", re.I),
    "DESIGNATION": re.compile(r"\b(?:DESIGNATION|DESC(?:RIPTION)?)\b", re.I),
    "QTY": re.compile(r"\bQTY\b", re.I),
}

WIRE_LIST_TITLE_RE = re.compile(r"\bWIRE\s*LIST\b|\bWIRE\s*LFH\b", re.I)
FROM_RE = re.compile(r"\bFROM\b", re.I)
TO_RE = re.compile(r"\bTO\b", re.I)


@dataclass
class UploadValidation:
    ok: bool
    reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _fail(*reasons: str, warnings: list[str] | None = None) -> UploadValidation:
    return UploadValidation(ok=False, reasons=list(reasons), warnings=list(warnings or []))


def _ok(warnings: list[str] | None = None) -> UploadValidation:
    return UploadValidation(ok=True, reasons=[], warnings=list(warnings or []))


def _reversed_lines(text: str) -> str:
    # OCR often flips 180-degree rotated sheets; check reversed text too.
    return "\n".join("".join(reversed(line)) for line in text.splitlines())


def _pl_header_present(text: str) -> bool:
    return all(rx.search(text) for rx in PL_HEADER_TOKENS.values())


def _wire_table_present(text: str) -> bool:
    # A real Wire List has a FROM / TO table. The title alone is not enough,
    # because GA notes may say "AS PER WIRE LIST".
    return bool(FROM_RE.search(text) and TO_RE.search(text))


def _excel_text(data: bytes, ext: str) -> str:
    # _excel_to_tsv_text expects the extension without the dot ("xlsx").
    text, _warns = _excel_to_tsv_text(data, ext.lstrip(".").lower())
    return text or ""


# --- GA ---------------------------------------------------------------------

def _validate_drawing(data: bytes, filename: str, ext: str) -> UploadValidation:
    warnings: list[str] = []
    if ext == ".pdf":
        text = (ingest_pdf(data, want_tables=False).text or "")[:60000]
    elif ext in {".tif", ".tiff"}:
        text, _pages, ocr_warns = ocr_image_bytes(data)
        text = (text or "")[:60000]
        if not text.strip():
            return _fail(
                "Could not read text from the TIFF drawing. Upload a clear BEL GA scan or a PDF.",
                warnings=ocr_warns,
            )
        warnings.append("Drawing text was read by OCR. Check the drawing preview.")
    else:
        return _fail(f"Unsupported drawing type {ext}. Expected PDF or TIFF.")

    if not text.strip():
        return _fail("Could not read any text from the GA drawing. Upload a BEL GA PDF with a text layer.")

    blob = f"{text}\n{_reversed_lines(text)}"

    # A Parts List title block also carries a part number, so rule out PL tables first.
    if ext == ".pdf" and _pl_header_present(blob):
        pl_items = parse_partslist_bytes(data, filename).get("items") or []
        if len(pl_items) >= 2:
            return _fail(
                "This looks like a Parts List, not a GA drawing. Upload it in the Parts List slot.",
            )

    cues = {name for name, rx in GA_CUES.items() if rx.search(blob)}
    if BEL_PN_RE.search(blob) or len(cues) >= 2:
        return _ok(warnings)
    return _fail(
        "Not a BEL GA drawing: no drawing number or title-block cues were found.",
        warnings=warnings,
    )


# --- PL ---------------------------------------------------------------------

def _validate_partslist(data: bytes, filename: str, ext: str) -> UploadValidation:
    parsed = parse_partslist_bytes(data, filename)
    items = parsed.get("items") or []
    if ext in {".xls", ".xlsx"}:
        header_text = _excel_text(data, ext)
    else:
        header_text = parsed.get("raw_text") or ""

    if _wire_table_present(header_text):
        return _fail("This looks like a Wire List, not a Parts List. Upload it in the Wire List slot.")
    if not items:
        return _fail(
            "Parts List: no item rows were found. Expected a BEL PL with ITEM | DESIGNATION | PART NO | QTY columns.",
        )
    if not _pl_header_present(header_text):
        return _fail(
            "Parts List: the ITEM | DESIGNATION | PART NO | QTY header was not found.",
        )

    warnings: list[str] = []
    if len(items) < 2 and not re.search(r"\b(pl|parts?\s*list|bom)\b", filename or "", re.I):
        warnings.append("Parts List has only one item row. Verify this is the complete Parts List.")
    return _ok(warnings)


# --- WL ---------------------------------------------------------------------

def _validate_wirelist(data: bytes, filename: str, ext: str) -> UploadValidation:
    parsed = parse_wirelist_bytes(data, filename)
    wire_count = int(parsed.get("wireCount") or 0)
    raw = parsed.get("raw_text") or ""
    if ext in {".xls", ".xlsx"}:
        raw = _excel_text(data, ext) or raw

    if not wire_count:
        return _fail(
            "Wire List: no wire rows (FROM / TO / part no / length) were found.",
        )
    if not _wire_table_present(raw):
        return _fail("Wire List: the FROM / TO table header was not found.")
    if _pl_header_present(raw) and not WIRE_LIST_TITLE_RE.search(raw):
        return _fail("This looks like a Parts List, not a Wire List. Upload it in the Parts List slot.")
    return _ok()


# --- entry point ------------------------------------------------------------

def validate_upload(role: str, data: bytes, filename: str, ext: str) -> UploadValidation:
    """Validate an uploaded GA / PL / WL file. Call before anything is stored."""
    role = (role or "").lower().strip()
    ext = (ext or "").lower()
    label = ROLE_LABEL.get(role)
    if label is None:
        return _fail(f"Unsupported upload role: {role or 'unknown'}.")

    validators = {
        "drawing": _validate_drawing,
        "partslist": _validate_partslist,
        "wirelist": _validate_wirelist,
    }
    try:
        return validators[role](data, filename, ext)
    except Exception:  # noqa: BLE001 - any parser failure means the file is not readable as this role
        logger.exception("upload format validation failed for role=%s file=%s", role, filename)
        return _fail(f"Could not read this file as a BEL {label}. Check that it is the correct document.")
