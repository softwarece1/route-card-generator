"""Render PDF pages / note bands to base64 images for local VLM calls."""

from __future__ import annotations

import base64
import io
import re
from typing import Any


_NOTE_HEADING = re.compile(r"\bNOTES?\b", re.I)


def _encode_image(
    img: Any,
    *,
    image_format: str = "JPEG",
    jpeg_quality: int = 90,
    max_edge: int | None = None,
) -> dict[str, Any]:
    from PIL import Image

    if max_edge is not None:
        w, h = img.size
        longest = max(w, h)
        if longest > max_edge:
            scale = max_edge / float(longest)
            img = img.resize(
                (max(1, int(w * scale)), max(1, int(h * scale))),
                Image.Resampling.LANCZOS,
            )
    fmt = (image_format or "JPEG").upper()
    if fmt not in {"JPEG", "JPG", "PNG"}:
        fmt = "JPEG"
    if fmt == "JPG":
        fmt = "JPEG"
    buf = io.BytesIO()
    save_kwargs: dict[str, Any] = {}
    if fmt == "JPEG":
        save_kwargs["quality"] = max(40, min(int(jpeg_quality or 90), 95))
        save_kwargs["optimize"] = True
    img.save(buf, format=fmt, **save_kwargs)
    raw = buf.getvalue()
    mime = "image/jpeg" if fmt == "JPEG" else "image/png"
    return {
        "mime": mime,
        "b64": base64.b64encode(raw).decode("ascii"),
        "width": img.size[0],
        "height": img.size[1],
        "raw": raw,
    }


def _note_clip_rects(page: Any) -> list[Any]:
    """
    Return one or more fitz.Rects covering NOTE columns.

    Text-layer NOTE headings → expand around those boxes.
    Outline-only sheets (common for BEL GA) → two bottom columns left of the
    title block so NOTE I and NOTE II are not OCR'd as one interleaved band.
    """
    import fitz

    page_rect = page.rect
    note_rects: list[Any] = []
    try:
        for block in page.get_text("dict").get("blocks") or []:
            if block.get("type") != 0:
                continue
            for line in block.get("lines") or []:
                for span in line.get("spans") or []:
                    txt = str(span.get("text") or "")
                    if _NOTE_HEADING.search(txt):
                        note_rects.append(fitz.Rect(span.get("bbox")))
    except Exception:
        note_rects = []

    if note_rects:
        # Cluster headings by x so side-by-side NOTE I / NOTE II stay separate.
        note_rects.sort(key=lambda r: r.x0)
        clusters: list[list[Any]] = []
        for r in note_rects:
            if not clusters or abs(r.x0 - clusters[-1][0].x0) > page_rect.width * 0.12:
                clusters.append([r])
            else:
                clusters[-1].append(r)
        clips: list[Any] = []
        for group in clusters:
            union = group[0]
            for r in group[1:]:
                union |= r
            pad_x = page_rect.width * 0.015
            pad_y = page_rect.height * 0.015
            # Column width: from heading to next heading or 32% of page.
            x1 = min(page_rect.x1, union.x0 + page_rect.width * 0.34)
            clip = fitz.Rect(
                max(page_rect.x0, union.x0 - pad_x),
                max(page_rect.y0, union.y0 - pad_y),
                x1,
                min(page_rect.y1, page_rect.y0 + page_rect.height * 0.98),
            )
            clips.append(clip)
        return clips

    # Outline-only: bottom band split into left (NOTE I) and mid (NOTE II).
    y0 = page_rect.y0 + page_rect.height * 0.52
    y1 = page_rect.y1 - page_rect.height * 0.02
    x_margin = page_rect.width * 0.02
    # Title block typically occupies the right ~38%.
    notes_right = page_rect.x0 + page_rect.width * 0.62
    # NOTE I is the wider left column; NOTE II sits just left of the title block.
    mid = page_rect.x0 + page_rect.width * 0.36
    return [
        fitz.Rect(page_rect.x0 + x_margin, y0, mid, y1),
        fitz.Rect(mid - page_rect.width * 0.01, y0, notes_right, y1),
    ]


