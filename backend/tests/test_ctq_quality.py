"""CTQ POINTS → Quality & Inspection, not Manufacturing ops."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.route_card.extractor import extract_notes, is_ctq_note
from app.route_card.route_generator import generate_route, partition_notes_for_route


def test_extract_notes_tags_ctq_header():
    pages = [
        """
        NOTES:
        1. Assemble Item No. 90 as per wire list.
        CTQ POINTS:
        1. Verify bonding continuity after assembly.
        2. Check leak test at 1.5 bar.
        """
    ]
    notes = extract_notes(pages)
    assert notes
    assembly, ctq = partition_notes_for_route(notes)
    assert any("wire list" in (n.get("text") or "").lower() for n in assembly)
    assert ctq
    assert all(is_ctq_note(n) for n in ctq)
    assert any("bonding" in (n.get("text") or "").lower() for n in ctq)
    assert any("leak" in (n.get("text") or "").lower() for n in ctq)


def test_generate_route_ctq_goes_to_inspection_not_ops():
    extraction = {
        "notes": [
            {
                "stepNo": 1,
                "text": "Assemble Item No. 90 as per wire list.",
                "items": [90],
                "noteKind": "note",
                "noteSection": "NOTES",
            },
            {
                "stepNo": 1,
                "text": "Verify bonding continuity after assembly.",
                "items": [],
                "noteKind": "ctq",
                "noteSection": "CTQ POINTS",
            },
            {
                "stepNo": 2,
                "text": "Check leak test at 1.5 bar.",
                "items": [],
                "noteKind": "ctq",
                "noteSection": "CTQ POINTS",
            },
        ],
        "bom_items": [{"itemNo": 90, "qty": 1, "description": "CABLE SET"}],
        "title_block": {},
        "torque_specs": [],
        "dimensions": [],
        "references": [],
    }
    route = generate_route(extraction)
    ops = [
        o
        for o in route["operations"]
        if o.get("operation") != "Final inspection"
    ]
    op_texts = " ".join(
        (o.get("instructionText") or "") + " " + (o.get("operation") or "") for o in ops
    ).lower()
    assert "wire list" in op_texts
    assert "bonding continuity" not in op_texts
    assert "leak test" not in op_texts

    insp = route["inspection"]
    ctq_insp = [i for i in insp if i.get("source") == "ctq" or i.get("criticality") == "Critical"]
    dims = " ".join(i.get("dimension") or "" for i in insp).lower()
    assert "bonding continuity" in dims
    assert "leak test" in dims
    assert all(
        i.get("criticality") == "Critical"
        for i in insp
        if "bonding" in (i.get("dimension") or "").lower()
        or "leak" in (i.get("dimension") or "").lower()
    )
    assert ctq_insp


if __name__ == "__main__":
    test_extract_notes_tags_ctq_header()
    test_generate_route_ctq_goes_to_inspection_not_ops()
    print("test_ctq_quality: OK")
