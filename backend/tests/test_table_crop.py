"""Gated TABLE crop — unique caption only; never invent cells."""

from __future__ import annotations

import io

import fitz

from app.route_card.drawing_mind.table_crop import (
    find_table_title_hits,
    render_table_crop,
)


def _pdf_with_table_caption(*, pages: list[list[tuple[str, tuple[float, float]]]]) -> bytes:
    """Build a simple PDF. pages: list of [(text, (x,y)), ...] per page."""
    doc = fitz.open()
    for page_items in pages:
        page = doc.new_page(width=600, height=800)
        for text, (x, y) in page_items:
            page.insert_text((x, y), text, fontsize=12)
            # Fake a few "cell" lines under a TABLE title
            if text.upper().startswith("TABLE"):
                page.insert_text((x, y + 24), "X2.1   X2.2   X2.3", fontsize=10)
                page.insert_text((x, y + 40), "Pin map row A", fontsize=10)
                page.insert_text((x, y + 80), "FIGURE 2", fontsize=12)
    buf = io.BytesIO()
    doc.save(buf)
    doc.close()
    return buf.getvalue()


def test_unique_table_title_crop_available():
    data = _pdf_with_table_caption(
        pages=[[("TABLE 1", (72, 120)), ("Other note", (72, 400))]]
    )
    out = render_table_crop(data, table_id="1", page_no=1)
    assert out["available"] is True
    assert out["label"] == "TABLE 1"
    assert out["page"] == 1
    assert out["confidence"] >= 0.82
    assert out["mime"] == "image/jpeg"
    assert out["imageBase64"]
    assert out["width"] > 20 and out["height"] > 20


def test_missing_table_not_available():
    data = _pdf_with_table_caption(pages=[[("NOTES", (72, 100))]])
    out = render_table_crop(data, table_id="1", page_no=1)
    assert out["available"] is False
    assert "not found" in (out.get("reason") or "").lower()


def test_ambiguous_duplicate_titles_rejected():
    data = _pdf_with_table_caption(
        pages=[[("TABLE 1", (72, 100)), ("TABLE 1", (72, 400))]]
    )
    out = render_table_crop(data, table_id="1", page_no=1)
    assert out["available"] is False
    assert "ambiguous" in (out.get("reason") or "").lower()


def test_prose_mention_is_not_a_caption():
    data = _pdf_with_table_caption(
        pages=[[("Fix wires as per table 1 on the left side of assembly", (72, 120))]]
    )
    doc = fitz.open(stream=data, filetype="pdf")
    try:
        hits = find_table_title_hits(doc.load_page(0), "1")
    finally:
        doc.close()
    assert hits == []


def test_wrong_page_rejected():
    data = _pdf_with_table_caption(pages=[[("TABLE 1", (72, 120))]])
    out = render_table_crop(data, table_id="1", page_no=2)
    assert out["available"] is False
