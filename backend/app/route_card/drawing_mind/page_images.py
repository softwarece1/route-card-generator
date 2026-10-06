"""Render PDF pages to base64 images for local VLM (Ollama) calls."""

from __future__ import annotations

import base64
import io
from typing import Any


def render_pdf_pages(
    pdf_bytes: bytes,
    *,
    dpi: int = 160,
    max_pages: int = 6,
    max_edge: int = 1600,
    image_format: str = "JPEG",
    jpeg_quality: int = 85,
    page_indexes: list[int] | None = None,
    cancel_event=None,
) -> list[dict[str, Any]]:
    """
    Render PDF pages to base64-encoded images.

    ``page_indexes`` is 1-based page numbers. When set, only those pages are
    rendered (still capped by ``max_pages``). Otherwise the first ``max_pages``.

    Returns a list of dicts:
      { "page": 1-based int, "mime": "image/jpeg", "b64": str, "width": int, "height": int }
    """
    import fitz
    from PIL import Image

    from app.route_card.analyze_jobs import check_cancelled

    dpi = max(72, min(int(dpi or 160), 300))
    max_pages = max(1, int(max_pages or 6))
    max_edge = max(512, int(max_edge or 1600))
    fmt = (image_format or "JPEG").upper()
    if fmt not in {"JPEG", "JPG", "PNG"}:
        fmt = "JPEG"
    if fmt == "JPG":
        fmt = "JPEG"

    zoom = dpi / 72.0
    matrix = fitz.Matrix(zoom, zoom)
    out: list[dict[str, Any]] = []

    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        if page_indexes:
            idxs = []
            for p in page_indexes:
                try:
                    pi = int(p)
                except (TypeError, ValueError):
                    continue
                if 1 <= pi <= doc.page_count:
                    idxs.append(pi - 1)
            # preserve order, unique, cap
            seen: set[int] = set()
            ordered: list[int] = []
            for i in idxs:
                if i not in seen:
                    seen.add(i)
                    ordered.append(i)
                if len(ordered) >= max_pages:
                    break
            page_iter = ordered
        else:
            page_iter = list(range(min(doc.page_count, max_pages)))
        for i in page_iter:
            check_cancelled(cancel_event)
            page = doc.load_page(i)
            pix = page.get_pixmap(matrix=matrix, alpha=False)
            img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            w, h = img.size
            longest = max(w, h)
            if longest > max_edge:
                scale = max_edge / float(longest)
                img = img.resize(
                    (max(1, int(w * scale)), max(1, int(h * scale))),
                    Image.Resampling.LANCZOS,
                )
            buf = io.BytesIO()
            save_kwargs: dict[str, Any] = {}
            if fmt == "JPEG":
                save_kwargs["quality"] = max(40, min(int(jpeg_quality or 85), 95))
                save_kwargs["optimize"] = True
            img.save(buf, format=fmt, **save_kwargs)
            raw = buf.getvalue()
            mime = "image/jpeg" if fmt == "JPEG" else "image/png"
            out.append(
                {
                    "page": i + 1,
                    "mime": mime,
                    "b64": base64.b64encode(raw).decode("ascii"),
                    "width": img.size[0],
                    "height": img.size[1],
                }
            )
    finally:
        doc.close()

    return out