def render_note_bands(
    pdf_bytes: bytes,
    *,
    dpi: int = 300,
    max_pages: int = 6,
    max_edge: int = 2400,
    image_format: str = "JPEG",
    jpeg_quality: int = 92,
    page_indexes: list[int] | None = None,
    cancel_event=None,
) -> list[dict[str, Any]]:
    """
    Render high-resolution crops of the NOTE / instruction band per page.

    Returns dicts:
      {
        "page": 1-based int,
        "mime", "b64", "width", "height",
        "raw": JPEG/PNG bytes for OCR,
        "clip": [x0,y0,x1,y1] in page points,
      }
    """
    import fitz
    from PIL import Image

    from app.route_card.analyze_jobs import check_cancelled

    dpi = max(150, min(int(dpi or 300), 400))
    max_pages = max(1, int(max_pages or 6))
    max_edge = max(800, int(max_edge or 2400))
    zoom = dpi / 72.0
    matrix = fitz.Matrix(zoom, zoom)
    out: list[dict[str, Any]] = []

    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        if page_indexes:
            idxs: list[int] = []
            seen: set[int] = set()
            for p in page_indexes:
                try:
                    pi = int(p)
                except (TypeError, ValueError):
                    continue
                if 1 <= pi <= doc.page_count and (pi - 1) not in seen:
                    seen.add(pi - 1)
                    idxs.append(pi - 1)
                if len(idxs) >= max_pages:
                    break
            page_iter = idxs
        else:
            page_iter = list(range(min(doc.page_count, max_pages)))

        for i in page_iter:
            check_cancelled(cancel_event)
            page = doc.load_page(i)
            for col_idx, clip in enumerate(_note_clip_rects(page)):
                check_cancelled(cancel_event)
                pix = page.get_pixmap(matrix=matrix, clip=clip, alpha=False)
                img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
                encoded = _encode_image(
                    img,
                    image_format=image_format,
                    jpeg_quality=jpeg_quality,
                    max_edge=max_edge,
                )
                out.append(
                    {
                        "page": i + 1,
                        "column": col_idx,
                        "mime": encoded["mime"],
                        "b64": encoded["b64"],
                        "width": encoded["width"],
                        "height": encoded["height"],
                        "raw": encoded["raw"],
                        "clip": [clip.x0, clip.y0, clip.x1, clip.y1],
                    }
                )
    finally:
        doc.close()

    return out


def _preprocess_for_ocr(img: Any) -> Any:
    """Upscale + contrast for dense CAD note lettering."""
    from PIL import Image, ImageEnhance, ImageFilter, ImageOps

    if img.mode != "L":
        img = ImageOps.grayscale(img)
    w, h = img.size
    # Slight upscale helps Tesseract on thin vector strokes.
    if max(w, h) < 2200:
        scale = 1.5
        img = img.resize(
            (max(1, int(w * scale)), max(1, int(h * scale))),
            Image.Resampling.LANCZOS,
        )
    img = ImageOps.autocontrast(img, cutoff=1)
    img = ImageEnhance.Sharpness(img).enhance(1.4)
    img = img.filter(ImageFilter.MedianFilter(size=3))
    return img


def ocr_image_raw(raw: bytes) -> str:
    """OCR a rendered note-band image. Returns plain text (may be empty)."""
    if not raw:
        return ""
    try:
        from app.route_card.pdf_ingest import _configure_tesseract
    except Exception:
        return ""
    ok, _warn = _configure_tesseract()
    if not ok:
        return ""
    try:
        import pytesseract
        from PIL import Image
    except ImportError:
        return ""
    try:
        img = Image.open(io.BytesIO(raw))
        img = _preprocess_for_ocr(img)
        # PSM 6 = assume a single uniform block of text (note columns).
        text = pytesseract.image_to_string(img, config="--psm 6") or ""
        return text.strip()
    except Exception:
        return ""


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
            encoded = _encode_image(
                img,
                image_format=image_format,
                jpeg_quality=jpeg_quality,
                max_edge=max_edge,
            )
            out.append(
                {
                    "page": i + 1,
                    "mime": encoded["mime"],
                    "b64": encoded["b64"],
                    "width": encoded["width"],
                    "height": encoded["height"],
                }
            )
    finally:
        doc.close()

    return out


