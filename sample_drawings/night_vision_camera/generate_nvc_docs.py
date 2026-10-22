"""Generate realistic sample docs for a Night Vision Camera.

- GA  → PDF (engineering sheet: zone border, dimensioned views, section hatch,
  balloons with leaders, BOM, specs, title block) with a real text layer so the
  app extracts offline with cpu_spatial — no OCR/VLM.
- PL  → Excel (.xlsx), matches partslist_parser header detection (header in first 5 rows).
- WL  → Excel (.xlsx), rows match the wirelist_parser WIRE_ROW token order.
- No BEL branding (fictional company: OPTRONIX SYSTEMS PVT. LTD.)

Run:
  cd backend
  PYTHONPATH=. .venv/Scripts/python.exe ../sample_drawings/night_vision_camera/generate_nvc_docs.py
"""

from __future__ import annotations

import math
from pathlib import Path

import fitz

OUT = Path(__file__).resolve().parent

COMPANY = "OPTRONIX SYSTEMS PVT. LTD."
CITY = "BENGALURU, INDIA"
PART_NO = "1121 990 001 01"
PART_NO_COMPACT = "112199000101"
TITLE = "NIGHT VISION CAMERA"
BLACK = (0, 0, 0)
GREY = (0.45, 0.45, 0.45)


# ----------------------------------------------------------------------------- helpers
def _text(page, x, y, s, size=9, bold=False, color=BLACK):
    page.insert_text((x, y), s, fontsize=size, fontname="hebo" if bold else "helv", color=color)


def _ctext(page, cx, y, s, size=9, bold=False, color=BLACK):
    """Centered text."""
    w = fitz.get_text_length(s, fontname="hebo" if bold else "helv", fontsize=size)
    _text(page, cx - w / 2, y, s, size=size, bold=bold, color=color)


def _arrow(page, tip: fitz.Point, angle_deg: float, length=7.0, width=2.6):
    a = math.radians(angle_deg)
    base = fitz.Point(tip.x - length * math.cos(a), tip.y - length * math.sin(a))
    perp = fitz.Point(-math.sin(a), math.cos(a))
    p1 = fitz.Point(base.x + perp.x * width, base.y + perp.y * width)
    p2 = fitz.Point(base.x - perp.x * width, base.y - perp.y * width)
    page.draw_polyline([p1, tip, p2], color=BLACK, width=0.7, closePath=True, fill=BLACK)


def _dim_h(page, x0, x1, y, label, ext_up=8, size=8):
    """Horizontal dimension with extension lines + arrows + centered label."""
    page.draw_line(fitz.Point(x0, y - ext_up), fitz.Point(x0, y + 3), color=BLACK, width=0.5)
    page.draw_line(fitz.Point(x1, y - ext_up), fitz.Point(x1, y + 3), color=BLACK, width=0.5)
    page.draw_line(fitz.Point(x0, y), fitz.Point(x1, y), color=BLACK, width=0.6)
    _arrow(page, fitz.Point(x0, y), 180)
    _arrow(page, fitz.Point(x1, y), 0)
    _ctext(page, (x0 + x1) / 2, y - 3, label, size=size)


def _dim_v(page, x, y0, y1, label, ext=8, size=8):
    page.draw_line(fitz.Point(x - ext, y0), fitz.Point(x + 3, y0), color=BLACK, width=0.5)
    page.draw_line(fitz.Point(x - ext, y1), fitz.Point(x + 3, y1), color=BLACK, width=0.5)
    page.draw_line(fitz.Point(x, y0), fitz.Point(x, y1), color=BLACK, width=0.6)
    _arrow(page, fitz.Point(x, y0), 270)
    _arrow(page, fitz.Point(x, y1), 90)
    _text(page, x + 4, (y0 + y1) / 2 + 3, label, size=size)


def _balloon(page, cx, cy, num, leader_to: fitz.Point | None = None, r=10):
    if leader_to is not None:
        page.draw_line(fitz.Point(cx, cy), leader_to, color=BLACK, width=0.6)
        page.draw_circle(leader_to, 1.1, color=BLACK, fill=BLACK)
    page.draw_circle(fitz.Point(cx, cy), r, color=BLACK, width=1.0, fill=(1, 1, 1))
    _ctext(page, cx, cy + 3.2, str(num), size=9, bold=True)


