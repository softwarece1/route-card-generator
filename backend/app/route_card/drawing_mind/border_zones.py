"""Detect GA drawing-border zone labels and map balloons to cells (e.g. A-8).

Column/row counts come from the printed frame — never a fixed 12×4 assumption.
Zone is returned only when confirmed; otherwise omitted.
"""

from __future__ import annotations

import base64
import io
import json
import re
from typing import Any

_JSON_FENCE = re.compile(r"```(?:json)?\s*([\s\S]*?)```", re.I)
_COL_LABEL = re.compile(r"^(?:[1-9]|1[0-9]|2[0-4])$")
_ROW_LABEL = re.compile(r"^[A-H]$", re.I)

BORDER_VLM_PROMPT = """You are reading ONLY the drawing-border zone frame of a GA sheet
(thin strips: top/bottom for column numbers, left/right for row letters).

List the printed zone labels you can see. Counts vary by drawing — do not assume 12 columns.

Return JSON only:
{
  "cols": [{"label": "1", "xPct": 4.0}, {"label": "2", "xPct": 12.0}],
  "rows": [{"label": "A", "yPct": 8.0}, {"label": "B", "yPct": 28.0}],
  "confidence": 0.85,
  "warnings": []
}

Rules:
- cols left→right; xPct is 0–100 across the full page width.
- rows top→bottom; yPct is 0–100 down the full page height.
- label for columns = digit string; rows = single letter A–H.
- If the border is unreadable, return {"cols": [], "rows": [], "confidence": 0}.
"""


def _parse_json(raw: str) -> dict[str, Any]:
    text = (raw or "").strip()
    m = _JSON_FENCE.search(text)
    if m:
        text = m.group(1).strip()
    brace = text.find("{")
    if brace > 0:
        text = text[brace:]
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("JSON root must be an object")
    return data


def empty_border_grid(*, reason: str = "") -> dict[str, Any]:
    return {
        "cols": [],
        "rows": [],
        "confidence": 0.0,
        "confirmed": False,
        "source": "",
        "warnings": [reason] if reason else [],
    }


def _normalize_col_label(raw: str) -> str | None:
    t = str(raw or "").strip()
    if _COL_LABEL.match(t):
        return t
    return None


def _normalize_row_label(raw: str) -> str | None:
    t = str(raw or "").strip().upper()
    if _ROW_LABEL.match(t):
        return t
    return None


def _is_monotonic_numeric(labels: list[str]) -> bool:
    try:
        nums = [int(x) for x in labels]
    except ValueError:
        return False
    if len(nums) < 2:
        return False
    asc = all(nums[i] < nums[i + 1] for i in range(len(nums) - 1))
    desc = all(nums[i] > nums[i + 1] for i in range(len(nums) - 1))
    return asc or desc


def _is_monotonic_alpha(labels: list[str]) -> bool:
    labs = [str(x).upper() for x in labels]
    if len(labs) < 2:
        return False
    ords = [ord(x) for x in labs if len(x) == 1]
    if len(ords) != len(labs):
        return False
    asc = all(ords[i] < ords[i + 1] for i in range(len(ords) - 1))
    desc = all(ords[i] > ords[i + 1] for i in range(len(ords) - 1))
    return asc or desc


