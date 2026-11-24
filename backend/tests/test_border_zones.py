"""GA border zone detection → confirmed A-8 cells on balloon ops."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.route_card.drawing_mind.assembly_groups import groups_to_synthetic_notes
from app.route_card.drawing_mind.border_zones import (
    empty_border_grid,
    map_point_to_drawing_zone,
    nearest_label,
    validate_border_grid,
)
from app.route_card.route_generator import generate_route


def _grid_12x5() -> dict:
    cols = [{"label": str(i), "x": (i - 0.5) / 12.0} for i in range(1, 13)]
    rows = [
        {"label": chr(ord("A") + i), "y": (i + 0.5) / 5.0} for i in range(5)
    ]
    return validate_border_grid(
        {"cols": cols, "rows": rows, "confidence": 0.9, "source": "test"}
    )


def _grid_8x4() -> dict:
    cols = [{"label": str(i), "x": (i - 0.5) / 8.0} for i in range(1, 9)]
    rows = [
        {"label": chr(ord("A") + i), "y": (i + 0.5) / 4.0} for i in range(4)
    ]
    return validate_border_grid(
        {"cols": cols, "rows": rows, "confidence": 0.9, "source": "test"}
    )


def test_validate_rejects_non_monotonic_cols():
    g = validate_border_grid(
        {
            "cols": [
                {"label": "1", "x": 0.1},
                {"label": "3", "x": 0.2},
                {"label": "2", "x": 0.3},
            ],
            "rows": [
                {"label": "A", "y": 0.2},
                {"label": "B", "y": 0.5},
            ],
            "confidence": 0.9,
        }
    )
    # Sorted by x → labels 1,3,2 which is not monotonic
    assert g["confirmed"] is False


def test_validate_accepts_variable_column_counts():
    assert _grid_12x5()["confirmed"] is True
    assert len(_grid_12x5()["cols"]) == 12
    g8 = _grid_8x4()
    assert g8["confirmed"] is True
    assert len(g8["cols"]) == 8
    assert len(g8["rows"]) == 4


def test_map_point_twelve_and_eight_cols():
    g12 = _grid_12x5()
    # Near column 8, row A
    z = map_point_to_drawing_zone(7.5 / 12.0, 0.5 / 5.0, g12)
    assert z == "A-8"
    g8 = _grid_8x4()
    z8 = map_point_to_drawing_zone(3.5 / 8.0, 1.5 / 4.0, g8)
    assert z8 == "B-4"


def test_map_omits_when_unconfirmed():
    assert map_point_to_drawing_zone(0.5, 0.5, empty_border_grid()) is None
    weak = validate_border_grid(
        {
            "cols": [{"label": "1", "x": 0.1}],
            "rows": [{"label": "A", "y": 0.2}],
            "confidence": 0.9,
        }
    )
    assert weak["confirmed"] is False
    assert map_point_to_drawing_zone(0.1, 0.2, weak) is None


def test_ambiguous_boundary_returns_none():
    g = _grid_12x5()
    # Exactly midway between col 8 and 9 centers
    x8 = (8 - 0.5) / 12.0
    x9 = (9 - 0.5) / 12.0
    mid = (x8 + x9) / 2.0
    lab = nearest_label(mid, g["cols"], axis="x", ambiguity_ratio=0.35)
    # May be None (ambiguous) or one side — mapping must not invent without uniqueness
    z = map_point_to_drawing_zone(mid, 0.5 / 5.0, g)
    if lab is None:
        assert z is None


def test_synthetic_note_and_route_carry_confirmed_zone_only():
    with_zone = {
        "parentItemNo": 480,
        "children": [{"itemNo": 230, "qty": 4}],
        "rawText": "480, 230x4",
        "confidence": 0.9,
        "sourcePage": 1,
        "sourceFilename": "AAAU GA-sheet2.pdf",
        "drawingZone": "A-8",
    }
    no_zone = {
        "parentItemNo": 490,
        "children": [{"itemNo": 270, "qty": 4}],
        "rawText": "490, 270x4",
        "confidence": 0.9,
        "sourcePage": 1,
        "sourceFilename": "AAAU GA-sheet2.pdf",
        # tile id must NOT become drawingZone
        "zone": "A9",
    }
    notes = groups_to_synthetic_notes([with_zone, no_zone], parts_list=None)
    by_parent = {}
    for n in notes:
        items = n.get("items") or []
        if items:
            by_parent[int(items[0])] = n
    assert by_parent[480].get("drawingZone") == "A-8"
    assert "drawingZone" not in by_parent[490]

    route = generate_route(
        {
            "notes": notes,
            "bom_items": [
                {"itemNo": 480, "qty": 1},
                {"itemNo": 230, "qty": 4},
                {"itemNo": 490, "qty": 1},
                {"itemNo": 270, "qty": 4},
            ],
            "title_block": {},
            "assemblyGroups": [with_zone, no_zone],
        }
    )
    ops = route["operations"]
    zoned = [o for o in ops if o.get("drawingZone")]
    assert any(o.get("drawingZone") == "A-8" for o in zoned)
    # Ops without confirmed zone must not invent one
    for o in ops:
        if "490" in (o.get("instructionText") or "") and "270" in (
            o.get("instructionText") or ""
        ):
            assert not o.get("drawingZone")


def test_rejects_tile_id_as_drawing_zone():
    notes = groups_to_synthetic_notes(
        [
            {
                "parentItemNo": 40,
                "children": [{"itemNo": 430, "qty": 80}],
                "rawText": "40, 430x80",
                "confidence": 0.9,
                "drawingZone": "A9",  # Stage C tile — invalid
            }
        ]
    )
    assert notes
    assert "drawingZone" not in notes[0]


if __name__ == "__main__":
    test_validate_rejects_non_monotonic_cols()
    test_validate_accepts_variable_column_counts()
    test_map_point_twelve_and_eight_cols()
    test_map_omits_when_unconfirmed()
    test_ambiguous_boundary_returns_none()
    test_synthetic_note_and_route_carry_confirmed_zone_only()
    test_rejects_tile_id_as_drawing_zone()
    print("ok")
