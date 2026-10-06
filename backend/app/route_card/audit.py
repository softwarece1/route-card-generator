"""Audit trail helpers (Phase 5)."""

from __future__ import annotations

from datetime import datetime

from fastapi import HTTPException
from pony.orm import commit, db_session, desc, select

from app.route_card.models import RcAuditEvent, RcRouteCard, RcUser


def audit_dict(e: RcAuditEvent) -> dict:
    return {
        "id": e.id,
        "routeCardId": e.route_card.id if e.route_card else None,
        "sessionId": e.session,
        "action": e.action,
        "detail": e.detail or {},
        "comment": e.comment or "",
        "userEmpId": e.user.emp_id if e.user else None,
        "userName": e.user.name if e.user else None,
        "createdAt": e.created_at.isoformat() + "Z" if e.created_at else None,
    }


@db_session
def record_audit(
    *,
    action: str,
    user: dict | None = None,
    route_card_id: int | None = None,
    session_id: int | None = None,
    detail: dict | None = None,
    comment: str | None = None,
) -> dict:
    card = RcRouteCard.get(id=route_card_id) if route_card_id else None
    u = None
    if user and user.get("id"):
        u = RcUser.get(id=user["id"])
    e = RcAuditEvent(
        route_card=card,
        session=session_id,
        user=u,
        action=action,
        detail=detail or {},
        comment=comment or "",
        created_at=datetime.utcnow(),
    )
    commit()
    return audit_dict(e)


@db_session
def list_route_audit(route_id: int, limit: int = 100) -> list[dict]:
    card = RcRouteCard.get(id=route_id)
    if not card:
        raise HTTPException(404, "Route card not found")
    rows = select(e for e in RcAuditEvent if e.route_card == card).order_by(
        desc(RcAuditEvent.created_at)
    )[: max(1, min(limit, 500))]
    return [audit_dict(e) for e in rows]
