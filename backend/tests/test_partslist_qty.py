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


def test_unpadded_items_wrapped_designation_and_units():
    """ADSN / MS rows use 1, 2, 3 and keep UNIT/SET/size wraps and G/CM/MM."""
    text = """
1 MECHANICAL ASSY_MFR_PSPU
1180 005 096 03
1 NO
10 THERMAL PAD (PSPU)_2
2300 523 401 70
1 NO
39 HARDWARE RAM 16GB DDR4-SODIMM
4806 123 101 48
2 NO
39 H/W RAM DDR4 16GB
4806 197 201 72
2 NO
57 SLEEVING 1/2INCH SPIRAL WRAPPING POLYETH
4909 139 601 17
600 MM Cir Conn-Fil (150MM)
0060
ARRAY- POWER DISTRIBUTION
UNIT
1120 059 848 75
1
NO
0090
AAAU POWER AND DIGITAL CABLE
SET
1120 060 810 02
1
NO
0230
SCREW HEXAGON SKT HD AISI
316- M3x6
3004 004 304 38
4
NO
0490
AMPLIFIER UNIT CAL 9-10GHz
25dBm
4561 111 801 55
1
NO
0560
2W 18GHZ SMA/M
COAXIALTERMINATION.
4555 418 501 01
3
NO
0052
LOCTITE 270
5605 806 201 47
10
G
1120
DIODE ESD PROTECTOR 0603
4240 111 201 17
2
CM
""".strip()
    items = _parse_pl_line_items(text)
    by_no = {}
    for it in items:
        by_no.setdefault(it["itemNo"], it)
    assert by_no[1]["qty"] == 1
    assert by_no[10]["description"].startswith("THERMAL PAD")
    assert by_no[39]["description"].startswith("HARDWARE RAM")
    assert by_no[39]["partNumber"] == "4806 123 101 48"
    assert by_no[57]["qty"] == 600 and by_no[57]["unit"] == "MM"
    assert "UNIT" in by_no[60]["description"].upper()
    assert by_no[60]["qty"] == 1
    assert "SET" in by_no[90]["description"].upper()
    assert "316- M3X6" in by_no[230]["description"].upper()
    assert by_no[230]["qty"] == 4
    assert "25DBM" in by_no[490]["description"].upper()
    assert by_no[560]["description"].startswith("2W 18GHZ")
    assert by_no[560]["qty"] == 3
    assert by_no[52]["qty"] == 10 and by_no[52]["unit"] == "G"
    assert by_no[1120]["qty"] == 2 and by_no[1120]["unit"] == "CM"


def test_split_decimal_and_thousands_qty():
    text = """
0510
CONN RF50 SMP INSER AD FE-FE
L12.98
4605 126 109 30
1,536
NO
0620
COMPOUND HEAT-SINK
5710 008 001 39
0.40
0
KG
0280
SCREW HEXAGON SKT HD AISI
3004 004 383 92
32
NO
REM.
316-M4x12
0290
SCREW HEXAGON SKT HD AISI
316-M4x16
3004 004 386 83
40
NO
""".strip()
    items = _parse_pl_line_items(text)
    by_no = {it["itemNo"]: it for it in items}
    assert by_no[510]["qty"] == 1536
    assert "L12.98" in by_no[510]["description"]
    assert by_no[620]["qty"] == 0.4 and by_no[620]["unit"] == "KG"
    assert "316-M4X12" in by_no[280]["description"].upper()
    assert "316-M4X16" in by_no[290]["description"].upper()
    assert by_no[290]["qty"] == 40


def test_glued_pitch_is_designation_not_item():
    text = """
0830
CONN PCB HDR DR VER 20 CKTS
2MM PTH
4655 265 501 45
2
NO
""".strip()
    items = _parse_pl_line_items(text)
    by_no = {it["itemNo"]: it for it in items}
    assert 2 not in by_no
    assert by_no[830]["qty"] == 2
    assert "2MM PTH" in by_no[830]["description"].upper()
    assert by_no[830]["partNumber"] == "4655 265 501 45"


def test_ns2_tsv_unpadded_and_compact_part_no():
    text = (
        "ITEM\tDESIGNATION\tPART NO\tQTY\tUNT\tCIRCUIT REFERENCE\n"
        "1\tFACIA PANEL ASSY\t112184802920AA\t1\tNO\t,,,\n"
        '40\t"IC LIN OPAMP,HIGH POWER,547F"\t4320 756 101 01\t12\tNO\t"U1, U2"\n'
        "55\tWIRE COP ENAMEL POLYESTER-0.280\t4851 007 090 86\t0.5\tM\t,,,\n"
    )
    items = _parse_pl_line_items(text)
    by_no = {it["itemNo"]: it for it in items}
    assert set(by_no) == {1, 40, 55}
    assert by_no[1]["partNumber"] == "1121 848 029 20 AA"
    assert by_no[1]["qty"] == 1
    assert "OPAMP" in by_no[40]["description"]
    assert "U1" not in by_no[40]["description"]
    assert by_no[40]["qty"] == 12
    assert by_no[55]["qty"] == 0.5 and by_no[55]["unit"] == "M"


def test_title_block_revision_indexes_are_not_items():
    text = """
0280
SCREW HEXAGON SKT HD AISI
3004 004 383 92
32
NO
PARTS LIST
00
000005813050
22.07.2024
Original
10
000005931313
Refer ECR
12
000005942799
Refer ECR
VER
TITLE
ACTIVE ARRAY ANTENNA
PART NUMBER
1120 059 762 42
0290
SCREW HEXAGON SKT HD AISI
3004 004 386 83
40
NO
""".strip()
    items = _parse_pl_line_items(text)
    nos = {it["itemNo"] for it in items}
    assert nos == {280, 290}
    assert all(it["partNumber"] != "1120 059 762 42" for it in items)


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
