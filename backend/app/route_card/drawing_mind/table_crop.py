"""Gated visual crops for TABLE / FIGURE / DETAIL captions on a GA PDF page.

Accuracy policy: return a crop only when the caption is found uniquely
on the target page and the expanded region looks like a real block.
Never invent cell/geometry data — image pixels only.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass
from typing import Any


_KIND_PATTERNS: dict[str, tuple[re.Pattern[str], re.Pattern[str], str]] = {
    "table": (
        re.compile(
            r"^\s*(?:TABLES?|TABELS?|TAB\.?)\s*(?:NO\.?|#)?\s*([0-9]{1,2}|[A-Z])\s*$",
            re.I,
        ),
        re.compile(
            r"^\s*(?:TABLES?|TABELS?|TAB\.?)\s*(?:NO\.?|#)?\s*([0-9]{1,2}|[A-Z])\b",
            re.I,
        ),
        "TABLE",
    ),
    "figure": (
        re.compile(
            r"^\s*(?:FIGURES?|FIG\.?)\s*(?:NO\.?|#)?\s*([0-9]{1,2}|[A-Z])\s*$",
            re.I,
        ),
        re.compile(
            r"^\s*(?:FIGURES?|FIG\.?)\s*(?:NO\.?|#)?\s*([0-9]{1,2}|[A-Z])\b",
            re.I,
        ),
        "FIGURE",
    ),
    "detail": (
        re.compile(
            r"^\s*(?:DETAILS?)\s*(?:NO\.?|#)?\s*([0-9]{1,2}|[A-Z])\s*$",
            re.I,
        ),
        re.compile(
            r"^\s*(?:DETAILS?)\s*(?:NO\.?|#)?\s*([0-9]{1,2}|[A-Z])\b",
            re.I,
        ),
        "DETAIL",
    ),
}

_NEXT_BLOCK = re.compile(
    r"^\s*(?:TABLES?|TABELS?|TAB\.?|FIGURES?|FIG\.?|SHEETS?|SH\.?|DETAILS?|NOTES?|VIEW)\b",
    re.I,
)

_MIN_CLIP_W = 60.0
_MIN_CLIP_H = 36.0
_MAX_CLIP_H_FRAC = 0.55
_MAX_CLIP_H_FRAC_FIGURE = 0.72
_MAX_CLIP_W_FRAC = 0.98
_MIN_CONFIDENCE = 0.82

# ISOMETRIC VIEW — caption sits UNDER the view body on GA sheets, so the crop
# grows upward from the caption (not downward like TABLE/FIGURE captions).
_ISO_KIND = "isometric"
_ITEM_VIEW_KIND = "item_view"
_ISO_CAPTION = "ISOMETRIC VIEW"
_ISO_CAPTION_RE = re.compile(r"^\s*ISOMETRIC\s+VIEW\b", re.I)
_ISO_HALF_W_FRAC = 0.24  # half window width around caption centre (fraction of page width)
_ISO_MAX_H_FRAC = 0.42  # max height above caption (fraction of page height)


def _max_h_frac(kind: str) -> float:
    return _MAX_CLIP_H_FRAC_FIGURE if kind in {"figure", "named", _ISO_KIND, _ITEM_VIEW_KIND} else _MAX_CLIP_H_FRAC


@dataclass
class TitleHit:
    ref_id: str
    bbox: tuple[float, float, float, float]  # x0,y0,x1,y1
    text: str
    font_size: float = 0.0

    @property
    def table_id(self) -> str:
        # Back-compat for older call sites / tests
        return self.ref_id


def _norm_id(rid: str | int) -> str:
    return str(rid or "").strip().upper()


_NAMED_CAPTIONS: dict[str, re.Pattern[str]] = {
    "INTERCONNECTION TABLE": re.compile(
        r"^\s*INTERCONNECT(?:ION)?\s+(?:TABLE|LIST(?:ING)?|DETAILS?)\b",
        re.I,
    ),
    "TOOLING MATRIX": re.compile(
        r"^\s*(?:TOOLING\s+MATRIX|TOOLS?\s+FOR\s+CONNECTORISATION)\b",
        re.I,
    ),
}


def _norm_item_list(rid: str | int) -> str:
    """Normalize item numbers like '2, 3' or '3 & 2' -> '2,3'."""
    nums = sorted({int(m) for m in re.findall(r"\b[1-9]\d?\b", str(rid or ""))})
    return ",".join(str(n) for n in nums)


def _norm_kind(kind: str | None) -> str:
    k = str(kind or "table").strip().lower()
    if k in {"fig", "figs", "figures"}:
        return "figure"
    if k in {"tab", "tabs", "tables"}:
        return "table"
    if k in {"details"}:
        return "detail"
    if k in {"named", "name", "block"}:
        return "named"
    if k in {"iso", "isom", "isometric", "isometric_view", "isometric view"}:
        return _ISO_KIND
    if k in {"item_view", "item-view", "itemview", "callout", "items"}:
        return _ITEM_VIEW_KIND
    return k if k in _KIND_PATTERNS or k in {"named", _ISO_KIND, _ITEM_VIEW_KIND} else "table"


def _label_for(kind: str, rid: str) -> str:
    kind = _norm_kind(kind)
    if kind == _ISO_KIND:
        return _ISO_CAPTION
    if kind == _ITEM_VIEW_KIND:
        items = _norm_item_list(rid)
        if not items:
            return "DRAWING VIEW"
        parts = items.split(",")
        return f"VIEW (ITEM {parts[0]})" if len(parts) == 1 else f"VIEW (ITEMS {', '.join(parts)})"
    if kind == "named":
        return (_norm_id(rid) or "NAMED BLOCK").replace("_", " ")
    prefix = _KIND_PATTERNS[kind][2]
    return f"{prefix} {_norm_id(rid) or '?'}"


def _named_key(rid: str) -> str:
    u = re.sub(r"\s+", " ", _norm_id(rid)).strip()
    if "INTERCONNECT" in u:
        return "INTERCONNECTION TABLE"
    if "TOOLING" in u or "CONNECTORISATION" in u:
        return "TOOLING MATRIX"
    return u


def _union(a: tuple[float, float, float, float], b: tuple[float, float, float, float]):
    return (min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3]))


def _find_isometric_hits(page) -> list[TitleHit]:
    """Locate 'ISOMETRIC VIEW' caption lines (ignores prose that merely mentions it)."""
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
            if not text or len(text) > 48 or not _ISO_CAPTION_RE.match(text):
                continue
            x0 = min(float(s["bbox"][0]) for s in spans)
            y0 = min(float(s["bbox"][1]) for s in spans)
            x1 = max(float(s["bbox"][2]) for s in spans)
            y1 = max(float(s["bbox"][3]) for s in spans)
            fs = max(float(s.get("size") or 0) for s in spans)
            hits.append(TitleHit(ref_id=_ISO_CAPTION, bbox=(x0, y0, x1, y1), text=text, font_size=fs))
    return hits


def find_title_hits(page, kind: str, ref_id: str | int) -> list[TitleHit]:
    """Locate caption-like TITLE <id> lines on a PyMuPDF page."""
    kind = _norm_kind(kind)
    if kind == _ISO_KIND:
        return _find_isometric_hits(page)
    want = _norm_id(ref_id) if kind != "named" else _named_key(str(ref_id or ""))
    if not want:
        return []
    if kind == "named":
        named_re = _NAMED_CAPTIONS.get(want)
        if not named_re:
            return []
    elif kind not in _KIND_PATTERNS:
        return []
    else:
        title_line, title_prefix, _ = _KIND_PATTERNS[kind]
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
            if kind == "named":
                if not named_re.match(text) and not (
                    len(text) <= 48 and named_re.search(text)
                ):
                    continue
                # Skip cross-sheet citations
                if re.search(r"PROVIDED\s+IN\s+SHEET|IN\s+SHEET\s*\d", text, re.I):
                    continue
            else:
                # Skip DETAIL/ITEM NO table header noise when looking for DETAIL A/B callouts
                if kind == "detail" and re.search(r"DETAIL\s*/\s*ITEM", text, re.I):
                    continue
                m = title_line.match(text) or (
                    title_prefix.match(text) if len(text) <= 36 else None
                )
                if not m or _norm_id(m.group(1)) != want:
                    continue
                # Skip prose that merely mentions the caption
                if len(text) > 40 and not title_line.match(text):
                    continue
            x0 = min(float(s["bbox"][0]) for s in spans)
            y0 = min(float(s["bbox"][1]) for s in spans)
            x1 = max(float(s["bbox"][2]) for s in spans)
            y1 = max(float(s["bbox"][3]) for s in spans)
            fs = max(float(s.get("size") or 0) for s in spans)
            hits.append(TitleHit(ref_id=want, bbox=(x0, y0, x1, y1), text=text, font_size=fs))
    return hits


def find_table_title_hits(page, table_id: str | int) -> list[TitleHit]:
    return find_title_hits(page, "table", table_id)


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


def _expand_isometric_clip(page, title: TitleHit, *, pad: float = 6.0) -> tuple[float, float, float, float]:
    """Crop the view body ABOVE its caption (ISOMETRIC VIEW sits under the drawing)."""
    import fitz

    pr = page.rect
    x0, y0, x1, y1 = title.bbox
    cx = (x0 + x1) / 2
    left = max(pr.x0 + 2, cx - pr.width * _ISO_HALF_W_FRAC)
    right = min(pr.x1 - 2, cx + pr.width * _ISO_HALF_W_FRAC)
    bottom = min(pr.y1 - 2, y1 + pad)
    top = max(pr.y0 + 2, y0 - pr.height * _ISO_MAX_H_FRAC)

    # Stop just below the nearest heading / NOTE band above the caption (same column only)
    try:
        data = page.get_text("dict") or {}
        for block in data.get("blocks") or []:
            if block.get("type", 0) != 0:
                continue
            for line in block.get("lines") or []:
                spans = line.get("spans") or []
                if not spans:
                    continue
                text = "".join(str(s.get("text") or "") for s in spans).strip()
                ly1 = max(float(s["bbox"][3]) for s in spans)
                lx0 = min(float(s["bbox"][0]) for s in spans)
                lx1 = max(float(s["bbox"][2]) for s in spans)
                if ly1 >= y0 - 1 or ly1 < top:
                    continue
                if lx1 < left or lx0 > right:
                    continue
                if _NEXT_BLOCK.match(text) or re.match(r"^\s*NOTES?\b", text, re.I):
                    top = max(top, ly1 + 2)
    except Exception:
        pass

    if right - left < _MIN_CLIP_W:
        left = max(pr.x0 + 2, cx - _MIN_CLIP_W / 2)
        right = min(pr.x1 - 2, left + _MIN_CLIP_W)
    clip = fitz.Rect(left, top, right, max(bottom, top + _MIN_CLIP_H))
    return (clip.x0, clip.y0, clip.x1, clip.y1)


_BALLOON_NUM_RE = re.compile(r"^[1-9]\d?$")


def _extract_clip_callout_items(
    page,
    clip_t: tuple[float, float, float, float],
    *,
    caption_y0: float,
) -> list[int]:
    """Return sorted item/balloon numbers (1..99) visible inside an isometric crop."""
    import fitz

    found: set[int] = set()
    try:
        data = page.get_text("dict", clip=fitz.Rect(*clip_t)) or {}
    except Exception:
        return []
    for block in data.get("blocks") or []:
        if block.get("type", 0) != 0:
            continue
        for line in block.get("lines") or []:
            spans = line.get("spans") or []
            if not spans:
                continue
            ly1 = max(float(s["bbox"][3]) for s in spans)
            if ly1 >= caption_y0 - 2:
                continue
            text = "".join(str(s.get("text") or "") for s in spans).strip()
            if _BALLOON_NUM_RE.fullmatch(text):
                found.add(int(text))
    return sorted(found)


def expand_clip(
    page,
    title: TitleHit,
    *,
    kind: str = "table",
    pad_x: float = 8.0,
    pad_top: float = 4.0,
) -> tuple[float, float, float, float]:
    """Expand from title bbox down to next heading or a capped page fraction."""
    import fitz

    kind = _norm_kind(kind)
    if kind == _ISO_KIND:
        return _expand_isometric_clip(page, title)
    max_h_frac = _max_h_frac(kind)
    pr = page.rect
    x0, y0, x1, y1 = title.bbox
    # Prefer full content width under the title band
    left = max(pr.x0 + 4, min(x0 - pad_x, pr.x0 + pr.width * 0.04))
    right = min(pr.x1 - 4, max(x1 + pad_x, pr.x0 + pr.width * 0.96))
    # DETAIL callouts are often compact boxes near the label — keep tighter width seed
    if kind == "detail":
        left = max(pr.x0 + 4, x0 - max(24.0, (x1 - x0) * 2))
        right = min(pr.x1 - 4, x1 + max(120.0, pr.width * 0.28))
    top = max(pr.y0 + 2, y0 - pad_top)

    below = y1 + 2
    next_y = _next_heading_y(page, below, pr.y1)
    max_bottom = top + pr.height * max_h_frac
    if next_y is not None:
        bottom = min(next_y - 4, max_bottom, pr.y1 - 4)
    else:
        default_band = 180.0 if kind in {"figure", "named"} else 120.0
        bottom = min(max_bottom, pr.y1 - 4, y1 + max(default_band, pr.height * 0.28))

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
                if kind == "detail":
                    # Only grow with nearby text in a lateral band around the label
                    mid = (x0 + x1) / 2
                    if lx1 < mid - pr.width * 0.35 or lx0 > mid + pr.width * 0.45:
                        continue
                left = min(left, lx0 - 4)
                right = max(right, lx1 + 4)
    except Exception:
        pass

    left = max(pr.x0 + 2, left)
    right = min(pr.x1 - 2, right)
    if right - left < _MIN_CLIP_W:
        mid = (x0 + x1) / 2
        left = max(pr.x0 + 2, mid - _MIN_CLIP_W / 2)
        right = min(pr.x1 - 2, left + _MIN_CLIP_W)

    clip = fitz.Rect(left, top, right, max(bottom, top + _MIN_CLIP_H))
    return (clip.x0, clip.y0, clip.x1, clip.y1)


def expand_table_clip(page, title: TitleHit, **kwargs) -> tuple[float, float, float, float]:
    return expand_clip(page, title, kind="table", **kwargs)


def _confidence_for(
    kind: str,
    title: TitleHit,
    clip: tuple[float, float, float, float],
    page_rect,
) -> float:
    kind = _norm_kind(kind)
    max_h_frac = _max_h_frac(kind)
    pw = float(page_rect.width or 1)
    ph = float(page_rect.height or 1)
    cw = clip[2] - clip[0]
    ch = clip[3] - clip[1]
    score = 0.55
    if kind == _ISO_KIND:
        if _ISO_CAPTION_RE.match(title.text.strip()):
            score += 0.25
    elif kind == "named":
        named_re = _NAMED_CAPTIONS.get(title.ref_id) or _NAMED_CAPTIONS.get(
            _named_key(title.ref_id)
        )
        if named_re and named_re.match(title.text.strip()):
            score += 0.25
        elif named_re and named_re.search(title.text.strip()):
            score += 0.15
    else:
        title_line, title_prefix, _ = _KIND_PATTERNS[kind]
        if title_line.match(title.text.strip()):
            score += 0.25
        elif title_prefix.match(title.text.strip()) and len(title.text.strip()) <= 36:
            score += 0.15
    if title.font_size >= 8:
        score += 0.05
    if _MIN_CLIP_W <= cw <= pw * _MAX_CLIP_W_FRAC:
        score += 0.08
    if _MIN_CLIP_H <= ch <= ph * max_h_frac:
        score += 0.07
    return min(0.99, score)


def _encode_clip_jpeg(
    page,
    clip_t: tuple[float, float, float, float],
    *,
    dpi: int,
    jpeg_quality: int,
) -> tuple[str, int, int]:
    import base64

    import fitz
    from PIL import Image

    dpi = max(120, min(int(dpi or 200), 300))
    zoom = dpi / 72.0
    clip = fitz.Rect(*clip_t)
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), clip=clip, alpha=False)
    img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=max(70, min(int(jpeg_quality or 90), 95)))
    return base64.b64encode(buf.getvalue()).decode("ascii"), pix.width, pix.height


def _clip_passes_gates(
    kind: str,
    clip_t: tuple[float, float, float, float],
    page_rect,
) -> str | None:
    """Return a refusal reason, or None if the clip is acceptable."""
    kind = _norm_kind(kind)
    max_h_frac = _max_h_frac(kind)
    cw = clip_t[2] - clip_t[0]
    ch = clip_t[3] - clip_t[1]
    pw = float(page_rect.width or 1)
    ph = float(page_rect.height or 1)
    if cw < _MIN_CLIP_W or ch < _MIN_CLIP_H:
        return "region too small to display reliably"
    if ch > ph * max_h_frac or cw > pw * _MAX_CLIP_W_FRAC:
        return "region too large — refusing a half-page guess"
    return None


_VLM_LOCATE_PROMPT = """You are viewing a GA / assembly drawing page image.

