"""Admin / master-data module V&V checks."""

from __future__ import annotations

import pytest

pytestmark = [pytest.mark.vnv, pytest.mark.admin]


def test_system_health_admin_only(vnv_client, auth_header):
    """TEST-ADM-SYSTEM — REQ-ADM-01"""
    ok = vnv_client.get(
        "/api/v1/route-card/system/health", headers=auth_header("admin")
    )
    assert ok.status_code == 200, ok.text
    denied = vnv_client.get(
        "/api/v1/route-card/system/health", headers=auth_header("engineer")
    )
    assert denied.status_code == 403


def test_uploads_admin_only(vnv_client, auth_header):
    """TEST-ADM-UPLOADS — REQ-ADM-02"""
    ok = vnv_client.get(
        "/api/v1/route-card/admin/uploads", headers=auth_header("admin")
    )
    assert ok.status_code == 200, ok.text
    denied = vnv_client.get(
        "/api/v1/route-card/admin/uploads", headers=auth_header("engineer")
    )
    assert denied.status_code == 403


def test_users_scope(vnv_client, auth_header):
    """TEST-ADM-USERS — REQ-ADM-03"""
    for persona in ("admin", "sbu_head", "dept_head"):
        resp = vnv_client.get(
            "/api/v1/route-card/sbu/users", headers=auth_header(persona)
        )
        assert resp.status_code == 200, f"{persona}: {resp.text}"
    denied = vnv_client.get(
        "/api/v1/route-card/sbu/users", headers=auth_header("engineer")
    )
    assert denied.status_code == 403
    denied_ied = vnv_client.get(
        "/api/v1/route-card/sbu/users", headers=auth_header("engineer_ied")
    )
    assert denied_ied.status_code == 403


def test_org_departments(vnv_client, auth_header):
    """TEST-ADM-ORG — REQ-ADM-04"""
    ok = vnv_client.get(
        "/api/v1/route-card/departments", headers=auth_header("sbu_head")
    )
    assert ok.status_code == 200, ok.text
    denied = vnv_client.get(
        "/api/v1/route-card/departments", headers=auth_header("engineer")
    )
    assert denied.status_code == 403


def test_ref_docs_browse(vnv_client, auth_header):
    """TEST-ADM-REF-BROWSE — REQ-ADM-05"""
    for persona in ("engineer", "engineer_ied", "admin"):
        resp = vnv_client.get(
            "/api/v1/route-card/ref-docs/catalog", headers=auth_header(persona)
        )
        assert resp.status_code == 200, f"{persona}: {resp.text}"


def test_work_centers_list_authenticated(vnv_client, auth_header):
    resp = vnv_client.get(
        "/api/v1/route-card/work-centers", headers=auth_header("engineer")
    )
    assert resp.status_code == 200
    assert "items" in resp.json()
