from __future__ import annotations

import os
import re
from datetime import datetime, timedelta
from io import BytesIO
from pathlib import Path

from fastapi import HTTPException, UploadFile
from pony.orm import commit, db_session, desc, select

from app.config.settings import settings
from app.route_card.extractor import ingest_drawing_pdf, parse_drawing_text
from app.route_card.format_templates import (
    bump_use_count,
    fingerprint_text,
    learn_template,
    list_templates,
    match_template,
    delete_template,
)
from app.route_card.pmf_oarc_export import payload_to_pmf_oarc
from app.route_card.models import (
    RcDepartment,
    RcDocument,
    RcDrawing,
    RcExtraction,
    RcInspectionChar,
    RcOperation,
    RcRouteCard,
    RcSession,
    RcUser,
)
from app.route_card.partslist_parser import enrich_bom_with_pl, enrich_ops_items, parse_partslist_bytes
from app.route_card.route_generator import generate_route
from app.route_card.wirelist_parser import parse_wirelist_bytes, wirelist_to_route_additions
from app.services.minio_service import MinioService

ALLOWED_EXT = {".pdf", ".tif", ".tiff", ".xls", ".xlsx"}
ROLE_ALLOWED = {
    "drawing": {".pdf", ".tif", ".tiff"},
    "wirelist": {".pdf", ".xls", ".xlsx"},
    "partslist": {".pdf", ".xls", ".xlsx"},
}
MAX_BYTES = 10 * 1024 * 1024
CONTENT_TYPES = {
    ".pdf": "application/pdf",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
    ".xls": "application/vnd.ms-excel",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}


def get_local_upload_root() -> Path:
    """Directory for local GA/PL/WL files (configurable; not required under backend/)."""
    from app.config.settings import settings

    raw = (getattr(settings, "LOCAL_UPLOAD_ROOT", None) or "").strip()
    if raw:
        p = Path(raw).expanduser()
        if not p.is_absolute():
            p = Path.cwd() / p
        return p.resolve()
    return (Path.cwd() / "uploads" / "route-card").resolve()

_PL_USER_MSG = (
    "Parts List could not be read or does not match the expected format. "
    "Please upload a valid PDF or Excel Parts List."
)
_WL_USER_MSG = (
    "Wire List could not be read or does not match the expected format. "
    "Please upload a valid PDF or Excel Wire List."
)
_TECHNICAL_WARN_RE = re.compile(
    r"tesseract|drawing\s*mind|local_vlm|ocr|balloon|cpu\)|gpu|"
    r"spatial|pdfplumber|pymupdf|pypdf|ingest|oda\b|dxf|dwg|dwf|"
    r"low-confidence|note order|item balloon",
    re.I,
)


def user_facing_warnings(warnings: list[str] | None) -> list[str]:
    """Collapse internal/OCR/mind noise into short end-user messages."""
    if not warnings:
        return []
    pl_issue = False
    wl_issue = False
    out: list[str] = []
    for raw in warnings:
        w = (raw or "").strip()
        if not w:
            continue
        low = w.lower()
        if _TECHNICAL_WARN_RE.search(low):
            continue
        if "wire list not provided" in low or "continuity checklist skipped" in low:
            continue
        if "parts list not provided" in low:
            pl_issue = True
            continue
        # Informational PL notes (e.g. TSV-as-.xls) — hide from end users
        if "parts list" in low and (
            "plain text" in low or "parsed as" in low or "tsv" in low
        ):
            continue
        if "wire list" in low and (
            "plain text" in low or "parsed as" in low or "tsv" in low
        ):
            continue
        if "parts list" in low and any(
            k in low
            for k in (
                "no item",
                "could not",
                "failed",
                "expected columns",
                "little/no text",
                "not match",
                "no item rows",
            )
        ):
            pl_issue = True
            continue
        if "could not open as excel" in low or "openpyxl" in low or "xlrd is not installed" in low:
            pl_issue = True
            continue
        if "wire list" in low and any(
            k in low
            for k in (
                "could not",
                "failed",
                "few/no",
                "little/no",
                "prefer a clean",
                "unsupported",
            )
        ):
            wl_issue = True
            continue
        if "wire list part number" in low and "differs" in low:
            out.append(
                "Wire List part number does not match the drawing. Please verify the files."
            )
            continue
        # Drop leftover verbose internal notes
        if len(w) > 180:
            continue
        out.append(w)
    if pl_issue:
        out.insert(0, _PL_USER_MSG)
    if wl_issue:
        out.append(_WL_USER_MSG)
    return list(dict.fromkeys(out))

_minio: MinioService | None = None
_minio_down_until: float = 0.0


def minio() -> MinioService:
    global _minio
    if _minio is None:
        _minio = MinioService()
    return _minio


def _storage_mode() -> str:
    try:
        mode = (getattr(settings, "STORAGE_BACKEND", None) or "auto").strip().lower()
    except Exception:
        mode = (os.getenv("STORAGE_BACKEND") or "auto").strip().lower()
    if mode in {"local", "minio", "auto"}:
        return mode
    return "auto"


def _minio_cache_sec() -> float:
    try:
        return float(getattr(settings, "MINIO_DOWN_CACHE_SEC", 60.0) or 60.0)
    except Exception:
        return 60.0


def _store_local(prefix: str, filename: str, data: bytes) -> tuple[str, str]:
    root = get_local_upload_root()
    root.mkdir(parents=True, exist_ok=True)
    dest_dir = root / prefix.replace("/", "_")
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / filename
    dest.write_bytes(data)
    return str(dest).replace("\\", "/"), "local"


def format_bytes(n: int) -> str:
    if not n:
        return "—"
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{(n / 1024):.1f} KB"
    return f"{(n / (1024 * 1024)):.1f} MB"


def file_type_from_name(name: str) -> str:
    ext = Path(name).suffix.lower()
    return {".stp": "STEP", ".step": "STEP"}.get(ext, ext.lstrip(".").upper() or "FILE")


async def read_upload(file: UploadFile, role: str | None = None) -> tuple[bytes, str, str]:
    filename = os.path.basename(file.filename or "document")
    ext = Path(filename).suffix.lower()
    allowed = ROLE_ALLOWED.get(role) if role else ALLOWED_EXT
    if allowed is None:
        raise HTTPException(400, f"Unknown document role: {role}")
    if ext not in allowed:
        role_label = {
            "drawing": "Drawing (GA)",
            "partslist": "Parts List",
            "wirelist": "Wire List",
        }.get(role or "", role or "upload")
        raise HTTPException(
            400,
            f"{role_label}: unsupported file type “{ext or '(none)'}”. "
            f"Allowed: {', '.join(sorted(allowed))}.",
        )
    data = await file.read()
    if not data:
        raise HTTPException(400, "Empty file")
    if len(data) > MAX_BYTES:
        raise HTTPException(400, "File exceeds 10 MB limit")
    return data, filename, ext


def _store_path(prefix: str, filename: str, data: bytes, content_type: str) -> tuple[str, str]:
    """Persist upload bytes. Prefer MinIO when available; never stall ~60s on dead MinIO."""
    global _minio_down_until
    import time

    object_name = f"route-card/{prefix}/{filename}"
    mode = _storage_mode()

    if mode == "local":
        return _store_local(prefix, filename, data)

    now = time.monotonic()
    if mode == "auto" and now < _minio_down_until:
        path, backend = _store_local(prefix, filename, data)
        return path, f"{backend}:minio_cached_down"

    try:
        minio().upload_file(BytesIO(data), object_name, content_type)
        _minio_down_until = 0.0
        return object_name, "minio"
    except Exception as exc:
        if mode == "minio":
            raise HTTPException(503, f"MinIO upload failed: {exc}") from exc
        _minio_down_until = time.monotonic() + _minio_cache_sec()
        path, backend = _store_local(prefix, filename, data)
        return path, f"{backend}:{exc.__class__.__name__}"


def _store(drawing_id: int, filename: str, data: bytes, content_type: str) -> tuple[str, str]:
    return _store_path(str(drawing_id), filename, data, content_type)


def _user_prefix(user: dict | None) -> str:
    if not user:
        return "anonymous"
    emp = (user.get("empId") or user.get("username") or "user").strip() or "user"
    uid = user.get("id") or 0
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", emp)
    return f"users/{safe}_{uid}"


def _session_storage_prefix(user: dict | None, session_id: int) -> str:
    """One folder per session for GA + PL + WL (not per role)."""
    return f"{_user_prefix(user)}/sessions/{session_id}"


def _safe_store_filename(role: str, filename: str, *, unique: bool = False) -> str:
    """Prefix with role so GA/PL/WL coexist in the same session folder."""
    base = os.path.basename(filename or "document")
    stem = Path(base).stem
    suffix = Path(base).suffix
    role_key = re.sub(r"[^a-z0-9]+", "", (role or "file").lower()) or "file"
    if unique:
        return f"{role_key}__{stem}__{int(datetime.utcnow().timestamp())}{suffix}"
    return f"{role_key}__{base}"


def _try_unlink_local(object_path: str | None, storage_backend: str | None) -> None:
    if not object_path:
        return
    backend = (storage_backend or "").lower()
    path = Path(object_path)
    looks_local = (
        backend.startswith("local")
        or str(object_path).startswith("uploads/")
        or path.is_absolute()
    )
    if not looks_local:
        return
    try:
        path.unlink(missing_ok=True)
    except Exception:
        pass


