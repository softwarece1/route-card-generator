"""Review flags + PL↔GA item link report (Phase 1)."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from fastapi import HTTPException
from pony.orm import commit, db_session, desc, select

from app.route_card.models import RcReviewFlag, RcRouteCard, RcSession, RcUser

_ITEM_REF_RE = re.compile(
    r"(?:item|itm|balloon|balloon\s*#|pl\s*item|#)\s*[-:]?\s*(\d{1,4})\b",
    re.I,
)
_BARE_ITEM_RE = re.compile(r"\b(?:ITM|ITEM)[-_\s]?(\d{1,4})\b", re.I)
_AS_SHOWN_RE = re.compile(r"\bas\s*shown\b", re.I)


def flag_dict(f: RcReviewFlag) -> dict:
    return {
        "id": f.id,
        "sessionId": f.session.id if f.session else None,
        "routeCardId": f.route_card.id if f.route_card else None,
        "kind": f.kind,
        "severity": f.severity,
        "message": f.message,
        "source": f.source or "",
        "resolved": bool(f.resolved),
        "resolvedAt": f.resolved_at.isoformat() + "Z" if f.resolved_at else None,
        "resolvedBy": f.resolved_by,
        "createdAt": f.created_at.isoformat() + "Z" if f.created_at else None,
    }


def _pl_item_nos(parts_list: dict | None) -> set[str]:
    nos: set[str] = set()
    if not parts_list:
        return nos
    for it in parts_list.get("items") or []:
        n = str(it.get("itemNo") or it.get("item_no") or it.get("no") or "").strip()
        if n:
            nos.add(re.sub(r"^0+", "", n) or n)
    for k in (parts_list.get("itemMap") or {}):
        nos.add(re.sub(r"^0+", "", str(k)) or str(k))
    return nos


def _refs_from_text(text: str) -> set[str]:
    found: set[str] = set()
    for m in _ITEM_REF_RE.finditer(text or ""):
        found.add(re.sub(r"^0+", "", m.group(1)) or m.group(1))
    for m in _BARE_ITEM_RE.finditer(text or ""):
        found.add(re.sub(r"^0+", "", m.group(1)) or m.group(1))
    return found


def collect_drawing_item_refs(
    parsed: dict,
    mind: dict | None = None,
    notes: list | None = None,
) -> set[str]:
    refs: set[str] = set()
    for bom in parsed.get("bom_items") or []:
        n = str(bom.get("itemNo") or bom.get("item") or bom.get("no") or "").strip()
        if n.isdigit() or re.match(r"^\d+", n):
            refs.add(re.sub(r"^0+", "", re.match(r"^\d+", n).group(0)) or n)
    for note in notes or parsed.get("notes") or []:
        if isinstance(note, dict):
            refs |= _refs_from_text(note.get("text") or note.get("elaboratedText") or "")
            for step in note.get("steps") or []:
                if isinstance(step, dict):
                    refs |= _refs_from_text(step.get("text") or step.get("instruction") or "")
                else:
                    refs |= _refs_from_text(str(step))
        else:
            refs |= _refs_from_text(str(note))
    mind = mind or {}
    for link in mind.get("pcbLinks") or []:
        n = str(link.get("plItemNo") or "").strip()
        if n:
            refs.add(re.sub(r"^0+", "", n) or n)
    for cr in mind.get("crossRefs") or []:
        if isinstance(cr, dict):
            refs |= _refs_from_text(str(cr.get("text") or cr.get("itemNo") or ""))
    refs |= _refs_from_text(parsed.get("raw_text") or "")
    return refs


def build_item_link_report(parsed: dict, parts_list: dict | None, mind: dict | None = None) -> dict:
    pl_nos = _pl_item_nos(parts_list)
    ga_refs = collect_drawing_item_refs(parsed, mind=mind)
    pl_only = sorted(pl_nos - ga_refs, key=lambda x: int(x) if x.isdigit() else 0)
    ga_only = sorted(ga_refs - pl_nos, key=lambda x: int(x) if x.isdigit() else 0)
    matched = sorted(pl_nos & ga_refs, key=lambda x: int(x) if x.isdigit() else 0)
    rows = []
    item_map = (parts_list or {}).get("itemMap") or {}
    for n in sorted(pl_nos | ga_refs, key=lambda x: int(x) if x.isdigit() else 0):
        desc = ""
        meta = item_map.get(n) or item_map.get(str(n).zfill(2)) or {}
        if isinstance(meta, dict):
            desc = meta.get("description") or ""
        rows.append(
            {
                "itemNo": n,
                "description": desc,
                "onPartsList": n in pl_nos,
                "onDrawing": n in ga_refs,
                "status": (
                    "matched"
                    if n in pl_nos and n in ga_refs
                    else ("pl_only" if n in pl_nos else "ga_only")
                ),
            }
        )
    return {
        "matched": matched,
        "plOnly": pl_only,
        "gaOnly": ga_only,
        "rows": rows,
        "summary": {
            "plCount": len(pl_nos),
            "gaRefCount": len(ga_refs),
            "matchedCount": len(matched),
            "mismatchCount": len(pl_only) + len(ga_only),
        },
    }


def _clear_auto_flags(session: RcSession | None, card: RcRouteCard | None) -> None:
    q = select(f for f in RcReviewFlag if not f.resolved)
    for f in q:
        if session and f.session and f.session.id == session.id and (f.source or "").startswith("auto:"):
            f.delete()
        elif card and f.route_card and f.route_card.id == card.id and (f.source or "").startswith("auto:"):
            f.delete()


def rebuild_review_flags(
    *,
    session: RcSession | None,
    card: RcRouteCard | None,
    user: RcUser | None,
    parsed: dict,
    parts_list: dict | None,
    mind: dict | None,
    extra_warnings: list[str] | None,
    operations: list[dict] | None,
) -> list[dict]:
    """Replace auto-* flags after analyze; return flag dicts."""
    _clear_auto_flags(session, card)
    created: list[RcReviewFlag] = []

    def add(kind: str, severity: str, message: str, source: str = "auto:analyze"):
        f = RcReviewFlag(
            session=session,
            route_card=card,
            user=user,
            kind=kind,
            severity=severity,
            message=message,
            source=source,
            resolved=False,
        )
        created.append(f)

    if not parts_list or not (parts_list.get("items") or parts_list.get("itemMap")):
        add("missing_pl", "high", "Parts List missing or empty — item descriptions may be incomplete.")

    ops = operations or []
    if len(ops) == 0:
        add("empty_ops", "high", "No operations generated — review drawing notes and regenerate.")

    notes = parsed.get("notes") or []
    mind = mind or {}
    low_conf = False
    as_shown_weak = False
    for note in notes:
        if not isinstance(note, dict):
            continue
        conf = note.get("mindConfidence")
        try:
            if conf is not None and float(conf) < 0.45:
                low_conf = True
        except (TypeError, ValueError):
            pass
        text = (note.get("text") or "") + " " + (note.get("elaboratedText") or "")
        if _AS_SHOWN_RE.search(text):
            elab = (note.get("elaboratedText") or "").strip()
            steps = note.get("steps") or []
            if not elab and not steps:
                as_shown_weak = True
    for n in mind.get("notes") or []:
        if isinstance(n, dict):
            try:
                if n.get("mindConfidence") is not None and float(n["mindConfidence"]) < 0.45:
                    low_conf = True
            except (TypeError, ValueError):
                pass
    if low_conf:
        add(
            "low_confidence",
            "medium",
            "One or more notes have low drawing-mind confidence — verify instructions.",
        )
    if as_shown_weak:
        add(
            "as_shown",
            "medium",
            "AS SHOWN found without elaboration — confirm what the view shows.",
        )

    for w in extra_warnings or []:
        if not w or not str(w).strip():
            continue
        add("warning", "low", str(w).strip(), source="auto:warning")

    report = build_item_link_report(parsed, parts_list, mind=mind)
    if report["summary"]["mismatchCount"] > 0:
        pl_n = len(report["plOnly"])
        ga_n = len(report["gaOnly"])
        add(
            "pl_ga_mismatch",
            "medium" if (pl_n + ga_n) < 8 else "high",
            f"PL↔GA item mismatch: {pl_n} PL-only, {ga_n} drawing-only refs.",
            source="auto:item_link",
        )

    commit()
    return [flag_dict(f) for f in created]


@db_session
def list_flags_for_route(route_id: int, user: dict | None = None) -> list[dict]:
    card = RcRouteCard.get(id=route_id)
    if not card:
        raise HTTPException(404, "Route card not found")
    flags = select(f for f in RcReviewFlag if f.route_card == card).order_by(
        desc(RcReviewFlag.created_at)
    )[:]
    return [flag_dict(f) for f in flags]


@db_session
def list_flags_for_session(session_id: int) -> list[dict]:
    session = RcSession.get(id=session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    flags = select(f for f in RcReviewFlag if f.session == session).order_by(
        desc(RcReviewFlag.created_at)
    )[:]
    return [flag_dict(f) for f in flags]


@db_session
def resolve_flag(flag_id: int, user: dict, resolved: bool = True) -> dict:
    f = RcReviewFlag.get(id=flag_id)
    if not f:
        raise HTTPException(404, "Review flag not found")
    f.resolved = bool(resolved)
    if resolved:
        f.resolved_at = datetime.utcnow()
        f.resolved_by = (user or {}).get("empId") or (user or {}).get("username") or ""
    else:
        f.resolved_at = None
        f.resolved_by = None
    commit()
    return flag_dict(f)


def unresolved_blocking(route_id: int) -> list[dict]:
    """High/medium unresolved flags that block approve."""
    card = RcRouteCard.get(id=route_id)
    if not card:
        return []
    out = []
    for f in select(x for x in RcReviewFlag if x.route_card == card and not x.resolved):
        if (f.severity or "").lower() in ("high", "medium"):
            out.append(flag_dict(f))
    return out


@db_session
def item_link_report_for_session(session_id: int, user: dict) -> dict:
    from pony.orm import desc

    from app.route_card import service
    from app.route_card.models import RcDrawing, RcExtraction, RcSession

    service.get_session(session_id, user)
    sess = RcSession.get(id=session_id)
    if not sess:
        raise HTTPException(404, "Session not found")
    parsed = {"bom_items": [], "notes": [], "raw_text": ""}
    mind = {}
    pl = None
    drawing = sess.drawings.select().order_by(desc(RcDrawing.created_at)).first()
    if drawing:
        ex = drawing.extractions.select().order_by(desc(RcExtraction.created_at)).first()
        if ex:
            parsed["bom_items"] = ex.bom_items or []
            parsed["notes"] = ex.notes or []
            parsed["raw_text"] = ex.raw_text or ""
    for doc in sess.documents:
        if doc.role == "partslist" and isinstance(doc.extraction, dict):
            pl = doc.extraction
            break
    return build_item_link_report(parsed, pl, mind=mind)
