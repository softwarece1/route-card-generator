"""Local VLM drawing-mind tests (mocked Ollama).

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
    _merge_elaboration_onto_ocr,
    _normalize_placement,
    _normalize_step,
    _parse_vlm_json,
    _vlm_notes_usable,
)
from app.route_card.drawing_mind.ollama_client import OllamaError, _clean_assistant_content


def test_parse_vlm_json_plain_and_fenced():
    plain = '{"instructionBlockTitle": "NOTES", "steps": [], "warnings": []}'
    assert _parse_vlm_json(plain)["instructionBlockTitle"] == "NOTES"

    fenced = 'Here you go:\n```json\n{"steps": [{"step": "1", "text": "DRILL 3mm HOLES"}]}\n```\n'
    data = _parse_vlm_json(fenced)
    assert data["steps"][0]["text"].startswith("DRILL")


def test_clean_assistant_strips_thinking():
    raw = (
        "<think>I should return JSON only.</think>\n"
        '{"instructionBlockTitle": "NOTES", "steps": [], "warnings": []}'
    )
    cleaned = _clean_assistant_content(raw)
    assert "<think>" not in cleaned
    assert _parse_vlm_json(cleaned)["instructionBlockTitle"] == "NOTES"


def test_normalize_step_as_shown_forces_elaboration_flag():
    step = _normalize_step(
        {
            "step": "2",
            "text": "STICK ITEM 2 & 3 AS SHOWN ON DC OUT",
            "items": [2, 3],
            "needsVisualElaboration": False,
            "viewUsed": "side view",
            "elaboratedText": "Paste item 2 above item 3 on DC OUT face, 5 mm from edges.",
            "confidence": 0.8,
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
    assert "DC OUT" in step["elaboratedText"]
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
    assert "item 2" in composed.lower() or "Item 2" in composed
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


def test_merge_elaboration_onto_ocr():
    ocr = [
        {
            "stepNo": 1,
            "text": "STICK ITEM 2 & 3 AS SHOWN",
            "items": [2, 3],
            "elaboratedText": "",
        }
    ]
    vlm = [
        {
            "text": "STICK ITEM 2 & 3 AS SHOWN on the face",
            "elaboratedText": "Paste item 2 on top of item 3 on DC OUT.",
            "mindConfidence": 0.75,
            "needsVisualElaboration": True,
        }
    ]
    merged = _merge_elaboration_onto_ocr(ocr, vlm)
    assert "DC OUT" in (merged[0].get("elaboratedText") or "")
    assert merged[0].get("mindEngine") == "local_vlm"


def test_factory_returns_local_vlm():
    mind = get_drawing_mind("local_vlm")
    assert mind.engine == "local_vlm"
    assert type(mind).__name__ == "LocalVlmMind"


def test_local_vlm_falls_back_when_ollama_down():
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
    with patch(
        "app.route_card.drawing_mind.local_vlm.ollama_reachable", return_value=False
    ):
        result = mind.understand(
            pdf_bytes=b"%PDF-1.4 fake",
            ga_extraction=ga,
            spatial_pages=[],
            source_drawing_id=1,
            source_filename="demo.pdf",
        )
    assert result.engine == "local_vlm_fallback_cpu"
    assert any("Ollama not reachable" in w for w in result.warnings)
    assert result.notes
    assert result.notes[0]["text"].startswith("CLEAN")


def test_local_vlm_uses_vision_steps_when_usable():
    ga = {
        "notes": [{"sheet": 1, "stepNo": 1, "text": "weak ocr", "items": []}],
        "raw_text": "",
        "title_block": {},
    }
    fake_pages = [{"page": 1, "mime": "image/jpeg", "b64": "aaa", "width": 100, "height": 100}]
    vlm_payload = {
        "instructionBlockTitle": "ASSEMBLY INSTRUCTIONS",
        "steps": [
            {
                "step": "1",
                "text": "ASSEMBLE CONNECTOR TO HOUSING AS SHOWN",
                "items": [8],
                "needsVisualElaboration": True,
                "elaboratedText": "Assemble connector item 8 onto the housing boss as shown in Detail A.",
                "confidence": 0.82,
            }
        ],
        "warnings": [],
    }

    mind = LocalVlmMind()
    with (
        patch("app.route_card.drawing_mind.local_vlm.ollama_reachable", return_value=True),
        patch(
            "app.route_card.drawing_mind.local_vlm.render_pdf_pages",
            return_value=fake_pages,
        ),
        patch(
            "app.route_card.drawing_mind.local_vlm.chat_vision",
            return_value=json.dumps(vlm_payload),
        ),
    ):
        result = mind.understand(
            pdf_bytes=b"%PDF-1.4 fake",
            ga_extraction=ga,
            spatial_pages=[],
            source_filename="assy.pdf",
        )

    assert result.engine == "local_vlm"
    assert len(result.notes) == 1
    assert "CONNECTOR" in result.notes[0]["text"].upper()
    assert "Detail A" in (result.notes[0].get("elaboratedText") or "")
    assert result.notes[0].get("mindEngine") == "local_vlm"


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
    fake_pages = [{"page": 1, "mime": "image/jpeg", "b64": "bbb", "width": 80, "height": 80}]
    mind = LocalVlmMind()
    with (
        patch("app.route_card.drawing_mind.local_vlm.ollama_reachable", return_value=True),
        patch(
            "app.route_card.drawing_mind.local_vlm.render_pdf_pages",
            return_value=fake_pages,
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
    test_merge_elaboration_onto_ocr()
    test_factory_returns_local_vlm()
    test_local_vlm_falls_back_when_ollama_down()
    test_local_vlm_uses_vision_steps_when_usable()
    test_chat_vision_error_path_falls_back_partial()
    print("test_drawing_mind_local_vlm: OK")


if __name__ == "__main__":
    _run()
