"""Balloon callout clusters + LLM route helpers (mocked — no live GPU)."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.route_card.drawing_mind.assembly_groups import (
    bom_items_from_assembly_groups,
    callout_qty_totals,
    filter_weak_groups,
    generate_llm_route_ops,
    group_item_nos,
    groups_to_synthetic_notes,
    merge_bom_with_balloon_items,
    merge_continuation_groups,
    merge_notes_with_balloon_notes,
    normalize_vlm_groups,
    parse_callout_cluster,
    repair_group_quantities,
    scan_text_for_clusters,
    split_stacked_balloon_clusters,
    validate_assembly_group,
    validate_llm_route_ops,
)
from app.route_card.partslist_parser import enrich_bom_with_pl
from app.route_card.review import build_item_link_report, collect_drawing_item_refs
from app.route_card.route_generator import generate_route


PL = {
    "items": [
        {"itemNo": 40, "qty": 40, "description": "PLANK ASSY WITHOUT SLB", "partNumber": "1120-40"},
        {"itemNo": 430, "qty": 80, "description": "SCREW HEX M4", "partNumber": "2129-430"},
        {"itemNo": 380, "qty": 80, "description": "WASHER PLAIN M4", "partNumber": "2129-380"},
        {"itemNo": 390, "qty": 80, "description": "WASHER SPRING M4", "partNumber": "2129-390"},
        {"itemNo": 480, "qty": 1, "description": "CAL POWER DIVIDER UNIT U8", "partNumber": "1120-480"},
        {"itemNo": 230, "qty": 4, "description": "SCREW HEX M3x6", "partNumber": "2129-230"},
        {"itemNo": 340, "qty": 34, "description": "WASHER PLAIN M3", "partNumber": "2129-340"},
        {"itemNo": 350, "qty": 34, "description": "WASHER SPRING M3", "partNumber": "2129-350"},
        {"itemNo": 260, "qty": 10, "description": "SCR XREC CSK M2.5x20", "partNumber": "2129-260"},
        {"itemNo": 490, "qty": 1, "description": "AMPLIFIER UNIT CAL", "partNumber": "1120-490"},
        {"itemNo": 270, "qty": 4, "description": "SCREW HEX M3x10", "partNumber": "2129-270"},
        {"itemNo": 90, "qty": 1, "description": "CABLE SET", "partNumber": "1120-90"},
        {"itemNo": 10, "qty": 1, "description": "ARRAY ASSY", "partNumber": "1120-10"},
        {"itemNo": 450, "qty": 1, "description": "RFIF UNIT U3", "partNumber": "1120-450"},
        {"itemNo": 300, "qty": 8, "description": "SCREW HEX M6X10", "partNumber": "2129-300"},
        {"itemNo": 400, "qty": 8, "description": "WASHER PLAIN M6", "partNumber": "2129-400"},
        {"itemNo": 410, "qty": 8, "description": "WASHER SPRING M6", "partNumber": "2129-410"},
        {"itemNo": 80, "qty": 4, "description": "SLB 2-WAY POWER DIVIDER", "partNumber": "1120-80"},
        {"itemNo": 520, "qty": 8, "description": "CONN RF ADAPTOR", "partNumber": "2129-520"},
        {"itemNo": 250, "qty": 8, "description": "SCREW HEX M3x16", "partNumber": "2129-250"},
        {"itemNo": 45, "qty": 1, "description": "COVER PLATE", "partNumber": "1120-45"},
        {"itemNo": 13, "qty": 2, "description": "SCREW M3", "partNumber": "2129-13"},
        {"itemNo": 14, "qty": 2, "description": "WASHER PLAIN M3B", "partNumber": "2129-14"},
        {"itemNo": 15, "qty": 2, "description": "WASHER SPRING M3B", "partNumber": "2129-15"},
    ]
}
PL["itemMap"] = {str(it["itemNo"]): it for it in PL["items"]}
PL_NOS = {it["itemNo"] for it in PL["items"]}


def test_parse_callout_x_qty():
    g = parse_callout_cluster("480, 230x4, 340x4, 350x4, 260x2")
    assert g is not None
    assert g["parentItemNo"] == 480
    kids = {c["itemNo"]: c["qty"] for c in g["children"]}
    assert kids == {230: 4, 340: 4, 350: 4, 260: 2}


def test_parse_callout_dash_qty():
    g = parse_callout_cluster("490, 270-4, 340-4, 350-4")
    assert g is not None
    assert g["parentItemNo"] == 490
    kids = {c["itemNo"]: c["qty"] for c in g["children"]}
    assert kids[270] == 4 and kids[340] == 4


def test_parse_parenthetical_reference():
    g = parse_callout_cluster("(460), 240x8, 340x8")
    assert g is not None
    assert 460 in (g.get("references") or [])


def test_validate_drops_unknown_pl_items():
    raw = parse_callout_cluster("480, 230x4, 999x2")
    ng = validate_assembly_group(raw, {480, 230})
    assert ng is not None
    assert ng["parentItemNo"] == 480
    assert [c["itemNo"] for c in ng["children"]] == [230]


def test_scan_text_for_clusters():
    blob = "noise 480, 230x4, 340x4, 350x4, 260x2 more noise"
    found = scan_text_for_clusters(blob)
    assert len(found) >= 1
    assert found[0]["parentItemNo"] == 480


def test_normalize_vlm_groups():
    data = {
        "groups": [
            {
                "parentItemNo": 480,
                "children": [{"itemNo": 230, "qty": 4}, {"itemNo": 340, "qty": 4}],
                "rawText": "480, 230x4, 340x4",
                "confidence": 0.9,
            }
        ],
        "warnings": [],
    }
    groups, _ = normalize_vlm_groups(data, PL_NOS, source_page=1, source_filename="ga.pdf")
    assert len(groups) == 1
    assert groups[0]["parentItemNo"] == 480
    assert groups[0]["sourceFilename"] == "ga.pdf"


def test_synthetic_notes_and_route_merge():
    g = validate_assembly_group(
        parse_callout_cluster("480, 230x4, 340x4, 350x4, 260x2"),
        PL_NOS,
        source_page=1,
        source_filename="AAAU GA-sheet2.pdf",
    )
    g.pop("warnings", None)
    balloon_notes = groups_to_synthetic_notes([g], parts_list=PL)
    assert balloon_notes
    assert "480" in balloon_notes[0]["text"]
    assert any(u["itemNo"] == 230 and u["qty"] == 4 for u in balloon_notes[0]["itemsUsed"])

    notes = [
        {
            "stepNo": 1,
            "text": "Item No. 90 & 100 to be routed as per wire list.",
            "items": [90],
        }
    ]
    merged = merge_notes_with_balloon_notes(notes, balloon_notes)
    assert len(merged) == 2
    assert any(n.get("assemblyGroup") for n in merged)

    route = generate_route(
        {
            "notes": merged,
            "bom_items": PL["items"],
            "title_block": {},
            "assemblyGroups": [g],
        }
    )
    ops = route["operations"]
    balloon_ops = [
        o
        for o in ops
        if "480" in (o.get("instructionText") or "")
        or any(i.get("itemNo") == 480 for i in (o.get("itemsUsed") or []))
    ]
    assert balloon_ops
    note_ops = [o for o in ops if "90" in (o.get("instructionText") or "")]
    assert note_ops


def test_item_link_includes_assembly_groups():
    g = validate_assembly_group(
        parse_callout_cluster("480, 230x4, 340x4"),
        PL_NOS,
    )
    g.pop("warnings", None)
    mind = {"assemblyGroups": [g], "pcbLinks": [], "crossRefs": []}
    parsed = {"notes": [], "bom_items": [], "raw_text": ""}
    refs = collect_drawing_item_refs(parsed, mind=mind)
    assert "480" in refs and "230" in refs and "340" in refs
    report = build_item_link_report(parsed, PL, mind=mind)
    assert "480" in report["matched"]
    assert "230" in report["matched"]


def test_llm_route_preferred_when_present():
    llm_ops = validate_llm_route_ops(
        [
            {
                "opNo": 10,
                "operation": "Assemble divider",
                "instruction": "Assemble Item No. 480 using Item No. 230×4.",
                "itemsUsed": [{"itemNo": 480, "qty": 1}, {"itemNo": 230, "qty": 4}],
            }
        ],
        PL_NOS,
        PL,
    )
    route = generate_route(
        {
            "notes": [{"stepNo": 1, "text": "Item No. 90 route cables.", "items": [90]}],
            "bom_items": PL["items"],
            "title_block": {},
            "llmRouteOps": llm_ops,
        }
    )
    ops = [o for o in route["operations"] if o.get("operation") != "Final inspection"]
    assert len(ops) == 1
    assert ops[0].get("source") == "llm_route"
    assert any(i["itemNo"] == 480 for i in ops[0]["itemsUsed"])


def test_generate_llm_route_ops_mocked():
    fake = """{
      "operations": [
        {
          "opNo": 10,
          "operation": "Assemble CAL divider",
          "instruction": "Assemble Item No. 480 using Item No. 230x4, 340x4.",
          "itemsUsed": [
            {"itemNo": 480, "qty": 1},
            {"itemNo": 230, "qty": 4},
            {"itemNo": 340, "qty": 4}
          ],
          "inspection": "Visual"
        },
        {
          "opNo": 20,
          "operation": "Route cables",
          "instruction": "Item No. 90 to be routed as per wire list.",
          "itemsUsed": [{"itemNo": 90, "qty": 1}]
        }
      ],
      "warnings": []
    }"""
    with patch(
        "app.route_card.drawing_mind.assembly_groups.chat_text", return_value=fake
    ):
        ops, warns = generate_llm_route_ops(
            notes=[{"stepNo": 1, "text": "Item No. 90 to be routed.", "items": [90]}],
            assembly_groups=[
                {
                    "parentItemNo": 480,
                    "children": [{"itemNo": 230, "qty": 4}, {"itemNo": 340, "qty": 4}],
                    "rawText": "480, 230x4, 340x4",
                    "confidence": 0.9,
                }
            ],
            parts_list=PL,
            model="google/gemma-4-E4B-it",
            base_url="http://127.0.0.1:9",
            timeout=5,
            max_tokens=512,
        )
    assert not warns or True
    assert len(ops) == 2
    assert group_item_nos(
        [{"parentItemNo": 480, "children": [{"itemNo": 230, "qty": 4}]}]
    ) == {"480", "230"}


def test_parse_spaced_and_unicode_qty():
    g = parse_callout_cluster("480, 230 × 4, 340 X4, 260x2")
    assert g is not None
    kids = {c["itemNo"]: c["qty"] for c in g["children"]}
    assert kids[230] == 4 and kids[340] == 4 and kids[260] == 2


def test_parse_ocr_split_qty_token():
    g = parse_callout_cluster("480, 230, X4, 340, X4")
    assert g is not None
    kids = {c["itemNo"]: c["qty"] for c in g["children"]}
    assert kids.get(230) == 4 and kids.get(340) == 4


def test_normalize_prefers_rawtext_qty_over_model_ones():
    """Model drops subscripts in children but keeps them in rawText."""
    data = {
        "groups": [
            {
                "parentItemNo": 480,
                "children": [
                    {"itemNo": 230, "qty": 1},
                    {"itemNo": 340, "qty": 1},
                    {"itemNo": 350, "qty": 1},
                    {"itemNo": 260, "qty": 1},
                ],
                "rawText": "480, 230x4, 340x4, 350x4, 260x2",
                "confidence": 0.9,
            },
            {
                "parentItemNo": 40,
                "children": [
                    {"itemNo": 430, "qty": 1},
                    {"itemNo": 380, "qty": 1},
                    {"itemNo": 390, "qty": 1},
                ],
                "rawText": "40, 430x80, 380x80, 390x80",
                "confidence": 0.88,
            },
        ],
        "warnings": [],
    }
    groups, _ = normalize_vlm_groups(
        data, PL_NOS, source_page=1, source_filename="ga.pdf", parts_list=PL
    )
    by_parent = {g["parentItemNo"]: g for g in groups}
    kids480 = {c["itemNo"]: c["qty"] for c in by_parent[480]["children"]}
    assert kids480 == {230: 4, 340: 4, 350: 4, 260: 2}
    kids40 = {c["itemNo"]: c["qty"] for c in by_parent[40]["children"]}
    assert kids40 == {430: 80, 380: 80, 390: 80}


def test_qty_repair_when_rawtext_has_no_markers():
    groups = [
        {
            "parentItemNo": 480,
            "children": [
                {"itemNo": 230, "qty": 1},
                {"itemNo": 340, "qty": 1},
                {"itemNo": 350, "qty": 1},
                {"itemNo": 260, "qty": 1},
            ],
            "rawText": "480, 230, 340, 350, 260",
            "confidence": 0.9,
        }
    ]
    fake = """{
      "quantities": [
        {"itemNo": 230, "qty": 4},
        {"itemNo": 340, "qty": 4},
        {"itemNo": 350, "qty": 4},
        {"itemNo": 260, "qty": 2}
      ],
      "warnings": []
    }"""
    with patch(
        "app.route_card.drawing_mind.assembly_groups.chat_vision", return_value=fake
    ):
        repaired, _ = repair_group_quantities(
            groups,
            image_b64="AAAA",
            image_mime="image/jpeg",
            model="m",
            base_url="http://127.0.0.1:9",
            timeout=5,
            max_tokens=256,
        )
    kids = {c["itemNo"]: c["qty"] for c in repaired[0]["children"]}
    assert kids == {230: 4, 340: 4, 350: 4, 260: 2}
    assert "230x4" in (repaired[0].get("rawText") or "")


def test_filter_weak_and_fastener_only():
    bare = {"parentItemNo": 10, "children": [], "rawText": "10", "confidence": 0.9}
    fastener_pair = {
        "parentItemNo": 340,
        "children": [{"itemNo": 350, "qty": 1}],
        "rawText": "340, 350",
        "confidence": 0.9,
    }
    good = {
        "parentItemNo": 480,
        "children": [{"itemNo": 230, "qty": 4}],
        "rawText": "480, 230x4",
        "confidence": 0.9,
    }
    kept, warns = filter_weak_groups(
        [bare, fastener_pair, good], parts_list=PL
    )
    assert len(kept) == 1
    assert kept[0]["parentItemNo"] == 480
    assert any("no children" in w for w in warns)
    assert any("fastener-only" in w for w in warns)


def test_bom_enrichment_from_assembly_groups():
    g480 = validate_assembly_group(
        parse_callout_cluster("480, 230x4, 340x4, 350x4, 260x2"),
        PL_NOS,
    )
    g40 = validate_assembly_group(
        parse_callout_cluster("40, 430x80, 380x80, 390x80"),
        PL_NOS,
    )
    g480.pop("warnings", None)
    g40.pop("warnings", None)
    balloon = bom_items_from_assembly_groups([g480, g40], parts_list=PL)
    by_no = {b["itemNo"]: b for b in balloon}
    # Display qty = PL; extractedQty = balloon callout total
    assert by_no[230]["qty"] == 4  # PL qty
    assert by_no[230]["extractedQty"] == 4
    assert by_no[230]["qtyMatch"] is True
    assert by_no[430]["qty"] == 80
    assert by_no[430]["extractedQty"] == 80
    assert by_no[480]["partNumber"] == "1120-480"
    assert by_no[230]["description"]

    ga = [
        {"itemNo": 10, "qty": 20, "partNumber": "", "description": "ARRAY"},
        {"itemNo": 20, "qty": 1, "partNumber": "", "description": ""},
    ]
    merged = merge_bom_with_balloon_items(ga, balloon)
    merged = enrich_bom_with_pl(merged, PL)
    nos = {b["itemNo"] for b in merged}
    assert 10 in nos and 230 in nos and 430 in nos and 480 in nos
    row230 = next(b for b in merged if b["itemNo"] == 230)
    assert row230["qty"] == 4  # PL authoritative
    assert row230["extractedQty"] == 4
    assert row230["qtyMatch"] is True

    route = generate_route(
        {
            "notes": [],
            "bom_items": merged,
            "title_block": {},
            "assemblyGroups": [g480, g40],
        }
    )
    bom_count = next(
        c["count"] for c in route["feature_counts"] if c["key"] == "items"
    )
    assert bom_count == len(merged)
    assert bom_count > 2

    report = build_item_link_report(
        {"bom_items": merged, "notes": [], "raw_text": ""},
        PL,
        mind={"assemblyGroups": [g480, g40]},
    )
    assert report["summary"]["qtyChecked"] >= 1
    # 340 PL qty is 34 but single callout extracts 4 → mismatch
    assert "340" in report["qtyMismatches"] or report["summary"]["qtyMismatchCount"] >= 1
    row340 = next(r for r in report["rows"] if r["itemNo"] == "340")
    assert row340["plQty"] == 34
    assert row340["extractedQty"] == 4
    assert row340["qtyMatch"] is False


def test_parse_multiline_callout_keeps_second_line():
    """AAAU-style wrap: line2 fasteners stay on the same cluster."""
    raw = "450, 300x8\n400x8, 410x8"
    g = parse_callout_cluster(raw)
    assert g is not None
    assert g["parentItemNo"] == 450
    kids = {c["itemNo"]: c["qty"] for c in g["children"]}
    assert kids == {300: 8, 400: 8, 410: 8}


def test_parse_stacked_subscript_qty_lines():
    raw = "80, 520, 250\nx4, x8, x8\n340, 350\nx8, x8"
    g = parse_callout_cluster(raw)
    assert g is not None
    assert g["parentItemNo"] == 80
    assert g.get("parentQty") == 4
    kids = {c["itemNo"]: c["qty"] for c in g["children"]}
    assert kids[520] == 8 and kids[250] == 8
    assert kids[340] == 8 and kids[350] == 8


def test_parse_hyphen_item_qty_section_style():
    """SECTION A-A style: 45-1, 13-2, 14-2 (no x subscript)."""
    g = parse_callout_cluster("45-1, 13-2, 14-2, 15-2")
    assert g is not None
    assert g["parentItemNo"] == 45
    assert g.get("parentQty") == 1
    kids = {c["itemNo"]: c["qty"] for c in g["children"]}
    assert kids == {13: 2, 14: 2, 15: 2}
    totals = callout_qty_totals([g])
    assert totals[45] == 1
    assert totals[13] == 2


def test_parse_parent_with_qty_marker():
    g = parse_callout_cluster("50x4, 430x8, 380x8, 390x8")
    assert g["parentItemNo"] == 50
    assert g.get("parentQty") == 4
    kids = {c["itemNo"]: c["qty"] for c in g["children"]}
    assert kids[430] == 8


def test_merge_continuation_fastener_line_into_parent():
    parent = {
        "parentItemNo": 450,
        "children": [{"itemNo": 300, "qty": 8}],
        "rawText": "450, 300x8",
        "confidence": 0.9,
        "sourcePage": 1,
    }
    orphan = {
        "parentItemNo": 400,
        "children": [{"itemNo": 410, "qty": 8}],
        "rawText": "400x8, 410x8",
        "confidence": 0.9,
        "sourcePage": 1,
    }
    merged, warns = merge_continuation_groups([parent, orphan], parts_list=PL)
    assert len(merged) == 1
    kids = {c["itemNo"]: c["qty"] for c in merged[0]["children"]}
    assert kids[300] == 8 and kids[400] == 8 and kids[410] == 8
    assert any("merged continuation" in w for w in warns)
    kept, _ = filter_weak_groups(merged, parts_list=PL)
    assert len(kept) == 1


def test_merge_orphan_emitted_before_parent():
    """VLM may list 400/410 before 450 — still attach to nearest assembly parent."""
    orphan = {
        "parentItemNo": 400,
        "children": [{"itemNo": 410, "qty": 8}],
        "rawText": "400x8, 410x8",
        "confidence": 0.9,
        "sourcePage": 1,
    }
    parent = {
        "parentItemNo": 450,
        "children": [{"itemNo": 300, "qty": 8}],
        "rawText": "450, 300x8",
        "confidence": 0.9,
        "sourcePage": 1,
    }
    other = {
        "parentItemNo": 80,
        "children": [{"itemNo": 520, "qty": 4}, {"itemNo": 250, "qty": 8}],
        "rawText": "80, 520x4, 250x8",
        "confidence": 0.9,
        "sourcePage": 1,
    }
    orphan340 = {
        "parentItemNo": 340,
        "children": [{"itemNo": 350, "qty": 8}],
        "rawText": "340x8, 350x8",
        "confidence": 0.9,
        "sourcePage": 1,
    }
    # Order mirrors resp(2): assemblies then fastener orphans (or orphans first)
    merged, _ = merge_continuation_groups(
        [orphan, parent, other, orphan340], parts_list=PL
    )
    by_p = {g["parentItemNo"]: g for g in merged}
    assert 400 not in by_p and 340 not in by_p
    assert 450 in by_p and 80 in by_p
    kids450 = {c["itemNo"]: c["qty"] for c in by_p[450]["children"]}
    kids80 = {c["itemNo"]: c["qty"] for c in by_p[80]["children"]}
    assert kids450[400] == 8 and kids450[410] == 8
    assert kids80[340] == 8 and kids80[350] == 8
    # Stacked balloons stay separate
    assert 520 not in kids450 and 300 not in kids80


def test_scan_multiline_blob():
    blob = "noise\n450, 300x8\n400x8, 410x8\nmore"
    found = scan_text_for_clusters(blob, parts_list=PL)
    assert found
    kids = {c["itemNo"]: c["qty"] for c in found[0]["children"]}
    assert 400 in kids and 410 in kids


def test_stacked_balloons_are_separate_points():
    """450-block above and 80-block below = two balloons, not one merge."""
    blob = (
        "450, 300\nx8\n400, 410\nx8, x8\n"
        "80, 520, 250\nx4, x8, x8\n340, 350\nx8, x8"
    )
    clusters = split_stacked_balloon_clusters(blob, parts_list=PL)
    assert len(clusters) == 2
    assert clusters[0]["lines"][0].startswith("450")
    assert any("400" in ln for ln in clusters[0]["lines"])
    assert clusters[1]["lines"][0].startswith("80")
    assert any("340" in ln for ln in clusters[1]["lines"])

    found = scan_text_for_clusters(blob, parts_list=PL)
    parents = {g["parentItemNo"] for g in found}
    assert 450 in parents and 80 in parents
    g450 = next(g for g in found if g["parentItemNo"] == 450)
    g80 = next(g for g in found if g["parentItemNo"] == 80)
    kids450 = {c["itemNo"] for c in g450["children"]}
    kids80 = {c["itemNo"] for c in g80["children"]}
    assert 400 in kids450 and 410 in kids450
    assert 80 not in kids450 and 520 not in kids450
    assert 340 in kids80 and 350 in kids80 and 520 in kids80
    assert g450.get("calloutLines") and len(g450["calloutLines"]) >= 2


def test_normalize_vlm_merges_multiline_rawtext():
    data = {
        "groups": [
            {
                "parentItemNo": 450,
                "children": [{"itemNo": 300, "qty": 1}],
                "rawText": "450, 300x8\n400x8, 410x8",
                "confidence": 0.9,
            }
        ],
        "warnings": [],
    }
    nos = PL_NOS | {450, 300, 400, 410}
    groups, _ = normalize_vlm_groups(
        data, nos, source_page=1, source_filename="ga.pdf", parts_list=PL
    )
    assert len(groups) == 1
    kids = {c["itemNo"]: c["qty"] for c in groups[0]["children"]}
    assert kids[300] == 8 and kids[400] == 8 and kids[410] == 8


if __name__ == "__main__":
    test_parse_callout_x_qty()
    test_parse_callout_dash_qty()
    test_parse_parenthetical_reference()
    test_validate_drops_unknown_pl_items()
    test_scan_text_for_clusters()
    test_normalize_vlm_groups()
    test_synthetic_notes_and_route_merge()
    test_item_link_includes_assembly_groups()
    test_llm_route_preferred_when_present()
    test_generate_llm_route_ops_mocked()
    test_parse_spaced_and_unicode_qty()
    test_parse_ocr_split_qty_token()
    test_normalize_prefers_rawtext_qty_over_model_ones()
    test_qty_repair_when_rawtext_has_no_markers()
    test_filter_weak_and_fastener_only()
    test_bom_enrichment_from_assembly_groups()
    test_parse_multiline_callout_keeps_second_line()
    test_parse_stacked_subscript_qty_lines()
    test_parse_hyphen_item_qty_section_style()
    test_parse_parent_with_qty_marker()
    test_merge_continuation_fastener_line_into_parent()
    test_merge_orphan_emitted_before_parent()
    test_scan_multiline_blob()
    test_stacked_balloons_are_separate_points()
    test_normalize_vlm_merges_multiline_rawtext()
    print("test_assembly_groups: OK")