def _sniff_upload_warnings(role: str, data: bytes, filename: str, ext: str) -> list[str]:
    """Soft checks — upload still succeeds; UI shows warnings."""
    role = (role or "").lower().strip()
    name = (filename or "").lower()
    warnings: list[str] = []

    if role == "drawing":
        if ext not in {".pdf", ".tif", ".tiff"}:
            warnings.append(
                f"Unexpected drawing type {ext}. Expected PDF or TIFF engineering drawing."
            )
            return warnings
        if ext == ".pdf":
            text = ""
            try:
                from app.route_card.pdf_ingest import ingest_pdf

                text = (ingest_pdf(data, want_tables=False).text or "")[:8000]
            except Exception:
                text = ""
            cues = re.search(
                r"\b(NOTE|NOTES|GA\b|ASSEMBLY|ITEM\s*\d|AS\s+SHOWN|REVISION|SCALE|SHEET)\b",
                text,
                re.I,
            )
            name_cue = re.search(r"\b(ga|drawing|dwg|assy|assembly)\b", name, re.I)
            if not cues and not name_cue:
                warnings.append(
                    "This file may not be a GA / engineering drawing "
                    "(few drawing cues found). Confirm you uploaded the correct sheet."
                )
        return warnings

    if role == "partslist":
        try:
            from app.route_card.partslist_parser import parse_partslist_bytes

            parsed = parse_partslist_bytes(data, filename)
            items = parsed.get("items") or []
            if not items:
                warnings.append(
                    "Parts List uploaded, but no item rows were detected. "
                    "Check that the file is a PL (PDF/Excel) in the expected layout."
                )
            elif not re.search(r"\b(pl|parts?\s*list|bom)\b", name, re.I) and len(items) < 2:
                warnings.append(
                    "Parts List looks sparse — verify this is the correct Parts List file."
                )
        except Exception:
            warnings.append(
                "Parts List could not be pre-checked. Analyze may still fail if the format is wrong."
            )
        return warnings

    if role == "wirelist":
        try:
            from app.route_card.wirelist_parser import parse_wirelist_bytes

            parsed = parse_wirelist_bytes(data, filename)
            wires = parsed.get("wires") or parsed.get("materials") or []
            count = parsed.get("wireCount") or len(wires)
            if not count:
                warnings.append(
                    "Wire List uploaded, but no wire/material rows were detected. "
                    "Check that the file is a WL (PDF/Excel) in the expected layout."
                )
        except Exception:
            warnings.append(
                "Wire List could not be pre-checked. Analyze may still fail if the format is wrong."
            )
        return warnings

    return warnings


def _resolve_user(user: dict | None) -> RcUser | None:
    if not user:
        return None
    uid = user.get("id")
    if uid:
        hit = RcUser.get(id=int(uid))
        if hit:
            return hit
    emp = user.get("empId") or user.get("username")
    if emp:
        return RcUser.get(emp_id=str(emp))
    return None


def _is_admin(user: dict | None) -> bool:
    return bool(user and user.get("role") == "admin")


def _assert_session_access(session: RcSession, user: dict | None, *, write: bool = False) -> None:
    if _is_admin(user):
        return
    owner = session.user
    if not owner:
        # Legacy sessions without owner — only admin can touch after auth is on
        if user and user.get("id"):
            raise HTTPException(403, "This session is not owned by your account")
        return
    uid = user.get("id") if user else None
    if not uid or owner.id != int(uid):
        raise HTTPException(403, "Not allowed to access this session")


def _store(drawing_id: int, filename: str, data: bytes, content_type: str) -> tuple[str, str]:
    return _store_path(str(drawing_id), filename, data, content_type)


def load_path_bytes(object_path: str, storage_backend: str) -> bytes:
    path = Path(object_path)
    if (
        storage_backend.startswith("local")
        or object_path.startswith("uploads/")
        or path.is_file()
    ):
        if not path.is_file():
            raise FileNotFoundError(f"File not found on disk: {object_path}")
        return path.read_bytes()
    stream = minio().get_file(object_path)
    try:
        return stream.read()
    finally:
        try:
            stream.close()
            stream.release_conn()
        except Exception:
            pass


def load_bytes(drawing: RcDrawing) -> bytes:
    return load_path_bytes(drawing.object_path, drawing.storage_backend)


def drawing_dict(d: RcDrawing, warnings: list[str] | None = None) -> dict:
    return {
        "id": d.id,
        "filename": d.filename,
        "file_type": d.file_type,
        "size_bytes": d.size_bytes,
        "size_label": format_bytes(d.size_bytes),
        "pages": d.pages,
        "status": d.status,
        "drawing_type": d.drawing_type or "unknown",
        "warnings": warnings or [],
    }


def _extract_from_bytes(
    data: bytes,
    filename: str,
    ext: str,
    *,
    format_aliases: dict | None = None,
) -> dict:
    warnings: list[str] = []
    text = ""
    pages = 1
    if ext == ".pdf":
        parsed = ingest_drawing_pdf(data, filename, format_aliases=format_aliases)
        parsed["warnings"] = list(dict.fromkeys((parsed.get("warnings") or []) + warnings))
        return parsed
    if ext in {".tif", ".tiff"}:
        from app.route_card.pdf_ingest import ocr_image_bytes

        text, pages, ocr_warns = ocr_image_bytes(data)
        warnings.extend(ocr_warns)
        if not (text or "").strip():
            warnings.append("Drawing image could not be read. Please upload a clear PDF or TIFF.")
        parsed = parse_drawing_text(text, filename, pages or 1, format_aliases=format_aliases)
        parsed["warnings"] = list(dict.fromkeys((parsed.get("warnings") or []) + warnings))
        parsed["pages"] = pages or 1
        return parsed

    warnings.append("Unsupported drawing format. Please upload a PDF or TIFF.")
    parsed = parse_drawing_text(text, filename, pages, format_aliases=format_aliases)
    parsed["warnings"] = list(dict.fromkeys((parsed.get("warnings") or []) + warnings))
    parsed["pages"] = pages
    return parsed


def _match_and_aliases(text: str, doc_type: str) -> tuple[dict, dict | None]:
    """Match format template; return (match_info, aliases_or_None)."""
    match = match_template(text or "", doc_type_hint=doc_type)
    aliases = None
    if match.get("matched") and match.get("template"):
        aliases = match["template"].get("aliases") or {}
        tid = match["template"].get("id")
        if tid:
            bump_use_count(tid)
    return match, aliases


def build_payload(
    drawing: RcDrawing,
    extraction: RcExtraction | None,
    route: RcRouteCard | None,
    *,
    documents: list[dict] | None = None,
    wire_list: dict | None = None,
    parts_list: dict | None = None,
    extra_warnings: list[str] | None = None,
    format_matches: dict | None = None,
    mind: dict | None = None,
    drawings: list[dict] | None = None,
    cross_refs: list[dict] | None = None,
    view_refs: list[dict] | None = None,
) -> dict:
    title = (extraction.title_block if extraction else None) or {}
    notes = (extraction.notes if extraction else None) or []
    bom = (extraction.bom_items if extraction else None) or []
    generated = generate_route(
        {
            "title_block": title,
            "notes": notes,
            "bom_items": bom,
            "torque_specs": (extraction.torque_specs if extraction else None) or [],
            "dimensions": (extraction.dimensions if extraction else None) or [],
            "references": (extraction.references if extraction else None) or [],
            "drawing_type": drawing.drawing_type,
        }
    ) if extraction else {
        "operations": [],
        "inspection": [],
        "feature_counts": [],
        "manufacturing_features": [],
        "intelligence_dimensions": [],
        "intelligence_requirements": [],
        "referenced_documents": [],
    }

    ops = generated["operations"]
    inspection = generated["inspection"]
    if route:
        ops = [op_to_out(o) for o in sorted(route.operations, key=lambda x: x.op_no)]
        inspection = [insp_to_out(c) for c in route.inspection_chars]
        if not ops:
            ops = generated["operations"]
        if not inspection:
            inspection = generated["inspection"]

    mind_info = mind or {}
    tasks = [
        {"key": "ocr", "label": "Text extraction", "value": 100 if extraction else 0},
        {"key": "notes", "label": "Assembly notes", "value": 100 if notes else 0},
        {"key": "bom", "label": "BOM callouts", "value": 100 if bom else 0},
        {"key": "torque", "label": "Torque / standards", "value": 100 if (extraction and extraction.torque_specs) else 0},
        {"key": "dims", "label": "Interface dimensions", "value": 100 if (extraction and extraction.dimensions) else 0},
        {
            "key": "mind",
            "label": "Drawing mind",
            "value": 100
            if (
                mind_info.get("placements")
                or mind_info.get("pcbLinks")
                or mind_info.get("viewRefs")
                or any(
                    isinstance(n, dict) and n.get("elaboratedText")
                    for n in notes
                )
            )
            else (50 if extraction else 0),
        },
        {"key": "wl", "label": "Wire list", "value": 100 if wire_list and wire_list.get("wireCount") else (50 if wire_list else 0)},
        {"key": "pl", "label": "Parts list", "value": 100 if parts_list and (parts_list.get("items") or []) else (50 if parts_list else 0)},
        {"key": "route", "label": "Route generation", "value": 100 if ops else 0},
    ]

    warnings = list((extraction.warnings if extraction else None) or [])
    if extra_warnings:
        warnings.extend(extra_warnings)
    if wire_list:
        warnings.extend(wire_list.get("warnings") or [])
    if parts_list:
        warnings.extend(parts_list.get("warnings") or [])
    warnings.extend(mind_info.get("warnings") or [])
    warnings = user_facing_warnings(list(dict.fromkeys(warnings)))

    # Keep mind diagnostics for the client (engine + warnings) so fallbacks are visible
    mind_public = dict(mind_info) if mind_info else {}

    return {
        "id": route.id if route else None,
        "status": route.status if route else "draft",
        "drawing": drawing_dict(drawing, []),
        "drawingInfo": title,
        "bomItems": bom,
        "featureCounts": generated["feature_counts"],
        "manufacturingFeatures": generated["manufacturing_features"],
        "intelligenceDimensions": generated["intelligence_dimensions"],
        "intelligenceRequirements": generated["intelligence_requirements"],
        "suggestedOperations": generated["operations"],
        "routeOperations": ops,
        "inspectionChars": inspection,
        "referencedDocuments": generated["referenced_documents"],
        "revisions": (extraction.revisions if extraction else None) or [],
        "notes": notes,
        "warnings": warnings,
        "analysisTasks": tasks,
        "documents": documents or [],
        "wireList": {
            "partNumber": (wire_list or {}).get("partNumber"),
            "title": (wire_list or {}).get("title"),
            "wireCount": (wire_list or {}).get("wireCount", 0),
            "materials": (wire_list or {}).get("materials") or [],
        }
        if wire_list
        else None,
        "partsList": {
            "partNumber": (parts_list or {}).get("partNumber"),
            "itemCount": len((parts_list or {}).get("items") or []),
            "items": (parts_list or {}).get("items") or [],
        }
        if parts_list
        else None,
        "sessionId": drawing.session.id if drawing.session else None,
        "formatMatches": format_matches or {},
        "mind": mind_public,
        "drawings": drawings
        or (
            [{"id": drawing.id, "filename": drawing.filename, "status": drawing.status}]
            if drawing
            else []
        ),
        "crossRefs": cross_refs if cross_refs is not None else (mind_info.get("crossRefs") or []),
        "viewRefs": view_refs if view_refs is not None else (mind_info.get("viewRefs") or []),
    }


