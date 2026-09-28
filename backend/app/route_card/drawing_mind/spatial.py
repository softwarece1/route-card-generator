"""Build a spatial entity graph from word bounding boxes."""

from __future__ import annotations

import re
from typing import Any

WORD_DIM = re.compile(r"^(\d+(?:\.\d+)?)$")
BALLOON = re.compile(r"^(\d{1,3})$")
SURFACE_HINT = re.compile(
    r"\b(DC\s*OUT|AC\s*IN|AC\s*OUT|CONNECTOR|FACIA|FRONT|REAR|"
    r"TOP\s+VIEW|SIDE\s+VIEW|BOTTOM|MOUNTING\s+FACE)\b",
    re.I,
)
# Sticker/legend text — not a mounting face (do not treat as primary surface)
SURFACE_STICKER_NOISE = re.compile(r"\bPOWER\s+SUPPLY\b", re.I)
CONNECTOR_REF = re.compile(r"\b([JXCP]\d{1,3}|SFPDP|P\d{1,2})\b", re.I)
ITEM_NEAR = re.compile(r"(?:ITEMS?|ITMS?|IT\.?)\s*(?:NO\.?|#)?\s*-?\s*(\d{1,3})", re.I)


def _cx(box: dict) -> float:
    return (float(box["x0"]) + float(box["x1"])) / 2.0


def _cy(box: dict) -> float:
    return (float(box["y0"]) + float(box["y1"])) / 2.0


def _dist(a: dict, b: dict) -> float:
    return ((_cx(a) - _cx(b)) ** 2 + (_cy(a) - _cy(b)) ** 2) ** 0.5


def _page_extent(words: list[dict]) -> tuple[float, float, float, float]:
    if not words:
        return 0.0, 0.0, 1.0, 1.0
    return (
        min(w["x0"] for w in words),
        min(w["y0"] for w in words),
        max(w["x1"] for w in words),
        max(w["y1"] for w in words),
    )


def detect_unit(text: str) -> str:
    if re.search(r"ALL\s+DIMENSIONS\s+ARE\s+IN\s+MM|DIMS?\s+IN\s+MM", text or "", re.I):
        return "mm"
    return "mm"  # BEL GA default


def build_page_entities(page: dict[str, Any]) -> dict[str, Any]:
    """Classify words on one page into balloons, dimensions, surfaces, connectors."""
    page_no = int(page.get("page") or 1)
    words = list(page.get("words") or [])
    width = float(page.get("width") or 0) or 1.0
    height = float(page.get("height") or 0) or 1.0
    x0, y0, x1, y1 = _page_extent(words)
    span_x = max(x1 - x0, 1.0)
    span_y = max(y1 - y0, 1.0)

    balloons: list[dict] = []
    dimensions: list[dict] = []
    surfaces: list[dict] = []
    connectors: list[dict] = []

    # Merge adjacent surface tokens (DC + OUT)
    texts = [str(w.get("text") or "") for w in words]
    for i, w in enumerate(words):
        t = texts[i].strip()
        if not t:
            continue
        # Two-token surface: DC OUT
        if i + 1 < len(words):
            pair = f"{t} {texts[i + 1].strip()}"
            if SURFACE_HINT.search(pair) and _dist(w, words[i + 1]) < span_x * 0.08:
                surfaces.append(
                    {
                        "label": re.sub(r"\s+", " ", pair).upper(),
                        "x0": w["x0"],
                        "y0": min(w["y0"], words[i + 1]["y0"]),
                        "x1": words[i + 1]["x1"],
                        "y1": max(w["y1"], words[i + 1]["y1"]),
                        "page": page_no,
                    }
                )
        if SURFACE_HINT.search(t) and len(t) > 3:
            surfaces.append(
                {
                    "label": re.sub(r"\s+", " ", t).upper(),
                    "x0": w["x0"],
                    "y0": w["y0"],
                    "x1": w["x1"],
                    "y1": w["y1"],
                    "page": page_no,
                }
            )
        # Still record POWER SUPPLY as a weak label (sticker content) for PL matching only
        elif SURFACE_STICKER_NOISE.search(t) and len(t) > 3:
            surfaces.append(
                {
                    "label": re.sub(r"\s+", " ", t).upper(),
                    "x0": w["x0"],
                    "y0": w["y0"],
                    "x1": w["x1"],
                    "y1": w["y1"],
                    "page": page_no,
                    "weak": True,
                }
            )
        for m in CONNECTOR_REF.finditer(t):
            connectors.append(
                {
                    "ref": m.group(1).upper(),
                    "x0": w["x0"],
                    "y0": w["y0"],
                    "x1": w["x1"],
                    "y1": w["y1"],
                    "page": page_no,
                }
            )
        bm = BALLOON.fullmatch(t)
        if bm:
            n = int(bm.group(1))
            # Balloons are small isolated digits (item callouts), not years/sheet sizes
            if 1 <= n <= 80:
                # Prefer compact glyphs (height small vs page)
                glyph_h = max(float(w["y1"]) - float(w["y0"]), 1.0)
                if glyph_h < span_y * 0.06:
                    balloons.append(
                        {
                            "itemNo": n,
                            "x0": w["x0"],
                            "y0": w["y0"],
                            "x1": w["x1"],
                            "y1": w["y1"],
                            "page": page_no,
                            "cx": _cx(w),
                            "cy": _cy(w),
                        }
                    )
        dm = WORD_DIM.fullmatch(t)
        if dm and ("." in t or float(dm.group(1)) in {5.0, 5, 10.0, 10}):
            val = float(dm.group(1))
            if 0.5 <= val <= 2000:
                dimensions.append(
                    {
                        "value": val,
                        "raw": t,
                        "x0": w["x0"],
                        "y0": w["y0"],
                        "x1": w["x1"],
                        "y1": w["y1"],
                        "page": page_no,
                        "cx": _cx(w),
                        "cy": _cy(w),
                    }
                )
        elif dm:
            val = float(dm.group(1))
            if 1.0 <= val <= 500 and "." in t:
                dimensions.append(
                    {
                        "value": val,
                        "raw": t,
                        "x0": w["x0"],
                        "y0": w["y0"],
                        "x1": w["x1"],
                        "y1": w["y1"],
                        "page": page_no,
                        "cx": _cx(w),
                        "cy": _cy(w),
                    }
                )

    # Deduplicate surfaces by label+approx position
    uniq_surf: list[dict] = []
    seen_s: set[str] = set()
    for s in surfaces:
        key = f"{s['label']}:{int(s['x0']//10)}:{int(s['y0']//10)}"
        if key not in seen_s:
            seen_s.add(key)
            uniq_surf.append(s)

    return {
        "page": page_no,
        "width": width,
        "height": height,
        "extent": {"x0": x0, "y0": y0, "x1": x1, "y1": y1},
        "balloons": balloons,
        "dimensions": dimensions,
        "surfaces": uniq_surf,
        "connectors": connectors,
        "words": words,
    }


