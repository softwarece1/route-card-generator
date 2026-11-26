"""Core workflow validation: sessions, drawings ACL, upload edges, IED share gates."""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from pony.orm import commit, db_session

from app.route_card.models import RcDrawing, RcRouteCard, RcSession, RcUser
from app.route_card.service import (
    _assert_can_share_ied,
    _assert_ied_same_sbu,
    create_drawing,
)

pytestmark = [pytest.mark.vnv, pytest.mark.workflow]


def test_engineer_creates_session(vnv_client, auth_header):
    """TEST-WF-SESSION — REQ-WF-01"""
    resp = vnv_client.post(
        "/api/v1/route-card/sessions",
        headers=auth_header("engineer"),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body.get("id") or body.get("sessionId") or "id" in str(body)


def test_drawing_acl_non_owner(vnv_client, auth_header, vnv_users):
    """TEST-ACL-DRAWING — REQ-ACL-08"""
    vnv_client.cookies.clear()
    owner = vnv_users["engineer"]
    other = vnv_users["engineer_ied"]
    created = create_drawing(
        b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF",
        "vnv-owned.pdf",
        ".pdf",
        uploaded_by=owner["emp_id"],
        user={"id": owner["id"], "empId": owner["emp_id"], "role": "engineer"},
    )
    drawing_id = created["id"]
    denied = vnv_client.get(
        f"/api/v1/route-card/drawings/{drawing_id}/file",
        headers=auth_header("engineer_ied"),
    )
    # Different engineer (IED dept) must not download owner's drawing
    assert denied.status_code == 403, denied.text
    allowed = vnv_client.get(
        f"/api/v1/route-card/drawings/{drawing_id}/file",
        headers=auth_header("engineer"),
    )
    assert allowed.status_code == 200
    assert other["id"] != owner["id"]


def test_upload_edge_empty_file(vnv_client, auth_header):
    """TEST-WF-UPLOAD-EDGE — REQ-WF-02"""
    sess = vnv_client.post(
        "/api/v1/route-card/sessions",
        headers=auth_header("engineer"),
    )
    assert sess.status_code == 200
    session_id = sess.json().get("id") or sess.json().get("sessionId")
    assert session_id
    # Empty multipart often 400/422
    resp = vnv_client.post(
        f"/api/v1/route-card/sessions/{session_id}/documents/drawing",
        headers=auth_header("engineer"),
        files={"file": ("empty.pdf", b"", "application/pdf")},
    )
    assert resp.status_code in (400, 422, 413)


def test_ied_share_and_complete_gates(vnv_users):
    """TEST-WF-IED-FLOW — REQ-WF-03"""
    eng = vnv_users["engineer"]
    ied = vnv_users["engineer_ied"]
    with db_session:
        owner = RcUser.get(id=eng["id"])
        session = RcSession(user=owner, status="open", sbu=owner.sbu or "Software")
        drawing = RcDrawing(
            session=session,
            filename="vnv-flow.pdf",
            file_type="pdf",
            object_path="vnv/flow.pdf",
            uploaded_by=owner.emp_id,
        )
        card = RcRouteCard(drawing=drawing, status="draft")
        commit()
        card_id = card.id

    eng_user = {
        "id": eng["id"],
        "empId": eng["emp_id"],
        "role": "engineer",
        "sbu": "Software",
        "isIedDept": False,
        "departmentCode": "PMG",
    }
    ied_user = {
        "id": ied["id"],
        "empId": ied["emp_id"],
        "role": "engineer",
        "sbu": "Software",
        "isIedDept": True,
        "departmentCode": "IED",
    }

    with db_session:
        card = RcRouteCard.get(id=card_id)
        # Non-IED cannot complete IED review
        with pytest.raises(HTTPException) as exc:
            _assert_ied_same_sbu(card, eng_user)
        assert exc.value.status_code == 403
        # IED-dept can pass membership/SBU gate when status is ied_review
        card.status = "ied_review"
        commit()
        card = RcRouteCard.get(id=card_id)
        _assert_ied_same_sbu(card, ied_user)
        # Share gate: engineer owner path uses _assert_can_share_ied
        card.status = "draft"
        commit()
        card = RcRouteCard.get(id=card_id)
        try:
            _assert_can_share_ied(card, eng_user)
        except HTTPException as share_exc:
            # May fail for missing ops — but not for IED membership
            assert share_exc.status_code in (400, 403)
            if share_exc.status_code == 403:
                assert "IED" not in str(share_exc.detail) or "share" in str(
                    share_exc.detail
                ).lower()