def _hatch(page, rect: fitz.Rect, step=7.0):
    x = rect.x0 - rect.height
    while x < rect.x1:
        p0 = fitz.Point(max(rect.x0, x), rect.y1 - max(0, min(rect.height, x + rect.height - rect.x0)))
        # simple clipped 45° lines
        xa, ya = x, rect.y1
        xb, yb = x + rect.height, rect.y0
        # clip to rect horizontally
        if xa < rect.x0:
            yb_adj = rect.y1 - (rect.x0 - xa)
            xa, ya = rect.x0, yb_adj
        if xb > rect.x1:
            ya_adj = rect.y0 + (xb - rect.x1)
            xb, yb = rect.x1, ya_adj
        if xa < xb:
            page.draw_line(fitz.Point(xa, ya), fitz.Point(xb, yb), color=GREY, width=0.4)
        x += step


def _zone_border(page, outer: fitz.Rect, cols=8, rows=6):
    inner = fitz.Rect(outer.x0 + 14, outer.y0 + 14, outer.x1 - 14, outer.y1 - 14)
    page.draw_rect(outer, color=BLACK, width=1.4)
    page.draw_rect(inner, color=BLACK, width=0.8)
    # column numbers top/bottom
    for i in range(cols):
        x0 = outer.x0 + 14 + (inner.width) * i / cols
        x1 = outer.x0 + 14 + (inner.width) * (i + 1) / cols
        if i:
            page.draw_line(fitz.Point(x0, outer.y0), fitz.Point(x0, outer.y0 + 14), color=BLACK, width=0.6)
            page.draw_line(fitz.Point(x0, outer.y1 - 14), fitz.Point(x0, outer.y1), color=BLACK, width=0.6)
        _ctext(page, (x0 + x1) / 2, outer.y0 + 10.5, str(i + 1), size=7)
        _ctext(page, (x0 + x1) / 2, outer.y1 - 4.5, str(i + 1), size=7)
    # row letters left/right
    letters = "ABCDEFGH"
    for j in range(rows):
        y0 = outer.y0 + 14 + (inner.height) * j / rows
        y1 = outer.y0 + 14 + (inner.height) * (j + 1) / rows
        if j:
            page.draw_line(fitz.Point(outer.x0, y0), fitz.Point(outer.x0 + 14, y0), color=BLACK, width=0.6)
            page.draw_line(fitz.Point(outer.x1 - 14, y0), fitz.Point(outer.x1, y0), color=BLACK, width=0.6)
        _ctext(page, outer.x0 + 7, (y0 + y1) / 2 + 2.5, letters[j], size=7)
        _ctext(page, outer.x1 - 7, (y0 + y1) / 2 + 2.5, letters[j], size=7)
    return inner


def _ruled_table(page, rect: fitz.Rect, col_xs: list[float], row_h: float, n_rows: int,
                 headers: list[str], header_bold=True, header_size=8, line_w=0.6):
    """Draw grid; return list of row baseline ys (first = header)."""
    page.draw_rect(rect, color=BLACK, width=1.0)
    for x in col_xs[1:-1]:
        page.draw_line(fitz.Point(x, rect.y0), fitz.Point(x, rect.y1), color=BLACK, width=line_w)
    ys = []
    for r in range(n_rows + 1):
        y = rect.y0 + row_h * (r + 1)
        if r < n_rows:
            page.draw_line(fitz.Point(rect.x0, y), fitz.Point(rect.x1, y), color=BLACK, width=0.4 if r else line_w)
        ys.append(rect.y0 + row_h * r + row_h - 4)
    for i, h in enumerate(headers):
        _text(page, col_xs[i] + 4, ys[0], h, size=header_size, bold=header_bold)
    return ys


