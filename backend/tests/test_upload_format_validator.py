"""BEL-structure validation for GA / PL / WL uploads (sample files + wrong-slot content)."""

from __future__ import annotations

import io
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.route_card.upload_format_validator import validate_upload  # noqa: E402

SAMPLES = Path(__file__).resolve().parents[2] / "sample_drawings" / "night_vision_camera"
GA_PDF = SAMPLES / "112199000101 - GA.pdf"
PL_XLSX = SAMPLES / "112199000101 - PL.xlsx"
WL_XLSX = SAMPLES / "112199000101 - WL.xlsx"


def _read(path: Path) -> bytes:
    if not path.is_file():
        pytest.skip(f"sample missing: {path}")
    return path.read_bytes()


def _generic_xlsx() -> bytes:
    openpyxl = pytest.importorskip("openpyxl")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Name", "Score"])
    ws.append(["Alice", 91])
    ws.append(["Bob", 77])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _generic_pdf() -> bytes:
    fitz = pytest.importorskip("fitz")
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "The quick brown fox jumps over the lazy dog.")
    return doc.tobytes()


# --- positive: correct document in correct slot -----------------------------

def test_sample_ga_passes_as_drawing():
    result = validate_upload("drawing", _read(GA_PDF), GA_PDF.name, ".pdf")
    assert result.ok, result.reasons


def test_sample_pl_passes_as_partslist():
    result = validate_upload("partslist", _read(PL_XLSX), PL_XLSX.name, ".xlsx")
    assert result.ok, result.reasons


def test_sample_wl_passes_as_wirelist():
    result = validate_upload("wirelist", _read(WL_XLSX), WL_XLSX.name, ".xlsx")
    assert result.ok, result.reasons


# --- negative: wrong content for the slot -----------------------------------

def test_generic_pdf_rejected_as_drawing():
    result = validate_upload("drawing", _generic_pdf(), "random.pdf", ".pdf")
    assert not result.ok
    assert result.reasons


def test_generic_excel_rejected_as_partslist():
    result = validate_upload("partslist", _generic_xlsx(), "scores.xlsx", ".xlsx")
    assert not result.ok
    assert any("no item rows" in r or "header" in r for r in result.reasons)


def test_generic_excel_rejected_as_wirelist():
    result = validate_upload("wirelist", _generic_xlsx(), "scores.xlsx", ".xlsx")
    assert not result.ok


def test_ga_pdf_rejected_as_partslist():
    result = validate_upload("partslist", _read(GA_PDF), GA_PDF.name, ".pdf")
    assert not result.ok


def test_wl_rejected_as_partslist():
    result = validate_upload("partslist", _read(WL_XLSX), WL_XLSX.name, ".xlsx")
    assert not result.ok
    assert any("Wire List" in r for r in result.reasons)


def test_pl_rejected_as_wirelist():
    result = validate_upload("wirelist", _read(PL_XLSX), PL_XLSX.name, ".xlsx")
    assert not result.ok


def test_unknown_role_rejected():
    result = validate_upload("bogus", b"x", "x.pdf", ".pdf")
    assert not result.ok


def test_corrupt_pl_bytes_rejected_without_raising():
    result = validate_upload("partslist", b"not a workbook", "pl.xlsx", ".xlsx")
    assert not result.ok
