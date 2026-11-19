"""Gated visual crops for TABLE N on a GA PDF page.

Accuracy policy: return a crop only when the table title is found uniquely
on the target page and the expanded region looks like a real table block.
Never invent cell data — image pixels only.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass
from typing import Any


# Title must look like a table caption, not a sentence mentioning "table 1".
_TITLE_LINE = re.compile(
    r"^\s*(?:TABLES?|TABELS?|TAB\.?)\s*(?:NO\.?|#)?\s*([0-9]{1,2}|[A-Z])\s*$",
    re.I,
)
_TITLE_PREFIX = re.compile(
    r"^\s*(?:TABLES?|TABELS?|TAB\.?)\s*(?:NO\.?|#)?\s*([0-9]{1,2}|[A-Z])\b",
    re.I,
)
_NEXT_BLOCK = re.compile(
    r"^\s*(?:TABLES?|TABELS?|TAB\.?|FIGURES?|FIG\.?|SHEETS?|SH\.?|DETAILS?|NOTES?|VIEW)\b",
    re.I,
)

# Reject crops that are tiny/huge relative to the page
_MIN_TITLE_HITS = 1
_MAX_TITLE_HITS = 1
_MIN_CLIP_W = 60.0
_MIN_CLIP_H = 36.0
_MAX_CLIP_H_FRAC = 0.55
_MAX_CLIP_W_FRAC = 0.98
_MIN_CONFIDENCE = 0.82


@dataclass
class TitleHit:
    table_id: str
    bbox: tuple[float, float, float, float]  # x0,y0,x1,y1
    text: str
    font_size: float = 0.0


def _norm_id(rid: str | int) -> str:
    return str(rid or "").strip().upper()


def _union(a: tuple[float, float, float, float], b: tuple[float, float, float, float]):
    return (min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3]))


def find_table_title_hits(page, table_id: str | int) -> list[TitleHit]:
    """Locate caption-like TABLE <id> lines on a PyMuPDF page."""
    want = _norm_id(table_id)
    if not want:
        return []
    hits: list[TitleHit] = []
    try:
        data = page.get_text("dict") or {}
    except Exception:
        return []
    for block in data.get("blocks") or []:
        if block.get("type", 0) != 0:
            continue
        for line in block.get("lines") or []:
            spans = line.get("spans") or []
            if not spans:
                continue
            text = "".join(str(s.get("text") or "") for s in spans).strip()
            if not text:
                continue
            m = _TITLE_LINE.match(text) or (
                _TITLE_PREFIX.match(text) if len(text) <= 28 else None
            )
            if not m or _norm_id(m.group(1)) != want:
                continue
            # Skip prose that merely mentions the table
            if len(text) > 36 and not _TITLE_LINE.match(text):
                continue
            x0 = min(float(s["bbox"][0]) for s in spans)
            y0 = min(float(s["bbox"][1]) for s in spans)
            x1 = max(float(s["bbox"][2]) for s in spans)
            y1 = max(float(s["bbox"][3]) for s in spans)
            fs = max(float(s.get("size") or 0) for s in spans)
            hits.append(TitleHit(table_id=want, bbox=(x0, y0, x1, y1), text=text, font_size=fs))
    return hits


def _next_heading_y(page, below_y: float, page_h: float) -> float | None:
    """Y of the next TABLE/FIGURE/SHEET/DETAIL/NOTES heading below the title."""
    try:
        data = page.get_text("dict") or {}
    except Exception:
        return None
    best: float | None = None
    for block in data.get("blocks") or []:
        if block.get("type", 0) != 0:
            continue
        for line in block.get("lines") or []:
            spans = line.get("spans") or []
            if not spans:
                continue
            text = "".join(str(s.get("text") or "") for s in spans).strip()
            if not text or not _NEXT_BLOCK.match(text):
                continue
            y0 = min(float(s["bbox"][1]) for s in spans)
            if y0 <= below_y + 8:
                continue
            if best is None or y0 < best:
                best = y0
    if best is not None and best < page_h:
        return best
    return None


def expand_table_clip(
    page,
    title: TitleHit,
    *,
    pad_x: float = 8.0,
    pad_top: float = 4.0,
) -> tuple[float, float, float, float]:
    """Expand from title bbox down to next heading or a capped page fraction."""
    import fitz

    pr = page.rect
    x0, y0, x1, y1 = title.bbox
    # Prefer full content width under the title band (tables are often wider than the label)
    left = max(pr.x0 + 4, min(x0 - pad_x, pr.x0 + pr.width * 0.04))
    right = min(pr.x1 - 4, max(x1 + pad_x, pr.x0 + pr.width * 0.96))
    top = max(pr.y0 + 2, y0 - pad_top)

    below = y1 + 2
    next_y = _next_heading_y(page, below, pr.y1)
    max_bottom = top + pr.height * _MAX_CLIP_H_FRAC
    if next_y is not None:
        bottom = min(next_y - 4, max_bottom, pr.y1 - 4)
    else:
        # No next heading — take a moderate band; still gated by size checks
        bottom = min(max_bottom, pr.y1 - 4, y1 + max(120.0, pr.height * 0.28))

    # Grow horizontally using nearby text in the vertical band (cells under title)
    try:
        data = page.get_text("dict") or {}
        for block in data.get("blocks") or []:
            if block.get("type", 0) != 0:
                continue
            for line in block.get("lines") or []:
                spans = line.get("spans") or []
                if not spans:
                    continue
                ly0 = min(float(s["bbox"][1]) for s in spans)
                ly1 = max(float(s["bbox"][3]) for s in spans)
                if ly1 < top or ly0 > bottom:
                    continue
                lx0 = min(float(s["bbox"][0]) for s in spans)
                lx1 = max(float(s["bbox"][2]) for s in spans)
                left = min(left, lx0 - 4)
                right = max(right, lx1 + 4)
    except Exception:
        pass

    left = max(pr.x0 + 2, left)
    right = min(pr.x1 - 2, right)
    if right - left < _MIN_CLIP_W:
        # Center a minimum width on the title
        mid = (x0 + x1) / 2
        left = max(pr.x0 + 2, mid - _MIN_CLIP_W / 2)
        right = min(pr.x1 - 2, left + _MIN_CLIP_W)

    clip = fitz.Rect(left, top, right, max(bottom, top + _MIN_CLIP_H))
    return (clip.x0, clip.y0, clip.x1, clip.y1)


def _confidence_for(title: TitleHit, clip: tuple[float, float, float, float], page_rect) -> float:
    pw = float(page_rect.width or 1)
    ph = float(page_rect.height or 1)
    cw = clip[2] - clip[0]
    ch = clip[3] - clip[1]
    score = 0.55
    if _TITLE_LINE.match(title.text.strip()):
        score += 0.25
    elif _TITLE_PREFIX.match(title.text.strip()) and len(title.text.strip()) <= 28:
        score += 0.15
    if title.font_size >= 8:
        score += 0.05
    if _MIN_CLIP_W <= cw <= pw * _MAX_CLIP_W_FRAC:
        score += 0.08
    if _MIN_CLIP_H <= ch <= ph * _MAX_CLIP_H_FRAC:
        score += 0.07
    return min(0.99, score)


def render_table_crop(
    pdf_bytes: bytes,
    *,
    table_id: str | int,
    page_no: int | None = None,
    dpi: int = 200,
    jpeg_quality: int = 90,
) -> dict[str, Any]:
    """
    Render a gated TABLE <id> crop.

    Returns either:
      { available: True, label, page, confidence, mime, imageBase64, width, height, clip }
    or:
      { available: False, reason, label, page? }
    """
    import fitz
    from PIL import Image

    label = f"TABLE {_norm_id(table_id) or '?'}"
    if not pdf_bytes:
        return {"available": False, "reason": "Empty PDF", "label": label}
    want = _norm_id(table_id)
    if not want:
        return {"available": False, "reason": "Table id required", "label": label}

    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    except Exception as exc:
        return {"available": False, "reason": f"Could not open PDF ({exc})", "label": label}

    try:
        if doc.page_count < 1:
            return {"available": False, "reason": "PDF has no pages", "label": label}

        # Prefer explicit page; else search all pages but only accept a unique hit overall
        pages: list[int]
        if page_no is not None:
            p = int(page_no)
            if p < 1 or p > doc.page_count:
                return {
                    "available": False,
                    "reason": f"Sheet/page {p} not in PDF ({doc.page_count} page(s))",
                    "label": label,
                    "page": p,
                }
            pages = [p]
        else:
            pages = list(range(1, doc.page_count + 1))

        candidates: list[tuple[int, TitleHit]] = []
        for p in pages:
            page = doc.load_page(p - 1)
            for hit in find_table_title_hits(page, want):
                candidates.append((p, hit))

        if not candidates:
            return {
                "available": False,
                "reason": f"{label} title not found as a caption on the drawing",
                "label": label,
                "page": pages[0] if len(pages) == 1 else None,
            }

        # Group near-duplicate hits on the same page (split spans)
        by_page: dict[int, list[TitleHit]] = {}
        for p, hit in candidates:
            by_page.setdefault(p, []).append(hit)

        unique_pages = []
        for p, hits in by_page.items():
            # Merge overlapping / nearby titles into one
            hits_sorted = sorted(hits, key=lambda h: (h.bbox[1], -h.font_size))
            merged: list[TitleHit] = []
            for h in hits_sorted:
                if not merged:
                    merged.append(h)
                    continue
                last = merged[-1]
                # Same title fragment if vertically close
                if abs(h.bbox[1] - last.bbox[1]) < 14 and abs(h.bbox[0] - last.bbox[0]) < 80:
                    merged[-1] = TitleHit(
                        table_id=want,
                        bbox=_union(last.bbox, h.bbox),
                        text=last.text if len(last.text) >= len(h.text) else h.text,
                        font_size=max(last.font_size, h.font_size),
                    )
                else:
                    merged.append(h)
            if len(merged) == 1:
                unique_pages.append((p, merged[0]))

        if len(unique_pages) != 1:
            return {
                "available": False,
                "reason": (
                    f"{label} caption is ambiguous "
                    f"({len(candidates)} hit(s) across {len(by_page)} page(s)); not showing a guess"
                ),
                "label": label,
            }

        page_idx, title = unique_pages[0]
        page = doc.load_page(page_idx - 1)
        clip_t = expand_table_clip(page, title)
        conf = _confidence_for(title, clip_t, page.rect)
        cw = clip_t[2] - clip_t[0]
        ch = clip_t[3] - clip_t[1]
        pw = float(page.rect.width or 1)
        ph = float(page.rect.height or 1)

        if conf < _MIN_CONFIDENCE:
            return {
                "available": False,
                "reason": f"Low confidence ({conf:.2f}) locating {label}",
                "label": label,
                "page": page_idx,
            }
        if cw < _MIN_CLIP_W or ch < _MIN_CLIP_H:
            return {
                "available": False,
                "reason": f"{label} region too small to display reliably",
                "label": label,
                "page": page_idx,
            }
        if ch > ph * _MAX_CLIP_H_FRAC or cw > pw * _MAX_CLIP_W_FRAC:
            return {
                "available": False,
                "reason": f"{label} region too large — refusing a half-page guess",
                "label": label,
                "page": page_idx,
            }

        dpi = max(120, min(int(dpi or 200), 300))
        zoom = dpi / 72.0
        clip = fitz.Rect(*clip_t)
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), clip=clip, alpha=False)
        img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=max(70, min(int(jpeg_quality or 90), 95)))
        import base64

        b64 = base64.b64encode(buf.getvalue()).decode("ascii")
        return {
            "available": True,
            "kind": "table",
            "label": label,
            "tableId": want,
            "page": page_idx,
            "confidence": round(conf, 3),
            "mime": "image/jpeg",
            "imageBase64": b64,
            "width": pix.width,
            "height": pix.height,
            "clip": [round(v, 2) for v in clip_t],
            "titleText": title.text,
        }
    finally:
        doc.close()