# ----------------------------------------------------------------------------- GA
PL_ITEMS = [
    (1, "HOUSING NVC MAIN BODY AL", "1121 990 101 01", "1", "NO", "AL ALLOY 6061-T6"),
    (2, "LABEL NAMEPLATE NVC", "2127 990 201 02", "1", "NO", "POLYESTER"),
    (3, "LABEL WARNING IR", "2127 990 201 03", "1", "NO", "POLYESTER"),
    (4, "LENS OBJECTIVE IR F1.4", "4466 990 301 04", "1", "NO", "GLASS + AL"),
    (5, "OCULAR ASSEMBLY NVC", "4466 990 301 05", "1", "NO", "GLASS + AL"),
    (6, "PCB IMAGE SENSOR ASSY", "4579 990 401 06", "1", "NO", "FR-4 CMOS"),
    (7, "CABLE HARNESS NVC", "1121 990 501 07", "1", "NO", "PTFE WIRES"),
    (8, "CONNECTOR PANEL REAR", "4615 990 601 08", "1", "NO", "SS 304"),
    (9, "GASKET REAR PANEL", "4909 990 701 09", "1", "NO", "SILICONE"),
    (10, "ADHESIVE THREAD LOCKER", "5605 990 801 10", "0.1", "NO", "ANAEROBIC"),
    (11, "SCREW M3x8 SS", "4627 990 901 11", "8", "NO", "SS 304"),
    (12, "IR ILLUMINATOR MODULE", "4466 990 311 12", "1", "NO", "AL + LED"),
]


