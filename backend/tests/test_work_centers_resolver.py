"""Unit tests for WC resolver helpers (no DB)."""

from app.route_card.work_centers import (
    BUILTIN_WC_ALIASES,
    HEURISTIC_TAG_MAP,
    LINK_LINKED,
    LINK_OVERRIDE,
    LINK_UNRESOLVED,
    SEED_CODE_FALLBACKS,
    _derived_keywords,
    _effective_aliases,
    _hint_tags,
    _norm,
    _score_wc,
    merge_resolved_preserving_overrides,
    remap_heuristic_to_catalog,
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


def test_hint_tags_synonyms_and_remapped_code():
    tags = _hint_tags("", "Apply CONFORMAL coating; check SHORT / JUMPER; RoHS")
    assert "pcb" in tags
    assert "pcb" in _hint_tags("PCB", "inspect board")  # after alias remap


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


def test_builtin_pcb_assembly_beats_bare_asm():
    """Generator heuristic + solder note prefers plant PCB over generic ASM."""
    pcb = _FakeWC(
        code="PCB",
        name="PCB Assembly Cell",
        capability_tags=["pcb", "solder"],
        match_keywords=[],
        is_shared=False,
    )
    asm = _FakeWC(
        code="ASM",
        name="Assembly",
        capability_tags=["assembly"],
        match_keywords=[],
        is_shared=False,
    )
    aliases = _effective_aliases({})
    instr = "Solder unused holes per RoHS; drill vias"
    # Mimic resolve remapping of heuristic label → seed code
    heuristic = aliases.get("PCB Assembly", "PCB Assembly")
    high = _score_wc(pcb, heuristic, instr, aliases)
    low = _score_wc(asm, heuristic, instr, aliases)
    assert high > low
    assert "PCB Assembly" in BUILTIN_WC_ALIASES


def test_derived_keywords_when_match_keywords_empty():
    wc = _FakeWC(
        code="1100-PCB-01",
        name="PCB Soldering Bay",
        sap_code="PCB_SOLDER",
        match_keywords=[],
    )
    kws = _derived_keywords(wc)
    assert "PCB" in kws
    assert "SOLDERING" in kws or "SOLDER" in kws or "PCB_SOLDER" in kws or "SOLDER" in " ".join(kws)
    score = _score_wc(wc, "PCB Assembly", "PCB soldering of transformer pads", {})
    bare = _FakeWC(code="ASM", name="Assembly", match_keywords=[], capability_tags=["assembly"])
    assert score > _score_wc(bare, "PCB Assembly", "PCB soldering of transformer pads", {})


def test_close_scores_prefer_non_shared_plant_wc():
    plant = _FakeWC(
        code="PCB",
        name="PCB",
        capability_tags=["pcb"],
        match_keywords=["SOLDER"],
        is_shared=False,
        sort_order=10,
    )
    shared = _FakeWC(
        code="PCB",
        name="PCB",
        capability_tags=["pcb"],
        match_keywords=["SOLDER"],
        is_shared=True,
        sort_order=1,
    )
    aliases = {}
    instr = "Solder unused holes"
    plant_score = _score_wc(plant, "PCB", instr, aliases)
    shared_score = _score_wc(shared, "PCB", instr, aliases)
    assert plant_score > shared_score
    assert plant_score - shared_score >= 2.0


def test_merge_resolved_preserves_manual_override():
    existing = [
        {
            "opNo": 10,
            "operation": "Prep",
            "workCentre": "OLD",
            "workCentreId": 1,
            "linkStatus": LINK_OVERRIDE,
            "machine": "Hand",
            "machineId": 9,
        },
        {
            "opNo": 20,
            "operation": "Solder",
            "workCentre": "PCB Assembly",
            "workCentreId": None,
            "linkStatus": LINK_UNRESOLVED,
        },
    ]
    resolved = [
        {
            "opNo": 10,
            "workCentre": "SHOULD_NOT_APPLY",
            "workCentreId": 99,
            "linkStatus": LINK_LINKED,
            "machine": "X",
            "machineId": 8,
            "linkReason": "Matched SHOULD_NOT_APPLY",
        },
        {
            "opNo": 20,
            "workCentre": "PCB",
            "workCentreName": "PCB Assembly",
            "workCentreId": 42,
            "linkStatus": LINK_LINKED,
            "linkConfidence": 0.9,
            "linkReason": "Matched PCB (PCB Assembly)",
            "machine": "",
            "machineId": None,
        },
    ]
    merged, counts = merge_resolved_preserving_overrides(existing, resolved)
    assert counts["skippedOverrides"] == 1
    assert counts["linked"] == 1
    assert merged[0]["workCentre"] == "OLD"
    assert merged[0]["workCentreId"] == 1
    assert merged[0]["linkStatus"] == LINK_OVERRIDE
    assert merged[1]["workCentre"] == "PCB"
    assert merged[1]["workCentreId"] == 42
    assert merged[1]["linkStatus"] == LINK_LINKED


def test_heuristic_map_covers_generator_buckets():
    for name in ("Torque", "Bonding", "PCB Assembly", "Quality", "Special Assembly", "Assembly", "Cable Prep"):
        assert name in HEURISTIC_TAG_MAP
        assert name in BUILTIN_WC_ALIASES


def test_remap_seed_asm_to_plant_assy():
    """Bootstrap path (no plant scoring) may still use seed fallbacks."""
    catalog = [
        _FakeWC(code="ASSY", name="ASSY", capability_tags=["assembly"]),
        _FakeWC(code="AIPH", name="PHYSICAL INSPECTION", capability_tags=["inspect"]),
        _FakeWC(code="QTEST", name="TESTING / MS", capability_tags=["inspect"]),
    ]
    code, reason = remap_heuristic_to_catalog("ASM", catalog, use_seed_fallbacks=True)
    assert code == "ASSY"
    assert "ASSY" in reason
    q, _ = remap_heuristic_to_catalog("QUALITY", catalog, use_seed_fallbacks=True)
    assert q == "AIPH"
    # Already in catalog — unchanged
    same, empty = remap_heuristic_to_catalog("ASSY", catalog)
    assert same == "ASSY" and empty == ""


def test_remap_without_seed_fallbacks_does_not_invent_assy():
    """Plant-catalog mode: no hard-coded ASM→ASSY / QUALITY→AIPH."""
    catalog = [
        _FakeWC(code="ASSY", name="ASSY", capability_tags=["assembly"]),
        _FakeWC(code="AIPH", name="PHYSICAL INSPECTION", capability_tags=["inspect"]),
    ]
    code, reason = remap_heuristic_to_catalog("ASM", catalog, use_seed_fallbacks=False)
    assert code == "ASM"
    assert reason == ""
    q, qreason = remap_heuristic_to_catalog("QUALITY", catalog, use_seed_fallbacks=False)
    assert q == "QUALITY"
    assert qreason == ""


def test_score_prefers_wc_name_semantics_over_seed_codes():
    """Instruction verbs match plant WC names (description), not seed ASSY/BOND."""
    inspect = _FakeWC(
        code="AIPH",
        name="PHYSICAL INSPECTION",
        match_keywords=["AIPH"],
        capability_tags=[],
        is_shared=False,
    )
    wiring = _FakeWC(
        code="AMW1",
        name="MECH MTG & WIRING OF SUB ASSY",
        match_keywords=["AMW1"],
        capability_tags=[],
        is_shared=False,
    )
    solder = _FakeWC(
        code="ASOL",
        name="SOLDERING",
        match_keywords=["ASOL"],
        capability_tags=[],
        is_shared=False,
    )
    aliases = _effective_aliases({}, include_builtins=False)
    insp_score = _score_wc(
        inspect, "", "Verify dimensions and visual inspect warpage", aliases, include_builtins=False
    )
    wire_score = _score_wc(
        wiring, "", "Crimp and wire harness to sub assembly", aliases, include_builtins=False
    )
    sol_score = _score_wc(
        solder, "", "Solder transformer pads per RoHS", aliases, include_builtins=False
    )
    assert insp_score > _score_wc(
        wiring, "", "Verify dimensions and visual inspect warpage", aliases, include_builtins=False
    )
    assert wire_score > _score_wc(
        inspect, "", "Crimp and wire harness to sub assembly", aliases, include_builtins=False
    )
    assert sol_score > _score_wc(
        inspect, "", "Solder transformer pads per RoHS", aliases, include_builtins=False
    )


def test_derived_keywords_include_name_even_when_match_keywords_set():
    wc = _FakeWC(code="AIPH", name="PHYSICAL INSPECTION", match_keywords=["AIPH"])
    kws = _derived_keywords(wc)
    assert "AIPH" in kws
    assert "PHYSICAL" in kws
    assert "INSPECTION" in kws


def test_seed_fallbacks_cover_builtin_codes():
    for seed in BUILTIN_WC_ALIASES.values():
        assert seed in SEED_CODE_FALLBACKS or seed in {"PCB"}  # PCB may exist as real code
    assert "ASSY" in SEED_CODE_FALLBACKS["ASM"]
    assert "AIPH" in SEED_CODE_FALLBACKS["QUALITY"]
