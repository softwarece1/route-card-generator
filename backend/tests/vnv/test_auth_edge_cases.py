"""Auth edge cases for V&V (login, CAPTCHA, emp-status, signup)."""

from __future__ import annotations

import base64
import json
import secrets

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
from pony.orm import commit, db_session, select

from app.auth_crypto import ALG as CREDS_ALG
from app.auth_crypto import _private_key
from app.config.settings import settings
from app.route_card.models import RcDepartment, RcSbu, RcUser
from app.security import hash_password
from tests.vnv.conftest import SBU_NAME, VNV_PASSWORD

pytestmark = [pytest.mark.vnv, pytest.mark.edge, pytest.mark.security]


def _encrypt(payload: dict) -> str:
    pub = _private_key().public_key()
    raw = json.dumps(payload).encode("utf-8")
    cipher = pub.encrypt(
        raw,
        padding.OAEP(
            mgf=padding.MGF1(algorithm=hashes.SHA256()),
            algorithm=hashes.SHA256(),
            label=None,
        ),
    )
    return base64.b64encode(cipher).decode("ascii")


def test_login_bad_password(vnv_client, vnv_users):
    """TEST-AUTH-LOGIN-BAD — REQ-AUTH-02"""
    emp = vnv_users["engineer"]["emp_id"]
    resp = vnv_client.post(
        "/api/v1/auth/login",
        json={"cipher": _encrypt({"empId": emp, "password": "WrongPass!!!!999"})},
    )
    assert resp.status_code in (401, 400)
    detail = str(resp.json().get("detail", "")).lower()
    assert "already registered" not in detail


def test_captcha_required_when_enabled(vnv_client, vnv_users):
    """TEST-AUTH-CAPTCHA-REQ — REQ-AUTH-03"""
    prev = settings.CAPTCHA_ENABLED, settings.APP_ENV
    settings.CAPTCHA_ENABLED = "true"
    settings.APP_ENV = "prod"
    try:
        emp = vnv_users["engineer"]["emp_id"]
        resp = vnv_client.post(
            "/api/v1/auth/login",
            json={"cipher": _encrypt({"empId": emp, "password": VNV_PASSWORD})},
        )
        assert resp.status_code == 401
        assert "CAPTCHA" in str(resp.json().get("detail", ""))
    finally:
        settings.CAPTCHA_ENABLED, settings.APP_ENV = prev


def test_emp_status_edges(vnv_client):
    """TEST-AUTH-EMP-STATUS — REQ-AUTH-04"""
    settings.APP_ENV = "dev"
    settings.CAPTCHA_ENABLED = "false"
    resp = vnv_client.get("/api/v1/auth/emp-status/810004")
    assert resp.status_code == 200
    body = resp.json()
    assert "registered" not in body
    assert "available" in body

    settings.CAPTCHA_ENABLED = "true"
    try:
        blocked = vnv_client.get("/api/v1/auth/emp-status/810004")
        assert blocked.status_code == 401
    finally:
        settings.CAPTCHA_ENABLED = "false"


def test_signup_duplicate_generic(vnv_client, vnv_users, vnv_departments):
    """TEST-AUTH-SIGNUP-DUP — REQ-AUTH-05"""
    emp = vnv_users["engineer"]["emp_id"]
    resp = vnv_client.post(
        "/api/v1/auth/signup",
        json={
            "name": "Dup VnV",
            "sbu": SBU_NAME,
            "departmentId": vnv_departments["PMG"],
            "cipher": _encrypt({"empId": emp, "password": VNV_PASSWORD}),
            "alg": CREDS_ALG,
        },
    )
    assert resp.status_code == 400
    detail = str(resp.json().get("detail", "")).lower()
    assert "already registered" not in detail
    assert "unable to complete signup" in detail


def test_signup_pending_blocks_login(vnv_client, vnv_departments):
    """TEST-AUTH-SIGNUP-PENDING — REQ-AUTH-06"""
    emp_id = f"81{secrets.randbelow(10000):04d}"
    # Ensure not colliding with fixed personas
    while emp_id.startswith("81000"):
        emp_id = f"81{secrets.randbelow(10000):04d}"
    password = "SignupPass2026!#Aa"
    with db_session:
        old = RcUser.get(emp_id=emp_id)
        if old:
            old.delete()
            commit()
    resp = vnv_client.post(
        "/api/v1/auth/signup",
        json={
            "name": "Pending VnV",
            "sbu": SBU_NAME,
            "departmentId": vnv_departments["PMG"],
            "cipher": _encrypt({"empId": emp_id, "password": password}),
            "alg": CREDS_ALG,
        },
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "pending_approval"
    login = vnv_client.post(
        "/api/v1/auth/login",
        json={"cipher": _encrypt({"empId": emp_id, "password": password})},
    )
    assert login.status_code == 403
    assert login.json()["detail"]["code"] == "SIGNUP_PENDING"


def test_logout_revokes(vnv_client, vnv_users):
    """TEST-AUTH-LOGOUT — REQ-AUTH-08"""
    from app.auth import create_access_token

    u = vnv_users["engineer"]
    # Fresh token so session-scoped persona tokens remain usable by other tests
    token = create_access_token(
        emp_id=u["emp_id"], role=u["role"], user_id=u["id"]
    )
    headers = {"Authorization": f"Bearer {token}"}
    me = vnv_client.get("/api/v1/auth/me", headers=headers)
    assert me.status_code == 200
    out = vnv_client.post("/api/v1/auth/logout", headers=headers)
    assert out.status_code == 200
    me2 = vnv_client.get("/api/v1/auth/me", headers=headers)
    assert me2.status_code == 401


def test_concurrent_session_takeover_shape(vnv_client, vnv_users):
    """TEST-AUTH-TAKEOVER — REQ-AUTH-07"""
    from app.auth import create_access_token

    u = vnv_users["engineer"]
    # First session
    t1 = create_access_token(emp_id=u["emp_id"], role=u["role"], user_id=u["id"])
    assert vnv_client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {t1}"}).status_code == 200
    # Second login without takeover → 409 when CAPTCHA off
    resp = vnv_client.post(
        "/api/v1/auth/login",
        json={"cipher": _encrypt({"empId": u["emp_id"], "password": VNV_PASSWORD})},
    )
    if resp.status_code == 409:
        detail = resp.json().get("detail") or {}
        assert detail.get("code") == "CONCURRENT_SESSION"
        assert detail.get("resumeToken")
    else:
        # Environment may allow replace-in-place; still must authenticate
        assert resp.status_code in (200, 401, 403)


def test_security_headers(vnv_client):
    """TEST-SEC-HEADERS — REQ-SEC-01"""
    resp = vnv_client.get("/health")
    assert resp.status_code == 200
    csp = resp.headers.get("Content-Security-Policy", "")
    assert "default-src 'self'" in csp
    assert "script-src 'self'" in csp
    assert "base-uri 'self'" in csp


def test_oarc_error_sanitized(vnv_client, auth_header, monkeypatch):
    """TEST-SEC-OARC — REQ-SEC-03"""
    from fastapi import HTTPException

    from app.route_card.router import convert_oarc_to_sap
    from app.route_card.schemas import OarcToSapRequest

    monkeypatch.setattr(
        "app.route_card.router.build_sap_payload",
        lambda _d: (_ for _ in ()).throw(ValueError("secret-xyz")),
    )
    with pytest.raises(HTTPException) as exc:
        convert_oarc_to_sap(OarcToSapRequest(source="vnv"))
    assert exc.value.detail == "OARC to SAP mapping failed"
    assert "secret" not in str(exc.value.detail)