Locate ONLY this caption/block if it is clearly visible on THIS page:
  Target: {label}

Rules:
- If the caption is not visible on this page, return found=false.
- If more than one matching caption appears, return found=false (do not guess).
- Do NOT invent a figure/table that is not drawn.
- bboxNorm is the full content block (caption + figure/table body) in normalized
  page coordinates [x0, y0, x1, y1] where 0,0 is top-left and 1,1 is bottom-right.
- confidence: 0–1 how sure you are the caption matches and the box is correct.

Return JSON only:
{{
  "found": true,
  "page": {page_no},
  "bboxNorm": [0.1, 0.2, 0.6, 0.55],
  "confidence": 0.9,
  "labelText": "FIGURE 1"
}}
"""


def _parse_vlm_locate_json(raw: str) -> dict[str, Any] | None:
    import json

    text = (raw or "").strip()
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text, re.I)
    if fence:
        text = fence.group(1).strip()
    brace = text.find("{")
    if brace > 0:
        text = text[brace:]
    try:
        data = json.loads(text)
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def _render_view_crop_vlm(
    pdf_bytes: bytes,
    *,
    kind: str,
    want: str,
    label: str,
    page_no: int | None,
    dpi: int,
    jpeg_quality: int,
) -> dict[str, Any]:
    """VLM caption locate + gated pixmap crop. Soft-fails — never invents."""
    import fitz

    try:
        from app.config.settings import settings
        from app.route_card.drawing_mind.ollama_client import (
            chat_vision,
            ollama_reachable,
            vlm_status,
        )
        from app.route_card.drawing_mind.page_images import render_pdf_pages
    except Exception as exc:
        return {
            "available": False,
            "reason": f"VLM locate unavailable ({exc})",
            "kind": kind,
            "label": label,
            "source": "vlm",
        }

    base_url = getattr(settings, "OLLAMA_BASE_URL", "") or ""
    model = getattr(settings, "OLLAMA_VLM_MODEL", "") or ""
    timeout = float(getattr(settings, "OLLAMA_TIMEOUT_SEC", 120) or 120)
    max_tokens = min(512, int(getattr(settings, "OLLAMA_VLM_MAX_TOKENS", 2048) or 2048))
    ok, _err = vlm_status(base_url, model=model, timeout=min(4.0, timeout))
    if not (ok or ollama_reachable(base_url, timeout=min(4.0, timeout))):
        return {
            "available": False,
            "reason": "Vision server not reachable for caption locate",
            "kind": kind,
            "label": label,
            "source": "vlm",
        }

    page_indexes = [int(page_no)] if page_no is not None else None
    try:
        imgs = render_pdf_pages(
            pdf_bytes,
            dpi=min(160, int(dpi or 160)),
            max_pages=1 if page_indexes else 3,
            max_edge=1600,
            page_indexes=page_indexes,
        )
    except Exception as exc:
        return {
            "available": False,
            "reason": f"Could not render pages for VLM ({exc})",
            "kind": kind,
            "label": label,
            "source": "vlm",
        }
    if not imgs:
        return {
            "available": False,
            "reason": "No page images for VLM locate",
            "kind": kind,
            "label": label,
            "source": "vlm",
        }

    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    except Exception as exc:
        return {
            "available": False,
            "reason": f"Could not open PDF for VLM crop ({exc})",
            "kind": kind,
            "label": label,
            "source": "vlm",
        }

    try:
        for img in imgs:
            page_idx = int(img.get("page") or 1)
            if kind == _ITEM_VIEW_KIND:
                prompt = (
                    f"You are inspecting page {page_idx} of an engineering GA drawing.\n"
                    f"Locate the SINGLE orthographic or detail view on this page that shows "
                    f"the item callout leader/balloon numbers: {want.replace(',', ', ')}.\n"
                    "Include the entire view, its leader lines, callout numbers, and nearby "
                    "placement dimensions (e.g. offset distances in mm) in the bounding box.\n"
                    "Do NOT include the parts list / BOM table, title block, or other unrelated views.\n"
                    "If no single view clearly shows these callouts, return found=false.\n"
                    'Reply with ONLY valid JSON: {"found": true/false, "confidence": 0.0-1.0, '
                    '"bboxNorm": [x0, y0, x1, y1], "labelText": "short view description"}'
                )
                sys_prompt = (
                    "You locate engineering drawing views containing specific item callout numbers. "
                    "Reply with JSON only — no markdown fences."
                )
            else:
                prompt = _VLM_LOCATE_PROMPT.format(label=label, page_no=page_idx)
                sys_prompt = (
                    "You locate drawing captions only when clearly visible. "
                    "Reply with JSON only — no markdown fences."
                )
            try:
                raw = chat_vision(
                    prompt=prompt,
                    images_b64=[img["b64"]],
                    model=model,
                    base_url=base_url,
                    timeout=timeout,
                    temperature=0.0,
                    system=sys_prompt,
                    image_mime=str(img.get("mime") or "image/jpeg"),
                    max_tokens=max_tokens,
                )
            except Exception as exc:
                continue
            data = _parse_vlm_locate_json(raw)
            if not data or not data.get("found"):
                continue
            try:
                conf = float(data.get("confidence") or 0)
            except (TypeError, ValueError):
                conf = 0.0
            if conf < _MIN_CONFIDENCE:
                continue
            bbox = data.get("bboxNorm") or data.get("bbox")
            if not (isinstance(bbox, (list, tuple)) and len(bbox) == 4):
                continue
            try:
                nx0, ny0, nx1, ny1 = (float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3]))
            except (TypeError, ValueError):
                continue
            # Normalize order and clamp
            x0n, x1n = sorted((max(0.0, min(1.0, nx0)), max(0.0, min(1.0, nx1))))
            y0n, y1n = sorted((max(0.0, min(1.0, ny0)), max(0.0, min(1.0, ny1))))
            if x1n - x0n < 0.02 or y1n - y0n < 0.02:
                continue
            if page_idx < 1 or page_idx > doc.page_count:
                continue
            page = doc.load_page(page_idx - 1)
            pr = page.rect
            clip_t = (
                pr.x0 + x0n * pr.width,
                pr.y0 + y0n * pr.height,
                pr.x0 + x1n * pr.width,
                pr.y0 + y1n * pr.height,
            )
            refuse = _clip_passes_gates(kind, clip_t, pr)
            if refuse:
                continue
            # Soft OCR agreement: caption text near box boosts trust; absence is OK
            label_text = str(data.get("labelText") or "").strip()
            b64, w, h = _encode_clip_jpeg(
                page, clip_t, dpi=dpi, jpeg_quality=jpeg_quality
            )
            return {
                "available": True,
                "kind": kind,
                "label": label,
                "refId": want,
                "tableId": want if kind == "table" else None,
                "page": page_idx,
                "confidence": round(conf, 3),
                "mime": "image/jpeg",
                "imageBase64": b64,
                "width": w,
                "height": h,
                "clip": [round(v, 2) for v in clip_t],
                "titleText": label_text or label,
                "source": "vlm",
            }
    finally:
        doc.close()

    return {
        "available": False,
        "reason": f"VLM could not uniquely locate {label} with high confidence",
        "kind": kind,
        "label": label,
        "source": "vlm",
    }


def _render_view_crop_ocr(
    pdf_bytes: bytes,
    *,
    kind: str,
    want: str,
    label: str,
    page_no: int | None = None,
    dpi: int = 200,
    jpeg_quality: int = 90,
) -> dict[str, Any]:
    """OCR/caption-gated crop (deterministic)."""
    import fitz

    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    except Exception as exc:
        return {
            "available": False,
            "reason": f"Could not open PDF ({exc})",
            "kind": kind,
            "label": label,
            "source": "ocr",
        }

    try:
        if doc.page_count < 1:
            return {
                "available": False,
                "reason": "PDF has no pages",
                "kind": kind,
                "label": label,
                "source": "ocr",
            }

        if page_no is not None:
            p = int(page_no)
            if p < 1 or p > doc.page_count:
                return {
                    "available": False,
                    "reason": f"Sheet/page {p} not in PDF ({doc.page_count} page(s))",
                    "kind": kind,
                    "label": label,
                    "page": p,
                    "source": "ocr",
                }
            pages = [p]
        else:
            pages = list(range(1, doc.page_count + 1))

        candidates: list[tuple[int, TitleHit]] = []
        for p in pages:
            page = doc.load_page(p - 1)
            for hit in find_title_hits(page, kind, want):
                candidates.append((p, hit))

        if not candidates:
            return {
                "available": False,
                "reason": f"{label} caption not found on the drawing",
                "kind": kind,
                "label": label,
                "page": pages[0] if len(pages) == 1 else None,
                "source": "ocr",
            }

        by_page: dict[int, list[TitleHit]] = {}
        for p, hit in candidates:
            by_page.setdefault(p, []).append(hit)

        unique_pages = []
        for p, hits in by_page.items():
            hits_sorted = sorted(hits, key=lambda h: (h.bbox[1], -h.font_size))
            merged: list[TitleHit] = []
            for h in hits_sorted:
                if not merged:
                    merged.append(h)
                    continue
                last = merged[-1]
                if abs(h.bbox[1] - last.bbox[1]) < 14 and abs(h.bbox[0] - last.bbox[0]) < 80:
                    merged[-1] = TitleHit(
                        ref_id=want,
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
                "kind": kind,
                "label": label,
                "source": "ocr",
            }

        page_idx, title = unique_pages[0]
        page = doc.load_page(page_idx - 1)
        clip_t = expand_clip(page, title, kind=kind)
        conf = _confidence_for(kind, title, clip_t, page.rect)
        if conf < _MIN_CONFIDENCE:
            return {
                "available": False,
                "reason": f"Low confidence ({conf:.2f}) locating {label}",
                "kind": kind,
                "label": label,
                "page": page_idx,
                "source": "ocr",
            }
        refuse = _clip_passes_gates(kind, clip_t, page.rect)
        if refuse:
            return {
                "available": False,
                "reason": f"{label} {refuse}",
                "kind": kind,
                "label": label,
                "page": page_idx,
                "source": "ocr",
            }

        b64, w, h = _encode_clip_jpeg(page, clip_t, dpi=dpi, jpeg_quality=jpeg_quality)
        res: dict[str, Any] = {
            "available": True,
            "kind": kind,
            "label": label,
            "refId": want,
            "tableId": want if kind == "table" else None,
            "page": page_idx,
            "confidence": round(conf, 3),
            "mime": "image/jpeg",
            "imageBase64": b64,
            "width": w,
            "height": h,
            "clip": [round(v, 2) for v in clip_t],
            "titleText": title.text,
            "source": "ocr",
        }
        if kind == _ISO_KIND:
            res["calloutItems"] = _extract_clip_callout_items(
                page, clip_t, caption_y0=title.bbox[1]
            )
        return res
    finally:
        doc.close()


def render_view_crop(
    pdf_bytes: bytes,
    *,
    kind: str,
    ref_id: str | int,
    page_no: int | None = None,
    dpi: int = 200,
    jpeg_quality: int = 90,
    allow_vlm: bool = True,
) -> dict[str, Any]:
    """
    Render a gated TABLE/FIGURE/DETAIL <id> crop.

    OCR caption path first; optional VLM locate fallback when OCR misses.
    Never invents — low confidence / ambiguous → available=false.

    Returns either:
      { available: True, kind, label, page, confidence, mime, imageBase64, width, height, clip, source }
    or:
      { available: False, reason, kind, label, page? }
    """
    kind = _norm_kind(kind)
    label = _label_for(kind, ref_id)
    if not pdf_bytes:
        return {"available": False, "reason": "Empty PDF", "kind": kind, "label": label}
    if kind == _ISO_KIND:
        want = _ISO_CAPTION
    elif kind == _ITEM_VIEW_KIND:
        want = _norm_item_list(ref_id)
    elif kind == "named":
        want = _named_key(str(ref_id or ""))
    else:
        want = _norm_id(ref_id)
    if not want:
        return {
            "available": False,
            "reason": "Item numbers required" if kind == _ITEM_VIEW_KIND else "Reference id required",
            "kind": kind,
            "label": label,
        }
    if kind == "named" and want not in _NAMED_CAPTIONS:
        return {
            "available": False,
            "reason": f"No gated crop for named block '{want}'",
            "kind": kind,
            "label": label,
        }

    if kind == _ITEM_VIEW_KIND:
        if not allow_vlm:
            return {
                "available": False,
                "reason": "VLM required for item_view crop",
                "kind": kind,
                "label": label,
            }
        return _render_view_crop_vlm(
            pdf_bytes,
            kind=kind,
            want=want,
            label=label,
            page_no=page_no,
            dpi=dpi,
            jpeg_quality=jpeg_quality,
        )

    ocr = _render_view_crop_ocr(
        pdf_bytes,
        kind=kind,
        want=want,
        label=label,
        page_no=page_no,
        dpi=dpi,
        jpeg_quality=jpeg_quality,
    )
    if ocr.get("available"):
        return ocr
    if not allow_vlm:
        return ocr

    vlm = _render_view_crop_vlm(
        pdf_bytes,
        kind=kind,
        want=want,
        label=label,
        page_no=page_no,
        dpi=dpi,
        jpeg_quality=jpeg_quality,
    )
    if vlm.get("available"):
        return vlm
    out = dict(ocr)
    if vlm.get("reason"):
        out["vlmReason"] = vlm.get("reason")
    return out


def render_table_crop(
    pdf_bytes: bytes,
    *,
    table_id: str | int,
    page_no: int | None = None,
    dpi: int = 200,
    jpeg_quality: int = 90,
) -> dict[str, Any]:
    """Back-compat wrapper for TABLE crops."""
    return render_view_crop(
        pdf_bytes,
        kind="table",
        ref_id=table_id,
        page_no=page_no,
        dpi=dpi,
        jpeg_quality=jpeg_quality,
    )
