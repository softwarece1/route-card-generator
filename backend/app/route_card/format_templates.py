"""Offline format template bank — fingerprint, match, learn (no external LLM).

Templates are JSON on disk. Uploads do not auto-train; engineers save a template
after a successful (or corrected) extract so similar drawings match next time.
"""

from __future__ import annotations

import json
import re
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_LOCK = threading.RLock()

# Signals used to fingerprint a document family (presence/absence + counts).
_KEYWORD_GROUPS: dict[str, tuple[str, ...]] = {
    "notes": (
        "NOTE",
        "NOTES",
        "REMARKS",
        "ASSEMBLY NOTES",
        "ASSY NOTES",
        "ASSEMBLY INSTRUCTIONS",
        "ASSY INSTRUCTIONS",
        "INSTRUCTIONS",
        "INSTRUCTION",
        "CTQ POINTS",
        "CTQ POINT",
        "CRITICAL TO QUALITY",
    ),
    "parts_list": ("PARTS LIST", "PART LIST", "DESIGNATION", "ITEM NO", "PART NO", "PART NUMBER"),
    "wire_list": ("WIRE LIST", "WIRELIST", "FROM", "TO", "WIRE LFH", "PIN"),
    "title": ("TITLE", "DRAWING", "SHEET", "SCALE", "REV", "VERSION", "ISSUE"),
    "ga": ("GENERAL ARRANGEMENT", " GA ", "ASSEMBLY", "ASSEMBLE", "CABLE ASSY", "CABLE ASSEMBLY"),
    "bel_pn": (),  # filled via regex below
}

_PART_NO_HINT = re.compile(r"\b\d{4}\s+\d{3}\s+\d{3}\s+\d{2}\b")
_NOTE_HDR = re.compile(
    r"\b(?:ASSEMBLY\s+INSTRUCTIONS?|ASSY\.?\s+INSTRUCTIONS?|INSTRUCTIONS?|NOTES?|"
    r"CTQ\s+POINTS?|CRITICAL\s+TO\s+QUALITY\s+POINTS?)\b"
    r"\s*(?:[IVX]+|\d{1,2})?\b",
    re.I,
)
_ITEM_HDR = re.compile(r"\b(?:ITEM|ITM|S\.?\s*NO|SL\.?\s*NO)\b", re.I)

