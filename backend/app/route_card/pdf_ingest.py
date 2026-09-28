"""Offline PDF ingest: PyMuPDF text → pdfplumber tables → Tesseract OCR fallback.

No cloud APIs and no LLMs. Designed for GA drawings, Parts Lists, and Wire Lists
on CPU-only machines (Intel UHD is fine).
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from io import BytesIO
from typing import Any

logger = logging.getLogger(__name__)

# Below this many non-whitespace chars, treat the PDF as scan-like and try OCR.
SPARSE_TEXT_CHARS = 80
# Cap OCR pages so huge drawings stay responsive on CPU.
DEFAULT_OCR_MAX_PAGES = 12


@dataclass
class PdfIngestResult:
    text: str
    page_count: int
    method: str  # "pymupdf" | "pypdf" | "ocr" | "empty"
    warnings: list[str] = field(default_factory=list)
    tables: list[dict[str, Any]] = field(default_factory=list)
    ocr_used: bool = False


def _tesseract_cmd() -> str:
    try:
        from app.config.settings import settings

        return (getattr(settings, "TESSERACT_CMD", "") or "").strip()
    except Exception:
        return (os.getenv("TESSERACT_CMD") or "").strip()


def _ocr_enabled() -> bool:
    try:
        from app.config.settings import settings

        return bool(getattr(settings, "OCR_ENABLED", True))
    except Exception:
        return os.getenv("OCR_ENABLED", "true").lower() not in {"0", "false", "no"}


def _ocr_dpi() -> int:
    try:
        from app.config.settings import settings

        return int(getattr(settings, "OCR_DPI", 200) or 200)
    except Exception:
        return int(os.getenv("OCR_DPI", "200") or "200")


def _ocr_max_pages() -> int:
    try:
        from app.config.settings import settings

        return int(getattr(settings, "OCR_MAX_PAGES", DEFAULT_OCR_MAX_PAGES) or DEFAULT_OCR_MAX_PAGES)
    except Exception:
        return int(os.getenv("OCR_MAX_PAGES", str(DEFAULT_OCR_MAX_PAGES)) or DEFAULT_OCR_MAX_PAGES)


def _configure_tesseract() -> tuple[bool, str | None]:
    """Return (ok, warning). Sets pytesseract binary path when configured."""
    try:
        import pytesseract
    except ImportError:
        return False, "pytesseract not installed; OCR unavailable."

    cmd = _tesseract_cmd()
    if cmd:
        pytesseract.pytesseract.tesseract_cmd = cmd
    else:
        # Common Windows install path when PATH was not updated.
        win_default = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
        if os.name == "nt" and os.path.isfile(win_default):
            pytesseract.pytesseract.tesseract_cmd = win_default

    try:
        pytesseract.get_tesseract_version()
        return True, None
    except Exception as exc:
        return False, (
            f"Tesseract OCR binary not found ({exc}). "
            "Install Tesseract and set TESSERACT_CMD in backend/.env for scanned PDFs."
        )


def extract_text_pymupdf(data: bytes) -> tuple[str, int]:
    import fitz  # PyMuPDF

    doc = fitz.open(stream=data, filetype="pdf")
    try:
        chunks: list[str] = []
        for page in doc:
            # "text" preserves reading order better than dumping dict blocks alone.
            chunks.append(page.get_text("text") or "")
        return "\n\n".join(chunks), doc.page_count
    finally:
        doc.close()


def extract_text_pypdf(data: bytes) -> tuple[str, int]:
    from pypdf import PdfReader

    reader = PdfReader(BytesIO(data))
    chunks = [page.extract_text() or "" for page in reader.pages]
    return "\n\n".join(chunks), len(reader.pages)


def extract_tables_pdfplumber(data: bytes) -> list[dict[str, Any]]:
    """Extract tables with page index and raw cell rows (for PL / WL)."""
    try:
        import pdfplumber
    except ImportError:
        return []

    tables: list[dict[str, Any]] = []
    try:
        with pdfplumber.open(BytesIO(data)) as pdf:
            for i, page in enumerate(pdf.pages):
                try:
                    found = page.extract_tables() or []
                except Exception:
                    found = []
                for t_idx, rows in enumerate(found):
                    cleaned = [
                        [re.sub(r"\s+", " ", str(c or "")).strip() for c in (row or [])]
                        for row in (rows or [])
                    ]
                    if any(any(cell for cell in row) for row in cleaned):
                        tables.append({"page": i + 1, "tableIndex": t_idx, "rows": cleaned})
    except Exception as exc:
        logger.debug("pdfplumber table extract failed: %s", exc)
    return tables


def ocr_image_bytes(data: bytes) -> tuple[str, int, list[str]]:
    """OCR a TIFF/PNG/JPEG drawing image. Returns (text, page_count, warnings)."""
    warnings: list[str] = []
    ok, warn = _configure_tesseract()
    if not ok:
        if warn:
            warnings.append(warn)
        return "", 0, warnings

    import pytesseract
    from PIL import Image

    try:
        img = Image.open(BytesIO(data))
    except Exception as exc:
        return "", 0, [f"Could not open image: {exc}"]

    chunks: list[str] = []
    n = getattr(img, "n_frames", 1) or 1
    limit = min(n, _ocr_max_pages())
    try:
        for i in range(limit):
            try:
                img.seek(i)
            except EOFError:
                break
            frame = img.convert("RGB")
            try:
                chunks.append(pytesseract.image_to_string(frame) or "")
            except Exception as exc:
                warnings.append(f"OCR failed on page {i + 1}: {exc}")
                chunks.append("")
    finally:
        img.close()
    return "\n\n".join(chunks), n, warnings


def ocr_pdf_pages(data: bytes, max_pages: int | None = None) -> tuple[str, int, list[str]]:
    """Render PDF pages with PyMuPDF and OCR with Tesseract (CPU)."""
    warnings: list[str] = []
    ok, warn = _configure_tesseract()
    if not ok:
        if warn:
            warnings.append(warn)
        return "", 0, warnings

    import fitz
    import pytesseract
    from PIL import Image

    dpi = max(120, min(_ocr_dpi(), 300))
    limit = max_pages if max_pages is not None else _ocr_max_pages()
    zoom = dpi / 72.0
    matrix = fitz.Matrix(zoom, zoom)

    doc = fitz.open(stream=data, filetype="pdf")
    try:
        n = doc.page_count
        if n > limit:
            warnings.append(f"OCR limited to first {limit} of {n} pages (OCR_MAX_PAGES).")
        chunks: list[str] = []
        for i in range(min(n, limit)):
            page = doc.load_page(i)
            pix = page.get_pixmap(matrix=matrix, alpha=False)
            img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            try:
                text = pytesseract.image_to_string(img) or ""
            except Exception as exc:
                warnings.append(f"OCR failed on page {i + 1}: {exc}")
                text = ""
            chunks.append(text)
        return "\n\n".join(chunks), n, warnings
    finally:
        doc.close()


def ingest_pdf(
    data: bytes,
    *,
    want_tables: bool = False,
    force_ocr: bool = False,
    merge_ocr: bool = False,
) -> PdfIngestResult:
    """
    Fallback order:
      1. PyMuPDF text layer
      2. pypdf text layer (if PyMuPDF missing/empty)
      3. Tesseract OCR when text is sparse, or force_ocr/merge_ocr is set
    Optionally attach pdfplumber tables (PL/WL).

    merge_ocr: run OCR even when a text layer exists and APPEND it (for drawings
    where NOTES are drawn as graphics but the title block is real text).
    """
    warnings: list[str] = []
    text = ""
    page_count = 0
    method = "empty"

    try:
        text, page_count = extract_text_pymupdf(data)
        method = "pymupdf"
    except ImportError:
        warnings.append("PyMuPDF not installed; falling back to pypdf.")
        try:
            text, page_count = extract_text_pypdf(data)
            method = "pypdf"
        except Exception as exc:
            warnings.append(f"pypdf failed: {exc}")
    except Exception as exc:
        warnings.append(f"PyMuPDF extract failed ({exc}); trying pypdf.")
        try:
            text, page_count = extract_text_pypdf(data)
            method = "pypdf"
        except Exception as exc2:
            warnings.append(f"pypdf failed: {exc2}")

    ocr_used = False
    need_ocr = force_ocr or merge_ocr or len((text or "").strip()) < SPARSE_TEXT_CHARS
    if need_ocr:
        if not _ocr_enabled():
            warnings.append(
                "OCR requested but OCR_ENABLED=false. Enable it in backend/.env for graphic NOTES."
            )
        else:
            ocr_text, ocr_pages, ocr_warns = ocr_pdf_pages(data)
            warnings.extend(ocr_warns)
            if len((ocr_text or "").strip()) >= 40:
                if merge_ocr and (text or "").strip():
                    # Keep vector title-block text + OCR body (notes often graphics-only)
                    text = f"{text}\n\n--- OCR ---\n\n{ocr_text}"
                    method = f"{method}+ocr"
                else:
                    text = ocr_text
                    method = "ocr"
                page_count = ocr_pages or page_count
                ocr_used = True
            elif not ocr_warns:
                warnings.append(
                    "OCR produced little text. Prefer a vector PDF export when possible."
                )
            elif len((text or "").strip()) < SPARSE_TEXT_CHARS:
                warnings.append(
                    "PDF has little or no text layer (likely a scan). "
                    "Install Tesseract OCR for scanned PDF support."
                )

    tables: list[dict[str, Any]] = []
    if want_tables:
        tables = extract_tables_pdfplumber(data)
        if not tables and "ocr" not in method:
            logger.debug("No pdfplumber tables found")

    return PdfIngestResult(
        text=text or "",
        page_count=page_count or (1 if text else 0),
        method=method,
        warnings=list(dict.fromkeys(warnings)),
        tables=tables,
        ocr_used=ocr_used,
    )


def pdf_to_text(data: bytes) -> tuple[str, int]:
    """Drop-in replacement for extractor.pdf_to_text (text + page count only)."""
    result = ingest_pdf(data, want_tables=False)
    return result.text, result.page_count or 1


def tables_to_tsv_lines(tables: list[dict[str, Any]]) -> str:
    """Flatten table rows to tab-separated lines for regex parsers."""
    lines: list[str] = []
    for t in tables:
        for row in t.get("rows") or []:
            cells = [c for c in row if c]
            if cells:
                lines.append("\t".join(cells))
    return "\n".join(lines)


def _spatial_dpi() -> int:
    try:
        from app.config.settings import settings

        return int(getattr(settings, "DRAWING_MIND_SPATIAL_DPI", None) or _ocr_dpi() or 200)
    except Exception:
        return _ocr_dpi()


def _spatial_max_pages() -> int:
    try:
        from app.config.settings import settings

        return int(getattr(settings, "DRAWING_MIND_MAX_PAGES", None) or _ocr_max_pages() or 12)
    except Exception:
        return _ocr_max_pages()


def extract_spatial_pages(data: bytes, max_pages: int | None = None) -> tuple[list[dict[str, Any]], list[str]]:
    """
    Per-page word bounding boxes for the drawing mind.

    Prefer PyMuPDF text dict (vector PDFs). If a page is sparse, fall back to
    Tesseract image_to_data on a rendered pixmap (CPU).
    """
    warnings: list[str] = []
    pages_out: list[dict[str, Any]] = []
    try:
        import fitz
    except ImportError:
        return [], ["PyMuPDF not installed; spatial word boxes unavailable."]

    limit = max_pages if max_pages is not None else _spatial_max_pages()
    dpi = max(120, min(_spatial_dpi(), 300))
    zoom = dpi / 72.0
    matrix = fitz.Matrix(zoom, zoom)

    doc = fitz.open(stream=data, filetype="pdf")
    try:
        n = doc.page_count
        if n > limit:
            warnings.append(f"Spatial OCR limited to first {limit} of {n} pages.")
        for i in range(min(n, limit)):
            page = doc.load_page(i)
            rect = page.rect
            words: list[dict[str, Any]] = []
            try:
                td = page.get_text("dict") or {}
                for block in td.get("blocks") or []:
                    if block.get("type", 0) != 0:
                        continue
                    for line in block.get("lines") or []:
                        for span in line.get("spans") or []:
                            text = (span.get("text") or "").strip()
                            if not text:
                                continue
                            bbox = span.get("bbox") or [0, 0, 0, 0]
                            # Split multi-word spans so balloons/dims stay atomic
                            x0, y0, x1, y1 = [float(v) for v in bbox]
                            tokens = text.split()
                            if len(tokens) <= 1:
                                words.append(
                                    {
                                        "text": text,
                                        "x0": x0,
                                        "y0": y0,
                                        "x1": x1,
                                        "y1": y1,
                                    }
                                )
                            else:
                                span_w = max(x1 - x0, 1.0)
                                total_chars = max(sum(len(t) for t in tokens), 1)
                                cursor = x0
                                for tok in tokens:
                                    tw = span_w * (len(tok) / total_chars)
                                    words.append(
                                        {
                                            "text": tok,
                                            "x0": cursor,
                                            "y0": y0,
                                            "x1": cursor + tw,
                                            "y1": y1,
                                        }
                                    )
                                    cursor += tw
            except Exception as exc:
                warnings.append(f"Spatial text dict failed page {i + 1}: {exc}")

            # Sparse page → OCR word boxes (page coordinates via zoom)
            non_ws = sum(len(re.sub(r"\s+", "", w["text"])) for w in words)
            if non_ws < 40 and _ocr_enabled():
                ok, warn = _configure_tesseract()
                if not ok:
                    if warn:
                        warnings.append(warn)
                else:
                    try:
                        import pytesseract
                        from PIL import Image

                        pix = page.get_pixmap(matrix=matrix, alpha=False)
                        img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
                        data_tsv = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT)
                        ocr_words: list[dict[str, Any]] = []
                        n_boxes = len(data_tsv.get("text") or [])
                        for j in range(n_boxes):
                            raw = (data_tsv["text"][j] or "").strip()
                            if not raw:
                                continue
                            conf = data_tsv.get("conf", ["-1"])[j]
                            try:
                                if float(conf) < 30:
                                    continue
                            except (TypeError, ValueError):
                                pass
                            # image pixels → PDF points
                            lx = float(data_tsv["left"][j]) / zoom
                            ty = float(data_tsv["top"][j]) / zoom
                            ww = float(data_tsv["width"][j]) / zoom
                            hh = float(data_tsv["height"][j]) / zoom
                            ocr_words.append(
                                {
                                    "text": raw,
                                    "x0": lx,
                                    "y0": ty,
                                    "x1": lx + ww,
                                    "y1": ty + hh,
                                }
                            )
                        if len(ocr_words) > len(words):
                            words = ocr_words
                    except Exception as exc:
                        warnings.append(f"Spatial OCR failed page {i + 1}: {exc}")

            pages_out.append(
                {
                    "page": i + 1,
                    "width": float(rect.width),
                    "height": float(rect.height),
                    "words": words,
                }
            )
    finally:
        doc.close()

    return pages_out, list(dict.fromkeys(warnings))