def generate_ga() -> Path:
    doc = fitz.open()
    page = doc.new_page(width=1191, height=842)  # A3 landscape
    inner = _zone_border(page, fitz.Rect(24, 24, 1167, 818))

    # ---------------- FRONT VIEW (flange + concentric lens rings + 4 holes)
    fv = fitz.Rect(70, 120, 300, 350)
    cx, cy = (fv.x0 + fv.x1) / 2, (fv.y0 + fv.y1) / 2
    page.draw_rect(fv, color=BLACK, width=1.3)
    for r in (78, 58, 40, 26):
        page.draw_circle(fitz.Point(cx, cy), r, color=BLACK, width=1.0 if r > 40 else 0.7)
    for dx, dy in ((1, 1), (1, -1), (-1, 1), (-1, -1)):
        hx, hy = cx + dx * 95, cy + dy * 95
        page.draw_circle(fitz.Point(hx, hy), 7, color=BLACK, width=0.9)
        page.draw_circle(fitz.Point(hx, hy), 3, color=BLACK, width=0.5)
    # centerlines
    page.draw_line(fitz.Point(cx - 115, cy), fitz.Point(cx + 115, cy), color=GREY, width=0.4, dashes="[4 3] 0")
    page.draw_line(fitz.Point(cx, cy - 115), fitz.Point(cx, cy + 115), color=GREY, width=0.4, dashes="[4 3] 0")

    _dim_h(page, fv.x0, fv.x1, fv.y0 - 18, "72.0")
    _dim_v(page, fv.x0 - 18, fv.y0, fv.y1, "68.5")
    _text(page, cx + 30, cy - 62, "Ø56.0", size=8)

    _ctext(page, cx, fv.y1 + 18, "FRONT VIEW", size=10, bold=True)
    _ctext(page, cx, fv.y1 + 32, "SCALE 1:1", size=8)
    _ctext(page, cx, fv.y1 + 48, "FRONT FACE", size=10, bold=True)

    # labels (items 2 & 3) with 5.0 offsets — used by cpu_spatial
    lx, ly = fv.x0 + 36, fv.y0 + 34
    page.draw_rect(fitz.Rect(lx, ly, lx + 46, ly + 14), color=BLACK, width=0.7)
    page.draw_rect(fitz.Rect(lx, ly + 24, lx + 46, ly + 38), color=BLACK, width=0.7)
    _balloon(page, lx - 22, ly + 7, 2, leader_to=fitz.Point(lx, ly + 7))
    _balloon(page, lx - 22, ly + 31, 3, leader_to=fitz.Point(lx, ly + 31))
    _text(page, lx + 2, ly - 4, "5.0", size=8)
    _text(page, lx - 16, ly - 14, "5.0", size=8)

    # ---------------- SIDE VIEW (stepped barrel profile)
    sv_y0, sv_y1 = 150, 320
    prof = [
        (360, 200), (360, 270),          # lens front
        (395, 270), (395, 290), (470, 290), (470, 300),
        (640, 300), (640, 170), (470, 170), (470, 180),
        (395, 180), (395, 200), (360, 200),
    ]
    page.draw_polyline([fitz.Point(x, y) for x, y in prof], color=BLACK, width=1.3, closePath=True)
    # lens barrel ribs
    for rx in range(372, 393, 5):
        page.draw_line(fitz.Point(rx, 203), fitz.Point(rx, 267), color=BLACK, width=0.5)
    # body panel lines
    page.draw_line(fitz.Point(470, 180), fitz.Point(470, 290), color=BLACK, width=0.6)
    page.draw_line(fitz.Point(560, 170), fitz.Point(560, 300), color=BLACK, width=0.5)
    page.draw_rect(fitz.Rect(585, 190, 625, 225), color=BLACK, width=0.8)  # top block
    _dim_h(page, 360, 640, 135, "142.3")
    _dim_h(page, 360, 470, 318, "48.7")
    _dim_h(page, 470, 640, 318, "93.6")
    _dim_v(page, 662, 170, 300, "Ø62.0")
    _ctext(page, 500, 352, "SIDE VIEW", size=10, bold=True)
    _ctext(page, 500, 366, "SCALE 1:1", size=8)
    _balloon(page, 352, 150, 4, leader_to=fitz.Point(375, 205))
    _balloon(page, 650, 150, 1, leader_to=fitz.Point(600, 175))

    # ---------------- REAR VIEW (connector panel)
    rv = fitz.Rect(90, 470, 270, 650)
    page.draw_rect(rv, color=BLACK, width=1.3)
    rcx, rcy = (rv.x0 + rv.x1) / 2, (rv.y0 + rv.y1) / 2
    page.draw_circle(fitz.Point(rcx - 30, rcy), 26, color=BLACK, width=1.0)
    page.draw_circle(fitz.Point(rcx - 30, rcy), 19, color=BLACK, width=0.6)
    for k in range(8):
        a = math.radians(k * 45)
        page.draw_circle(fitz.Point(rcx - 30 + 12 * math.cos(a), rcy + 12 * math.sin(a)), 1.6, color=BLACK, fill=BLACK)
    page.draw_circle(fitz.Point(rcx + 42, rcy - 25), 15, color=BLACK, width=0.9)
    page.draw_circle(fitz.Point(rcx + 42, rcy + 30), 15, color=BLACK, width=0.9)
    _text(page, rcx - 44, rcy + 44, "J1 POWER", size=8, bold=True)
    _text(page, rcx + 24, rcy - 46, "J2 VIDEO", size=8, bold=True)
    _ctext(page, rcx, rv.y1 + 16, "REAR VIEW", size=10, bold=True)
    _ctext(page, rcx, rv.y1 + 30, "SCALE 1:1", size=8)
    _ctext(page, rcx, rv.y1 + 46, "REAR FACE", size=10, bold=True)
    _balloon(page, rv.x1 + 24, rv.y0 + 16, 8, leader_to=fitz.Point(rcx + 42, rcy - 25))
    _balloon(page, rv.x0 - 24, rv.y0 + 16, 9, leader_to=fitz.Point(rv.x0 + 8, rcy - 60))
    _text(page, rv.x0 - 10, rv.y0 - 8, "M3 (4x)", size=7)

    # ---------------- SECTION A-A (hatched housing w/ internals)
    sec = fitz.Rect(350, 430, 700, 640)
    page.draw_rect(sec, color=BLACK, width=1.3)
    wall = 14
    inner_sec = fitz.Rect(sec.x0 + wall, sec.y0 + wall, sec.x1 - wall, sec.y1 - wall)
    page.draw_rect(inner_sec, color=BLACK, width=0.8)
    _hatch(page, fitz.Rect(sec.x0, sec.y0, sec.x1, sec.y0 + wall))
    _hatch(page, fitz.Rect(sec.x0, sec.y1 - wall, sec.x1, sec.y1))
    _hatch(page, fitz.Rect(sec.x0, sec.y0, sec.x0 + wall, sec.y1))
    _hatch(page, fitz.Rect(sec.x1 - wall, sec.y0, sec.x1, sec.y1))
    # lens group
    for i, lx0 in enumerate((inner_sec.x0 + 8, inner_sec.x0 + 34, inner_sec.x0 + 58)):
        page.draw_oval(fitz.Rect(lx0, inner_sec.y0 + 24, lx0 + 14, inner_sec.y1 - 24), color=BLACK, width=0.8)
    # sensor PCB
    pcb = fitz.Rect(inner_sec.x0 + 150, inner_sec.y0 + 30, inner_sec.x0 + 162, inner_sec.y1 - 30)
    page.draw_rect(pcb, color=BLACK, width=0.9)
    _hatch(page, pcb, step=4)
    # processor module
    pm = fitz.Rect(inner_sec.x0 + 200, inner_sec.y0 + 46, inner_sec.x0 + 250, inner_sec.y1 - 46)
    page.draw_rect(pm, color=BLACK, width=0.9)
    # harness line
    page.draw_line(fitz.Point(pm.x1, (pm.y0 + pm.y1) / 2), fitz.Point(inner_sec.x1 - 6, (pm.y0 + pm.y1) / 2),
                   color=BLACK, width=0.8, dashes="[3 2] 0")
    _ctext(page, (sec.x0 + sec.x1) / 2, sec.y1 + 16, "SECTION A-A", size=10, bold=True)
    _ctext(page, (sec.x0 + sec.x1) / 2, sec.y1 + 30, "SCALE 1:1", size=8)
    _balloon(page, sec.x0 - 20, sec.y0 - 6, 5, leader_to=fitz.Point(inner_sec.x0 + 40, inner_sec.y0 + 40))
    _balloon(page, sec.x0 + 150, sec.y0 - 14, 6, leader_to=fitz.Point(pcb.x0 + 6, pcb.y0 + 10))
    _balloon(page, sec.x1 + 20, sec.y0 - 6, 7, leader_to=fitz.Point(inner_sec.x1 - 20, (pm.y0 + pm.y1) / 2))
    _balloon(page, sec.x1 + 20, sec.y1 + 6, 12, leader_to=fitz.Point(pm.x1 - 6, pm.y1 - 6))
    _dim_v(page, sec.x0 - 16, sec.y0, sec.y1, "62.0")

    # Parts List lives in the separate PL.xlsx — no BOM table on the GA
    # (avoids title-block / MATERIAL false hits from BOM headers).

    # ---------------- SPECS BOX (top-right)
    spec = fitz.Rect(730, 80, 1000, 80 + 14 * 8 + 18)
    _text(page, spec.x0, spec.y0 - 5, "SPECIFICATIONS (NIGHT VISION CAMERA)", size=8.5, bold=True)
    specs = [
        ("Resolution", "1920 x 1080 (FHD)"),
        ("Sensor Type", "CMOS (sensitive to NIR)"),
        ("Field of View", "12 deg (H) x 9 deg (V)"),
        ("IR Wavelength", "850 NANOMETRE"),
        ("Power Supply", "12 V DC +/- 10%"),
        ("Operating Temp.", "-20 C to +60 C"),
        ("Weight", "1.2 +/- 0.1 kg"),
        ("Protection", "IP67"),
    ]
    sys = _ruled_table(page, spec, [spec.x0, spec.x0 + 110, spec.x1], 14, len(specs), ["PARAMETER", "VALUE"], header_size=7.5)
    for i, (k, v) in enumerate(specs):
        _text(page, spec.x0 + 4, sys[i + 1], k, size=7.5)
        _text(page, spec.x0 + 114, sys[i + 1], v, size=7.5)

    # ---------------- NOTES (below specs; no BOM on this sheet)
    nx, ny = 730, 230
    _text(page, nx, ny, "ASSEMBLY NOTES:", size=11, bold=True)
    notes = [
        "1. ASSEMBLE ITEM 1 HOUSING AS PER THIS GA.",
        "2. STICK ITEM 2 & 3 AS SHOWN USING SUITABLE ADHESIVE ON FRONT FACE.",
        "3. ASSEMBLE ITEM 4 OBJECTIVE LENS AND ITEM 5 OCULAR INTO HOUSING.",
        "4. ASSEMBLE ITEM 6 IMAGE SENSOR PCB ON INTERNAL BOSS. TORQUE SCREWS TO 0.6 Nm.",
        "5. CONNECT HARNESS ITEM 7 AS PER WIRE LIST. REFER INTERCONNECTION TABLE.",
        "6. ASSEMBLE ITEM 8 CONNECTOR PANEL ON REAR FACE. USE ITEM 9 GASKET.",
        "7. USE ITEM 10 THREAD LOCKER ON FASTENERS WHERE INDICATED.",
        "8. PERFORM FUNCTIONAL TEST: POWER, VIDEO OUT, AND IR ILLUMINATOR.",
    ]
    y = ny + 16
    for line in notes:
        _text(page, nx, y, line, size=8)
        y += 14
    _text(page, nx, y + 4, "END OF ASSEMBLY NOTES.", size=7.5)

    _text(page, nx, y + 26, "ALL DIMENSIONS ARE IN MM", size=9, bold=True)
    _text(page, nx, y + 38, "UNLESS OTHERWISE SPECIFIED", size=8)
    _text(page, nx, y + 54, "TOLERANCES:  X.X +/- 0.5   X.XX +/- 0.1", size=8)
    _text(page, nx, y + 68, "SURFACE FINISH: Ra 1.6 um UNLESS OTHERWISE SPECIFIED.", size=8)
    _text(page, nx, y + 84, "WEIGHT: 1.2 +/- 0.1 kg", size=8)

    # interconnection ref (small, above title block)
    _text(page, 440, 700, "INTERCONNECTION TABLE (REF):", size=8.5, bold=True)
    _text(page, 440, 714, "J1-1 +12V   J1-2 0V   J1-3 SHIELD", size=8)
    _text(page, 440, 728, "J2-1 VIDEO+   J2-2 VIDEO-   J2-3 SHIELD", size=8)

    # ---------------- TITLE BLOCK (bottom-right, ruled)
    tb = fitz.Rect(730, 690, 1150, 800)
    page.draw_rect(tb, color=BLACK, width=1.2)
    page.draw_line(fitz.Point(tb.x0, tb.y0 + 34), fitz.Point(tb.x1, tb.y0 + 34), color=BLACK, width=0.8)
    page.draw_line(fitz.Point(tb.x0, tb.y0 + 58), fitz.Point(tb.x1, tb.y0 + 58), color=BLACK, width=0.8)
    page.draw_line(fitz.Point(tb.x0 + 190, tb.y0 + 58), fitz.Point(tb.x0 + 190, tb.y1), color=BLACK, width=0.6)
    page.draw_line(fitz.Point(tb.x0 + 300, tb.y0 + 58), fitz.Point(tb.x0 + 300, tb.y1), color=BLACK, width=0.6)
    _text(page, tb.x0 + 10, tb.y0 + 16, COMPANY, size=11, bold=True)
    _text(page, tb.x0 + 10, tb.y0 + 28, CITY, size=7.5)
    _text(page, tb.x0 + 280, tb.y0 + 22, "ASSEMBLY DRAWING", size=9, bold=True)
    _text(page, tb.x0 + 10, tb.y0 + 50, "TITLE", size=7)
    _text(page, tb.x0 + 50, tb.y0 + 51, TITLE, size=11, bold=True)
    _text(page, tb.x0 + 300 + 8, tb.y0 + 50, "DOC CODE", size=7)
    _text(page, tb.x0 + 300 + 60, tb.y0 + 51, "GA", size=10, bold=True)
    _text(page, tb.x0 + 10, tb.y0 + 74, "NUMBER", size=7)
    _text(page, tb.x0 + 10, tb.y0 + 90, PART_NO, size=12, bold=True)
    _text(page, tb.x0 + 10, tb.y0 + 104, "SHEET No. 001 / 001", size=7.5)
    _text(page, tb.x0 + 196, tb.y0 + 74, "SIZE A3   SCALE NTS", size=7.5)
    _text(page, tb.x0 + 196, tb.y0 + 88, "ISSUE 00  ORIGINAL", size=7.5)
    _text(page, tb.x0 + 196, tb.y0 + 102, "DATE 07.10.26", size=7.5)
    _text(page, tb.x0 + 306, tb.y0 + 74, "DRAWN    R. KUMAR", size=7.5)
    _text(page, tb.x0 + 306, tb.y0 + 88, "CHECKED  S. PATEL", size=7.5)
    _text(page, tb.x0 + 306, tb.y0 + 102, "ENGR     M. SHARMA", size=7.5)

    _text(page, 50, 806, f"THIS DOCUMENT IS THE PROPERTY OF {COMPANY} — REPRODUCTION WITHOUT CONSENT PROHIBITED.", size=6.5, color=GREY)

    path = OUT / f"{PART_NO_COMPACT} - GA.pdf"
    doc.save(path)
    doc.close()
    return path


