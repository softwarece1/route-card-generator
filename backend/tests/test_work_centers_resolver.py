"""Unit tests for WC resolver helpers (no DB)."""

from app.route_card.work_centers import (
    HEURISTIC_TAG_MAP,
    _hint_tags,
    _norm,
    _score_wc,
)


class _FakeWC:
    def __init__(
        self,
        *,
        code,
        name,
        capability_tags=None,
        match_keywords=None,
        sap_code="",
        sort_order=0,
        is_shared=False,
    ):
        self.code = code
        self.name = name
        self.capability_tags = capability_tags or []
        self.match_keywords = match_keywords or []
        self.sap_code = sap_code
        self.sort_order = sort_order
        self.is_shared = is_shared


def test_norm_strips_noise():
    assert _norm("PCB Assembly") == "pcbassembly"
    assert _norm("PCB-ASM") == "pcbasm"


def test_hint_tags_from_heuristic():
    assert "torque" in _hint_tags("Torque", "")
    assert "pcb" in _hint_tags("PCB Assembly", "solder fill holes")
    assert "bonding" in _hint_tags("Bonding", "PEEL OFF and PASTE")


def test_score_prefers_alias_and_keywords():
    wc = _FakeWC(
        code="PCB",
        name="PCB Assembly",
        capability_tags=["pcb", "solder"],
        match_keywords=["SOLDER", "DRILL"],
    )
    aliases = {"PCB Assembly": "PCB"}
    high = _score_wc(wc, "PCB Assembly", "Solder unused holes", aliases)
    other = _FakeWC(code="ASM", name="Assembly", capability_tags=["assembly"])
    low = _score_wc(other, "PCB Assembly", "Solder unused holes", aliases)
    assert high > low
    assert high >= 100  # alias hit


def test_heuristic_map_covers_generator_buckets():
    for name in ("Torque", "Bonding", "PCB Assembly", "Quality", "Special Assembly", "Assembly", "Cable Prep"):
        assert name in HEURISTIC_TAG_MAP