def op_to_out(o: RcOperation) -> dict:
    items_used = o.items_used or []
    items_label = ""
    if isinstance(items_used, list) and items_used:
        items_label = ", ".join(
            f"#{i.get('itemNo')}" + (f"×{i.get('qty')}" if i.get("qty") else "")
            for i in items_used
            if isinstance(i, dict)
        )
    return {
        "id": str(o.id),
        "opNo": o.op_no,
        "operation": o.operation,
        "workCentre": o.work_centre or "",
        "machine": o.machine or "",
        "tool": o.tool or "",
        "items": items_label,
        "itemsUsed": items_used if isinstance(items_used, list) else [],
        "torqueSpec": o.torque_spec or "",
        "reference": o.reference or "",
        "setup": o.setup or "1",
        "time": o.time or "",
        "inspection": o.inspection or "",
        "instructionText": o.instruction_text or "",
        "status": o.status,
        "type": o.work_centre or "Assembly",
        "reason": (o.instruction_text or "")[:240],
        "features": [],
    }


def insp_to_out(c: RcInspectionChar) -> dict:
    return {
        "id": str(c.id),
        "dimension": c.characteristic,
        "nominal": c.nominal or "",
        "tolerance": c.tolerance or "",
        "method": c.method or "",
        "frequency": c.frequency or "",
        "criticality": c.criticality or "Standard",
    }


def persist_route(drawing: RcDrawing, generated: dict, existing: RcRouteCard | None = None) -> RcRouteCard:
    title = {}
    latest = drawing.extractions.select().order_by(desc(RcExtraction.created_at)).first()
    if latest and latest.title_block:
        title = latest.title_block
    card = existing or RcRouteCard(drawing=drawing, status="draft", part_info=title)
    card.part_info = title
    card.updated_at = datetime.utcnow()
    for old in list(card.operations):
        old.delete()
    for old in list(card.inspection_chars):
        old.delete()
    for op in generated.get("operations") or []:
        RcOperation(
            route_card=card,
            op_no=int(op.get("opNo") or 0),
            operation=op.get("operation") or "",
            work_centre=op.get("workCentre") or "",
            machine=op.get("machine") or "",
            tool=op.get("tool") or "",
            items_used=op.get("itemsUsed") or [],
            torque_spec=op.get("torqueSpec") or "",
            reference=op.get("reference") or "",
            setup=op.get("setup") or "1",
            time=op.get("time") or "",
            inspection=op.get("inspection") or "",
            instruction_text=op.get("instructionText") or "",
            status=op.get("status") or "Planned",
        )
    for ic in generated.get("inspection") or []:
        RcInspectionChar(
            route_card=card,
            characteristic=ic.get("dimension") or "",
            nominal=ic.get("nominal") or "",
            tolerance=ic.get("tolerance") or "",
            method=ic.get("method") or "",
            frequency=ic.get("frequency") or "100%",
            criticality=ic.get("criticality") or "Standard",
        )
    return card


@db_session
def create_drawing(data: bytes, filename: str, ext: str, uploaded_by: str | None) -> dict:
    drawing = RcDrawing(
        filename=filename,
        file_type=file_type_from_name(filename),
        content_type=CONTENT_TYPES.get(ext, "application/octet-stream"),
        object_path="pending",
        storage_backend="pending",
        size_bytes=len(data),
        status="uploaded",
        drawing_type="unknown",
        uploaded_by=uploaded_by or "",
    )
    commit()
    path, backend = _store(drawing.id, filename, data, drawing.content_type or "application/octet-stream")
    drawing.object_path = path
    drawing.storage_backend = backend
    drawing.updated_at = datetime.utcnow()
    commit()
    return drawing_dict(drawing, [])


@db_session
def analyze_drawing(drawing_id: int) -> dict:
    from app.route_card.drawing_mind import get_drawing_mind
    from app.route_card.pdf_ingest import extract_spatial_pages

    drawing = RcDrawing.get(id=drawing_id)
    if not drawing:
        raise HTTPException(404, "Drawing not found")
    drawing.status = "analyzing"
    drawing.updated_at = datetime.utcnow()
    commit()
    try:
        data = load_bytes(drawing)
        ext = Path(drawing.filename).suffix.lower()
        parsed = _extract_from_bytes(data, drawing.filename, ext)
        spatial_pages: list = []
        spatial_warns: list[str] = []
        if ext == ".pdf":
            spatial_pages, spatial_warns = extract_spatial_pages(data)
        mind = get_drawing_mind()
        mind_result = mind.understand(
            pdf_bytes=data if ext == ".pdf" else None,
            ga_extraction=parsed,
            spatial_pages=spatial_pages,
            source_drawing_id=drawing.id,
            source_filename=drawing.filename,
        )
        parsed["notes"] = mind_result.notes
        parsed["warnings"] = list(
            dict.fromkeys((parsed.get("warnings") or []) + spatial_warns + mind_result.warnings)
        )
        drawing.pages = parsed.get("pages")
        drawing.drawing_type = parsed.get("drawing_type") or "unknown"
        extraction = RcExtraction(
            drawing=drawing,
            title_block=parsed.get("title_block") or {},
            revisions=parsed.get("revisions") or [],
            bom_items=parsed.get("bom_items") or [],
            notes=parsed.get("notes") or [],
            torque_specs=parsed.get("torque_specs") or [],
            dimensions=parsed.get("dimensions") or [],
            references=parsed.get("references") or [],
            warnings=parsed.get("warnings") or [],
            raw_text=parsed.get("raw_text") or "",
        )
        generated = generate_route(parsed)
        existing = drawing.route_cards.select().order_by(desc(RcRouteCard.created_at)).first()
        card = persist_route(drawing, generated, existing)
        drawing.status = "analyzed"
        drawing.updated_at = datetime.utcnow()
        commit()
        return build_payload(
            drawing,
            extraction,
            card,
            mind=mind_result.to_dict(),
        )
    except HTTPException:
        drawing.status = "failed"
        commit()
        raise
    except Exception as exc:
        drawing.status = "failed"
        drawing.error_message = str(exc)[:500]
        drawing.updated_at = datetime.utcnow()
        commit()
        raise HTTPException(500, f"Analysis failed: {exc}") from exc


@db_session
def get_drawing_payload(drawing_id: int) -> dict:
    drawing = RcDrawing.get(id=drawing_id)
    if not drawing:
        raise HTTPException(404, "Drawing not found")
    extraction = drawing.extractions.select().order_by(desc(RcExtraction.created_at)).first()
    route = drawing.route_cards.select().order_by(desc(RcRouteCard.created_at)).first()
    return build_payload(drawing, extraction, route)


@db_session
def regenerate_route(drawing_id: int) -> dict:
    drawing = RcDrawing.get(id=drawing_id)
    if not drawing:
        raise HTTPException(404, "Drawing not found")
    extraction = drawing.extractions.select().order_by(desc(RcExtraction.created_at)).first()
    if not extraction:
        raise HTTPException(400, "Analyze the drawing before generating a route card")
    generated = generate_route(
        {
            "title_block": extraction.title_block or {},
            "notes": extraction.notes or [],
            "bom_items": extraction.bom_items or [],
            "torque_specs": extraction.torque_specs or [],
            "dimensions": extraction.dimensions or [],
            "references": extraction.references or [],
            "drawing_type": drawing.drawing_type,
        }
    )
    existing = drawing.route_cards.select().order_by(desc(RcRouteCard.created_at)).first()
    card = persist_route(drawing, generated, existing)
    card.status = "draft"
    commit()
    return build_payload(drawing, extraction, card)


@db_session
def update_route(route_id: int, body: dict, user: dict | None = None) -> dict:
    card = RcRouteCard.get(id=route_id)
    if not card:
        raise HTTPException(404, "Route card not found")
    ops = body.get("operations") or []
    generated = {
        "operations": [
            {
                "opNo": o.get("opNo"),
                "operation": o.get("operation"),
                "workCentre": o.get("workCentre"),
                "machine": o.get("machine"),
                "tool": o.get("tool"),
                "itemsUsed": o.get("itemsUsed") or [],
                "torqueSpec": o.get("torqueSpec"),
                "reference": o.get("reference"),
                "setup": o.get("setup"),
                "time": o.get("time"),
                "inspection": o.get("inspection"),
                "instructionText": o.get("instructionText") or "",
                "status": o.get("status") or "Planned",
            }
            for o in ops
        ],
        "inspection": [
            {
                "dimension": i.get("dimension"),
                "nominal": i.get("nominal"),
                "tolerance": i.get("tolerance"),
                "method": i.get("method"),
                "frequency": i.get("frequency"),
                "criticality": i.get("criticality"),
            }
            for i in (body.get("inspection") or [])
        ]
        or None,
    }
    extraction = card.drawing.extractions.select().order_by(desc(RcExtraction.created_at)).first()
    if not generated["inspection"]:
        generated["inspection"] = [
            {
                "dimension": c.characteristic,
                "nominal": c.nominal,
                "tolerance": c.tolerance,
                "method": c.method,
                "frequency": c.frequency,
                "criticality": c.criticality,
            }
            for c in card.inspection_chars
        ]
    persist_route(card.drawing, generated, card)
    commit()
    comment = (body.get("comment") or "").strip()
    if comment or ops:
        try:
            from app.route_card import audit

            audit.record_audit(
                action="update_route",
                user=user,
                route_card_id=route_id,
                session_id=card.drawing.session.id if card.drawing.session else None,
                detail={"opCount": len(ops)},
                comment=comment or None,
            )
        except Exception:
            pass
    return build_payload(card.drawing, extraction, card)


