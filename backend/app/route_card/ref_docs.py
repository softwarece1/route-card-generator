"""Shared company reference-document library (PS / DS / SS categories)."""

from __future__ import annotations

import re
from datetime import datetime

from fastapi import HTTPException
from pony.orm import db_session, select

from app.route_card.models import RcRefDocument, RcRefDocumentVersion, RcRefFolder
from app.route_card import service as rc_service

_FOLDER_CODE_RE = re.compile(r"^[A-Za-z]{1,6}$")
_MENTION_RE = re.compile(r"\b([A-Za-z]{1,6})\s*[-_]?\s*(\d{2,6})\b", re.IGNORECASE)
_FILENAME_STEM_RE = re.compile(
    r"^([A-Za-z]{1,6})\s*[-_]?\s*0*(\d{1,6})$", re.IGNORECASE
)


def normalize_folder_code(raw: str | None) -> str:
    letters = re.sub(r"[^A-Za-z]", "", str(raw or ""))
    return letters.upper()[:6]


def normalize_doc_code(folder_code: str, raw: str | None) -> str | None:
    """Canonical code: folder + int(digits) → PS200 (strips leading zeros)."""
    fc = normalize_folder_code(folder_code)
    if not fc or not _FOLDER_CODE_RE.match(fc):
        return None
    text = str(raw or "").strip()
    if not text:
        return None
    stem = text.rsplit(".", 1)[0] if "." in text else text
    stem = stem.strip()
    m = _FILENAME_STEM_RE.match(stem)
    if m:
        prefix = normalize_folder_code(m.group(1))
        if prefix != fc:
            return None
        return f"{fc}{int(m.group(2))}"
    if re.fullmatch(r"\d{1,6}", stem):
        return f"{fc}{int(stem)}"
    m2 = re.search(
        rf"^{re.escape(fc)}\s*[-_]?\s*0*(\d{{1,6}})$",
        stem,
        re.IGNORECASE,
    )
    if m2:
        return f"{fc}{int(m2.group(1))}"
    return None


def parse_upload_filename(folder_code: str, filename: str) -> str:
    """Require PDF named like PS200.pdf for category PS."""
    fc = normalize_folder_code(folder_code)
    name = (filename or "").strip()
    if not name.lower().endswith(".pdf"):
        raise HTTPException(400, "Only PDF files are allowed")
    stem = name.rsplit(".", 1)[0]
    code = normalize_doc_code(fc, stem)
    if not code:
        raise HTTPException(
            400,
            f"Filename must match category code (e.g. {fc}200.pdf)",
        )
    return code


def extract_candidate_codes(text: str, folder_codes: set[str] | list[str]) -> list[str]:
    known = {normalize_folder_code(c) for c in folder_codes if normalize_folder_code(c)}
    if not known or not text:
        return []
    found: list[str] = []
    seen: set[str] = set()
    for m in _MENTION_RE.finditer(str(text)):
        prefix = normalize_folder_code(m.group(1))
        if prefix not in known:
            continue
        code = f"{prefix}{int(m.group(2))}"
        if code not in seen:
            seen.add(code)
            found.append(code)
    return found


def _folder_out(folder: RcRefFolder, doc_count: int | None = None) -> dict:
    count = doc_count if doc_count is not None else len(folder.documents)
    return {
        "id": folder.id,
        "code": folder.code,
        "name": folder.name or folder.code,
        "documentCount": count,
        "createdBy": folder.created_by or "",
        "createdAt": folder.created_at.isoformat() if folder.created_at else None,
        "updatedAt": folder.updated_at.isoformat() if folder.updated_at else None,
    }


def _doc_out(doc: RcRefDocument, *, is_new_version: bool = False) -> dict:
    return {
        "id": doc.id,
        "folderId": doc.folder.id,
        "folderCode": doc.folder.code,
        "folderName": doc.folder.name or doc.folder.code,
        "categoryCode": doc.folder.code,
        "categoryName": doc.folder.name or doc.folder.code,
        "docCode": doc.doc_code,
        "originalFilename": doc.original_filename,
        "contentType": doc.content_type,
        "sizeBytes": doc.size_bytes,
        "uploadedBy": doc.uploaded_by or "",
        "versionNumber": doc.version_number or 1,
        "isNewVersion": is_new_version,
        "createdAt": doc.created_at.isoformat() if doc.created_at else None,
        "updatedAt": doc.updated_at.isoformat() if doc.updated_at else None,
    }


def _version_out(ver: RcRefDocumentVersion) -> dict:
    return {
        "id": ver.id,
        "documentId": ver.document.id,
        "versionNumber": ver.version_number,
        "originalFilename": ver.original_filename,
        "sizeBytes": ver.size_bytes,
        "uploadedBy": ver.uploaded_by or "",
        "createdAt": ver.created_at.isoformat() if ver.created_at else None,
    }


def _actor_label(user: dict | None) -> str:
    if not user:
        return ""
    return str(user.get("empId") or user.get("username") or user.get("name") or "")