# ----------------------------------------------------------------------------- Excel helpers
def _xl_styles():
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

    thin = Side(style="thin", color="FF333333")
    return {
        "border": Border(left=thin, right=thin, top=thin, bottom=thin),
        "head_font": Font(bold=True, size=10),
        "head_fill": PatternFill("solid", fgColor="FFE8EDF3"),
        "title_font": Font(bold=True, size=14),
        "sub_font": Font(bold=True, size=11),
        "center": Alignment(horizontal="center", vertical="center"),
        "left": Alignment(horizontal="left", vertical="center"),
    }


# ----------------------------------------------------------------------------- PL (Excel)
def generate_pl() -> Path:
    from openpyxl import Workbook

    st = _xl_styles()
    wb = Workbook()
    ws = wb.active
    ws.title = "PARTS LIST"

    ws["A1"] = COMPANY
    ws["A1"].font = st["sub_font"]
    ws["A2"] = f"PARTS LIST — {TITLE}"
    ws["A2"].font = st["title_font"]
    ws["A3"] = "PART NUMBER"
    ws["B3"] = PART_NO
    ws["B3"].font = st["sub_font"]
    ws["D3"] = "DOC CODE"
    ws["E3"] = "PL"
    ws["A4"] = "SHEET"
    ws["B4"] = "001 / 001"
    ws["D4"] = "ISSUE"
    ws["E4"] = "00"

    headers = ["ITEM", "DESIGNATION", "PART NO", "QTY", "UNT", "MATERIAL"]
    head_row = 5  # must stay within the first 5 rows for the app's header detection
    for c, h in enumerate(headers, start=1):
        cell = ws.cell(row=head_row, column=c, value=h)
        cell.font = st["head_font"]
        cell.fill = st["head_fill"]
        cell.border = st["border"]
        cell.alignment = st["center"]

    for r, (no, desc, pno, qty, unit, mat) in enumerate(PL_ITEMS, start=head_row + 1):
        vals = [no, desc, pno, float(qty) if "." in qty else int(qty), unit, mat]
        for c, v in enumerate(vals, start=1):
            cell = ws.cell(row=r, column=c, value=v)
            cell.border = st["border"]
            cell.alignment = st["center"] if c in (1, 4, 5) else st["left"]

    ws.cell(row=head_row + len(PL_ITEMS) + 2, column=1, value=f"END OF PARTS LIST — {TITLE}")
    for col, w in zip("ABCDEF", (8, 34, 20, 8, 8, 18)):
        ws.column_dimensions[col].width = w

    path = OUT / f"{PART_NO_COMPACT} - PL.xlsx"
    wb.save(path)
    return path


