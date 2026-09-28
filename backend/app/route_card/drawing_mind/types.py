"""Shared result schema for CPU spatial mind and future local VLM."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class PlacementFact:
    item_no: int
    surface: str = ""
    offsets: list[dict[str, Any]] = field(default_factory=list)
    # offsets: [{ "from": "top"|"left"|"bottom"|"right"|"item", "value": 5.0, "unit": "mm", "relativeToItem": 2 }]
    confidence: float = 0.0
    source_page: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "itemNo": self.item_no,
            "surface": self.surface,
            "offsets": self.offsets,
            "confidence": round(self.confidence, 3),
            "sourcePage": self.source_page,
        }


@dataclass
class PcbLinkFact:
    connector: str
    pl_item_no: int | None = None
    pl_description: str = ""
    wl_wire_count: int = 0
    confidence: float = 0.0
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "connector": self.connector,
            "plItemNo": self.pl_item_no,
            "plDescription": self.pl_description,
            "wlWireCount": self.wl_wire_count,
            "confidence": round(self.confidence, 3),
            "note": self.note,
        }


@dataclass
class CrossRefFact:
    drawing_number: str
    status: str  # resolved | missing
    source_drawing_id: int | None = None
    matched_drawing_id: int | None = None
    matched_filename: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "drawingNumber": self.drawing_number,
            "status": self.status,
            "sourceDrawingId": self.source_drawing_id,
            "matchedDrawingId": self.matched_drawing_id,
            "matchedFilename": self.matched_filename,
        }


@dataclass
class MindResult:
    engine: str
    notes: list[dict[str, Any]] = field(default_factory=list)
    placements: list[PlacementFact] = field(default_factory=list)
    pcb_links: list[PcbLinkFact] = field(default_factory=list)
    cross_refs: list[CrossRefFact] = field(default_factory=list)
    view_refs: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "engine": self.engine,
            "notes": self.notes,
            "placements": [p.to_dict() for p in self.placements],
            "pcbLinks": [p.to_dict() for p in self.pcb_links],
            "crossRefs": [c.to_dict() for c in self.cross_refs],
            "viewRefs": list(self.view_refs),
            "warnings": list(dict.fromkeys(self.warnings)),
        }