def _try_delete_storage(object_path: str, storage_backend: str) -> None:
    if not object_path:
        return
    backend = (storage_backend or "").split(":")[0]
    try:
        if backend == "minio":
            rc_service.minio().delete_file(object_path)
        else:
            from pathlib import Path

            p = Path(object_path)
            if p.is_file():
                p.unlink(missing_ok=True)
    except Exception:
        pass


def _add_version(
    doc: RcRefDocument,
    *,
    version_number: int,
    filename: str,
    object_path: str,
    storage_backend: str,
    content_type: str,
    size_bytes: int,
    user: dict | None,
) -> RcRefDocumentVersion:
    return RcRefDocumentVersion(
        document=doc,
        version_number=version_number,
        original_filename=filename,
        object_path=object_path,
        storage_backend=storage_backend,
        content_type=content_type,
        size_bytes=size_bytes,
        uploaded_by=_actor_label(user),
        created_at=datetime.utcnow(),
    )


@db_session
def list_folders() -> list[dict]:
    rows = list(select(f for f in RcRefFolder).order_by(RcRefFolder.code))
    return [_folder_out(f) for f in rows]


@db_session
def catalog() -> dict:
    codes = [f.code for f in select(f for f in RcRefFolder).order_by(RcRefFolder.code)]
    return {"folderCodes": codes, "categoryCodes": codes}