# ----------------------------------------------------------------------------- WL
WIRES = [
    (1, "J1-1", "PK1-P1-1", "POWER", "WIRE LFH 0.5 SQ MM", "4901 001 101 01", "250", "TWIST WITH J1-2"),
    (2, "J1-2", "PK1-P1-2", "GND", "WIRE LFH 0.5 SQ MM", "4901 001 101 01", "250", "TWIST WITH J1-1"),
    (3, "J1-3", "PK1-P1-3", "SHIELD", "WIRE LFH 0.5 SQ MM", "4901 001 101 01", "260", ""),
    (4, "J2-1", "PK1-P2-1", "VIDEO_P", "WIRE LFH 0.25 SQ MM", "4901 001 102 02", "300", "TWIST PAIR"),
    (5, "J2-2", "PK1-P2-2", "VIDEO_N", "WIRE LFH 0.25 SQ MM", "4901 001 102 02", "300", "TWIST PAIR"),
    (6, "J2-3", "PK1-P2-3", "SHIELD", "WIRE LFH 0.25 SQ MM", "4901 001 102 02", "310", ""),
    (7, "J1-4", "PK1-P3-1", "IR_EN", "WIRE LFH 0.5 SQ MM", "4901 001 101 01", "280", "TO ILLUMINATOR"),
    (8, "J1-5", "PK1-P3-2", "IR_GND", "WIRE LFH 0.5 SQ MM", "4901 001 101 01", "280", ""),
]


