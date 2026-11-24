"""Parts List qty + title-block regressions (4-digit item nos only)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.route_card.partslist_parser import (
    _parse_pl_line_items,
    _strip_bel_pl_title_blocks,
    rebuild_bom_from_pl,
)


def test_stacked_pl_does_not_eat_next_item_as_qty():
    """After part no, next 4-digit item must not become qty."""
    text = """
0010
ARRAY ASSY
1120 000 010 01
0020
COVER PLATE
1120 000 020 01
1 NO
0030
SCREW HEX M3
2129 000 030 01
4 NO
""".strip()
    items = _parse_pl_line_items(text)
    by_no = {it["itemNo"]: it for it in items}
    assert set(by_no) >= {10, 20, 30}
    assert by_no[10]["qty"] == 1  # not 20
    assert by_no[20]["qty"] == 1
    assert by_no[30]["qty"] == 4


def test_multiline_pl_qty_with_unit():
    text = """
0010 MECHANICAL ASSY_MFR
1180 005 096 03
1 NO
0020 CARD MOUNT BRACKET
1180 005 096 04
6 NO
""".strip()
    items = _parse_pl_line_items(text)
    by_no = {it["itemNo"]: it for it in items}
    assert by_no[10]["qty"] == 1
    assert by_no[20]["qty"] == 6


def test_title_block_version_not_parsed_as_item():
    """End-of-sheet BEL title block (VERSION/VER/…) must not create BOM rows."""
    text = """
ITEM DESIGNATION PART NO QTY
0010
ARRAY ASSY
1120 000 010 01
1 NO
0020
COVER PLATE
1120 000 020 01
1 NO

VER
Change No.
DATE
CHANGE
APVD
P1
000005614138
04.02.2021
Refer ECR
SVNS
02
000005583073
20.05.2020
Provisional
SVNS
TITLE
INTERFACE PCB SP&RC AKASH
DOC TYPE
PL
PART NUMBER
1183 052 442 21
BHARAT ELECTRONICS
HELD IN
PDG
VERSION
02
SHEET NO
1
NO OF SH
2
ALT BOM
1
This document is the property of Bharat Electronics Limited, India
BEL-PLM-REP002-01

0100
NEXT SHEET ITEM
1180 005 100 01
2 NO
""".strip()
    stripped = _strip_bel_pl_title_blocks(text)
    assert "0100" in stripped
    assert "NEXT SHEET ITEM" in stripped
    items = _parse_pl_line_items(text)
    by_no = {it["itemNo"]: it for it in items}
    assert 10 in by_no and 20 in by_no and 100 in by_no
    # Version "02" / sheet "1" must never become item 2 / 1
    assert 2 not in by_no
    assert 1 not in by_no
    # Title-block document PN must not appear as a line item
    assert all(it.get("partNumber") != "1183 052 442 21" for it in items)
    assert by_no[10]["description"] == "ARRAY ASSY"
    assert by_no[100]["description"] == "NEXT SHEET ITEM"


def test_short_version_tokens_are_not_items():
    """Bare 02 is VER, not a 4-digit item no."""
    text = """
02
VERSION
1183 052 442 21
0010
REAL ITEM
1120 000 010 01
1 NO
""".strip()
    items = _parse_pl_line_items(text)
    nos = {it["itemNo"] for it in items}
    assert 2 not in nos
    assert 10 in nos


def test_decimal_qty_stacked_and_cells():
    """Wire / braid metres must keep decimal qty (0.5, 1.25)."""
    text = """
0010
BRAID SLEEVE
2129 000 010 01
0.5
MTR
0020
HEAT SHRINK
2129 000 020 01
1.25
M
""".strip()
    items = _parse_pl_line_items(text)
    by_no = {it["itemNo"]: it for it in items}
    assert by_no[10]["qty"] == 0.5
    assert by_no[10]["unit"] == "MTR"
    assert by_no[20]["qty"] == 1.25
    assert by_no[20]["unit"] == "M"

    tsv = "0010\tBRAID SLEEVE\t2129 000 010 01\t0.5\tMTR\n0020\tHEAT SHRINK\t2129 000 020 01\t.75\tMTR\n"
    cells = _parse_pl_line_items(tsv)
    by2 = {it["itemNo"]: it for it in cells}
    assert by2[10]["qty"] == 0.5
    assert by2[20]["qty"] == 0.75


def test_rebuild_bom_pl_order_and_presence():
    pl = {
        "items": [
            {"itemNo": 10, "qty": 1, "description": "ARRAY", "partNumber": "A-10", "unit": "NO"},
            {"itemNo": 20, "qty": 4, "description": "SCREW", "partNumber": "S-20", "unit": "NO"},
            {"itemNo": 30, "qty": 2, "description": "WASHER", "partNumber": "W-30", "unit": "NO"},
        ]
    }
    pl["itemMap"] = {str(it["itemNo"]): it for it in pl["items"]}
    existing = [
        {"itemNo": 10, "qty": 20, "extractedQty": 20, "source": "ga", "description": "wrong"},
        {"itemNo": 99, "qty": 3, "extractedQty": 3, "source": "balloon", "description": "GA only"},
    ]
    rows = rebuild_bom_from_pl(pl, existing_bom=existing, extracted_by_item={10: 20, 20: 4})
    assert [r["itemNo"] for r in rows] == [10, 20, 30, 99]
    assert rows[0]["qty"] == 1
    assert rows[0]["extractedQty"] == 20
    assert rows[0]["qtyMatch"] is False
    assert rows[0]["gaPresence"] == "present"
    assert rows[0]["description"] == "ARRAY"
    assert rows[1]["qty"] == 4 and rows[1]["qtyMatch"] is True
    assert rows[2]["gaPresence"] == "not_present"
    assert rows[2]["extractedQty"] is None
    assert rows[3]["gaPresence"] == "ga_only"
    assert rows[3]["qty"] is None
