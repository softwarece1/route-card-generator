# Night Vision Camera — offline sample pack

Demo pack for **Automated OARC Generator** with `DRAWING_MIND_ENGINE=cpu_spatial` (no Ollama required).
Branding is fictional: **OPTRONIX SYSTEMS PVT. LTD.**

| File | Role |
|------|------|
| `112199000101 - GA.pdf` | General Arrangement (views, dimensions, section, specs, assembly notes — no BOM; PL is separate) |
| `112199000101 - PL.xlsx` | Parts List (12 items, Excel) |
| `112199000101 - WL.xlsx` | Wire List (8 wires, Excel) |

**Part number:** `1121 990 001 01`
**Title:** NIGHT VISION CAMERA

## How to use

1. Start backend + frontend (offline OK).
2. Open **Generator** → new session.
3. Upload **GA** (PDF), **PL** and **WL** (Excel) from this folder.
4. Click **Generate OARC**.

Expect:

- Title block: Night Vision Camera / `1121 990 001 01`
- 8 assembly notes, with the sticker step (items 2 & 3, 5 mm offsets) elaborated by `cpu_spatial`
- PL item descriptions on operations
- Wire-list ops appended: wire prep, twisted-pair forming, termination + 8 continuity inspections

## Regenerate

```bash
cd backend
PYTHONPATH=. .venv/Scripts/python.exe ../sample_drawings/night_vision_camera/generate_nvc_docs.py
```

The GA is built with PyMuPDF vector line work plus a real **text** layer (not a scan), so
spatial extraction works without Tesseract. PL/WL are written with openpyxl in the exact
column layouts the app's parsers expect.
