"""Pluggable drawing mind — CPU spatial or local VLM (Ollama)."""

from __future__ import annotations

from app.route_card.drawing_mind.base import DrawingMind
from app.route_card.drawing_mind.cpu_spatial import CpuSpatialMind
from app.route_card.drawing_mind.merge import merge_ga_extractions, resolve_cross_refs
from app.route_card.drawing_mind.types import MindResult
from app.route_card.drawing_mind.view_refs import resolve_view_refs_for_notes


def get_drawing_mind(engine: str | None = None) -> DrawingMind:
    try:
        from app.config.settings import settings

        name = (engine or getattr(settings, "DRAWING_MIND_ENGINE", "cpu_spatial") or "cpu_spatial").lower()
    except Exception:
        name = (engine or "cpu_spatial").lower()

    if name in {"local_vlm", "vlm"}:
        from app.route_card.drawing_mind.local_vlm import LocalVlmMind

        return LocalVlmMind()
    return CpuSpatialMind()


__all__ = [
    "DrawingMind",
    "CpuSpatialMind",
    "MindResult",
    "get_drawing_mind",
    "merge_ga_extractions",
    "resolve_cross_refs",
    "resolve_view_refs_for_notes",
]