def validate_border_grid(grid: dict[str, Any] | None) -> dict[str, Any]:
    """Keep only a usable variable border grid; mark confirmed when trustworthy."""
    if not isinstance(grid, dict):
        return empty_border_grid(reason="no grid")
    warns = [w for w in (grid.get("warnings") or []) if isinstance(w, str) and w.strip()]
    cols_in = grid.get("cols") or []
    rows_in = grid.get("rows") or []

    cols: list[dict[str, Any]] = []
    for c in cols_in:
        if not isinstance(c, dict):
            continue
        lab = _normalize_col_label(str(c.get("label") or ""))
        if not lab:
            continue
        try:
            x = float(c.get("x") if c.get("x") is not None else c.get("xPct", -1))
        except (TypeError, ValueError):
            continue
        # Accept 0–1 or 0–100
        if x > 1.5:
            x = x / 100.0
        if not (0.0 <= x <= 1.0):
            continue
        cols.append({"label": lab, "x": x})
    cols.sort(key=lambda r: r["x"])
    # Dedupe same label keeping first (leftmost)
    seen_c: set[str] = set()
    cols_u: list[dict[str, Any]] = []
    for c in cols:
        if c["label"] in seen_c:
            continue
        seen_c.add(c["label"])
        cols_u.append(c)
    cols = cols_u

    rows: list[dict[str, Any]] = []
    for r in rows_in:
        if not isinstance(r, dict):
            continue
        lab = _normalize_row_label(str(r.get("label") or ""))
        if not lab:
            continue
        try:
            y = float(r.get("y") if r.get("y") is not None else r.get("yPct", -1))
        except (TypeError, ValueError):
            continue
        if y > 1.5:
            y = y / 100.0
        if not (0.0 <= y <= 1.0):
            continue
        rows.append({"label": lab, "y": y})
    rows.sort(key=lambda r: r["y"])
    seen_r: set[str] = set()
    rows_u: list[dict[str, Any]] = []
    for r in rows:
        if r["label"] in seen_r:
            continue
        seen_r.add(r["label"])
        rows_u.append(r)
    rows = rows_u

    try:
        conf = float(grid.get("confidence") or 0)
    except (TypeError, ValueError):
        conf = 0.0

    ok_cols = len(cols) >= 2 and _is_monotonic_numeric([c["label"] for c in cols])
    ok_rows = len(rows) >= 2 and _is_monotonic_alpha([r["label"] for r in rows])
    confirmed = bool(ok_cols and ok_rows and conf >= 0.45)
    if not ok_cols:
        warns.append("border columns not monotonic or too few")
    if not ok_rows:
        warns.append("border rows not monotonic or too few")

    return {
        "cols": cols,
        "rows": rows,
        "confidence": round(min(0.99, max(0.0, conf)), 3),
        "confirmed": confirmed,
        "source": str(grid.get("source") or ""),
        "warnings": warns,
    }


