"""Collapse noisy analyze warnings into few review flags."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.route_card.review import summarize_extra_warnings


def test_summarize_skips_info_and_collapses_balloon_spam():
    raw = [
        "BOM enriched with 6 balloon callout item(s) (56 total BOM rows).",
        "Stage C filter: dropped fastener-only group parent=5 children=[6,7]",
        "Drawing mind: found 5 balloon assembly groups from OCR.",
        "Drawing mind: balloon(s) for item(s) [53] not found in spatial OCR; using heuristics.",
        "Drawing mind: balloon(s) for item(s) [29] not found in spatial OCR; using heuristics.",
        "Drawing mind: could not resolve placement offsets for items [1, 2]; keeping source note.",
        "Drawing mind: could not resolve placement offsets for items [3]; keeping source note.",
        "Drawing mind: item balloon positions were ambiguous; using note order.",
        "OP 10: work centre unresolved — Ambiguous work centre match",
        "OP 20: work centre unresolved — Ambiguous work centre match",
        "Drawing mind: Stage D LLM route skipped (vision server not reachable).",
        "Wire List not provided – cable pin map / continuity checklist skipped.",
        "Drawing 1180 005 096 03 not uploaded as a session drawing.",
    ]
    out = summarize_extra_warnings(raw)
    msgs = [m for _, _, m in out]
    kinds = [k for k, _, _ in out]

    assert "balloon_ocr" in kinds
    assert "placement" in kinds
    assert "balloon_order" in kinds
    assert any("Stage D" in m for m in msgs)
    assert any("Wire List" in m for m in msgs)
    assert any("not uploaded" in m for m in msgs)

    joined = " ".join(msgs)
    assert "BOM enriched" not in joined
    assert "dropped fastener" not in joined
    assert "OP 10" not in joined
    assert "OP 20" not in joined
    # Collapsed, not one row per balloon miss
    assert len(out) <= 8
    assert len(out) < len(raw)


if __name__ == "__main__":
    test_summarize_skips_info_and_collapses_balloon_spam()
    print("test_review_warnings: OK")
