"""Persona × endpoint authorization matrix (IED via department, not role)."""

from __future__ import annotations

import pytest

pytestmark = [pytest.mark.vnv, pytest.mark.authz]

# (path, method, allowed_personas) — GET unless noted
AUTHZ_CASES = [
    ("/api/v1/route-card/admin/users", "GET", {"admin"}),
    ("/api/v1/route-card/admin/uploads", "GET", {"admin"}),
    ("/api/v1/route-card/system/health", "GET", {"admin"}),
    ("/api/v1/route-card/sbu/users", "GET", {"admin", "sbu_head", "dept_head"}),
    ("/api/v1/route-card/signup-approvals", "GET", {"admin", "sbu_head"}),
    ("/api/v1/route-card/sbus", "GET", {"admin", "sbu_head"}),
    ("/api/v1/route-card/departments", "GET", {"admin", "sbu_head"}),
    ("/api/v1/route-card/my/extractions", "GET", {"admin", "sbu_head", "dept_head", "engineer", "engineer_ied"}),
    ("/api/v1/route-card/ref-docs/catalog", "GET", {"admin", "sbu_head", "dept_head", "engineer", "engineer_ied"}),
    ("/api/v1/route-card/operation-templates", "GET", {"admin", "sbu_head", "dept_head", "engineer", "engineer_ied"}),
    ("/api/v1/route-card/work-centers", "GET", {"admin", "sbu_head", "dept_head", "engineer", "engineer_ied"}),
]

MUTATION_FORBIDDEN_FOR_ENGINEER = [
    ("/api/v1/route-card/work-centers", "POST", {"admin", "sbu_head"}),
    ("/api/v1/route-card/ref-docs/folders", "POST", {"admin", "sbu_head"}),
    ("/api/v1/route-card/operation-templates", "POST", {"admin", "sbu_head", "dept_head", "engineer_ied"}),
]


@pytest.mark.parametrize("path,method,allowed", AUTHZ_CASES, ids=[c[0] for c in AUTHZ_CASES])
def test_authz_get_matrix(vnv_client, auth_header, vnv_users, path, method, allowed):
    """TEST-AUTHZ-ADMIN TEST-AUTHZ-USERS TEST-AUTHZ-ORG — REQ-ACL-01..06."""
    for persona in vnv_users:
        resp = vnv_client.request(method, path, headers=auth_header(persona))
        if persona in allowed:
            assert resp.status_code < 400, f"{persona} should access {path}: {resp.text}"
        else:
            assert resp.status_code == 403, f"{persona} must be forbidden on {path}: {resp.status_code}"


def test_unauthenticated_rejected(vnv_client):
    """TEST-AUTHZ-UNAUTH — REQ-AUTH-01"""
    resp = vnv_client.get("/api/v1/route-card/my/extractions")
    assert resp.status_code == 401


@pytest.mark.parametrize(
    "path,method,allowed",
    MUTATION_FORBIDDEN_FOR_ENGINEER,
    ids=[c[0] for c in MUTATION_FORBIDDEN_FOR_ENGINEER],
)
def test_mutation_authz(vnv_client, auth_header, vnv_users, path, method, allowed):
    """TEST-AUTHZ-WC TEST-AUTHZ-REF TEST-AUTHZ-TMPL — REQ-ACL-04..06"""
    body = {}
    if "operation-templates" in path:
        body = {"name": "vnv-tmpl", "sbu": "Software", "operations": []}
    elif "ref-docs/folders" in path:
        body = {"code": "VNV", "name": "V&V Folder"}
    elif "work-centers" in path:
        body = {"code": "VNVWC", "name": "V&V WC", "sbu": "Software"}

    for persona in ("engineer", "engineer_ied", "admin", "sbu_head", "dept_head"):
        if persona not in vnv_users:
            continue
        resp = vnv_client.request(
            method, path, headers=auth_header(persona), json=body
        )
        if persona in allowed:
            # May be 200/201 or 400/422 for validation — must not be 403
            assert resp.status_code != 403, f"{persona} unexpectedly 403 on {path}"
        else:
            assert resp.status_code == 403, f"{persona} must 403 on {path}: {resp.status_code}"


def test_ied_persona_flag_and_complete_gate(vnv_client, auth_header, vnv_users):
    """TEST-AUTHZ-IED-COMPLETE — REQ-ACL-07

    IED is department-based (isIedDept). complete-ied rejects non-IED after card exists.
    """
    me_eng = vnv_client.get("/api/v1/auth/me", headers=auth_header("engineer"))
    me_ied = vnv_client.get("/api/v1/auth/me", headers=auth_header("engineer_ied"))
    assert me_eng.status_code == 200
    assert me_ied.status_code == 200
    assert me_eng.json().get("isIedDept") is False
    assert me_ied.json().get("isIedDept") is True
    assert me_ied.json().get("role") == "engineer"

    from fastapi import HTTPException
    from pony.orm import commit, db_session

    from app.route_card.models import RcDrawing, RcRouteCard, RcSession, RcUser
    from app.route_card.service import _assert_ied_same_sbu

    eng = vnv_users["engineer"]
    with db_session:
        owner = RcUser.get(id=eng["id"])
        session = RcSession(user=owner, status="open", sbu=owner.sbu or "Software")
        drawing = RcDrawing(
            session=session,
            filename="vnv-ied.pdf",
            file_type="pdf",
            object_path="vnv/ied-gate.pdf",
            uploaded_by=owner.emp_id,
        )
        card = RcRouteCard(drawing=drawing, status="ied_review")
        commit()
        card_id = card.id

    with db_session:
        card = RcRouteCard.get(id=card_id)
        with pytest.raises(HTTPException) as exc_eng:
            _assert_ied_same_sbu(
                card,
                {
                    "id": eng["id"],
                    "empId": eng["emp_id"],
                    "role": "engineer",
                    "sbu": "Software",
                    "isIedDept": False,
                    "departmentCode": "PMG",
                },
            )
        assert exc_eng.value.status_code == 403

        ied = vnv_users["engineer_ied"]
        _assert_ied_same_sbu(
            card,
            {
                "id": ied["id"],
                "empId": ied["emp_id"],
                "role": "engineer",
                "sbu": "Software",
                "isIedDept": True,
                "departmentCode": "IED",
            },
        )
