"""IED may change only setup / per-piece hours during ied_review."""

from __future__ import annotations

import secrets

import pytest
from fastapi import HTTPException
from pony.orm import commit, db_session

from app.database.connection import connect_to_db
from app.route_card.models import RcDrawing, RcOperation, RcRouteCard, RcSession, RcUser
from app.route_card.service import _normalize_hour_value, update_route
from app.security import hash_password


def test_normalize_hour_value_decimals():
    assert _normalize_hour_value("0.25", field="setup") == "0.25"
    assert _normalize_hour_value(1.5, field="time") == "1.5"
    assert _normalize_hour_value("2", field="setup") == "2"
    assert _normalize_hour_value("", field="time") == ""
    with pytest.raises(HTTPException) as exc:
        _normalize_hour_value("-1", field="setup")
    assert exc.value.status_code == 400
    with pytest.raises(HTTPException):
        _normalize_hour_value("abc", field="time")


def _ensure_ied_and_route():
    connect_to_db()
    emp = f"81{secrets.randbelow(10000):04d}"
    with db_session:
        eng = RcUser.get(emp_id="810001")
        if not eng:
            eng = RcUser(emp_id="810001",
                name="IED Time Eng",
                sbu="Software",
                password_hash=hash_password("TestSecurePass2026!#"),
                role="engineer",
                is_active=True,
                approval_status="approved",
            )
        ied = RcUser.get(emp_id=emp)
        if not ied:
            ied = RcUser(emp_id=emp,
                name="IED Time Reviewer",
                sbu="Software",
                password_hash=hash_password("TestSecurePass2026!#"),
                role="ied",
                is_active=True,
                approval_status="approved",
            )
        else:
            ied.role = "ied"
            ied.sbu = "Software"
            ied.is_active = True
            ied.approval_status = "approved"
        commit()
        session = RcSession(user=eng, status="analyzed")
        drawing = RcDrawing(
            session=session,
            user=eng,
            filename="ied-time.pdf",
            file_type="pdf",
            object_path=f"uploads/test/ied-time-{secrets.token_hex(4)}.pdf",
            storage_backend="local",
            size_bytes=1,
            status="analyzed",
        )
        card = RcRouteCard(drawing=drawing, status="ied_review", part_info={})
        op = RcOperation(
            route_card=card,
            op_no=10,
            operation="ASSEMBLE FRAME",
            work_centre="WC100",
            machine="M1",
            setup="1",
            time="2",
            instruction_text="Do not change me",
            status="Planned",
        )
        commit()
        return {
            "route_id": card.id,
            "ied": {"id": ied.id, "empId": ied.emp_id, "role": "ied", "sbu": "Software"},
            "op_id": op.id,
        }


def test_ied_update_only_setup_and_time():
    meta = _ensure_ied_and_route()
    route_id = meta["route_id"]
    ied = meta["ied"]

    out = update_route(
        route_id,
        {
            "operations": [
                {
                    "opNo": 10,
                    "operation": "HACKED NAME",
                    "workCentre": "HACKED-WC",
                    "setup": "0.25",
                    "time": "1.5",
                    "instructionText": "Hacked instruction",
                },
                {
                    "opNo": 20,
                    "operation": "NEW OP SHOULD NOT APPEAR",
                    "setup": "9",
                    "time": "9",
                },
            ],
            "comment": "ied test",
        },
        user=ied,
    )

    ops = out.get("routeOperations") or out.get("operations") or []
    # build_payload shape
    if not ops and isinstance(out.get("payload"), dict):
        ops = out["payload"].get("routeOperations") or []

    with db_session:
        card = RcRouteCard.get(id=route_id)
        rows = sorted(card.operations, key=lambda o: o.op_no)
        assert len(rows) == 1
        assert rows[0].op_no == 10
        assert rows[0].operation == "ASSEMBLE FRAME"
        assert rows[0].work_centre == "WC100"
        assert rows[0].instruction_text == "Do not change me"
        assert rows[0].setup == "0.25"
        assert rows[0].time == "1.5"