def render_callout_zones(
    pdf_bytes: bytes,
    page_no: int,
    *,
    dpi: int = 280,
    n_cols: int = 12,
    n_rows: int = 4,
    col_bands: tuple[tuple[int, int], ...] = ((1, 4), (5, 8), (9, 12)),
    margin_frac: float = 0.02,
    min_ink: float = 0.004,
    jpeg_quality: int = 92,
    max_edge: int = 1600,
    cancel_event=None,
) -> list[dict[str, Any]]:
    """Crop one GA sheet into reading-order zones.

    Columns are numbered 1…n from the left. Rows are lettered A, B, C…
    from the top. Each tile is one row band × one column band, so a vision
    model sees subscript digits (x40, x80) large enough to read.
    Nearly blank tiles are omitted.
    """
    import fitz
    from PIL import Image

    from app.route_card.analyze_jobs import check_cancelled

    dpi = max(120, min(int(dpi or 280), 400))
    n_cols = max(1, int(n_cols or 12))
    n_rows = max(1, int(n_rows or 4))
    zoom = dpi / 72.0
    row_letters = [chr(ord("A") + i) for i in range(min(n_rows, 26))]
    out: list[dict[str, Any]] = []

    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        idx = int(page_no) - 1
        if idx < 0 or idx >= doc.page_count:
            return []
        check_cancelled(cancel_event)
        page = doc.load_page(idx)
        rect = page.rect
        mx = rect.width * float(margin_frac or 0)
        my = rect.height * float(margin_frac or 0)
        frame = fitz.Rect(rect.x0 + mx, rect.y0 + my, rect.x1 - mx, rect.y1 - my)
        col_w = frame.width / float(n_cols)
        row_h = frame.height / float(len(row_letters))
        for r_i, row in enumerate(row_letters):
            for band in col_bands:
                check_cancelled(cancel_event)
                try:
                    c0 = max(1, int(band[0]))
                    c1 = min(n_cols, int(band[1]))
                except (TypeError, ValueError, IndexError):
                    continue
                if c1 < c0:
                    continue
                clip = fitz.Rect(
                    frame.x0 + (c0 - 1) * col_w,
                    frame.y0 + r_i * row_h,
                    frame.x0 + c1 * col_w,
                    frame.y0 + (r_i + 1) * row_h,
                )
                pix = page.get_pixmap(
                    matrix=fitz.Matrix(zoom, zoom), clip=clip, alpha=False
                )
                if pix.width < 8 or pix.height < 8:
                    continue
                if _ink_fraction(pix.samples, pix.width, pix.height, pix.n) < float(
                    min_ink
                ):
                    continue
                img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
                encoded = _encode_image(
                    img,
                    image_format="JPEG",
                    jpeg_quality=jpeg_quality,
                    max_edge=max_edge,
                )
                out.append(
                    {
                        "page": int(page_no),
                        "row": row,
                        "colFrom": c0,
                        "colTo": c1,
                        "zone": f"{row}{c0}",
                        "mime": encoded["mime"],
                        "b64": encoded["b64"],
                        "width": encoded["width"],
                        "height": encoded["height"],
                    }
                )
    finally:
        doc.close()
    return out


def _ink_fraction(samples: bytes, width: int, height: int, n: int) -> float:
    """Share of sampled pixels that are not paper-white."""
    if width < 1 or height < 1 or n < 1:
        return 0.0
    step = 6
    dark = 0
    total = 0
    for y in range(0, height, step):
        row = y * width * n
        for x in range(0, width, step):
            i = row + x * n
            if samples[i] < 210 or (n > 1 and samples[i + 1] < 210):
                dark += 1
            total += 1
    if not total:
        return 0.0
    return dark / float(total)