@db_session
def set_route_status(
    route_id: int,
    status: str,
    user: dict | None = None,
    *,
    admin_override: bool = False,
    comment: str | None = None,
) -> dict:
    from app.route_card import audit
    from app.route_card import notifications
    from app.route_card import review as review_mod

    card = RcRouteCard.get(id=route_id)
    if not card:
        raise HTTPException(404, "Route card not found")
    if status == "approved":
        blocking = review_mod.unresolved_blocking(route_id)
        is_admin = (user or {}).get("role") == "admin"
        if blocking and not (admin_override and is_admin):
            raise HTTPException(
                400,
                detail={
                    "message": "Resolve review flags before approve (or admin override).",
                    "blockingFlags": blocking,
                },
            )
    card.status = status
    card.updated_at = datetime.utcnow()
    if status == "approved":
        for op in card.operations:
            op.status = "Released"
    commit()
    audit.record_audit(
        action=f"status_{status}",
        user=user,
        route_card_id=route_id,
        session_id=card.drawing.session.id if card.drawing.session else None,
        detail={"adminOverride": bool(admin_override)},
        comment=comment,
    )
    if status == "approved" and card.drawing.session and card.drawing.session.user:
        notifications.create_notification(
            card.drawing.session.user.id,
            "Route card approved",
            f"Route card #{route_id} was approved.",
            link="/history",
        )
    extraction = card.drawing.extractions.select().order_by(desc(RcExtraction.created_at)).first()
    return build_payload(card.drawing, extraction, card)


@db_session
def drawing_file_meta(drawing_id: int) -> tuple[bytes, str, str]:
    drawing = RcDrawing.get(id=drawing_id)
    if not drawing:
        raise HTTPException(404, "Drawing not found")
    data = load_bytes(drawing)
    return data, drawing.filename, drawing.content_type or "application/octet-stream"


def _doc_dict(doc: RcDocument) -> dict:
    drawing_id = None
    uploaded_by = None
    try:
        # Match linked drawing by shared object path within the same session
        sess = doc.session
        if sess:
            for d in sess.drawings:
                if d.object_path == doc.object_path:
                    drawing_id = d.id
                    uploaded_by = d.uploaded_by or None
                    break
            if not uploaded_by and sess.user:
                uploaded_by = sess.user.emp_id or sess.user.name
    except Exception:
        drawing_id = None
    return {
        "id": doc.id,
        "role": doc.role,
        "filename": doc.filename,
        "file_type": doc.file_type,
        "size_bytes": doc.size_bytes,
        "size_label": format_bytes(doc.size_bytes),
        "status": doc.status,
        "warnings": doc.warnings or [],
        "drawingId": drawing_id,
        "uploadedBy": uploaded_by,
        "createdAt": doc.created_at.isoformat() if doc.created_at else None,
        "objectPath": doc.object_path,
        "contentType": doc.content_type,
    }


def _session_docs(session: RcSession) -> list[dict]:
    return [
        _doc_dict(d)
        for d in sorted(session.documents, key=lambda x: (x.role, x.id))
    ]


def _get_role_doc(session: RcSession, role: str) -> RcDocument | None:
    """Latest document for a single-slot role (PL / WL)."""
    rows = list(session.documents.select(lambda d: d.role == role))
    if not rows:
        return None
    return max(rows, key=lambda d: d.id)


def _get_role_docs(session: RcSession, role: str) -> list[RcDocument]:
    return list(
        sorted(
            session.documents.select(lambda d: d.role == role),
            key=lambda d: d.id,
        )
    )


def _session_drawing_ids(session: RcSession) -> list[int]:
    return [d.id for d in sorted(session.drawings, key=lambda x: x.id)]


@db_session
def create_session(user: dict | None = None) -> dict:
    owner = _resolve_user(user)
    session = RcSession(status="open", user=owner)
    commit()
    return {
        "id": session.id,
        "status": session.status,
        "documents": [],
        "drawingIds": [],
        "userId": owner.id if owner else None,
    }


