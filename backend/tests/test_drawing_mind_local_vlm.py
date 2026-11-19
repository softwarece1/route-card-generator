"""Local VLM drawing-mind tests (mocked vLLM / OCR).

Run from backend/:
  python -m pytest tests/test_drawing_mind_local_vlm.py -q
  # or without pytest:
  python tests/test_drawing_mind_local_vlm.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.route_card.drawing_mind import get_drawing_mind
from app.route_card.drawing_mind.local_vlm import (
    LocalVlmMind,
    _compose_elaboration_from_placement,
    _is_weak_elaboration,
    _merge_cpu_enrichment_onto_vlm,
    _merge_elaboration_onto_ocr,
    _normalize_placement,
    _normalize_step,
    _parse_vlm_json,
    _stage_b_grounded_placements,
    _vlm_notes_usable,
    align_model_to_ocr,
    insight_is_safe,
    reconcile_ocr_with_model,
    split_ocr_note_lines,
    strip_leading_step_number,
    token_gate,
    tokens_are_ocr_confusable,
)
from app.route_card.drawing_mind.ollama_client import OllamaError, _clean_assistant_content
from app.route_card.route_generator import generate_route


OCR_BARE = (
    "FOR BARE BOARD VER 02, SHORT X53.2 TO P2.C19 & X54.2 TO P2.C16 "
    "USING COPPER ENAMELED WIRE P/N-485100709086"
)
BAD_MODEL = (
    "FOR BASE BOARD VER C2, SHORT X3.2 TO P2.C19 & X54.2 TO P2.C18 "
    "USING COPPER ENABLE WIRE P/N-4650150700088"
)


def test_parse_vlm_json_plain_and_fenced():
    plain = '{"blocks": [], "warnings": []}'
    assert _parse_vlm_json(plain)["blocks"] == []

    fenced = 'Here you go:\n```json\n{"blocks": [{"title": "NOTE I", "lines": ["1. DRILL 3mm HOLES"]}]}\n```\n'
    data = _parse_vlm_json(fenced)
    assert "DRILL" in data["blocks"][0]["lines"][0]


def test_clean_assistant_strips_thinking():
    raw = (
        "<think>I should return JSON only.</think>\n"
        '{"blocks": [], "warnings": []}'
    )
    cleaned = _clean_assistant_content(raw)
    assert "<think>" not in cleaned
    assert _parse_vlm_json(cleaned)["blocks"] == []


def test_normalize_step_as_shown_forces_elaboration_flag():
    step = _normalize_step(
        {
            "step": "2",
            "text": "STICK ITEM 2 & 3 AS SHOWN ON DC OUT",
            "items": [2, 3],
            "needsVisualElaboration": False,
            "viewUsed": "side view",
            "placement": [
                {
                    "itemNo": 2,
                    "surface": "DC OUT face (side)",
                    "offsets": [
                        {"from": "left", "value": 5, "unit": "mm"},
                        {"from": "top", "value": 5, "unit": "mm"},
                    ],
                    "confidence": 0.9,
                }
            ],
        },
        sheet=1,
        step_no=2,
    )
    assert step is not None
    assert step["needsVisualElaboration"] is True
    assert step["text"].startswith("STICK ITEM")
    assert step["elaboratedText"] == ""
    assert step["items"] == [2, 3]
    assert step["mindEngine"] == "local_vlm"
    assert step["placement"][0]["surface"].startswith("DC OUT")


def test_weak_elaboration_and_compose():
    assert _is_weak_elaboration(
        "Stick item 2 and item 3 as shown using suitable adhesive on the specified surface.",
        "STICK ITEM 2 & 3 AS SHOWN USING SUITABLE ADHESIVE.",
    )
    composed = _compose_elaboration_from_placement(
        "STICK ITEM 2 & 3 AS SHOWN USING SUITABLE ADHESIVE.",
        [
            {
                "itemNo": 2,
                "surface": "DC OUT face (side)",
                "offsets": [
                    {"from": "left", "value": 5.0, "unit": "mm"},
                    {"from": "top", "value": 5.0, "unit": "mm"},
                ],
            },
            {
                "itemNo": 3,
                "surface": "DC OUT face (side)",
                "offsets": [
                    {"from": "item", "value": 5.0, "unit": "mm", "relativeToItem": 2, "relation": "below"},
                ],
            },
        ],
        view_used="side view (confirmed by isometric)",
    )
    assert "DC OUT" in composed
    assert "5" in composed
    assert "stick" in composed.lower()
    assert "glue" in composed.lower() or "adhesive" in composed.lower()


def test_normalize_placement_drops_vague_surface():
    got = _normalize_placement(
        [{"itemNo": 2, "surface": "the indicated face", "offsets": [{"from": "left", "value": 5, "unit": "mm"}]}],
        source_page=1,
    )
    assert got[0]["surface"] == ""
    assert got[0]["offsets"][0]["value"] == 5


def test_vlm_notes_usable():
    assert not _vlm_notes_usable([])
    assert not _vlm_notes_usable([{"text": "ab"}])
    assert _vlm_notes_usable([{"text": "ASSEMBLE ITEM NO. 5 TO BRACKET"}])


def test_merge_insight_onto_ocr():
    ocr = [
        {
            "stepNo": 1,
            "text": "STICK ITEM 2 & 3 AS SHOWN",
            "items": [2, 3],
            "insight": "",
        }
    ]
    vlm = [
        {
            "text": "STICK ITEM 2 & 3 AS SHOWN on the face",
            "insight": "Links to ITEM 2 and ITEM 3 as written.",
            "mindConfidence": 0.75,
        }
    ]
    merged = _merge_elaboration_onto_ocr(ocr, vlm)
    assert "ITEM 2" in (merged[0].get("insight") or "")
    assert merged[0].get("mindEngine") == "local_vlm"


def test_token_gate_rejects_bare_board_corruption():
    ok, conflict = token_gate(OCR_BARE, BAD_MODEL)
    assert ok is False
    assert conflict is not None


def test_token_gate_rejects_dropped_r66():
    ocr = "DO NOT MOUNT ITEM R1, R14, R27, R40, R53, R66, TP1, TP2, TP3 & TP4"
    model = "DO NOT MOUNT ITEM R1, R14, R27, R40, R53, R86, TP1, TP2, TP3 & TP4"
    ok, conflict = token_gate(ocr, model)
    assert ok is False
    assert conflict in {"R66", "R86"}


def test_token_gate_rejects_dropped_b1_to_b8():
    ocr = "DRILL 3mm HOLES ON THE PCB FOR THE 4-40 UNC INSERTS OF THE TRANSFORMERS B1 TO B8."
    model = "DRILL 3mm HOLES ON THE PCB FOR THE 4-40 UNC INSERT FOR THE MOUNTING OF THE TRANSFORMERS"
    ok, conflict = token_gate(ocr, model)
    assert ok is False
    assert conflict is not None


def test_align_keeps_ocr_and_flags_review():
    ocr_lines = [{"title": "NOTE I", "label": "10", "text": OCR_BARE}]
    model_lines = [{"title": "NOTE I", "label": "10", "text": BAD_MODEL}]
    notes = align_model_to_ocr(ocr_lines, model_lines)
    assert len(notes) == 1
    # Invented BASE/C2/wrong P/N must not replace OCR.
    assert "BARE BOARD VER 02" in notes[0]["text"]
    assert "485100709086" in notes[0]["text"]
    assert "BASE BOARD" not in notes[0]["text"]
    assert notes[0]["needsReview"] is True
    assert notes[0].get("gateConflict")


def test_confusable_xi_x1():
    assert tokens_are_ocr_confusable("XI", "X1")
    text, needs, conflict = reconcile_ocr_with_model(
        "SHORT THE PIN NO 1 AND 2 OF Xi TO X30 USING ITEM NO-50.",
        "SHORT THE PIN NO 1 AND 2 OF X1 TO X30 USING ITEM NO-50.",
    )
    assert conflict is None
    assert needs is True
    assert "X1" in text
    assert "Xi" not in text and "XI" not in text.upper().replace("X1", "")


def test_confusable_5si_to_50():
    text, needs, conflict = reconcile_ocr_with_model(
        "SHORT PIN 2 AND 3 USING ITEM NO-5SI",
        "SHORT PIN 2 AND 3 USING ITEM NO-50",
    )
    assert conflict is None
    assert needs is True
    assert "50" in text
    assert "5SI" not in text.upper()


def test_confusable_tps_to_tp3():
    text, needs, conflict = reconcile_ocr_with_model(
        "DO NOT MOUNT ITEM R1, R14, R27, R40, R53, R66, TP1, TP2, TPS & TP4.",
        "DO NOT MOUNT ITEM R1, R14, R27, R40, R53, R66, TP1, TP2, TP3 & TP4.",
    )
    assert conflict is None
    assert needs is True
    assert "TP3" in text
    assert "TPS" not in text.upper()


def test_strip_leading_step_number():
    assert strip_leading_step_number("1. HELLO WORLD", "1") == "HELLO WORLD"
    assert strip_leading_step_number("HELLO WORLD", "1") == "HELLO WORLD"


def test_insight_rejects_new_part_number():
    note = "SHORT PIN 1 AND 2 OF X30 USING ITEM NO-50"
    assert insight_is_safe(note, "Uses ITEM 50 as written on the note.") is True
    assert insight_is_safe(note, "Use P/N-485100709086 copper wire.") is False


def test_split_ocr_note_lines_numbered():
    ocr = (
        "NOTE I\n"
        "1. THE FOLLOWING ARE LEAD-FREE COMPONENTS: U1-U12, FL1, FL2\n"
        "2. DRILL 3mm HOLES FOR TRANSFORMERS B1 TO B8.\n"
        "NOTE II\n"
        "1. P1, P2 & P3 CONNECTORS\n"
    )
    lines = split_ocr_note_lines(ocr)
    assert len(lines) >= 3
    assert "U1" in lines[0]["text"] or "FL1" in lines[0]["text"]
    assert any("B1" in (l["text"] or "") for l in lines)


def test_generate_route_uses_verbatim_not_insight():
    extraction = {
        "notes": [
            {
                "sheet": 1,
                "stepNo": 1,
                "text": OCR_BARE,
                "insight": "Mentions P/N already printed on the note.",
                "items": [],
                "elaboratedText": "Rewritten shop English that must NOT become the instruction.",
            }
        ],
        "bom_items": [],
        "title_block": {},
        "drawing_type": "assembly",
    }
    route = generate_route(extraction)
    ops = [o for o in (route.get("operations") or []) if o.get("opNo") == 10]
    assert len(ops) == 1
    instr = ops[0].get("instructionText") or ""
    # Verbatim note wins over free rewrite; sanitize may sentence-case for operators.
    assert "485100709086" in instr
    assert "BARE BOARD" in instr.upper()
    assert "Rewritten shop English" not in instr
    assert "Mentions P/N" in (ops[0].get("insight") or "")


def test_weight_guard_rejects_masking_tape():
    from app.route_card.extractor import parse_drawing_text

    text = (
        "TITLE AK630 DRVR U1\n"
        "NUMBER 112360195216AA\n"
        "MASKING TAPE (545501000341) BEFORE CONFORMAL COATING\n"
        "WEIGHT H MASKING TAPE (545501000341)\n"
    )
    parsed = parse_drawing_text(text, "112360195216AA - GA.pdf", 1)
    title = parsed.get("title_block") or {}
    assert not title.get("weight")


def test_weight_guard_accepts_numeric_mass():
    from app.route_card.extractor import parse_drawing_text

    text = "TITLE DEMO\nWEIGHT: 1.25 kg\nNUMBER 123\n"
    parsed = parse_drawing_text(text, "demo.pdf", 1)
    title = parsed.get("title_block") or {}
    assert "1.25" in (title.get("weight") or "")
    assert "kg" in (title.get("weight") or "").lower()


def test_factory_returns_local_vlm():
    mind = get_drawing_mind("local_vlm")
    assert mind.engine == "local_vlm"
    assert type(mind).__name__ == "LocalVlmMind"


def test_local_vlm_falls_back_when_server_down():
    ga = {
        "notes": [
            {
                "sheet": 1,
                "stepNo": 1,
                "text": "CLEAN THE HATCHED SURFACES.",
                "items": [],
            }
        ],
        "raw_text": "CLEAN THE HATCHED SURFACES.",
        "title_block": {"unit": "mm"},
    }
    mind = LocalVlmMind()
    with (
        patch(
            "app.route_card.drawing_mind.local_vlm.vlm_status",
            return_value=(False, "down"),
        ),
        patch(
            "app.route_card.drawing_mind.local_vlm.ollama_reachable", return_value=False
        ),
    ):
        result = mind.understand(
            pdf_bytes=b"%PDF-1.4 fake",
            ga_extraction=ga,
            spatial_pages=[],
            source_drawing_id=1,
            source_filename="demo.pdf",
        )
    assert result.engine == "local_vlm_fallback_cpu"
    assert any("vision server not reachable" in w for w in result.warnings)
    assert result.notes
    assert result.notes[0]["text"].startswith("CLEAN")


def test_local_vlm_uses_verbatim_ocr_when_usable():
    ga = {
        "notes": [{"sheet": 1, "stepNo": 1, "text": "weak ocr", "items": []}],
        "raw_text": "",
        "title_block": {},
    }
    fake_bands = [
        {
            "page": 1,
            "mime": "image/jpeg",
            "b64": "aaa",
            "width": 100,
            "height": 100,
            "raw": b"jpeg",
        }
    ]
    ocr_blob = (
        "NOTE I\n"
        "1. DRILL 3mm HOLES ON THE PCB FOR THE 4-40 UNC INSERTS OF THE TRANSFORMERS B1 TO B8.\n"
    )
    vlm_payload = {
        "blocks": [
            {
                "title": "NOTE I",
                "lines": [
                    "1. DRILL 3mm HOLES ON THE PCB FOR THE 4-40 UNC INSERTS OF THE TRANSFORMERS B1 TO B8."
                ],
            }
        ],
        "warnings": [],
    }

    mind = LocalVlmMind()
    with (
        patch(
            "app.route_card.drawing_mind.local_vlm.vlm_status",
            return_value=(True, None),
        ),
        patch("app.route_card.drawing_mind.local_vlm.ollama_reachable", return_value=True),
        patch(
            "app.route_card.drawing_mind.local_vlm.render_note_bands",
            return_value=fake_bands,
        ),
        patch(
            "app.route_card.drawing_mind.local_vlm.ocr_image_raw",
            return_value=ocr_blob,
        ),
        patch(
            "app.route_card.drawing_mind.local_vlm.chat_vision",
            return_value=json.dumps(vlm_payload),
        ),
        patch(
            "app.route_card.drawing_mind.local_vlm.chat_text",
            return_value=json.dumps({"text": "", "insight": "", "warnings": []}),
        ),
        patch(
            "app.route_card.drawing_mind.local_vlm.render_pdf_pages",
            return_value=[],
        ),
    ):
        result = mind.understand(
            pdf_bytes=b"%PDF-1.4 fake",
            ga_extraction=ga,
            spatial_pages=[],
            source_filename="assy.pdf",
        )

    assert result.engine == "local_vlm"
    assert len(result.notes) >= 1
    assert "B1" in result.notes[0]["text"].upper()
    # No PL extras → elaboratedText stays empty (verbatim only)
    assert not (result.notes[0].get("elaboratedText") or "").strip()
    assert result.notes[0].get("mindEngine") == "local_vlm"
    assert result.notes[0].get("needsReview") is False


def test_merge_cpu_enrichment_preserved_on_vlm_success():
    vlm = [
        {
            "text": "STICK ITEM 2 & 3 AS SHOWN USING SUITABLE ADHESIVE.",
            "elaboratedText": "",
            "placement": [],
            "viewRefs": [],
            "items": [2, 3],
        }
    ]
    cpu = [
        {
            "text": "STICK ITEM 2 & 3 AS SHOWN USING SUITABLE ADHESIVE.",
            "elaboratedText": "Stick Item 2 on the DC OUT side. (From drawing: STICK ITEM 2 & 3 AS SHOWN USING SUITABLE ADHESIVE.)",
            "placement": [{"itemNo": 2, "surface": "DC OUT", "offsets": []}],
            "viewRefs": [{"label": "SHEET 1"}],
            "elaborated": True,
            "items": [2, 3],
        }
    ]
    merged = _merge_cpu_enrichment_onto_vlm(vlm, cpu)
    assert "DC OUT" in (merged[0].get("elaboratedText") or "")
    assert merged[0].get("placement")
    assert merged[0].get("viewRefs")
    assert merged[0].get("elaborated") is True


def test_stage_b_rejects_invented_item_numbers():
    raw = {
        "placements": [
            {
                "itemNo": 99,
                "surface": "DC OUT",
                "offsets": [{"from": "top", "value": 5, "unit": "mm"}],
                "confidence": 0.9,
            },
            {
                "itemNo": 2,
                "surface": "DC OUT",
                "offsets": [{"from": "left", "value": 5, "unit": "mm"}],
                "confidence": 0.8,
            },
        ]
    }
    got = _stage_b_grounded_placements(raw, allowed_items={2, 3}, note_text="STICK ITEM 2")
    assert len(got) == 1
    assert got[0]["itemNo"] == 2


def test_chat_vision_error_path_falls_back_partial():
    ga = {
        "notes": [
            {
                "sheet": 1,
                "stepNo": 1,
                "text": "TORQUE ALL FASTENERS AS PER PS982",
                "items": [],
            }
        ],
        "raw_text": "TORQUE ALL FASTENERS AS PER PS982",
        "title_block": {},
    }
    fake_bands = [
        {
            "page": 1,
            "mime": "image/jpeg",
            "b64": "bbb",
            "width": 80,
            "height": 80,
            "raw": b"jpeg",
        }
    ]
    mind = LocalVlmMind()
    with (
        patch(
            "app.route_card.drawing_mind.local_vlm.vlm_status",
            return_value=(True, None),
        ),
        patch("app.route_card.drawing_mind.local_vlm.ollama_reachable", return_value=True),
        patch(
            "app.route_card.drawing_mind.local_vlm.render_note_bands",
            return_value=fake_bands,
        ),
        patch(
            "app.route_card.drawing_mind.local_vlm.ocr_image_raw",
            return_value="",
        ),
        patch(
            "app.route_card.drawing_mind.local_vlm.chat_vision",
            side_effect=OllamaError("boom"),
        ),
    ):
        result = mind.understand(
            pdf_bytes=b"%PDF",
            ga_extraction=ga,
            spatial_pages=[],
        )
    assert result.engine == "local_vlm_fallback_cpu"
    assert any("VLM page 1" in w for w in result.warnings)
    assert result.notes[0]["text"].startswith("TORQUE")


def _run():
    test_parse_vlm_json_plain_and_fenced()
    test_clean_assistant_strips_thinking()
    test_normalize_step_as_shown_forces_elaboration_flag()
    test_weak_elaboration_and_compose()
    test_normalize_placement_drops_vague_surface()
    test_vlm_notes_usable()
    test_merge_insight_onto_ocr()
    test_token_gate_rejects_bare_board_corruption()
    test_token_gate_rejects_dropped_r66()
    test_token_gate_rejects_dropped_b1_to_b8()
    test_align_keeps_ocr_and_flags_review()
    test_confusable_xi_x1()
    test_confusable_5si_to_50()
    test_confusable_tps_to_tp3()
    test_strip_leading_step_number()
    test_insight_rejects_new_part_number()
    test_split_ocr_note_lines_numbered()
    test_generate_route_uses_verbatim_not_insight()
    test_weight_guard_rejects_masking_tape()
    test_weight_guard_accepts_numeric_mass()
    test_factory_returns_local_vlm()
    test_local_vlm_falls_back_when_server_down()
    test_local_vlm_uses_verbatim_ocr_when_usable()
    test_merge_cpu_enrichment_preserved_on_vlm_success()
    test_stage_b_rejects_invented_item_numbers()
    test_chat_vision_error_path_falls_back_partial()
    print("test_drawing_mind_local_vlm: OK")


if __name__ == "__main__":
    _run()
