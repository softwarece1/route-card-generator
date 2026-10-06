"""CPU drawing-mind feasibility checks (sticker / AS SHOWN placement).

Run from backend/:
  python -m pytest tests/test_drawing_mind_cpu.py -q
  # or without pytest:
  python tests/test_drawing_mind_cpu.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.route_card.drawing_mind.cpu_spatial import CpuSpatialMind
from app.route_card.drawing_mind.merge import merge_ga_extractions, resolve_cross_refs
from app.route_card.drawing_mind.spatial import build_spatial_graph


def _sticker_spatial_pages():
    """Synthetic word boxes mimicking Item 2/3 stickers on DC OUT face with 5.0 offsets."""
    return [
        {
            "page": 1,
            "width": 800,
            "height": 500,
            "words": [
                {"text": "DC", "x0": 420, "y0": 180, "x1": 450, "y1": 200},
                {"text": "OUT", "x0": 455, "y0": 180, "x1": 500, "y1": 200},
                {"text": "5.0", "x0": 40, "y0": 55, "x1": 70, "y1": 70},
                {"text": "5.0", "x0": 25, "y0": 90, "x1": 55, "y1": 105},
                {"text": "5.0", "x0": 90, "y0": 150, "x1": 120, "y1": 165},
                {"text": "2", "x0": 80, "y0": 90, "x1": 95, "y1": 110},
                {"text": "3", "x0": 80, "y0": 170, "x1": 95, "y1": 190},
                {"text": "115.0", "x0": 300, "y0": 450, "x1": 350, "y1": 470},
                {"text": "55.0", "x0": 700, "y0": 250, "x1": 740, "y1": 270},
                {
                    "text": "ALL",
                    "x0": 520,
                    "y0": 420,
                    "x1": 550,
                    "y1": 435,
                },
                {
                    "text": "DIMENSIONS",
                    "x0": 555,
                    "y0": 420,
                    "x1": 640,
                    "y1": 435,
                },
                {
                    "text": "ARE",
                    "x0": 645,
                    "y0": 420,
                    "x1": 675,
                    "y1": 435,
                },
                {
                    "text": "IN",
                    "x0": 680,
                    "y0": 420,
                    "x1": 700,
                    "y1": 435,
                },
                {
                    "text": "MM",
                    "x0": 705,
                    "y0": 420,
                    "x1": 735,
                    "y1": 435,
                },
            ],
        }
    ]


def test_sticker_elaboration():
    note_text = "STICK ITEM 2 & 3 AS SHOWN USING SUITABLE ADHESIVE."
    ga = {
        "raw_text": note_text + "\nALL DIMENSIONS ARE IN MM UNLESS OTHERWISE SPECIFIED\nDC OUT\nPOWER SUPPLY",
        "title_block": {"unit": "mm", "drawingNumber": "1121 857 498 34"},
        "notes": [
            {
                "sheet": 1,
                "stepNo": 1,
                "text": note_text,
                "items": [2, 3],
                "torque": [],
                "connectors": [],
                "standards": [],
                "references": [],
            }
        ],
        "bom_items": [],
    }
    # Deliberately put balloon "3" above balloon "2" — note order must still win
    pages = _sticker_spatial_pages()
    pages[0]["words"].extend(
        [
            {"text": "3", "x0": 80, "y0": 40, "x1": 95, "y1": 55},  # higher on page (wrong)
            {"text": "POWER", "x0": 100, "y0": 200, "x1": 160, "y1": 215},
            {"text": "SUPPLY", "x0": 165, "y0": 200, "x1": 230, "y1": 215},
        ]
    )
    mind = CpuSpatialMind()
    result = mind.understand(
        pdf_bytes=None,
        ga_extraction=ga,
        spatial_pages=pages,
        source_drawing_id=1,
        source_filename="Masked112185749834 - GA.pdf",
    )
    assert result.engine == "cpu_spatial"
    note = result.notes[0]
    elaborated = (note.get("elaboratedText") or "")
    up = elaborated.upper()
    assert "ITEM 2" in up
    assert "ITEM 3" in up
    # Item 2 must be placed first (top/left), Item 3 below Item 2 — not swapped
    i2 = up.find("STICK ITEM 2")
    i3 = up.find("STICK ITEM 3")
    assert i2 >= 0 and i3 >= 0 and i2 < i3, elaborated
    assert "BELOW ITEM 2" in up
    assert "DC OUT" in up
    assert "POWER SUPPLY" not in up.split("(FROM DRAWING")[0]  # face must not be sticker legend
    assert "5" in elaborated
    assert "MM" in up
    assert "ADHESIVE" in up or "GLUE" in up
    assert result.placements
    assert result.placements[0].item_no == 2
    assert result.placements[1].item_no == 3
    assert elaborated


def test_item_order_from_note():
    from app.route_card.drawing_mind.cpu_spatial import _item_order_from_note

    assert _item_order_from_note("STICK ITEM 2 & 3 AS SHOWN", [2, 3]) == [2, 3]
    assert _item_order_from_note("STICK ITEM 3 AND 2 AS SHOWN", [2, 3]) == [3, 2]


def test_as_shown_without_spatial_warns():
    ga = {
        "raw_text": "STICK ITEM 2 & 3 AS SHOWN USING SUITABLE ADHESIVE. ALL DIMENSIONS ARE IN MM",
        "title_block": {"unit": "mm"},
        "notes": [
            {
                "sheet": 1,
                "stepNo": 1,
                "text": "STICK ITEM 2 & 3 AS SHOWN USING SUITABLE ADHESIVE.",
                "items": [2, 3],
                "torque": [],
                "connectors": [],
                "standards": [],
                "references": [],
            }
        ],
    }
    mind = CpuSpatialMind()
    result = mind.understand(
        pdf_bytes=None,
        ga_extraction=ga,
        spatial_pages=[],
        source_drawing_id=1,
        source_filename="test.pdf",
    )
    assert any("spatial" in w.lower() or "balloon" in w.lower() or "infer" in w.lower() or "verify" in w.lower() for w in result.warnings) or result.notes[
        0
    ].get("elaboratedText")


def test_multi_ga_cross_ref_missing():
    gas = [
        {
            "drawingId": 1,
            "filename": "assy-a.pdf",
            "drawingNumber": "1121 857 498 34",
            "title_block": {"drawingNumber": "1121 857 498 34"},
            "references": [],
            "rawText": "REFER GA 1121 857 498 35 FOR PCB ASSEMBLY",
            "notes": [{"text": "REFER GA 1121 857 498 35", "items": []}],
            "bom_items": [],
            "pages": 1,
            "drawing_type": "assembly",
        }
    ]
    refs = resolve_cross_refs(gas)
    assert any(r.status == "missing" and "1121 857 498 35" in r.drawing_number for r in refs)
    merged = merge_ga_extractions(gas)
    assert any("not uploaded" in w.lower() for w in merged.get("warnings") or [])


def test_spatial_graph_surfaces():
    graph = build_spatial_graph(_sticker_spatial_pages(), "ALL DIMENSIONS ARE IN MM")
    assert graph["unit"] == "mm"
    labels = [s["label"] for s in graph["allSurfaces"]]
    assert any("DC OUT" in lab for lab in labels)
    assert any(b["itemNo"] == 2 for b in graph["allBalloons"])


def test_pcb_pl_wl_link():
    mind = CpuSpatialMind()
    ga = {
        "raw_text": "SHORT PINS ON J1 AS SHOWN",
        "title_block": {},
        "notes": [
            {
                "sheet": 1,
                "stepNo": 1,
                "text": "DO NOT SHORT J1 PINS 1 AND 2",
                "items": [10],
                "torque": [],
                "connectors": ["J1"],
                "standards": [],
                "references": [],
            }
        ],
    }
    pages = [
        {
            "page": 1,
            "width": 400,
            "height": 400,
            "words": [{"text": "J1", "x0": 100, "y0": 100, "x1": 130, "y1": 120}],
        }
    ]
    pl = {
        "items": [{"itemNo": 10, "description": "CONN J1 CIRCULAR", "partNumber": "4615 010 027 12"}],
        "itemMap": {"10": {"description": "CONN J1 CIRCULAR", "partNumber": "4615 010 027 12"}},
    }
    wl = {"wires": [{"from": "J1-1", "to": "P2-3", "wireType": "AWG22"}]}
    result = mind.understand(
        pdf_bytes=None,
        ga_extraction=ga,
        spatial_pages=pages,
        parts_list=pl,
        wire_list=wl,
    )
    assert result.pcb_links
    assert any(l.connector == "J1" and l.pl_item_no == 10 for l in result.pcb_links)


def test_wiring_ga_view_refs_sheet2_figure_table():
    """Real NS2 wiring GAs: Sheet 2 / Figure 1 / Table 1 / Detail B."""
    from pathlib import Path
    from app.route_card.extractor import ingest_drawing_pdf
    from app.route_card.drawing_mind.merge import merge_ga_extractions
    from app.route_card.route_generator import generate_route

    base = Path(r"d:/PMF/docs/NS2 Sample Drawings/NS2 Sample Drawings/2. Wiring")
    ga1 = base / "masked-112188041168 - GA - 001.pdf"
    ga2 = base / "masked-112188041168 - GA - 002.pdf"
    if not ga1.is_file() or not ga2.is_file():
        print("SKIP wiring GA files not present")
        return

    p1 = ingest_drawing_pdf(ga1.read_bytes(), ga1.name)
    p2 = ingest_drawing_pdf(ga2.read_bytes(), ga2.name)
    p1["drawingId"] = 44
    p1["filename"] = ga1.name
    p1["drawingNumber"] = (p1.get("title_block") or {}).get("drawingNumber")
    p2["drawingId"] = 45
    p2["filename"] = ga2.name
    p2["drawingNumber"] = (p2.get("title_block") or {}).get("drawingNumber")

    merged = merge_ga_extractions([p1, p2])
    view_refs = merged.get("viewRefs") or []
    assert view_refs, "expected viewRefs"
    labels = {v["label"] for v in view_refs}
    assert any(l.startswith("FIGURE") for l in labels)
    assert any(l.startswith("SHEET") for l in labels)
    assert any(l.startswith("TABLE") for l in labels)

    sheet2 = next((v for v in view_refs if v["label"] == "SHEET 2"), None)
    assert sheet2, "SHEET 2 should be detected"
    assert sheet2["status"] == "resolved"
    assert "002" in (sheet2.get("matchedFilename") or "")

    # Notes should carry elaboratedText with arrow resolution
    sheet_note = next(
        (n for n in merged["notes"] if "SHEET 2" in (n.get("text") or "").upper()),
        None,
    )
    assert sheet_note
    elab = (sheet_note.get("elaboratedText") or "").upper()
    assert "002" in elab or "SHEET 2" in elab
    assert sheet_note.get("viewRefs")

    table_note = next(
        (n for n in merged["notes"] if "TABEL" in (n.get("text") or "").upper() or "TABLE 1" in (n.get("text") or "").upper()),
        None,
    )
    assert table_note
    assert table_note.get("elaboratedText")

    route = generate_route(merged)
    op7 = next((o for o in route["operations"] if "SHEET 2" in (o.get("instructionText") or "").upper() or "INTERCONNECTION" in (o.get("instructionText") or "").upper()), None)
    assert op7
    assert op7.get("elaborated") or "->" in (op7.get("instructionText") or "")
    assert "002" in (op7.get("reference") or "") or "SHEET 2" in (op7.get("reference") or "")


def test_item_pair_110_and_120():
    from app.route_card.extractor import _items_in

    assert _items_in("ITEM 110 & 120 TO BE CUT") == [110, 120]


if __name__ == "__main__":
    test_spatial_graph_surfaces()
    test_item_order_from_note()
    test_sticker_elaboration()
    test_as_shown_without_spatial_warns()
    test_multi_ga_cross_ref_missing()
    test_pcb_pl_wl_link()
    test_item_pair_110_and_120()
    test_wiring_ga_view_refs_sheet2_figure_table()
    print("OK — CPU drawing-mind feasibility checks passed.")
    print(
        "Failure modes for VLM phase: low OCR word boxes, graphics-only balloons, "
        "ambiguous dimension ownership, scanned PDFs without Tesseract."
    )
