"""Operator instruction sanitization (junk chrome → readable bullets)."""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.route_card.extractor import sanitize_operator_instruction
from app.route_card.route_generator import generate_route


JUNK_OP20 = (
    "Refer Note 8 of 1180 000 622 39 Sheet 1 Special Assembly Instructions for "
    "1180 000 622 39 Page 5 of 11 P/N: 2300 553 000 28 Special Assembly Instructions "
    "for 1180 000 622 39 Page 6 of 11 Carefully slide the tool shown above in-between "
    "the two columns of connectors (J1, J2 & J3, J4). The tool shall slide between the "
    "flat portions on either slide and fit tightly. Ensure the front face of tool remains "
    "in contact with chassis wall. Further engage and tighten the tool with fastener "
    "M3x8L Now tighten the connector Jam nuts using appropriate tools. Special Assembly "
    "Instructions for 1180 000 622 39 Page 7 of 11 P/N: 2300 553 100 19 Special Assembly "
    "Instructions for 1180 000 622 39 Page 8 of 11 Carefully slide the tool shown above "
    "in-between the two columns of connectors (J7 & J8, J9). The tool shall slide between "
    "the flat portions on either slide and fit tightly. Ensure the front face of tool "
    "remains in contact with chassis wall. Further engage and tighten the tool with "
    "fastener M3x8L Now tighten the connector Jam nuts using appropriate tools. "
    "P/N: 2300 553 200 10 Special Assembly Instructions for 1180 000 622 39 Page 9 of 11 "
    "Carefully slide the tool shown above in-between the two connectors (J5, J6). The "
    "tool shall slide between the flat portions on either slide and fit tightly. Ensure "
    "the front face of tool remains in contact with chassis wall. Refer Note 32 Engage "
    "Fischer Tool P/N: 2300 102 000 70 onto Standard extension as shown. J5, J6 connectors "
    "to be very carefully & slowly tightened using Fischer Tool. "
    "-> Open SHEET 1 — file 'pspu ga1.pdf' (sheet 1)"
)


def test_strips_special_assembly_page_headers():
    out = sanitize_operator_instruction(JUNK_OP20)
    assert "Special Assembly Instructions" not in out
    assert "Page 5 of 11" not in out
    assert "Page 9 of 11" not in out


def test_keeps_tool_pn_drops_chrome_pn():
    out = sanitize_operator_instruction(JUNK_OP20)
    assert "2300 102 000 70" in out  # Fischer tool
    assert "2300 553 000 28" not in out
    assert "2300 553 100 19" not in out
    assert "2300 553 200 10" not in out


def test_formats_bullets_and_keeps_actions():
    out = sanitize_operator_instruction(JUNK_OP20)
    assert "•" in out
    assert "J1" in out and "J4" in out
    assert "J7" in out and "J9" in out
    assert "J5" in out and "J6" in out
    assert "Fischer" in out
    assert "Open SHEET 1" in out or "pspu ga1.pdf" in out


def test_strips_parts_and_from_drawing_suffixes():
    raw = (
        "Stick Item 2 on the DC OUT side. (From drawing: STICK ITEM 2 AS SHOWN.) "
        "Parts: Item 2 LABEL (1121-001); Item 3 LABEL (1121-002)."
    )
    out = sanitize_operator_instruction(raw)
    assert "From drawing" not in out
    assert "Parts:" not in out
    assert "DC OUT" in out


def test_idempotent():
    once = sanitize_operator_instruction(JUNK_OP20)
    twice = sanitize_operator_instruction(once)
    assert once == twice


# Revision-table cells OCR-glued onto NOTES (BEL cable-assy style).
REV_BLEED_OP30 = (
    "TAKE THE PRINT BY LABEL PRINTING MACHINE OF THE TEXT INDICATED, IN "
    "INDELIBLE BLACK WITH TEXT HEIGHT GREATER THAN OR EQUAL TO 2.5MM, CUT "
    "THE LABEL TO THE DIMENSIONS INDICATED IN FIGURE 1 AND ITEM NO. 110 & "
    "120 TO BE CUT TO LENGTHS GREATER THAN THAT OF THE LABEL BY ABOUT 15MM, "
    "AND TO BE HEAT SHRUNK ON THE LABEL AS 15. 03. Indicated in the figure 1. "
    "Ee _ ee 9 deleted 1 one"
)