@db_session
def create_folder(payload: dict, user: dict | None) -> dict:
    code = normalize_folder_code(payload.get("code"))
    if not code or not _FOLDER_CODE_RE.match(code):
        raise HTTPException(400, "Category code must be 1–6 letters (e.g. PS, DS, SS)")
    name = str(payload.get("name") or "").strip() or code
    existing = RcRefFolder.get(code=code)
    if existing:
        raise HTTPException(409, f"Category '{code}' already exists")
    folder = RcRefFolder(
        code=code,
        name=name,
        created_by=_actor_label(user),
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    return _folder_out(folder, doc_count=0)


@db_session
def update_folder(folder_id: int, payload: dict) -> dict:
    folder = RcRefFolder.get(id=folder_id)
    if not folder:
        raise HTTPException(404, "Category not found")
    if "name" in payload:
        name = str(payload.get("name") or "").strip()
        folder.name = name or folder.code
    folder.updated_at = datetime.utcnow()
    return _folder_out(folder)


@db_session
def delete_folder(folder_id: int) -> dict:
    folder = RcRefFolder.get(id=folder_id)
    if not folder:
        raise HTTPException(404, "Category not found")
    code = folder.code
    for doc in list(folder.documents):
        for ver in list(doc.versions):
            _try_delete_storage(ver.object_path, ver.storage_backend)
            ver.delete()
        _try_delete_storage(doc.object_path, doc.storage_backend)
        doc.delete()
    folder.delete()
    return {"ok": True, "code": code}


@db_session
def list_documents(folder_id: int) -> list[dict]:
    folder = RcRefFolder.get(id=folder_id)
    if not folder:
        raise HTTPException(404, "Category not found")
    docs = sorted(folder.documents, key=lambda d: d.doc_code)
    return [_doc_out(d) for d in docs]


@db_session
def list_document_versions(document_id: int) -> list[dict]:
    doc = RcRefDocument.get(id=document_id)
    if not doc:
        raise HTTPException(404, "Document not found")
    vers = sorted(doc.versions, key=lambda v: v.version_number, reverse=True)
    return [_version_out(v) for v in vers]


@db_session
def upload_document_bytes(
    folder_id: int,
    *,
    filename: str,
    data: bytes,
    content_type: str | None,
    user: dict | None,
) -> dict:
    folder = RcRefFolder.get(id=folder_id)
    if not folder:
        raise HTTPException(404, "Category not found")
    name = filename or "upload.pdf"
    doc_code = parse_upload_filename(folder.code, name)
    if not data:
        raise HTTPException(400, "Empty file")
    from app.config.settings import settings

    max_mb = int(getattr(settings, "MAX_UPLOAD_SIZE_MB", 10) or 10)
    if len(data) > max_mb * 1024 * 1024:
        raise HTTPException(400, f"File exceeds maximum allowed size ({max_mb} MB)")
    if not data.startswith(b"%PDF"):
        raise HTTPException(400, "File does not look like a PDF")
    ctype = content_type or "application/pdf"

    existing = RcRefDocument.get(folder=folder, doc_code=doc_code)
    next_ver = 1
    if existing:
        # Same logical sheet → new version (PMF-style); keep prior objects
        max_ver = max((v.version_number for v in existing.versions), default=existing.version_number or 1)
        next_ver = int(max_ver) + 1

    store_name = f"{doc_code}_v{next_ver}.pdf"
    prefix = f"ref-docs/{folder.code}/{doc_code}"
    object_path, storage_backend = rc_service._store_path(
        prefix, store_name, data, ctype
    )

    if existing:
        _add_version(
            existing,
            version_number=next_ver,
            filename=name,
            object_path=object_path,
            storage_backend=storage_backend,
            content_type=ctype,
            size_bytes=len(data),
            user=user,
        )
        existing.original_filename = name
        existing.object_path = object_path
        existing.storage_backend = storage_backend
        existing.content_type = ctype
        existing.size_bytes = len(data)
        existing.uploaded_by = _actor_label(user)
        existing.version_number = next_ver
        existing.updated_at = datetime.utcnow()
        folder.updated_at = datetime.utcnow()
        return _doc_out(existing, is_new_version=True)

    doc = RcRefDocument(
        folder=folder,
        doc_code=doc_code,
        original_filename=name,
        object_path=object_path,
        storage_backend=storage_backend,
        content_type=ctype,
        size_bytes=len(data),
        uploaded_by=_actor_label(user),
        version_number=1,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    _add_version(
        doc,
        version_number=1,
        filename=name,
        object_path=object_path,
        storage_backend=storage_backend,
        content_type=ctype,
        size_bytes=len(data),
        user=user,
    )
    folder.updated_at = datetime.utcnow()
    return _doc_out(doc, is_new_version=False)


@db_session
def delete_document(document_id: int) -> dict:
    doc = RcRefDocument.get(id=document_id)
    if not doc:
        raise HTTPException(404, "Document not found")
    code = doc.doc_code
    for ver in list(doc.versions):
        _try_delete_storage(ver.object_path, ver.storage_backend)
        ver.delete()
    _try_delete_storage(doc.object_path, doc.storage_backend)
    folder = doc.folder
    doc.delete()
    folder.updated_at = datetime.utcnow()
    return {"ok": True, "docCode": code}


@db_session
def delete_document_version(document_id: int, version_number: int) -> dict:
    """Delete one version. If it was the last, remove the document too."""
    doc = RcRefDocument.get(id=document_id)
    if not doc:
        raise HTTPException(404, "Document not found")
    ver = RcRefDocumentVersion.get(document=doc, version_number=int(version_number))
    if not ver:
        raise HTTPException(404, f"Version {version_number} not found")
    code = doc.doc_code
    _try_delete_storage(ver.object_path, ver.storage_backend)
    ver.delete()
    remaining = sorted(doc.versions, key=lambda v: v.version_number, reverse=True)
    folder = doc.folder
    if not remaining:
        _try_delete_storage(doc.object_path, doc.storage_backend)
        doc.delete()
        folder.updated_at = datetime.utcnow()
        return {"ok": True, "docCode": code, "deletedVersion": int(version_number), "documentDeleted": True}

    latest = remaining[0]
    doc.original_filename = latest.original_filename
    doc.object_path = latest.object_path
    doc.storage_backend = latest.storage_backend
    doc.content_type = latest.content_type
    doc.size_bytes = latest.size_bytes
    doc.uploaded_by = latest.uploaded_by or ""
    doc.version_number = latest.version_number
    doc.updated_at = datetime.utcnow()
    folder.updated_at = datetime.utcnow()
    return {
        "ok": True,
        "docCode": code,
        "deletedVersion": int(version_number),
        "documentDeleted": False,
        "latestVersion": latest.version_number,
    }


@db_session
def get_document_file(
    document_id: int, version: int | None = None
) -> tuple[bytes, str, str]:
    doc = RcRefDocument.get(id=document_id)
    if not doc:
        raise HTTPException(404, "Document not found")
    if version is not None:
        ver = RcRefDocumentVersion.get(document=doc, version_number=int(version))
        if not ver:
            raise HTTPException(404, f"Version {version} not found")
        data = rc_service.load_path_bytes(ver.object_path, ver.storage_backend)
        filename = ver.original_filename or f"{doc.doc_code}_v{ver.version_number}.pdf"
        content_type = ver.content_type or "application/pdf"
        return data, filename, content_type
    data = rc_service.load_path_bytes(doc.object_path, doc.storage_backend)
    filename = doc.original_filename or f"{doc.doc_code}.pdf"
    content_type = doc.content_type or "application/pdf"
    return data, filename, content_type


@db_session
def resolve_codes(codes: list[str] | None) -> dict:
    """Return latest documents for requested codes (any category)."""
    raw = [str(c).strip() for c in (codes or []) if str(c).strip()]
    if not raw:
        return {"found": []}

    folders = {f.code: f for f in select(f for f in RcRefFolder)}
    wanted: set[str] = set()
    for c in raw:
        m = re.match(r"^([A-Za-z]{1,6})\s*[-_]?\s*0*(\d{1,6})$", c, re.I)
        if m:
            fc = normalize_folder_code(m.group(1))
            if fc in folders:
                wanted.add(f"{fc}{int(m.group(2))}")
                continue
        for fc in folders:
            n = normalize_doc_code(fc, c)
            if n:
                wanted.add(n)

    if not wanted:
        return {"found": []}

    found = []
    for doc in select(d for d in RcRefDocument if d.doc_code in wanted):
        found.append(
            {
                "code": doc.doc_code,
                "documentId": doc.id,
                "folderCode": doc.folder.code,
                "folderName": doc.folder.name or doc.folder.code,
                "categoryCode": doc.folder.code,
                "categoryName": doc.folder.name or doc.folder.code,
                "name": doc.original_filename or f"{doc.doc_code}.pdf",
                "versionNumber": doc.version_number or 1,
            }
        )
    found.sort(key=lambda x: x["code"])
    return {"found": found}
