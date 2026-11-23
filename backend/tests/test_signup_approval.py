"""Self-service engineer signup approval (dept_head / admin)."""

from __future__ import annotations

import base64
import json
import secrets

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
from pony.orm import commit, db_session
from starlette.testclient import TestClient

from app.auth_crypto import ALG as CREDS_ALG
from app.auth_crypto import _private_key
from app.config.settings import settings
from app.database.connection import connect_to_db
from app.main import app
from app.route_card.models import RcDepartment, RcNotification, RcUser
from app.security import hash_password

client = TestClient(app)


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


def _ensure_dept(name: str = "Software") -> str:
    connect_to_db()
    with db_session:
        d = RcDepartment.get(name=name)
        if not d:
            code = (name[:8] or "SFT").upper()
            RcDepartment(code=code, name=name, is_active=True, sort_order=99)
            commit()
    return name


def _ensure_head(dept: str, emp_id: str = "700001") -> int:
    connect_to_db()
    with db_session:
        u = RcUser.get(emp_id=emp_id)
        if not u:
            u = RcUser(
                emp_id=emp_id,
                name="Test Dept Head",
                dept=dept,
                password_hash=hash_password("HeadPass2026!#Aa"),
                role="dept_head",
                is_active=True,
                approval_status="approved",
            )
        else:
            u.role = "dept_head"
            u.dept = dept
            u.is_active = True
            u.approval_status = "approved"
            u.password_hash = hash_password("HeadPass2026!#Aa")
        commit()
        return u.id


def _token_for(user_id: int, emp_id: str, role: str) -> str:
    from app.auth import create_access_token

    return create_access_token(emp_id=emp_id, role=role, user_id=user_id)


@pytest.fixture
def captcha_off():
    prev_env, prev_flag = settings.APP_ENV, settings.CAPTCHA_ENABLED
    settings.APP_ENV = "dev"
    settings.CAPTCHA_ENABLED = "false"
    yield
    settings.APP_ENV = prev_env
    settings.CAPTCHA_ENABLED = prev_flag


def test_signup_pending_no_cookie_and_notifies_head(captcha_off):
    dept = _ensure_dept("Software")
    head_id = _ensure_head(dept, "700011")
    emp_id = f"71{secrets.randbelow(10000):04d}"
    password = "SignupPass2026!#Aa"

    with db_session:
        old = RcUser.get(emp_id=emp_id)
        if old:
            old.delete()
            commit()

    resp = client.post(
        "/api/v1/auth/signup",
        json={
            "name": "Pending Engineer",
            "dept": dept,
            "cipher": _encrypt({"empId": emp_id, "password": password}),
            "alg": CREDS_ALG,
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "pending_approval"
    assert "access_token" not in body
    assert resp.cookies.get("rc_access") in (None, "")

    with db_session:
        u = RcUser.get(emp_id=emp_id)
        assert u is not None
        assert u.is_active is False
        assert u.approval_status == "pending"
        notes = select_notifications_for(head_id)
        assert any("Signup approval" in (n.title or "") for n in notes)

    # Login blocked while pending
    login = client.post(
        "/api/v1/auth/login",
        json={"cipher": _encrypt({"empId": emp_id, "password": password})},
    )
    assert login.status_code == 403
    detail = login.json()["detail"]
    assert detail["code"] == "SIGNUP_PENDING"


def select_notifications_for(user_id: int):
    return [
        n
        for n in RcNotification.select()[:]
        if n.user.id == user_id
    ]


def test_approve_and_reject_signup(captcha_off):
    dept = _ensure_dept("Software")
    head_id = _ensure_head(dept, "700022")
    _ensure_dept("Assembly")
    other_head_id = _ensure_head("Assembly", "700044")

    emp_ok = f"72{secrets.randbelow(10000):04d}"
    emp_bad = f"73{secrets.randbelow(10000):04d}"
    password = "SignupPass2026!#Aa"

    for emp in (emp_ok, emp_bad):
        with db_session:
            old = RcUser.get(emp_id=emp)
            if old:
                old.delete()
                commit()
        r = client.post(
            "/api/v1/auth/signup",
            json={
                "name": "Pending Engineer Two" if emp == emp_ok else "Pending Engineer Three",
                "dept": dept,
                "cipher": _encrypt({"empId": emp, "password": password}),
                "alg": CREDS_ALG,
            },
        )
        assert r.status_code == 200, r.text

    with db_session:
        uid_ok = RcUser.get(emp_id=emp_ok).id
        uid_bad = RcUser.get(emp_id=emp_bad).id

    head_token = _token_for(head_id, "700022", "dept_head")
    other_token = _token_for(other_head_id, "700044", "dept_head")

    # Wrong dept cannot approve
    denied = client.post(
        f"/api/v1/route-card/signup-approvals/{uid_ok}/approve",
        headers={"Authorization": f"Bearer {other_token}"},
        json={},
    )
    assert denied.status_code == 403

    # List pending for head
    listed = client.get(
        "/api/v1/route-card/signup-approvals",
        headers={"Authorization": f"Bearer {head_token}"},
    )
    assert listed.status_code == 200
    ids = {row["id"] for row in listed.json().get("items") or []}
    assert uid_ok in ids and uid_bad in ids

    # Approve
    ok = client.post(
        f"/api/v1/route-card/signup-approvals/{uid_ok}/approve",
        headers={"Authorization": f"Bearer {head_token}"},
        json={"remark": "Welcome"},
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["approvalStatus"] == "approved"

    login_ok = client.post(
        "/api/v1/auth/login",
        json={"cipher": _encrypt({"empId": emp_ok, "password": password})},
    )
    assert login_ok.status_code == 200, login_ok.text
    # Drop engineer cookie so subsequent Bearer calls use the dept_head token
    client.cookies.clear()

    # Reject requires remark
    miss = client.post(
        f"/api/v1/route-card/signup-approvals/{uid_bad}/reject",
        headers={"Authorization": f"Bearer {head_token}"},
        json={"remark": ""},
    )
    assert miss.status_code == 400

    rej = client.post(
        f"/api/v1/route-card/signup-approvals/{uid_bad}/reject",
        headers={"Authorization": f"Bearer {head_token}"},
        json={"remark": "Incomplete details"},
    )
    assert rej.status_code == 200
    assert rej.json()["approvalStatus"] == "rejected"

    login_rej = client.post(
        "/api/v1/auth/login",
        json={"cipher": _encrypt({"empId": emp_bad, "password": password})},
    )
    assert login_rej.status_code == 403
    assert login_rej.json()["detail"]["code"] == "SIGNUP_REJECTED"
    assert "Incomplete details" in login_rej.json()["detail"]["message"]