DEFAULT_TEMPLATES: list[dict[str, Any]] = [
    {
        "id": "bel-ga-default",
        "name": "BEL GA / Assembly (default)",
        "docType": "GA",
        "builtin": True,
        "aliases": {
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
        "fingerprint": {
            "docTypeHint": "GA",
            "keywords": ["NOTE", "NOTES", "ASSEMBLE", "ITEM", "SHEET", "CTQ"],
            "hasBelPartNo": True,
            "hasNotesHeader": True,
            "hasPartsListHeader": False,
            "hasWireListHeader": False,
            "noteHeaderCountMin": 1,
        },
        "stats": {"useCount": 0, "learnCount": 0},
        "createdAt": "",
        "updatedAt": "",
    },
    {
        "id": "bel-wiring-assy-instructions",
        "name": "BEL Wiring / Cable GA (Assembly Instructions)",
        "docType": "GA",
        "builtin": True,
        "aliases": {
            "noteHeaders": [
                "ASSEMBLY INSTRUCTIONS",
                "ASSY INSTRUCTIONS",
                "INSTRUCTIONS",
                "INSTRUCTION",
                "NOTES",
                "NOTE",
                "REMARKS",
                "CTQ POINTS",
                "CTQ POINT",
                "CRITICAL TO QUALITY POINTS",
            ],
            "plColumns": {},
            "wlHints": [],
        },
        "fingerprint": {
            "docTypeHint": "GA",
            "keywords": [
                "ASSEMBLY INSTRUCTIONS",
                "INSTRUCTIONS",
                "CABLE",
                "HEAT SHRINK",
                "FIGURE",
                "CONNECTOR",
                "INTERCONNECTION",
                "CTQ",
            ],
            "hasBelPartNo": True,
            "hasNotesHeader": True,
            "hasPartsListHeader": False,
            "hasWireListHeader": False,
            "noteHeaderCountMin": 1,
        },
        "stats": {"useCount": 0, "learnCount": 0},
        "createdAt": "",
        "updatedAt": "",
    },
    {
        "id": "bel-pl-default",
        "name": "BEL Parts List (default)",
        "docType": "PL",
        "builtin": True,
        "aliases": {
            "noteHeaders": [],
            "plColumns": {
                "item": ["ITEM", "ITEM NO", "ITM", "S.NO", "SL NO", "SL.NO"],
                "description": ["DESIGNATION", "DESCRIPTION", "DESC", "PART NAME"],
                "partNo": ["PART NO", "PART NUMBER", "P/N", "PN"],
                "qty": ["QTY", "QUANTITY", "QTY.", "NOS"],
            },
            "wlHints": [],
        },
        "fingerprint": {
            "docTypeHint": "PL",
            "keywords": ["PARTS LIST", "DESIGNATION", "PART NO", "ITEM"],
            "hasBelPartNo": True,
            "hasNotesHeader": False,
            "hasPartsListHeader": True,
            "hasWireListHeader": False,
            "noteHeaderCountMin": 0,
        },
        "stats": {"useCount": 0, "learnCount": 0},
        "createdAt": "",
        "updatedAt": "",
    },
    {
        "id": "bel-wl-default",
        "name": "BEL Wire List (default)",
        "docType": "WL",
        "builtin": True,
        "aliases": {
            "noteHeaders": [],
            "plColumns": {},
            "wlHints": ["WIRE LIST", "FROM", "TO", "WIRE LFH"],
        },
        "fingerprint": {
            "docTypeHint": "WL",
            "keywords": ["WIRE LIST", "FROM", "TO", "WIRE"],
            "hasBelPartNo": True,
            "hasNotesHeader": False,
            "hasPartsListHeader": False,
            "hasWireListHeader": True,
            "noteHeaderCountMin": 0,
        },
        "stats": {"useCount": 0, "learnCount": 0},
        "createdAt": "",
        "updatedAt": "",
    },
]


def _templates_path() -> Path:
    try:
        from app.config.settings import settings

        raw = (getattr(settings, "FORMAT_TEMPLATES_PATH", "") or "").strip()
        if raw:
            return Path(raw)
    except Exception:
        pass
    # backend/data/format_templates.json (relative to this package → app → backend)
    return Path(__file__).resolve().parents[2] / "data" / "format_templates.json"


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _ensure_store() -> dict[str, Any]:
    path = _templates_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.is_file():
        payload = {
            "version": 1,
            "updatedAt": _utc_now(),
            "templates": [
                {**t, "createdAt": _utc_now(), "updatedAt": _utc_now()} for t in DEFAULT_TEMPLATES
            ],
        }
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return payload
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        data = {"version": 1, "templates": []}
    if not isinstance(data.get("templates"), list):
        data["templates"] = []
    # Ensure builtins exist (merge by id)
    have = {t.get("id") for t in data["templates"] if isinstance(t, dict)}
    for t in DEFAULT_TEMPLATES:
        if t["id"] not in have:
            data["templates"].append({**t, "createdAt": _utc_now(), "updatedAt": _utc_now()})
    return data


def _save_store(data: dict[str, Any]) -> None:
    path = _templates_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    data["updatedAt"] = _utc_now()
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def list_templates() -> list[dict[str, Any]]:
    with _LOCK:
        data = _ensure_store()
        return list(data.get("templates") or [])


def get_template(template_id: str) -> dict[str, Any] | None:
    for t in list_templates():
        if t.get("id") == template_id:
            return t
    return None


def fingerprint_text(text: str, *, doc_type_hint: str = "") -> dict[str, Any]:
    """Build a compact fingerprint used for nearest-template matching."""
    raw = text or ""
    upper = raw.upper()
    words = re.findall(r"[A-Z0-9/+.-]{2,}", upper)
    # Stable token set (cap size)
    tokens = sorted(set(words))[:400]

    def has_any(keys: tuple[str, ...]) -> bool:
        return any(k in upper for k in keys)

    note_headers = len(_NOTE_HDR.findall(raw))
    bel_pn = len(_PART_NO_HINT.findall(raw))
    item_hdr = bool(_ITEM_HDR.search(raw))

    kw_hits = {
        name: has_any(keys) if keys else False
        for name, keys in _KEYWORD_GROUPS.items()
    }
    kw_hits["bel_pn"] = bel_pn > 0

    # Soft doc-type guess from content
    guessed = (doc_type_hint or "").upper().strip()
    if not guessed:
        if kw_hits["wire_list"] and ("WIRE LIST" in upper or "WIRELIST" in upper):
            guessed = "WL"
        elif kw_hits["parts_list"] and ("PARTS LIST" in upper or "PART LIST" in upper):
            guessed = "PL"
        elif note_headers or kw_hits["ga"] or kw_hits["notes"]:
            guessed = "GA"
        else:
            guessed = "UNKNOWN"

    return {
        "docTypeHint": guessed,
        "charCount": len(raw.strip()),
        "lineCount": len(raw.splitlines()),
        "belPartNoCount": bel_pn,
        "noteHeaderCount": note_headers,
        "hasBelPartNo": bel_pn > 0,
        "hasNotesHeader": note_headers > 0 or kw_hits["notes"],
        "hasPartsListHeader": kw_hits["parts_list"],
        "hasWireListHeader": kw_hits["wire_list"],
        "hasItemHeader": item_hdr,
        "keywordHits": kw_hits,
        "tokenSample": tokens[:80],
    }


def _score_match(fp: dict[str, Any], template: dict[str, Any]) -> float:
    """0..1 similarity between a document fingerprint and a template."""
    tip = template.get("fingerprint") or {}
    score = 0.0
    weight = 0.0

    def add(cond: bool, w: float = 1.0) -> None:
        nonlocal score, weight
        weight += w
        if cond:
            score += w

    t_type = (tip.get("docTypeHint") or template.get("docType") or "").upper()
    f_type = (fp.get("docTypeHint") or "").upper()
    add(bool(t_type) and t_type == f_type, 3.0)

    for key, w in (
        ("hasBelPartNo", 1.5),
        ("hasNotesHeader", 1.5),
        ("hasPartsListHeader", 2.0),
        ("hasWireListHeader", 2.0),
    ):
        if key in tip:
            add(bool(fp.get(key)) == bool(tip.get(key)), w)

    min_notes = int(tip.get("noteHeaderCountMin") or 0)
    if min_notes:
        add(int(fp.get("noteHeaderCount") or 0) >= min_notes, 1.0)

    # Keyword overlap
    t_kw = [k.upper() for k in (tip.get("keywords") or []) if k]
    if t_kw:
        upper_blob = " ".join(fp.get("tokenSample") or [])
        hits = sum(1 for k in t_kw if k in upper_blob or k in " ".join(
            str(x) for x, v in (fp.get("keywordHits") or {}).items() if v
        ))
        # Also check boolean keywordHits names loosely
        textish = upper_blob
        hits = sum(1 for k in t_kw if k in textish)
        weight += 2.0
        score += 2.0 * (hits / max(len(t_kw), 1))

    if weight <= 0:
        return 0.0
    return round(min(1.0, score / weight), 4)


def match_template(
    text: str,
    *,
    doc_type_hint: str = "",
    min_score: float = 0.35,
) -> dict[str, Any]:
    """Return best matching template + score (or unmatched)."""
    fp = fingerprint_text(text, doc_type_hint=doc_type_hint)
    templates = list_templates()
    # Prefer same docType
    candidates = templates
    if doc_type_hint:
        preferred = [t for t in templates if (t.get("docType") or "").upper() == doc_type_hint.upper()]
        if preferred:
            candidates = preferred + [t for t in templates if t not in preferred]

    best: dict[str, Any] | None = None
    best_score = -1.0
    ranked: list[dict[str, Any]] = []
    for t in candidates:
        s = _score_match(fp, t)
        ranked.append({"id": t.get("id"), "name": t.get("name"), "score": s, "docType": t.get("docType")})
        if s > best_score:
            best_score = s
            best = t

    ranked.sort(key=lambda x: x["score"], reverse=True)
    matched = best is not None and best_score >= min_score
    return {
        "matched": matched,
        "score": best_score if matched else best_score,
        "template": (
            {
                "id": best.get("id"),
                "name": best.get("name"),
                "docType": best.get("docType"),
                "builtin": bool(best.get("builtin")),
                "aliases": best.get("aliases") or {},
            }
            if best and matched
            else None
        ),
        "fingerprint": fp,
        "candidates": ranked[:5],
    }


def bump_use_count(template_id: str) -> None:
    if not template_id:
        return
    with _LOCK:
        data = _ensure_store()
        for t in data["templates"]:
            if t.get("id") == template_id:
                stats = t.setdefault("stats", {})
                stats["useCount"] = int(stats.get("useCount") or 0) + 1
                t["updatedAt"] = _utc_now()
                break
        _save_store(data)


def apply_aliases_to_text(text: str, aliases: dict[str, Any] | None, *, doc_type: str = "") -> str:
    """Rewrite known synonym headers to canonical tokens the parsers already understand."""
    if not text or not aliases:
        return text or ""
    out = text

    # Note / remarks headers → NOTE
    for hdr in aliases.get("noteHeaders") or []:
        h = (hdr or "").strip()
        if not h or h.upper() in {"NOTE", "NOTES"}:
            continue
        out = re.sub(rf"(?im)(^|\n)\s*{re.escape(h)}\s*([:;.]\s*|\s*$)", r"\1NOTE\2", out)

    # PL column aliases → canonical headers (helps table/header lines)
    pl = aliases.get("plColumns") or {}
    canon_map = {
        "item": "ITEM",
        "description": "DESIGNATION",
        "partNo": "PART NO",
        "qty": "QTY",
    }
    for field, canon in canon_map.items():
        for alias in pl.get(field) or []:
            a = (alias or "").strip()
            if not a or a.upper() == canon:
                continue
            out = re.sub(rf"(?i)\b{re.escape(a)}\b", canon, out)

    # WL hints → WIRE LIST when present as section titles
    for hint in aliases.get("wlHints") or []:
        h = (hint or "").strip()
        if not h or h.upper() == "WIRE LIST":
            continue
        if h.upper() in {"FROM", "TO"}:
            continue
        out = re.sub(rf"(?im)(^|\n)\s*{re.escape(h)}\s*", r"\1WIRE LIST ", out)

    return out


def learn_template(
    *,
    name: str,
    doc_type: str,
    fingerprint: dict[str, Any],
    aliases: dict[str, Any] | None = None,
    source_session_id: int | None = None,
    notes: str = "",
    update_id: str | None = None,
) -> dict[str, Any]:
    """Create or update a learned template from a successful/corrected extract."""
    doc_type = (doc_type or fingerprint.get("docTypeHint") or "UNKNOWN").upper()
    aliases = aliases or {}
    with _LOCK:
        data = _ensure_store()
        now = _utc_now()
        existing = None
        if update_id:
            existing = next((t for t in data["templates"] if t.get("id") == update_id), None)

        fp_store = {
            "docTypeHint": doc_type,
            "keywords": list(
                dict.fromkeys(
                    [
                        *(aliases.get("noteHeaders") or [])[:8],
                        *([k for k, v in (fingerprint.get("keywordHits") or {}).items() if v][:8]),
                    ]
                )
            )[:16],
            "hasBelPartNo": bool(fingerprint.get("hasBelPartNo")),
            "hasNotesHeader": bool(fingerprint.get("hasNotesHeader")),
            "hasPartsListHeader": bool(fingerprint.get("hasPartsListHeader")),
            "hasWireListHeader": bool(fingerprint.get("hasWireListHeader")),
            "noteHeaderCountMin": 1 if fingerprint.get("hasNotesHeader") else 0,
            "sampleTokens": (fingerprint.get("tokenSample") or [])[:40],
        }

        if existing and not existing.get("builtin"):
            existing["name"] = name or existing.get("name")
            existing["docType"] = doc_type
            existing["aliases"] = {
                "noteHeaders": list(aliases.get("noteHeaders") or existing.get("aliases", {}).get("noteHeaders") or []),
                "plColumns": dict(aliases.get("plColumns") or existing.get("aliases", {}).get("plColumns") or {}),
                "wlHints": list(aliases.get("wlHints") or existing.get("aliases", {}).get("wlHints") or []),
            }
            existing["fingerprint"] = fp_store
            existing["updatedAt"] = now
            stats = existing.setdefault("stats", {})
            stats["learnCount"] = int(stats.get("learnCount") or 0) + 1
            if source_session_id is not None:
                existing["lastSessionId"] = source_session_id
            if notes:
                existing["notes"] = notes[:500]
            _save_store(data)
            return existing

        tid = f"learned-{doc_type.lower()}-{uuid.uuid4().hex[:10]}"
        row = {
            "id": tid,
            "name": name or f"Learned {doc_type} format",
            "docType": doc_type,
            "builtin": False,
            "aliases": {
                "noteHeaders": list(aliases.get("noteHeaders") or []),
                "plColumns": dict(aliases.get("plColumns") or {}),
                "wlHints": list(aliases.get("wlHints") or []),
            },
            "fingerprint": fp_store,
            "stats": {"useCount": 0, "learnCount": 1},
            "sourceSessionId": source_session_id,
            "notes": (notes or "")[:500],
            "createdAt": now,
            "updatedAt": now,
        }
        data["templates"].append(row)
        _save_store(data)
        return row


def delete_template(template_id: str) -> bool:
    with _LOCK:
        data = _ensure_store()
        before = len(data["templates"])
        data["templates"] = [
            t
            for t in data["templates"]
            if not (t.get("id") == template_id and not t.get("builtin"))
        ]
        if len(data["templates"]) == before:
            return False
        _save_store(data)
        return True