REV_BLEED_BULLETS = (
    "• And to be heat shrunk on the label as 15. 03.\n"
    "• Indicated in the figure 1.\n"
    "• Ee _ ee 9 deleted 1 one"
)


def test_strips_revision_table_date_and_deleted_bleed():
    out = sanitize_operator_instruction(REV_BLEED_OP30)
    low = out.lower()
    assert "15. 03" not in out and "15.03" not in out.replace(" ", "")
    assert "deleted" not in low
    assert "1 one" not in low
    assert "heat shrunk" in low
    assert "indicated" in low
    assert "figure 1" in low
    assert "item no. 110" in low or "110" in out


def test_strips_revision_bleed_from_existing_bullets():
    out = sanitize_operator_instruction(REV_BLEED_BULLETS)
    low = out.lower()
    assert "deleted" not in low
    assert "15. 03" not in out
    assert "indicated" in low
    assert "heat shrunk" in low


def test_inline_bullets_become_pointwise_lines():
    """Mid-line • markers (common after merge) must become one bullet per line."""
    raw = (
        "• Assemble Item 5 (Screw) on the ENGAGE CONNECTOR side, below Item 4. "
        "• Assemble Item 53 (Washer) on the ENGAGE CONNECTOR side, below Item 5. "
        "• Assemble Item 4 (Interface PCB) on the ENGAGE CONNECTOR side. "
        "(All sizes are in mm.) Ensure all jam nuts are removed before fitment."
    )
    out = sanitize_operator_instruction(raw)
    lines = [ln for ln in out.split("\n") if ln.strip()]
    assert len(lines) >= 4, out
    assert all(ln.lstrip().startswith("•") for ln in lines), out
    assert "Item 5" in out and "Item 53" in out and "Item 4" in out
    # Must not stay as one wrapped wall of text
    assert "\n•" in out
    assert "fitment" in out.lower()


def test_part_number_paren_tail_not_cut_off():
    """Do not split inside (… 306 32) or drop '32) on the …'."""
    raw = (
        "Assemble Item 5 (Screw hexagon skt hd aisi 316-m3x8, 3004 004 306 32) "
        "on the ENGAGE CONNECTOR side, below Item 4. "
        "Ensure all jam nuts are removed before fitment."
    )
    out = sanitize_operator_instruction(raw)
    assert "3004 004 306 32)" in out, out
    assert "on the ENGAGE CONNECTOR side" in out, out
    assert "fitment" in out.lower(), out
    # Must not start a bullet mid-phrase at the part-number tail
    assert not any(
        re.match(r"^•\s*32\)", ln) or re.match(r"^•\s*on the ENGAGE", ln)
        for ln in out.splitlines()
    ), out


def test_generate_route_sanitizes_instruction_text():
    route = generate_route(
        {
            "notes": [
                {
                    "stepNo": 1,
                    "text": JUNK_OP20,
                    "items": [],
                    "torque": [],
                    "standards": [],
                    "references": [],
                    "elaborated": True,
                    "elaboratedText": JUNK_OP20 + " Parts: Item 1 FOO (1).",
                }
            ],
            "bom_items": [],
            "title_block": {},
        }
    )
    instr = route["operations"][0]["instructionText"]
    assert "Special Assembly Instructions" not in instr
    assert "Parts:" not in instr
    assert "•" in instr


if __name__ == "__main__":
    test_strips_special_assembly_page_headers()
    test_keeps_tool_pn_drops_chrome_pn()
    test_formats_bullets_and_keeps_actions()
    test_strips_parts_and_from_drawing_suffixes()
    test_idempotent()
    test_generate_route_sanitizes_instruction_text()
    print("test_sanitize_operator_instruction: OK")
