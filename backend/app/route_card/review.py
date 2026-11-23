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

# Diagnostic noise → skip or collapse (do not flood Needs review).
_WARN_SKIP_RE = re.compile(
    r"(?:"
    r"BOM enriched with|"
    r"Stage C filter:\s*dropped fastener|"
    r"VLM Stage C(?:\s+page\s+\d+)?:\s*dropped (?:fastener-only|weak) group|"
    r"VLM Stage C:\s*merged continuation|"
    r"merged continuation callout|"
    r"balloon assembly group|"
    r"Stage C found \d+ balloon|"
    r"extracted \d+ verbatim note line|"
    r"Stage D LLM route produced|"
    r"OP\s+\d+:\s*work centre unresolved|"
    r"Ambiguous work centre match|"
    r"token gate conflict|"
    r"Items .+ from Parts List not|"
    r"were listed in Parts List but lacked"
    r")",
    re.I,
)
_WARN_BALLOON_MISS_RE = re.compile(
    r"balloon\(s\)\s+for\s+item|not found in spatial OCR",
    re.I,
)
_WARN_PLACEMENT_RE = re.compile(
    r"could not resolve placement offsets|placements? are low-confidence",
    re.I,
)
_WARN_AMBIGUOUS_BALLOON_RE = re.compile(
    r"balloon positions were ambiguous",
    re.I,
)


def summarize_extra_warnings(extra_warnings: list[str] | None) -> list[tuple[str, str, str]]:
    """Collapse analyze diagnostics into few reviewable (kind, severity, message) rows.

    Returns tuples suitable for RcReviewFlag creation. Informational Stage C/BOM
    chatter and per-OP work-centre echoes are dropped (those already have
    dedicated high/medium flags).
    """
    balloon_n = 0
    placement_n = 0
    ambiguous = False
    kept: list[tuple[str, str, str]] = []
    seen_kept: set[str] = set()

    for raw in extra_warnings or []:
        w = str(raw or "").strip()
        if not w:
            continue
        if _WARN_SKIP_RE.search(w):
            continue
        if _WARN_BALLOON_MISS_RE.search(w):
            balloon_n += 1
            continue
        if _WARN_PLACEMENT_RE.search(w):
            placement_n += 1
            continue
        if _WARN_AMBIGUOUS_BALLOON_RE.search(w):
            ambiguous = True
            continue
        # Dedupe identical leftovers (missing drawings, Stage D skip, etc.)
        key = w.lower()
        if key in seen_kept:
            continue
        seen_kept.add(key)
        # Soften purely informational mind messages to low; keep once.
        sev = "low"
        if re.search(r"not uploaded|not provided|timed out|not reachable|skipped", w, re.I):
            sev = "low"
        kept.append(("warning", sev, w))

    out: list[tuple[str, str, str]] = []
    if balloon_n:
        out.append(
            (
                "balloon_ocr",
                "low",
                f"Drawing mind: {balloon_n} balloon/OCR miss(es) — placement used heuristics; verify critical mounts on the GA.",
            )
        )
    if placement_n:
        out.append(
            (
                "placement",
                "low",
                f"Drawing mind: {placement_n} placement confidence note(s) — kept source wording; verify against the GA view.",
            )
        )
    if ambiguous:
        out.append(
            (
                "balloon_order",
                "low",
                "Drawing mind: some balloon positions were ambiguous — used note order for top–bottom placement.",
            )
        )
    out.extend(kept)
    return out


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
    for g in mind.get("assemblyGroups") or parsed.get("assemblyGroups") or []:
        if not isinstance(g, dict):
            continue
        for key in ("parentItemNo",):
            n = str(g.get(key) or "").strip()
            if n.isdigit():
                refs.add(re.sub(r"^0+", "", n) or n)
        for ch in g.get("children") or []:
            if isinstance(ch, dict):
                n = str(ch.get("itemNo") or "").strip()
                if n.isdigit():
                    refs.add(re.sub(r"^0+", "", n) or n)
        for r in g.get("references") or []:
            n = str(r).strip()
            if n.isdigit():
                refs.add(re.sub(r"^0+", "", n) or n)
    for op in mind.get("llmRouteOps") or parsed.get("llmRouteOps") or []:
        if not isinstance(op, dict):
            continue
        refs |= _refs_from_text(op.get("instructionText") or op.get("instruction") or "")
        for it in op.get("itemsUsed") or []:
            if isinstance(it, dict):
                n = str(it.get("itemNo") or "").strip()
                if n.isdigit():
                    refs.add(re.sub(r"^0+", "", n) or n)
    refs |= _refs_from_text(parsed.get("raw_text") or "")
    return refs