def build_spatial_graph(spatial_pages: list[dict[str, Any]], full_text: str = "") -> dict[str, Any]:
    pages = [build_page_entities(p) for p in (spatial_pages or [])]
    return {
        "unit": detect_unit(full_text),
        "pages": pages,
        "allBalloons": [b for p in pages for b in p["balloons"]],
        "allDimensions": [d for p in pages for d in p["dimensions"]],
        "allSurfaces": [s for p in pages for s in p["surfaces"]],
        "allConnectors": [c for p in pages for c in p["connectors"]],
    }


def nearest_surface(balloon: dict, surfaces: list[dict], max_dist_frac: float = 0.35) -> str:
    if not surfaces:
        return ""
    # Prefer surfaces on same page to the right/above of left-side stickers
    same = [s for s in surfaces if s.get("page") == balloon.get("page")]
    pool = same or surfaces
    best = None
    best_d = 1e18
    for s in pool:
        d = _dist(balloon, s)
        if d < best_d:
            best_d = d
            best = s
    if not best:
        return ""
    # Rough page span
    return best["label"] if best_d < 5000 else best["label"]


def classify_offset_role(
    dim: dict,
    balloon: dict,
    page_extent: dict,
) -> str | None:
    """Guess whether a nearby dimension is from top / left / below another item."""
    ex0, ey0 = page_extent["x0"], page_extent["y0"]
    ex1, ey1 = page_extent["x1"], page_extent["y1"]
    span_x = max(ex1 - ex0, 1.0)
    span_y = max(ey1 - ey0, 1.0)
    dx = dim["cx"] - balloon["cx"]
    dy = dim["cy"] - balloon["cy"]
    # Dimension between balloon and left edge of view
    if abs(dx) < span_x * 0.25 and dim["cx"] < balloon["cx"] and abs(dy) < span_y * 0.15:
        return "left"
    if abs(dy) < span_y * 0.25 and dim["cy"] < balloon["cy"] and abs(dx) < span_x * 0.2:
        return "top"
    if abs(dy) < span_y * 0.25 and dim["cy"] > balloon["cy"] and abs(dx) < span_x * 0.2:
        return "gap_below"
    if abs(dx) < span_x * 0.15 and abs(dy) < span_y * 0.15:
        # Very close — prefer top if above mid of balloon, else left
        if dim["cy"] <= balloon["cy"]:
            return "top"
        return "left"
    return None


def dims_near(balloon: dict, dimensions: list[dict], radius: float) -> list[dict]:
    return sorted(
        [d for d in dimensions if d.get("page") == balloon.get("page") and _dist(d, balloon) <= radius],
        key=lambda d: _dist(d, balloon),
    )