def generate_wl() -> Path:
    from openpyxl import Workbook

    st = _xl_styles()
    wb = Workbook()
    ws = wb.active
    ws.title = "WIRE LIST"

    ws["A1"] = COMPANY
    ws["A1"].font = st["sub_font"]
    ws["A2"] = "WIRE LIST"
    ws["A2"].font = st["title_font"]
    ws["A3"] = "TITLE"
    ws["B3"] = f"CABLE ASSY - {TITLE}"
    ws["B3"].font = st["sub_font"]
    ws["A4"] = "PART NUMBER"
    ws["B4"] = PART_NO
    ws["B4"].font = st["sub_font"]
    ws["D4"] = "DOC CODE"
    ws["E4"] = "WL"
    ws["G4"] = "ISSUE 00"

    headers = ["SL", "FROM", "TO", "FUNCTION", "WIRE TYPE", "PART NO", "LENGTH (MM)", "REMARKS"]
    head_row = 6
    for c, h in enumerate(headers, start=1):
        cell = ws.cell(row=head_row, column=c, value=h)
        cell.font = st["head_font"]
        cell.fill = st["head_fill"]
        cell.border = st["border"]
        cell.alignment = st["center"]

    for r, (sl, frm, to, fn, wtype, pno, length, rem) in enumerate(WIRES, start=head_row + 1):
        vals = [sl, frm, to, fn, wtype, pno, int(length), rem]
        for c, v in enumerate(vals, start=1):
            cell = ws.cell(row=r, column=c, value=v)
            cell.border = st["border"]
            cell.alignment = st["center"] if c in (1, 7) else st["left"]

    nr = head_row + len(WIRES) + 2
    ws.cell(row=nr, column=1, value="NOTES:").font = st["head_font"]
    wl_notes = [
        "1. WIRES/CORES/SHIELD TO BE TERMINATED AS PER THIS WIRE LIST AND TOOLING MATRIX.",
        "2. TWIST PAIRS AS INDICATED IN REMARKS. FOLD BACK SHIELD 10 MM AT CONNECTOR END.",
        "3. PL ITEM NO: 7  (CABLE HARNESS NVC) - USE THIS WL FOR HARNESS BUILD.",
        "4. CABLE LENGTH TOLERANCES: 100 TO 500 MM +/- 10 MM.",
    ]
    for i, line in enumerate(wl_notes):
        ws.cell(row=nr + 1 + i, column=1, value=line)

    for col, w in zip("ABCDEFGH", (6, 10, 12, 12, 24, 18, 12, 22)):
        ws.column_dimensions[col].width = w

    path = OUT / f"{PART_NO_COMPACT} - WL.xlsx"
    wb.save(path)
    return path


def main():
    for fn in (generate_ga, generate_pl, generate_wl):
        print("Wrote:", fn())


if __name__ == "__main__":
    main()
