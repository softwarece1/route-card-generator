"""DrawingMind provider interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from app.route_card.drawing_mind.types import MindResult


class DrawingMind(ABC):
    """Elaborate GA notes using spatial OCR (CPU) or a future local VLM."""

    engine: str = "base"

    @abstractmethod
    def understand(
        self,
        *,
        pdf_bytes: bytes | None,
        ga_extraction: dict[str, Any],
        spatial_pages: list[dict[str, Any]] | None = None,
        parts_list: dict[str, Any] | None = None,
        wire_list: dict[str, Any] | None = None,
        source_drawing_id: int | None = None,
        source_filename: str = "",
    ) -> MindResult:
        ...