def build_item_link_report(parsed: dict, parts_list: dict | None, mind: dict | None = None) -> dict:
    pl_nos = _pl_item_nos(parts_list)
    ga_refs = collect_drawing_item_refs(parsed, mind=mind)
    pl_only = sorted(pl_nos - ga_refs, key=lambda x: int(x) if x.isdigit() else 0)
    ga_only = sorted(ga_refs - pl_nos, key=lambda x: int(x) if x.isdigit() else 0)
    matched = sorted(pl_nos & ga_refs, key=lambda x: int(x) if x.isdigit() else 0)

    item_map = (parts_list or {}).get("itemMap") or {}
    if not item_map and parts_list:
        item_map = {
            str(it.get("itemNo")): it
            for it in (parts_list.get("items") or [])
            if isinstance(it, dict) and it.get("itemNo") is not None
        }

    bom_by_no: dict[str, dict] = {}
    for b in parsed.get("bom_items") or []:
        if not isinstance(b, dict):
            continue
        key = str(b.get("itemNo") or "").strip()
        if key:
            bom_by_no[re.sub(r"^0+", "", key) or key] = b

    callout_totals: dict[int, int] = {}
    try:
        from app.route_card.drawing_mind.assembly_groups import callout_qty_totals

        mind = mind or {}
        groups = mind.get("assemblyGroups") or parsed.get("assemblyGroups") or []
        callout_totals = callout_qty_totals(groups)
    except Exception:
        callout_totals = {}

    rows = []
    qty_mismatches: list[str] = []
    qty_checked = 0
    for n in sorted(pl_nos | ga_refs, key=lambda x: int(x) if x.isdigit() else 0):
        desc = ""
        pl_qty = None
        meta = item_map.get(n) or item_map.get(str(n).zfill(2)) or {}
        if isinstance(meta, dict):
            desc = meta.get("description") or ""
            if meta.get("qty") is not None:
                try:
                    pl_qty = int(meta.get("qty"))
                except (TypeError, ValueError):
                    pl_qty = None

        bom = bom_by_no.get(n) or {}
        extracted_qty = None
        if bom.get("extractedQty") is not None:
            try:
                extracted_qty = int(bom.get("extractedQty"))
            except (TypeError, ValueError):
                extracted_qty = None
        if extracted_qty is None and n.isdigit() and int(n) in callout_totals:
            extracted_qty = callout_totals[int(n)]
        if extracted_qty is None and bom.get("qty") is not None and n not in pl_nos:
            try:
                extracted_qty = int(bom.get("qty"))
            except (TypeError, ValueError):
                extracted_qty = None

        qty_match = None
        if pl_qty is not None and extracted_qty is not None:
            qty_checked += 1
            qty_match = pl_qty == extracted_qty
            if not qty_match:
                qty_mismatches.append(n)

        status = (
            "matched"
            if n in pl_nos and n in ga_refs
            else ("pl_only" if n in pl_nos else "ga_only")
        )
        if qty_match is False and status == "matched":
            status = "qty_mismatch"

        rows.append(
            {
                "itemNo": n,
                "description": desc,
                "plQty": pl_qty,
                "extractedQty": extracted_qty,
                "qtyMatch": qty_match,
                "onPartsList": n in pl_nos,
                "onDrawing": n in ga_refs,
                "status": status,
            }
        )
    return {
        "matched": matched,
        "plOnly": pl_only,
        "gaOnly": ga_only,
        "qtyMismatches": qty_mismatches,
        "rows": rows,
        "summary": {
            "plCount": len(pl_nos),
            "gaRefCount": len(ga_refs),
            "matchedCount": len(matched),
            "mismatchCount": len(pl_only) + len(ga_only),
            "qtyChecked": qty_checked,
            "qtyMismatchCount": len(qty_mismatches),
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

    unresolved_wc = [
        o for o in ops if (o.get("linkStatus") or o.get("link_status") or "") == "unresolved"
    ]
    partial_wc = [
        o for o in ops if (o.get("linkStatus") or o.get("link_status") or "") == "partial"
    ]
    if unresolved_wc:
        sample = ", ".join(f"OP {o.get('opNo')}" for o in unresolved_wc[:5])
        more = f" (+{len(unresolved_wc) - 5} more)" if len(unresolved_wc) > 5 else ""
        add(
            "wc_unresolved",
            "high",
            f"Work centre not linked for {len(unresolved_wc)} operation(s): {sample}{more}. "
            "Pick a department work centre or add one under Work centers.",
            source="auto:wc_resolve",
        )
    if partial_wc:
        sample = ", ".join(f"OP {o.get('opNo')}" for o in partial_wc[:5])
        add(
            "wc_partial",
            "medium",
            f"Machine not selected for {len(partial_wc)} linked work centre(s): {sample}.",
            source="auto:wc_resolve",
        )

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

    for kind, severity, message in summarize_extra_warnings(extra_warnings):
        add(kind, severity, message, source="auto:warning")

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
    qty_bad = int((report.get("summary") or {}).get("qtyMismatchCount") or 0)
    if qty_bad > 0:
        sample = ", ".join((report.get("qtyMismatches") or [])[:8])
        add(
            "pl_bom_qty_mismatch",
            "medium" if qty_bad < 5 else "high",
            f"PL qty ≠ BOM/callout extracted qty for {qty_bad} item(s)"
            + (f": {sample}" if sample else "")
            + ".",
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
