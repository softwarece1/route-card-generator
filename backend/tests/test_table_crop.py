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


def test_figure_and_detail_crops():
    from app.route_card.drawing_mind.table_crop import render_view_crop

    data = _pdf_with_table_caption(
        pages=[
            [
                ("FIGURE 1", (72, 80)),
                ("DETAIL A", (72, 220)),
                ("NOTES", (72, 400)),
            ]
        ]
    )
    fig = render_view_crop(data, kind="figure", ref_id="1", page_no=1)
    assert fig["available"] is True
    assert fig["label"] == "FIGURE 1"
    det = render_view_crop(data, kind="detail", ref_id="A", page_no=1)
    assert det["available"] is True
    assert det["label"] == "DETAIL A"


def test_named_interconnection_crop():
    from app.route_card.drawing_mind.table_crop import render_view_crop

    data = _pdf_with_table_caption(
        pages=[
            [
                ("INTERCONNECTION LISTING", (72, 100)),
                ("J1 pin 1 to J2 pin 1", (72, 130)),
                ("FIGURE 9", (72, 420)),
            ]
        ]
    )
    out = render_view_crop(
        data, kind="named", ref_id="INTERCONNECTION TABLE", page_no=1
    )
    assert out["available"] is True
    assert "INTERCONNECTION" in out["label"]


def _pdf_isometric_view(*, with_caption: bool = True) -> bytes:
    """GA-like page: a boxed isometric view with 'ISOMETRIC VIEW' caption underneath."""
    doc = fitz.open()
    page = doc.new_page(width=600, height=800)
    # Drawn view body (rectangle + balloon-ish marks) ABOVE the caption
    page.draw_rect(fitz.Rect(90, 300, 300, 480), color=(0, 0, 0), width=1)
    page.draw_circle((140, 340), 10, color=(0, 0, 0), width=1)
    page.draw_circle((220, 420), 10, color=(0, 0, 0), width=1)
    page.insert_text((136, 344), "1", fontsize=9)
    page.insert_text((216, 424), "2", fontsize=9)
    if with_caption:
        page.insert_text((96, 520), "ISOMETRIC VIEW", fontsize=10)
    page.insert_text((72, 700), "SCALE 1:1", fontsize=10)
    buf = io.BytesIO()
    doc.save(buf)
    doc.close()
    return buf.getvalue()


def test_isometric_view_crop_available_and_clips_above_caption():
    from app.route_card.drawing_mind.table_crop import render_view_crop

    data = _pdf_isometric_view()
    out = render_view_crop(data, kind="isometric", ref_id="", page_no=1, allow_vlm=False)
    assert out["available"] is True, out
    assert out["kind"] == "isometric"
    assert out["label"] == "ISOMETRIC VIEW"
    assert out["page"] == 1
    assert out["confidence"] >= 0.82
    assert out["imageBase64"]
    assert out["calloutItems"] == [1, 2]
    # Clip must sit ABOVE the caption (caption baseline ~y=520) and include the view box (y~300..480)
    x0, y0, x1, y1 = out["clip"]
    assert y1 >= 480
    assert y0 <= 330
    assert y1 < 600


def test_isometric_view_missing_caption_not_available():
    from app.route_card.drawing_mind.table_crop import render_view_crop

    data = _pdf_isometric_view(with_caption=False)
    out = render_view_crop(data, kind="isometric", ref_id="", page_no=1, allow_vlm=False)
    assert out["available"] is False
    assert out["label"] == "ISOMETRIC VIEW"