def nearest_label(
    value: float,
    labels: list[dict[str, Any]],
    *,
    axis: str,
    ambiguity_ratio: float = 0.35,
) -> str | None:
    """Return nearest label along x or y, or None if ambiguous / empty."""
    if not labels or value is None:
        return None
    key = "x" if axis == "x" else "y"
    scored = []
    for lab in labels:
        try:
            pos = float(lab[key])
        except (TypeError, ValueError, KeyError):
            continue
        scored.append((abs(pos - float(value)), str(lab["label"]), pos))
    if not scored:
        return None
    scored.sort()
    best_dist, best_lab, _ = scored[0]
    if len(scored) == 1:
        return best_lab
    # Spacing between neighbors for ambiguity threshold
    positions = sorted(float(l[key]) for l in labels if l.get(key) is not None)
    gaps = [positions[i + 1] - positions[i] for i in range(len(positions) - 1)]
    med = sorted(gaps)[len(gaps) // 2] if gaps else 0.08
    thresh = max(0.02, float(ambiguity_ratio) * med)
    second = scored[1][0]
    # Ambiguous when nearly equidistant to two labels
    if second - best_dist < thresh and best_dist > thresh * 0.25:
        return None
    # Too far from any label center
    if best_dist > med * 0.75 and med > 0:
        return None
    return best_lab


def map_point_to_drawing_zone(
    x_frac: float,
    y_frac: float,
    grid: dict[str, Any] | None,
) -> str | None:
    """Confirmed cell like A-8, or None when grid/position is unconfirmed."""
    g = validate_border_grid(grid)
    if not g.get("confirmed"):
        return None
    try:
        xf = float(x_frac)
        yf = float(y_frac)
    except (TypeError, ValueError):
        return None
    if not (0.0 <= xf <= 1.0 and 0.0 <= yf <= 1.0):
        return None
    col = nearest_label(xf, g.get("cols") or [], axis="x")
    row = nearest_label(yf, g.get("rows") or [], axis="y")
    if not col or not row:
        return None
    return f"{row}-{col}"


def _pdf_text_border_candidates(page: Any) -> dict[str, Any]:
    """Harvest short tokens near page edges from the PDF text layer."""
    rect = page.rect
    w, h = float(rect.width), float(rect.height)
    if w <= 0 or h <= 0:
        return empty_border_grid(reason="empty page")
    words = page.get_text("words") or []
    cols: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []
    for word in words:
        try:
            x0, y0, x1, y1, text = word[:5]
        except (TypeError, ValueError):
            continue
        t = str(text or "").strip()
        cx = (float(x0) + float(x1)) / 2.0
        cy = (float(y0) + float(y1)) / 2.0
        near_top = float(y0) < h * 0.045
        near_bot = float(y1) > h * 0.955
        near_left = float(x0) < w * 0.04
        near_right = float(x1) > w * 0.96
        col_lab = _normalize_col_label(t)
        row_lab = _normalize_row_label(t)
        if col_lab and (near_top or near_bot):
            cols.append({"label": col_lab, "x": cx / w})
        if row_lab and (near_left or near_right):
            rows.append({"label": row_lab, "y": cy / h})
    return validate_border_grid(
        {
            "cols": cols,
            "rows": rows,
            "confidence": 0.8 if cols and rows else 0.2,
            "source": "pdf_text",
        }
    )


def _render_edge_strips(
    page: Any,
    *,
    dpi: int = 260,
) -> dict[str, dict[str, Any]]:
    """Render thin border strips as JPEG payloads for OCR/VLM."""
    import fitz
    from PIL import Image

    from app.route_card.drawing_mind.page_images import _encode_image

    rect = page.rect
    w, h = float(rect.width), float(rect.height)
    zoom = max(72, int(dpi)) / 72.0
    matrix = fitz.Matrix(zoom, zoom)
    strip_h = h * 0.055
    strip_w = w * 0.045
    clips = {
        "top": fitz.Rect(rect.x0, rect.y0, rect.x1, rect.y0 + strip_h),
        "bottom": fitz.Rect(rect.x0, rect.y1 - strip_h, rect.x1, rect.y1),
        "left": fitz.Rect(rect.x0, rect.y0, rect.x0 + strip_w, rect.y1),
        "right": fitz.Rect(rect.x1 - strip_w, rect.y0, rect.x1, rect.y1),
    }
    out: dict[str, dict[str, Any]] = {}
    for name, clip in clips.items():
        pix = page.get_pixmap(matrix=matrix, clip=clip, alpha=False)
        img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        enc = _encode_image(img, image_format="JPEG", jpeg_quality=92, max_edge=2200)
        out[name] = {
            "mime": enc["mime"],
            "b64": enc["b64"],
            "raw": enc["raw"],
            "width": enc["width"],
            "height": enc["height"],
            "clip": (float(clip.x0), float(clip.y0), float(clip.x1), float(clip.y1)),
        }
    return out


def _ocr_strip_labels(
    strip: dict[str, Any],
    *,
    kind: str,
    page_w: float,
    page_h: float,
) -> list[dict[str, Any]]:
    """OCR one border strip; return labels with page-fraction positions."""
    raw = strip.get("raw") or b""
    if not raw:
        return []
    try:
        from app.route_card.pdf_ingest import _configure_tesseract
    except Exception:
        return []
    ok, _ = _configure_tesseract()
    if not ok:
        return []
    try:
        import pytesseract
        from PIL import Image

        from app.route_card.drawing_mind.page_images import _preprocess_for_ocr
    except ImportError:
        return []

    try:
        img = Image.open(io.BytesIO(raw))
        img = _preprocess_for_ocr(img)
        data = pytesseract.image_to_data(img, config="--psm 11", output_type=pytesseract.Output.DICT)
    except Exception:
        return []

    clip = strip.get("clip") or (0, 0, page_w, page_h)
    cx0, cy0, cx1, cy1 = clip
    sw = max(1.0, float(cx1 - cx0))
    sh = max(1.0, float(cy1 - cy0))
    iw = max(1, int(img.size[0]))
    ih = max(1, int(img.size[1]))
    found: list[dict[str, Any]] = []
    n = len(data.get("text") or [])
    for i in range(n):
        t = str(data["text"][i] or "").strip()
        if not t:
            continue
        try:
            conf = float(data["conf"][i])
        except (TypeError, ValueError):
            conf = -1
        if conf < 40:
            continue
        left = float(data["left"][i])
        top = float(data["top"][i])
        ww = float(data["width"][i])
        hh = float(data["height"][i])
        # Map strip pixel → page coords
        px = cx0 + (left + ww / 2.0) / iw * sw
        py = cy0 + (top + hh / 2.0) / ih * sh
        if kind == "col":
            lab = _normalize_col_label(t)
            if lab:
                found.append({"label": lab, "x": px / page_w})
        else:
            lab = _normalize_row_label(t)
            if lab:
                found.append({"label": lab, "y": py / page_h})
    return found


def detect_border_grid_ocr(pdf_bytes: bytes, page_no: int) -> dict[str, Any]:
    """OCR edge strips (+ PDF text) for printed border labels."""
    import fitz

    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        idx = int(page_no) - 1
        if idx < 0 or idx >= doc.page_count:
            return empty_border_grid(reason="bad page")
        page = doc.load_page(idx)
        text_grid = _pdf_text_border_candidates(page)
        if text_grid.get("confirmed"):
            return text_grid

        strips = _render_edge_strips(page)
        rect = page.rect
        w, h = float(rect.width), float(rect.height)
        cols: list[dict[str, Any]] = list(text_grid.get("cols") or [])
        rows: list[dict[str, Any]] = list(text_grid.get("rows") or [])
        for edge in ("top", "bottom"):
            cols.extend(
                _ocr_strip_labels(strips[edge], kind="col", page_w=w, page_h=h)
            )
        for edge in ("left", "right"):
            rows.extend(
                _ocr_strip_labels(strips[edge], kind="row", page_w=w, page_h=h)
            )
        return validate_border_grid(
            {
                "cols": cols,
                "rows": rows,
                "confidence": 0.7,
                "source": "ocr",
                "warnings": list(text_grid.get("warnings") or []),
            }
        )
    finally:
        doc.close()


def detect_border_grid_vlm(
    pdf_bytes: bytes,
    page_no: int,
    *,
    model: str,
    base_url: str,
    timeout: float,
    max_tokens: int = 512,
    cancel_event=None,
    system: str | None = None,
) -> dict[str, Any]:
    """Vision-read border strips when OCR cannot confirm the frame."""
    import fitz

    from app.route_card.analyze_jobs import check_cancelled
    from app.route_card.drawing_mind.ollama_client import chat_vision

    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        idx = int(page_no) - 1
        if idx < 0 or idx >= doc.page_count:
            return empty_border_grid(reason="bad page")
        check_cancelled(cancel_event)
        page = doc.load_page(idx)
        strips = _render_edge_strips(page, dpi=240)
    finally:
        doc.close()

    images = [
        strips["top"]["b64"],
        strips["bottom"]["b64"],
        strips["left"]["b64"],
        strips["right"]["b64"],
    ]
    try:
        raw = chat_vision(
            prompt=BORDER_VLM_PROMPT,
            images_b64=images,
            model=model,
            base_url=base_url,
            timeout=timeout,
            temperature=0.0,
            system=system
            or (
                "You read engineering drawing border zone labels. "
                "JSON only — no markdown fences."
            ),
            cancel_event=cancel_event,
            image_mime="image/jpeg",
            max_tokens=max_tokens,
        )
        data = _parse_json(raw)
    except Exception as exc:
        return empty_border_grid(reason=f"border VLM skipped: {exc}")

    data["source"] = "vlm"
    if data.get("confidence") is None:
        data["confidence"] = 0.75
    return validate_border_grid(data)


def detect_border_grid(
    pdf_bytes: bytes,
    page_no: int,
    *,
    model: str | None = None,
    base_url: str | None = None,
    timeout: float = 120.0,
    cancel_event=None,
    allow_vlm: bool = True,
) -> dict[str, Any]:
    """Detect printed border grid: PDF text → OCR → optional VLM."""
    grid = detect_border_grid_ocr(pdf_bytes, page_no)
    if grid.get("confirmed"):
        return grid
    if allow_vlm and model and base_url:
        vlm = detect_border_grid_vlm(
            pdf_bytes,
            page_no,
            model=model,
            base_url=base_url,
            timeout=timeout,
            cancel_event=cancel_event,
        )
        if vlm.get("confirmed"):
            return vlm
        # Prefer whichever has more labels even if unconfirmed
        if len(vlm.get("cols") or []) + len(vlm.get("rows") or []) > len(
            grid.get("cols") or []
        ) + len(grid.get("rows") or []):
            return vlm
    return grid


def locate_callout_point(
    pdf_bytes: bytes,
    page_no: int,
    group: dict[str, Any],
) -> tuple[float, float] | None:
    """Return callout center as (x_frac, y_frac) or None if not found."""
    import fitz

    raw = str(group.get("rawText") or "").strip()
    parent = group.get("parentItemNo")
    needles: list[str] = []
    if raw:
        # Prefer leading tokens of the callout
        head = re.split(r"[\n;]", raw)[0]
        needles.append(head.strip())
        needles.append(re.sub(r"\s+", "", head)[:24])
    if parent is not None:
        needles.append(str(parent))
        needles.append(f"{parent},")
    needles = [n for n in needles if n]
    if not needles:
        return None

    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        idx = int(page_no) - 1
        if idx < 0 or idx >= doc.page_count:
            return None
        page = doc.load_page(idx)
        rect = page.rect
        w, h = float(rect.width), float(rect.height)
        if w <= 0 or h <= 0:
            return None
        words = page.get_text("words") or []
        best = None
        best_score = -1
        for word in words:
            try:
                x0, y0, x1, y1, text = word[:5]
            except (TypeError, ValueError):
                continue
            t = str(text or "").strip()
            if not t:
                continue
            t_compact = re.sub(r"\s+", "", t)
            score = 0
            for n in needles:
                n_c = re.sub(r"\s+", "", n)
                if t == n or t.startswith(n) or n.startswith(t):
                    score = max(score, min(len(t), len(n)))
                elif n_c and (n_c in t_compact or t_compact in n_c):
                    score = max(score, min(len(t_compact), len(n_c)) // 2)
            if score > best_score:
                best_score = score
                best = (
                    ((float(x0) + float(x1)) / 2.0) / w,
                    ((float(y0) + float(y1)) / 2.0) / h,
                )
        if best is None or best_score < 2:
            return None
        return best
    finally:
        doc.close()


def annotate_groups_with_drawing_zones(
    groups: list[dict[str, Any]],
    *,
    pdf_bytes: bytes,
    border_grids: dict[int, dict[str, Any]] | None = None,
    model: str | None = None,
    base_url: str | None = None,
    timeout: float = 120.0,
    cancel_event=None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Set drawingZone on balloon groups only when the cell is confirmed."""
    warns: list[str] = []
    grids = dict(border_grids or {})
    out: list[dict[str, Any]] = []

    pages_needed: set[int] = set()
    for g in groups or []:
        if not isinstance(g, dict):
            continue
        try:
            pages_needed.add(int(g.get("sourcePage") or 1))
        except (TypeError, ValueError):
            pages_needed.add(1)

    for page_no in sorted(pages_needed):
        if page_no in grids and grids[page_no].get("confirmed"):
            continue
        grid = detect_border_grid(
            pdf_bytes,
            page_no,
            model=model,
            base_url=base_url,
            timeout=timeout,
            cancel_event=cancel_event,
            allow_vlm=bool(model and base_url),
        )
        grids[page_no] = grid
        if grid.get("confirmed"):
            warns.append(
                f"border grid page {page_no}: {len(grid.get('cols') or [])} cols × "
                f"{len(grid.get('rows') or [])} rows ({grid.get('source')})"
            )
        else:
            warns.append(
                f"border grid page {page_no}: unconfirmed — Zone omitted "
                f"({'; '.join((grid.get('warnings') or [])[:2]) or 'weak detect'})"
            )

    for g in groups or []:
        if not isinstance(g, dict):
            continue
        ng = dict(g)
        ng.pop("drawingZone", None)
        try:
            page_no = int(g.get("sourcePage") or 1)
        except (TypeError, ValueError):
            page_no = 1
        grid = grids.get(page_no) or empty_border_grid()
        if not grid.get("confirmed"):
            out.append(ng)
            continue
        pt = locate_callout_point(pdf_bytes, page_no, g)
        if not pt:
            out.append(ng)
            continue
        zone = map_point_to_drawing_zone(pt[0], pt[1], grid)
        if zone:
            ng["drawingZone"] = zone
        out.append(ng)
    return out, warns