@db_session
def get_session(session_id: int, user: dict | None = None) -> dict:
    session = RcSession.get(id=session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    _assert_session_access(session, user)
    drawings = list(sorted(session.drawings, key=lambda x: x.id))
    drawing = drawings[-1] if drawings else None
    return {
        "id": session.id,
        "status": session.status,
        "documents": _session_docs(session),
        "drawingId": drawing.id if drawing else None,
        "drawingIds": [d.id for d in drawings],
        "userId": session.user.id if session.user else None,
    }


@db_session
def upload_session_document(
    session_id: int,
    role: str,
    data: bytes,
    filename: str,
    ext: str,
    user: dict | None = None,
) -> dict:
    role = (role or "").lower().strip()
    if role not in ROLE_ALLOWED:
        raise HTTPException(400, "role must be drawing, wirelist, or partslist")
    session = RcSession.get(id=session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    _assert_session_access(session, user, write=True)
    owner = session.user or _resolve_user(user)
    if owner and not session.user:
        session.user = owner

    # PL / WL remain single-slot (replace). Drawings accumulate for multi-GA.
    if role != "drawing":
        existing = _get_role_doc(session, role)
        if existing:
            _try_unlink_local(existing.object_path, existing.storage_backend)
            existing.delete()
    else:
        # Reject duplicate GA filenames in the same session (case-insensitive).
        name_key = (filename or "").strip().lower()
        for existing in session.documents.select(lambda d: d.role == "drawing"):
            if (existing.filename or "").strip().lower() == name_key:
                raise HTTPException(
                    409,
                    f'Drawing "{filename}" is already uploaded in this session.',
                )

    # All roles for one session share a single folder
    prefix = _session_storage_prefix(user, session_id)
    store_name = _safe_store_filename(role, filename, unique=(role == "drawing"))

    path, backend = _store_path(
        prefix,
        store_name,
        data,
        CONTENT_TYPES.get(ext, "application/octet-stream"),
    )
    sniff_warns = _sniff_upload_warnings(role, data, filename, ext)
    doc = RcDocument(
        session=session,
        role=role,
        filename=filename,
        file_type=file_type_from_name(filename),
        content_type=CONTENT_TYPES.get(ext, "application/octet-stream"),
        object_path=path,
        storage_backend=backend,
        size_bytes=len(data),
        status="uploaded",
        warnings=sniff_warns,
    )

    drawing_id = None
    emp_label = (user or {}).get("empId") or (user or {}).get("username") or ""
    if role == "drawing":
        drawing = RcDrawing(
            session=session,
            user=owner,
            filename=filename,
            file_type=file_type_from_name(filename),
            content_type=CONTENT_TYPES.get(ext, "application/octet-stream"),
            object_path=path,
            storage_backend=backend,
            size_bytes=len(data),
            status="uploaded",
            drawing_type="unknown",
            uploaded_by=emp_label,
        )
        commit()
        drawing_id = drawing.id
    else:
        commit()
        drawing = session.drawings.select().order_by(desc(RcDrawing.created_at)).first()
        drawing_id = drawing.id if drawing else None

    session.updated_at = datetime.utcnow()
    session.status = "open"
    commit()
    drawing_ids = _session_drawing_ids(session)
    return {
        "sessionId": session.id,
        "document": _doc_dict(doc),
        "documents": _session_docs(session),
        "drawingId": drawing_id or (drawing_ids[-1] if drawing_ids else None),
        "drawingIds": drawing_ids,
        "canAnalyze": bool(drawing_ids),
        "warnings": sniff_warns,
    }


@db_session
def delete_session_document(
    session_id: int,
    role: str,
    user: dict | None = None,
    *,
    document_id: int | None = None,
) -> dict:
    session = RcSession.get(id=session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    _assert_session_access(session, user, write=True)
    role = (role or "").lower().strip()

    if document_id is not None:
        doc = RcDocument.get(id=document_id)
        if not doc or doc.session.id != session.id:
            raise HTTPException(404, "Document not found in this session")
        path = doc.object_path
        doc_role = doc.role
        doc.delete()
        if doc_role == "drawing":
            for d in list(session.drawings):
                if d.object_path == path:
                    d.session = None
    elif role == "drawing":
        # Remove all GA documents and unlink drawings
        for doc in list(_get_role_docs(session, "drawing")):
            doc.delete()
        for d in list(session.drawings):
            d.session = None
    else:
        doc = _get_role_doc(session, role)
        if doc:
            doc.delete()

    session.updated_at = datetime.utcnow()
    commit()
    drawings = list(sorted(session.drawings, key=lambda x: x.id))
    drawing = drawings[-1] if drawings else None
    return {
        "sessionId": session.id,
        "documents": _session_docs(session),
        "drawingId": drawing.id if drawing else None,
        "drawingIds": [d.id for d in drawings],
        "canAnalyze": bool(drawings),
    }


@db_session
def analyze_session(
    session_id: int,
    user: dict | None = None,
    cancel_event=None,
    vlm_page_indexes: list[int] | None = None,
) -> dict:
    from app.route_card.analyze_jobs import AnalysisCancelled, check_cancelled

    session = RcSession.get(id=session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    _assert_session_access(session, user, write=True)
    drawings = list(sorted(session.drawings, key=lambda x: x.id))
    if not drawings:
        raise HTTPException(400, "Upload at least one drawing before starting analysis")

    check_cancelled(cancel_event)
    session.status = "analyzing"
    for drawing in drawings:
        drawing.status = "analyzing"
        if not drawing.user and session.user:
            drawing.user = session.user
    commit()

    try:
        return _analyze_session_body(
            session,
            drawings,
            cancel_event=cancel_event,
            user=user,
            vlm_page_indexes=vlm_page_indexes,
        )
    except AnalysisCancelled:
        session.status = "cancelled"
        for drawing in drawings:
            if drawing.status == "analyzing":
                drawing.status = "uploaded"
        commit()
        raise


def _analyze_one_ga(
    drawing: RcDrawing,
    *,
    format_matches: dict,
    parts_list: dict | None = None,
    wire_list: dict | None = None,
    cancel_event=None,
    vlm_page_indexes: list[int] | None = None,
    prompt_addendum: str | None = None,
) -> dict:
    """Extract + drawing-mind for a single GA; returns enriched parse dict."""
    from app.route_card.analyze_jobs import check_cancelled
    from app.route_card.drawing_mind import get_drawing_mind
    from app.route_card.pdf_ingest import extract_spatial_pages

    check_cancelled(cancel_event)

    data = load_bytes(drawing)
    ext = Path(drawing.filename).suffix.lower()

    ga_aliases = None
    if ext == ".pdf":
        from app.route_card.pdf_ingest import ingest_pdf

        preview = ingest_pdf(data, want_tables=False)
        ga_match, ga_aliases = _match_and_aliases(preview.text, "GA")
        format_matches.setdefault("drawing", {
            "matched": ga_match.get("matched"),
            "score": ga_match.get("score"),
            "template": ga_match.get("template"),
            "candidates": ga_match.get("candidates"),
        })

    parsed = _extract_from_bytes(data, drawing.filename, ext, format_aliases=ga_aliases)
    if "drawing" not in format_matches and parsed.get("raw_text"):
        ga_match, _ = _match_and_aliases(parsed.get("raw_text") or "", "GA")
        format_matches["drawing"] = {
            "matched": ga_match.get("matched"),
            "score": ga_match.get("score"),
            "template": ga_match.get("template"),
            "candidates": ga_match.get("candidates"),
        }

    spatial_pages: list = []
    spatial_warns: list[str] = []
    if ext == ".pdf":
        spatial_pages, spatial_warns = extract_spatial_pages(
            data, cancel_event=cancel_event
        )

    check_cancelled(cancel_event)
    mind = get_drawing_mind()
    mind_result = mind.understand(
        pdf_bytes=data if ext == ".pdf" else None,
        ga_extraction=parsed,
        spatial_pages=spatial_pages,
        parts_list=parts_list,
        wire_list=wire_list,
        source_drawing_id=drawing.id,
        source_filename=drawing.filename,
        cancel_event=cancel_event,
        page_indexes=vlm_page_indexes,
        prompt_addendum=prompt_addendum,
    )
    parsed["notes"] = mind_result.notes
    parsed["mind"] = mind_result.to_dict()
    parsed["warnings"] = list(
        dict.fromkeys(
            (parsed.get("warnings") or [])
            + spatial_warns
            + mind_result.warnings
        )
    )
    parsed["drawingId"] = drawing.id
    parsed["filename"] = drawing.filename
    parsed["drawingNumber"] = (parsed.get("title_block") or {}).get("drawingNumber") or ""

    drawing.pages = parsed.get("pages")
    drawing.drawing_type = parsed.get("drawing_type") or "unknown"
    return parsed


def _analyze_session_body(
    session: RcSession,
    drawings: list[RcDrawing],
    cancel_event=None,
    user: dict | None = None,
    vlm_page_indexes: list[int] | None = None,
) -> dict:
    from app.route_card.analyze_jobs import AnalysisCancelled, check_cancelled
    from app.route_card.drawing_mind import merge_ga_extractions

    extra_warnings: list[str] = []
    wire_list = None
    parts_list = None
    format_matches: dict = {}
    primary = drawings[-1]

    try:
        check_cancelled(cancel_event)
        # --- Wire List / Parts List first so mind can cross-link ---
        wl_doc = _get_role_doc(session, "wirelist")
        if wl_doc:
            wl_bytes = load_path_bytes(wl_doc.object_path, wl_doc.storage_backend)
            from app.route_card.pdf_ingest import ingest_pdf as _ingest_wl

            wl_preview_text = ""
            if Path(wl_doc.filename).suffix.lower() == ".pdf":
                wl_preview_text = _ingest_wl(wl_bytes, want_tables=True).text
            wl_match, wl_aliases = _match_and_aliases(wl_preview_text, "WL")
            format_matches["wirelist"] = {
                "matched": wl_match.get("matched"),
                "score": wl_match.get("score"),
                "template": wl_match.get("template"),
                "candidates": wl_match.get("candidates"),
            }
            wire_list = parse_wirelist_bytes(wl_bytes, wl_doc.filename, format_aliases=wl_aliases)
            wl_doc.extraction = {
                **{
                    k: wire_list[k]
                    for k in (
                        "docType",
                        "partNumber",
                        "title",
                        "wireCount",
                        "materials",
                        "notes",
                        "plItemRefs",
                        "warnings",
                    )
                    if k in wire_list
                },
                "formatMatch": format_matches.get("wirelist"),
            }
            wl_doc.warnings = wire_list.get("warnings") or []
            wl_doc.status = "analyzed"
        else:
            extra_warnings.append(
                "Wire List not provided — cable pin map / continuity checklist skipped."
            )

        pl_doc = _get_role_doc(session, "partslist")
        if pl_doc:
            pl_bytes = load_path_bytes(pl_doc.object_path, pl_doc.storage_backend)
            pl_preview_text = ""
            if Path(pl_doc.filename).suffix.lower() == ".pdf":
                from app.route_card.pdf_ingest import ingest_pdf as _ingest_pl

                pl_preview_text = _ingest_pl(pl_bytes, want_tables=True).text
            pl_match, pl_aliases = _match_and_aliases(pl_preview_text, "PL")
            format_matches["partslist"] = {
                "matched": pl_match.get("matched"),
                "score": pl_match.get("score"),
                "template": pl_match.get("template"),
                "candidates": pl_match.get("candidates"),
            }
            parts_list = parse_partslist_bytes(pl_bytes, pl_doc.filename, format_aliases=pl_aliases)
            pl_doc.extraction = {
                "docType": "PL",
                "partNumber": parts_list.get("partNumber"),
                "itemCount": len(parts_list.get("items") or []),
                "warnings": parts_list.get("warnings") or [],
                "formatMatch": format_matches.get("partslist"),
            }
            pl_doc.warnings = parts_list.get("warnings") or []
            pl_doc.status = "analyzed"
            if not (parts_list.get("items") or []):
                extra_warnings.append("Parts List uploaded but no item rows parsed yet.")
        else:
            extra_warnings.append("Parts List not provided — item descriptions remain empty.")

        # --- Each GA ---
        ga_results: list[dict] = []
        mind_payloads: list[dict] = []
        for drawing in drawings:
            check_cancelled(cancel_event)
            dept = ""
            prompt_addendum = ""
            if user:
                dept = (user.get("dept") or "").strip()
            elif session.user:
                dept = (session.user.dept or "").strip()
            try:
                from app.route_card.dept_config import few_shot_prompt_block, get_dept_rules

                rules = (get_dept_rules(dept).get("rules") or {}) if dept else {}
                prompt_addendum = (rules.get("promptAddendum") or "").strip()
                fs = few_shot_prompt_block(dept or None, limit=3)
                if fs:
                    prompt_addendum = (prompt_addendum + "\n\n" + fs).strip()
            except Exception:
                prompt_addendum = ""
            parsed_one = _analyze_one_ga(
                drawing,
                format_matches=format_matches,
                parts_list=parts_list,
                wire_list=wire_list,
                cancel_event=cancel_event,
                vlm_page_indexes=vlm_page_indexes,
                prompt_addendum=prompt_addendum or None,
            )
            ga_results.append(parsed_one)
            if parsed_one.get("mind"):
                mind_payloads.append(parsed_one["mind"])

            RcExtraction(
                drawing=drawing,
                title_block=parsed_one.get("title_block") or {},
                revisions=parsed_one.get("revisions") or [],
                bom_items=parsed_one.get("bom_items") or [],
                notes=parsed_one.get("notes") or [],
                torque_specs=parsed_one.get("torque_specs") or [],
                dimensions=parsed_one.get("dimensions") or [],
                references=parsed_one.get("references") or [],
                warnings=parsed_one.get("warnings") or [],
                raw_text=parsed_one.get("raw_text") or "",
            )
            # Mark matching document analyzed
            for doc in _get_role_docs(session, "drawing"):
                if doc.object_path == drawing.object_path:
                    doc.extraction = {
                        "title_block": parsed_one.get("title_block"),
                        "bom_count": len(parsed_one.get("bom_items") or []),
                        "notes_count": len(parsed_one.get("notes") or []),
                        "drawingId": drawing.id,
                        "mindEngine": (parsed_one.get("mind") or {}).get("engine"),
                        "formatMatch": format_matches.get("drawing"),
                    }
                    doc.status = "analyzed"
                    break
            drawing.status = "analyzed"

        parsed = merge_ga_extractions(ga_results)
        extra_warnings.extend(parsed.get("warnings") or [])

        # Combined mind summary
        view_warns = [
            w
            for w in (parsed.get("warnings") or [])
            if any(
                k in w.upper()
                for k in (
                    "SHEET",
                    "FIGURE",
                    "TABLE",
                    "TABEL",
                    "DETAIL",
                    "VIEW REF",
                    "GA SHEET",
                )
            )
        ]
        combined_mind = {
            "engine": (mind_payloads[0].get("engine") if mind_payloads else "cpu_spatial"),
            "placements": [
                p for m in mind_payloads for p in (m.get("placements") or [])
            ],
            "pcbLinks": [
                p for m in mind_payloads for p in (m.get("pcbLinks") or [])
            ],
            "crossRefs": parsed.get("crossRefs") or [],
            "viewRefs": parsed.get("viewRefs") or [],
            "warnings": list(
                dict.fromkeys(
                    [w for m in mind_payloads for w in (m.get("warnings") or [])]
                    + view_warns
                )
            ),
            "gaSources": parsed.get("gaSources") or [],
        }
        parsed["mind"] = combined_mind

        if parts_list:
            parsed["bom_items"] = enrich_bom_with_pl(parsed.get("bom_items") or [], parts_list)

        # Persist merged extraction on primary drawing for route-card FK
        extraction = RcExtraction(
            drawing=primary,
            title_block=parsed.get("title_block") or {},
            revisions=parsed.get("revisions") or [],
            bom_items=parsed.get("bom_items") or [],
            notes=parsed.get("notes") or [],
            torque_specs=parsed.get("torque_specs") or [],
            dimensions=parsed.get("dimensions") or [],
            references=parsed.get("references") or [],
            warnings=list(dict.fromkeys((parsed.get("warnings") or []) + extra_warnings)),
            raw_text=parsed.get("raw_text") or "",
        )

        generated = generate_route(parsed)

        # Auto-apply department operation templates when configured
        try:
            from app.route_card.workflow import apply_auto_templates

            dept = ""
            if user:
                dept = (user.get("dept") or "").strip()
            elif session.user:
                dept = (session.user.dept or "").strip()
            generated["operations"] = apply_auto_templates(
                generated.get("operations") or [],
                dept=dept,
                title_block=parsed.get("title_block") or {},
                notes=parsed.get("notes") or [],
            )
        except Exception:
            pass

        if wire_list:
            ga_pn = re.sub(
                r"\s+", "", (parsed.get("title_block") or {}).get("partNumber") or ""
            )
            wl_pn = re.sub(r"\s+", "", wire_list.get("partNumber") or "")
            if ga_pn and wl_pn and ga_pn != wl_pn:
                extra_warnings.append(
                    f"Wire List part number ({wire_list.get('partNumber')}) differs from drawing "
                    f"({(parsed.get('title_block') or {}).get('partNumber')}). Merged anyway."
                )
            max_op = max((o.get("opNo") or 0 for o in generated["operations"]), default=0)
            additions = wirelist_to_route_additions(wire_list, start_op=max_op + 10)
            ga_ops = [
                o
                for o in generated["operations"]
                if (o.get("workCentre") or "") != "Quality"
                or "Final" not in (o.get("operation") or "")
            ]
            final_ops = [o for o in generated["operations"] if o not in ga_ops]
            generated["operations"] = ga_ops + additions["operations"] + final_ops
            generated["inspection"] = (generated.get("inspection") or []) + additions.get(
                "inspection", []
            )

        if parts_list:
            generated["operations"] = enrich_ops_items(generated["operations"], parts_list)
            generated["manufacturing_features"] = [
                {
                    **f,
                    "type": (
                        f.get("type", "")
                        + (
                            f" — {(parts_list.get('itemMap') or {}).get(str(f.get('id', '').replace('ITM-', '')), {}).get('description') or ''}"
                            if (parts_list.get("itemMap") or {}).get(
                                str(f.get("id", "").replace("ITM-", ""))
                            )
                            else ""
                        )
                    ).strip(" —"),
                }
                for f in (generated.get("manufacturing_features") or [])
            ]

        # Append PCB link callouts as soft intelligence requirements
        for link in combined_mind.get("pcbLinks") or []:
            generated.setdefault("intelligence_requirements", []).append(
                {
                    "label": f"Connector {link.get('connector')}",
                    "value": (
                        f"PL item {link.get('plItemNo') or '—'} "
                        f"({link.get('plDescription') or 'n/a'}); "
                        f"WL wires: {link.get('wlWireCount') or 0}"
                    ),
                    "level": "Important",
                }
            )

        existing = primary.route_cards.select().order_by(desc(RcRouteCard.created_at)).first()
        card = persist_route(primary, generated, existing)
        primary.status = "analyzed"
        session.status = "analyzed"
        session.updated_at = datetime.utcnow()
        primary.updated_at = datetime.utcnow()
        commit()

        # Phase 1: review flags + item link report
        review_flags = []
        item_link = {}
        try:
            from app.route_card import review as review_mod

            item_link = review_mod.build_item_link_report(
                parsed, parts_list, mind=combined_mind
            )
            u_ent = session.user
            review_flags = review_mod.rebuild_review_flags(
                session=session,
                card=card,
                user=u_ent,
                parsed=parsed,
                parts_list=parts_list,
                mind=combined_mind,
                extra_warnings=extra_warnings,
                operations=generated.get("operations") or [],
            )
        except Exception:
            review_flags = []
            item_link = {}

        extraction.bom_items = parsed.get("bom_items") or extraction.bom_items
        extraction.notes = parsed.get("notes") or extraction.notes
        payload = build_payload(
            primary,
            extraction,
            card,
            documents=_session_docs(session),
            wire_list=wire_list,
            parts_list=parts_list,
            extra_warnings=extra_warnings,
            format_matches=format_matches,
            mind=combined_mind,
            drawings=[
                {
                    "id": d.id,
                    "filename": d.filename,
                    "status": d.status,
                    "pages": d.pages,
                    "drawingType": d.drawing_type,
                }
                for d in drawings
            ],
            cross_refs=combined_mind.get("crossRefs") or [],
            view_refs=combined_mind.get("viewRefs") or [],
        )
        payload["reviewFlags"] = review_flags
        payload["itemLinkReport"] = item_link
        return payload
    except AnalysisCancelled:
        raise
    except HTTPException:
        for d in drawings:
            d.status = "failed"
        session.status = "failed"
        commit()
        raise
    except Exception as exc:
        for d in drawings:
            d.status = "failed"
            d.error_message = str(exc)[:500]
        session.status = "failed"
        commit()
        raise HTTPException(500, f"Analysis failed: {exc}") from exc


def get_format_templates() -> dict:
    rows = list_templates()
    return {
        "templates": [
            {
                "id": t.get("id"),
                "name": t.get("name"),
                "docType": t.get("docType"),
                "builtin": bool(t.get("builtin")),
                "aliases": t.get("aliases") or {},
                "stats": t.get("stats") or {},
                "updatedAt": t.get("updatedAt"),
                "notes": t.get("notes") or "",
            }
            for t in rows
        ]
    }


@db_session
def learn_format_from_session(session_id: int, body: dict, user: dict | None = None) -> dict:
    """Save a format template from the latest analyzed docs in a session (human-confirmed)."""
    session = RcSession.get(id=session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    _assert_session_access(session, user, write=True)

    role = (body.get("role") or "drawing").lower().strip()
    if role not in {"drawing", "wirelist", "partslist"}:
        raise HTTPException(400, "role must be drawing, wirelist, or partslist")

    doc_type = (body.get("docType") or {"drawing": "GA", "wirelist": "WL", "partslist": "PL"}[role]).upper()
    name = (body.get("name") or "").strip() or f"Learned {doc_type} — session {session_id}"
    aliases = body.get("aliases") if isinstance(body.get("aliases"), dict) else {}
    notes = (body.get("notes") or "").strip()
    update_id = (body.get("updateId") or "").strip() or None

    text = ""
    if role == "drawing":
        drawing = session.drawings.select().order_by(desc(RcDrawing.created_at)).first()
        if drawing:
            latest = drawing.extractions.select().order_by(desc(RcExtraction.created_at)).first()
            if latest and latest.raw_text:
                text = latest.raw_text
            else:
                data = load_bytes(drawing)
                if Path(drawing.filename).suffix.lower() == ".pdf":
                    from app.route_card.pdf_ingest import ingest_pdf

                    text = ingest_pdf(data, want_tables=False).text
    else:
        doc = _get_role_doc(session, role)
        if not doc:
            raise HTTPException(400, f"No {role} document in this session")
        data = load_path_bytes(doc.object_path, doc.storage_backend)
        if Path(doc.filename).suffix.lower() == ".pdf":
            from app.route_card.pdf_ingest import ingest_pdf

            text = ingest_pdf(data, want_tables=True).text
        else:
            text = (doc.extraction or {}).get("raw_text") or ""

    if len((text or "").strip()) < 40:
        raise HTTPException(
            400,
            "Not enough extracted text to fingerprint this format. Analyze the session first.",
        )

    fp = fingerprint_text(text, doc_type_hint=doc_type)

    defaults = {
        "GA": {
            "noteHeaders": [
                "NOTE",
                "NOTES",
                "REMARKS",
                "INSTRUCTIONS",
                "INSTRUCTION",
                "ASSY NOTES",
                "ASSEMBLY NOTES",
                "ASSY INSTRUCTIONS",
                "ASSEMBLY INSTRUCTIONS",
                "CTQ POINTS",
                "CTQ POINT",
                "CRITICAL TO QUALITY POINTS",
            ],
            "plColumns": {},
            "wlHints": [],
        },
        "PL": {
            "noteHeaders": [],
            "plColumns": {
                "item": ["ITEM", "ITEM NO", "ITM", "S.NO", "SL NO"],
                "description": ["DESIGNATION", "DESCRIPTION", "DESC"],
                "partNo": ["PART NO", "PART NUMBER", "P/N", "PN"],
                "qty": ["QTY", "QUANTITY", "NOS"],
            },
            "wlHints": [],
        },
        "WL": {
            "noteHeaders": [],
            "plColumns": {},
            "wlHints": ["WIRE LIST", "FROM", "TO", "WIRE LFH"],
        },
    }
    base = defaults.get(doc_type, {"noteHeaders": [], "plColumns": {}, "wlHints": []})
    merged = {
        "noteHeaders": list(
            dict.fromkeys([*(aliases.get("noteHeaders") or []), *(base.get("noteHeaders") or [])])
        ),
        "plColumns": {**(base.get("plColumns") or {}), **(aliases.get("plColumns") or {})},
        "wlHints": list(dict.fromkeys([*(aliases.get("wlHints") or []), *(base.get("wlHints") or [])])),
    }

    row = learn_template(
        name=name,
        doc_type=doc_type,
        fingerprint=fp,
        aliases=merged,
        source_session_id=session_id,
        notes=notes,
        update_id=update_id,
    )
    return {
        "ok": True,
        "template": {
            "id": row.get("id"),
            "name": row.get("name"),
            "docType": row.get("docType"),
            "builtin": bool(row.get("builtin")),
            "aliases": row.get("aliases") or {},
            "stats": row.get("stats") or {},
        },
        "message": (
            f"Saved format template “{row.get('name')}”. "
            "Similar uploads will match this layout next time."
        ),
    }


def remove_format_template(template_id: str) -> dict:
    ok = delete_template(template_id)
    if not ok:
        raise HTTPException(400, "Template not found or is a built-in default (cannot delete).")
    return {"ok": True, "id": template_id}


@db_session
def export_route_card_pmf_oarc(
    route_id: int,
    *,
    required_qty: int | None = None,
    plant: str | None = None,
    production_order: str = "",
    sale_order: str = "",
    wbs: str = "",
    project_name: str = "",
) -> dict:
    """Build PMF Create-Order (OARC) JSON from an analyzed route card."""
    card = RcRouteCard.get(id=route_id)
    if not card:
        raise HTTPException(404, "Route card not found")
    drawing = card.drawing
    extraction = drawing.extractions.select().order_by(desc(RcExtraction.created_at)).first()

    wire_list = None
    parts_list = None
    documents = []
    session = drawing.session
    if session:
        documents = _session_docs(session)
        pl_doc = _get_role_doc(session, "partslist")
        if pl_doc and pl_doc.extraction:
            parts_list = {
                "partNumber": (pl_doc.extraction or {}).get("partNumber"),
                "items": (pl_doc.extraction or {}).get("items")
                or [],
                "itemCount": (pl_doc.extraction or {}).get("itemCount") or 0,
            }
            # Prefer live re-parse for full item rows when file still available
            try:
                pl_bytes = load_path_bytes(pl_doc.object_path, pl_doc.storage_backend)
                parts_list = parse_partslist_bytes(pl_bytes, pl_doc.filename)
            except Exception:
                pass
        wl_doc = _get_role_doc(session, "wirelist")
        if wl_doc:
            try:
                wl_bytes = load_path_bytes(wl_doc.object_path, wl_doc.storage_backend)
                wire_list = parse_wirelist_bytes(wl_bytes, wl_doc.filename)
            except Exception:
                wire_list = wl_doc.extraction

    payload = build_payload(
        drawing,
        extraction,
        card,
        documents=documents,
        wire_list=wire_list,
        parts_list=parts_list,
    )
    return payload_to_pmf_oarc(
        payload,
        required_qty=required_qty if required_qty is not None else 1,
        plant=plant or "",
        production_order=production_order or "",
        sale_order=sale_order or "",
        wbs=wbs or "",
        project_name=project_name or "",
    )


def _session_summary(session: RcSession) -> dict:
    drawing = session.drawings.select().order_by(desc(RcDrawing.created_at)).first()
    title: dict = {}
    route_card_id = None
    route_status = None
    op_count = 0
    if drawing:
        extraction = drawing.extractions.select().order_by(desc(RcExtraction.created_at)).first()
        if extraction and extraction.title_block:
            title = dict(extraction.title_block or {})
        card = drawing.route_cards.select().order_by(desc(RcRouteCard.created_at)).first()
        if card:
            route_card_id = card.id
            route_status = card.status
            op_count = len(card.operations)
            if card.part_info and isinstance(card.part_info, dict):
                title = {**title, **dict(card.part_info or {})}
    owner = session.user
    owner_label = ""
    if owner:
        owner_label = owner.emp_id or owner.name or ""
    docs = []
    for d in sorted(session.documents, key=lambda x: (x.role, x.id)):
        uploaded_by = owner_label
        if d.role == "drawing":
            for dr in session.drawings:
                if dr.object_path == d.object_path and dr.uploaded_by:
                    uploaded_by = dr.uploaded_by
                    break
        docs.append(
            {
                "id": d.id,
                "role": d.role,
                "filename": d.filename,
                "fileType": d.file_type,
                "sizeBytes": d.size_bytes,
                "sizeLabel": format_bytes(d.size_bytes),
                "status": d.status,
                "storageBackend": d.storage_backend,
                "objectPath": d.object_path,
                "contentType": d.content_type,
                "createdAt": d.created_at.isoformat() if d.created_at else None,
                "uploadedBy": uploaded_by or None,
                "warnings": d.warnings or [],
            }
        )
    folder_key = _session_storage_prefix(
        {"empId": owner.emp_id, "id": owner.id} if owner else None,
        session.id,
    ).replace("/", "_")
    return {
        "sessionId": session.id,
        "status": session.status,
        "createdAt": session.created_at.isoformat() if session.created_at else None,
        "updatedAt": session.updated_at.isoformat() if session.updated_at else None,
        "partNumber": title.get("partNumber") or title.get("drawingNumber") or "",
        "partName": title.get("partName") or title.get("title") or "",
        "revision": title.get("version") or title.get("revision") or "",
        "drawingId": drawing.id if drawing else None,
        "routeCardId": route_card_id,
        "routeStatus": route_status,
        "operationCount": op_count,
        "documents": docs,
        "folder": str(get_local_upload_root() / folder_key).replace("\\", "/"),
        "user": (
            {
                "id": owner.id,
                "empId": owner.emp_id,
                "name": owner.name,
                "dept": owner.dept or "",
                "role": owner.role,
            }
            if owner
            else None
        ),
    }


@db_session
def list_my_extractions(user: dict | None) -> dict:
    owner = _resolve_user(user)
    if not owner and not _is_admin(user):
        raise HTTPException(401, "Not authenticated")
    if owner:
        sessions = RcSession.select(lambda s: s.user == owner).order_by(desc(RcSession.updated_at))[:]
    else:
        sessions = []
    items = [_session_summary(s) for s in sessions if s.status != "open" or s.documents]
    return {"items": items, "total": len(items)}


@db_session
def get_extraction_detail(session_id: int, user: dict | None) -> dict:
    session = RcSession.get(id=session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    _assert_session_access(session, user)
    summary = _session_summary(session)
    drawing = session.drawings.select().order_by(desc(RcDrawing.created_at)).first()
    payload = None
    if drawing:
        extraction = drawing.extractions.select().order_by(desc(RcExtraction.created_at)).first()
        card = drawing.route_cards.select().order_by(desc(RcRouteCard.created_at)).first()
        wire_list = None
        parts_list = None
        pl_doc = _get_role_doc(session, "partslist")
        if pl_doc:
            try:
                pl_bytes = load_path_bytes(pl_doc.object_path, pl_doc.storage_backend)
                parts_list = parse_partslist_bytes(pl_bytes, pl_doc.filename)
            except Exception:
                parts_list = {
                    "partNumber": (pl_doc.extraction or {}).get("partNumber"),
                    "items": (pl_doc.extraction or {}).get("items") or [],
                    "itemCount": (pl_doc.extraction or {}).get("itemCount") or 0,
                }
        wl_doc = _get_role_doc(session, "wirelist")
        if wl_doc:
            try:
                wl_bytes = load_path_bytes(wl_doc.object_path, wl_doc.storage_backend)
                wire_list = parse_wirelist_bytes(wl_bytes, wl_doc.filename)
            except Exception:
                wire_list = wl_doc.extraction
        if extraction or card:
            payload = build_payload(
                drawing,
                extraction,
                card,
                documents=_session_docs(session),
                wire_list=wire_list,
                parts_list=parts_list,
            )
    return {**summary, "payload": payload}


@db_session
def list_admin_users(user: dict | None) -> dict:
    if not _is_admin(user):
        raise HTTPException(403, "Admin access required")
    rows = _user_rows()
    return {"users": rows, "total": len(rows)}


def _user_rows(dept: str | None = None) -> list[dict]:
    dept_n = (dept or "").strip()
    rows = []
    for u in RcUser.select().order_by(RcUser.emp_id)[:]:
        if dept_n and (u.dept or "") != dept_n:
            continue
        session_count = 0
        analyzed = 0
        for s in u.sessions:
            session_count += 1
            if s.status in ("analyzed", "approved"):
                analyzed += 1
        rows.append(
            {
                "id": u.id,
                "empId": u.emp_id,
                "name": u.name,
                "dept": u.dept or "",
                "role": u.role,
                "isActive": u.is_active,
                "createdAt": u.created_at.isoformat() if u.created_at else None,
                "sessionCount": session_count,
                "analyzedCount": analyzed,
            }
        )
    return rows


@db_session
def list_dept_users(user: dict | None) -> dict:
    """Dept head: users in own department. Admin: all users."""
    if not user:
        raise HTTPException(401, "Not authenticated")
    role = user.get("role") or ""
    if role == "admin":
        rows = _user_rows()
        return {"users": rows, "total": len(rows)}
    if role != "dept_head":
        raise HTTPException(403, "Department head or admin access required")
    dept = (user.get("dept") or "").strip()
    if not dept:
        return {"users": [], "total": 0, "dept": ""}
    rows = _user_rows(dept)
    return {"users": rows, "total": len(rows), "dept": dept}


def update_admin_user_role(user: dict | None, user_id: int, role: str) -> dict:
    """Backward-compatible role-only update (admin)."""
    return update_managed_user(user, user_id, {"role": role})


def _public_user_row(u: RcUser) -> dict:
    return {
        "id": u.id,
        "empId": u.emp_id,
        "name": u.name,
        "dept": u.dept or "",
        "role": u.role,
        "isActive": u.is_active,
    }


def _assert_can_manage_target(actor: dict | None, target: RcUser) -> None:
    if not actor:
        raise HTTPException(401, "Not authenticated")
    actor_role = (actor.get("role") or "").strip().lower()
    if actor_role == "admin":
        return
    if actor_role != "dept_head":
        raise HTTPException(403, "Department head or admin access required")
    actor_dept = (actor.get("dept") or "").strip()
    if not actor_dept:
        raise HTTPException(400, "Your account has no department assigned")
    if target.role == "admin":
        raise HTTPException(403, "Cannot manage the admin account")
    if (target.dept or "").strip() != actor_dept:
        raise HTTPException(403, "User is not in your department")
    if target.role != "engineer":
        raise HTTPException(403, "Department heads can only manage engineers in their department")


def _validate_dept_name(dept: str) -> str:
    dept_n = (dept or "").strip()
    if not dept_n:
        raise HTTPException(400, "dept is required")
    master = select(d for d in RcDepartment if d.is_active and d.name == dept_n)[:1]
    if not master:
        raise HTTPException(400, "Select a valid department")
    return dept_n


@db_session
def create_managed_user(actor: dict | None, body: dict) -> dict:
    if not actor:
        raise HTTPException(401, "Not authenticated")
    actor_role = (actor.get("role") or "").strip().lower()
    if actor_role not in {"admin", "dept_head"}:
        raise HTTPException(403, "Department head or admin access required")

    emp_id = (body.get("empId") or "").strip()
    name = (body.get("name") or "").strip()
    password = body.get("password") or ""
    role_n = (body.get("role") or "engineer").strip().lower()
    if not name:
        raise HTTPException(400, "name is required")
    from app.auth import validate_employee_id

    emp_id = validate_employee_id(emp_id, allow_admin_id=False)
    if len(str(password)) < 4:
        raise HTTPException(400, "password must be at least 4 characters")

    if actor_role == "admin":
        if role_n not in {"dept_head", "engineer"}:
            raise HTTPException(400, "role must be dept_head or engineer")
        dept_n = _validate_dept_name(body.get("dept") or "")
    else:
        if role_n != "engineer":
            raise HTTPException(403, "Department heads can only create engineer accounts")
        dept_n = (actor.get("dept") or "").strip()
        if not dept_n:
            raise HTTPException(400, "Your account has no department assigned")

    if RcUser.get(emp_id=emp_id):
        raise HTTPException(400, f"Employee ID '{emp_id}' is already registered")

    from app.security import hash_password

    user = RcUser(
        emp_id=emp_id,
        name=name,
        dept=dept_n,
        password_hash=hash_password(str(password)),
        role=role_n,
        is_active=True,
    )
    commit()
    return {
        **_public_user_row(user),
        "createdAt": user.created_at.isoformat() if user.created_at else None,
        "sessionCount": 0,
        "analyzedCount": 0,
    }


@db_session
def update_managed_user(actor: dict | None, user_id: int, body: dict) -> dict:
    if not actor:
        raise HTTPException(401, "Not authenticated")
    actor_role = (actor.get("role") or "").strip().lower()
    if actor_role not in {"admin", "dept_head"}:
        raise HTTPException(403, "Department head or admin access required")

    target = RcUser.get(id=int(user_id))
    if not target:
        raise HTTPException(404, "User not found")
    if target.role == "admin":
        raise HTTPException(400, "Cannot change the admin account")

    if actor_role == "dept_head":
        _assert_can_manage_target(actor, target)
        # Dept head: name / empId only for engineers in own dept
        if "role" in body and body.get("role") is not None:
            role_n = str(body.get("role") or "").strip().lower()
            if role_n and role_n != target.role:
                raise HTTPException(403, "Department heads cannot change roles")
        if "dept" in body and body.get("dept") is not None:
            dept_n = str(body.get("dept") or "").strip()
            if dept_n and dept_n != (target.dept or "").strip():
                raise HTTPException(403, "Department heads cannot change department")

    if "empId" in body and body.get("empId") is not None:
        from app.auth import validate_employee_id

        emp_id = validate_employee_id(
            str(body.get("empId") or ""),
            allow_admin_id=(target.role == "admin"),
        )
        if emp_id != target.emp_id:
            clash = RcUser.get(emp_id=emp_id)
            if clash and clash.id != target.id:
                raise HTTPException(400, f"Employee ID '{emp_id}' is already registered")
            target.emp_id = emp_id

    if "name" in body and body.get("name") is not None:
        name = str(body.get("name") or "").strip()
        if not name:
            raise HTTPException(400, "name is required")
        target.name = name

    if actor_role == "admin":
        if "dept" in body and body.get("dept") is not None:
            target.dept = _validate_dept_name(body.get("dept") or "")
        if "role" in body and body.get("role") is not None:
            role_n = str(body.get("role") or "").strip().lower()
            if role_n not in {"dept_head", "engineer"}:
                raise HTTPException(400, "role must be dept_head or engineer")
            target.role = role_n

    commit()
    return _public_user_row(target)


@db_session
def reset_managed_user_password(actor: dict | None, user_id: int, password: str) -> dict:
    if not actor:
        raise HTTPException(401, "Not authenticated")
    actor_role = (actor.get("role") or "").strip().lower()
    if actor_role not in {"admin", "dept_head"}:
        raise HTTPException(403, "Department head or admin access required")
    raw = str(password or "")
    if len(raw) < 4:
        raise HTTPException(400, "password must be at least 4 characters")

    target = RcUser.get(id=int(user_id))
    if not target:
        raise HTTPException(404, "User not found")
    if target.role == "admin":
        raise HTTPException(400, "Cannot reset the admin account password here")

    if actor_role == "dept_head":
        _assert_can_manage_target(actor, target)
        if target.role != "engineer":
            raise HTTPException(403, "Department heads can only reset engineer passwords")

    from app.security import hash_password, verify_password

    new_hash = hash_password(raw)
    target.password_hash = new_hash
    commit()

    # Re-read and verify so we never report success if persist failed
    refreshed = RcUser.get(id=int(user_id))
    if not refreshed or not verify_password(raw, refreshed.password_hash):
        raise HTTPException(500, "Password reset did not persist. Please try again.")

    return {
        "id": refreshed.id,
        "empId": refreshed.emp_id,
        "name": refreshed.name,
        "ok": True,
        "message": "Password reset successfully",
    }


@db_session
def list_admin_extractions(
    user: dict | None,
    emp_id: str | None = None,
    dept: str | None = None,
    status: str | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
) -> dict:
    if not _is_admin(user):
        raise HTTPException(403, "Admin access required")

    emp = (emp_id or "").strip()
    dept_filter = (dept or "").strip()
    status_filter = (status or "").strip().lower()

    from_dt = None
    to_dt = None
    if from_date:
        try:
            from_dt = datetime.strptime(from_date.strip()[:10], "%Y-%m-%d")
        except ValueError as exc:
            raise HTTPException(400, "fromDate must be YYYY-MM-DD") from exc
    if to_date:
        try:
            to_dt = datetime.strptime(to_date.strip()[:10], "%Y-%m-%d") + timedelta(
                days=1, microseconds=-1
            )
        except ValueError as exc:
            raise HTTPException(400, "toDate must be YYYY-MM-DD") from exc

    if emp:
        owner = RcUser.get(emp_id=emp)
        if not owner:
            return {"items": [], "total": 0}
        sessions = RcSession.select(lambda s: s.user == owner).order_by(
            desc(RcSession.updated_at)
        )[:]
    elif dept_filter:
        owners = {u for u in RcUser.select() if (u.dept or "") == dept_filter}
        if not owners:
            return {"items": [], "total": 0}
        sessions = [
            s
            for s in RcSession.select().order_by(desc(RcSession.updated_at))[:]
            if s.user in owners
        ]
    else:
        sessions = RcSession.select().order_by(desc(RcSession.updated_at))[:]

    items = []
    for s in sessions:
        if s.status == "open" and not s.documents:
            continue
        if status_filter and (s.status or "").lower() != status_filter:
            continue
        if dept_filter and emp:
            owner = s.user
            if not owner or (owner.dept or "") != dept_filter:
                continue
        updated = s.updated_at
        if from_dt and (not updated or updated < from_dt):
            continue
        if to_dt and (not updated or updated > to_dt):
            continue
        items.append(_session_summary(s))

    return {"items": items, "total": len(items)}


@db_session
def session_document_file(
    session_id: int,
    role: str,
    user: dict | None,
    *,
    document_id: int | None = None,
) -> tuple[bytes, str, str]:
    session = RcSession.get(id=session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    _assert_session_access(session, user)
    if document_id is not None:
        doc = RcDocument.get(id=document_id)
        if not doc or doc.session.id != session.id:
            raise HTTPException(404, "Document not found in this session")
    else:
        doc = _get_role_doc(session, (role or "").lower().strip())
        if not doc:
            raise HTTPException(404, f"No {role} document in this session")
    try:
        data = load_path_bytes(doc.object_path, doc.storage_backend)
    except FileNotFoundError:
        raise HTTPException(
            404,
            f"File “{doc.filename}” is missing from storage. "
            "It may have been moved or deleted — re-upload the document.",
        ) from None
    return data, doc.filename, doc.content_type or "application/octet-stream"


@db_session
def list_admin_uploads(
    user: dict | None,
    emp_id: str | None = None,
    dept: str | None = None,
    status: str | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
) -> dict:
    """Admin uploads browser — same filters as extractions, includes open sessions with files."""
    return list_admin_extractions(
        user,
        emp_id=emp_id,
        dept=dept,
        status=status,
        from_date=from_date,
        to_date=to_date,
    )


@db_session
def get_admin_upload_session(session_id: int, user: dict | None) -> dict:
    if not _is_admin(user):
        raise HTTPException(403, "Admin access required")
    session = RcSession.get(id=session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    summary = _session_summary(session)
    summary["documentCount"] = len(summary.get("documents") or [])
    return summary


@db_session
def admin_document_file(document_id: int, user: dict | None) -> tuple[bytes, str, str]:
    if not _is_admin(user):
        raise HTTPException(403, "Admin access required")
    doc = RcDocument.get(id=int(document_id))
    if not doc:
        raise HTTPException(404, "Document not found")
    try:
        data = load_path_bytes(doc.object_path, doc.storage_backend)
    except FileNotFoundError:
        raise HTTPException(
            404,
            f"File “{doc.filename}” is missing from storage. "
            "It may have been moved or deleted — re-upload the document.",
        ) from None
    return data, doc.filename, doc.content_type or "application/octet-stream"
