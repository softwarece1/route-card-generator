"""Cookie auth + realtime hub tests (no refresh token)."""

from __future__ import annotations

import asyncio

import pytest
from starlette.testclient import TestClient

from app.main import app

client = TestClient(app)


def _ensure_user(emp_id: str = "888877", password: str = "CookieAuthPass2026!#"):
    from app.database.connection import connect_to_db
    from app.route_card.models import RcUser
    from app.security import hash_password
    from pony.orm import commit, db_session

    try:
        connect_to_db()
    except Exception:
        pass

    with db_session:
        u = RcUser.get(emp_id=emp_id)
        if not u:
            u = RcUser(
                emp_id=emp_id,
                name="Cookie Test",
                dept="Software",
                password_hash=hash_password(password),
                role="engineer",
                is_active=True,
            )
        else:
            u.password_hash = hash_password(password)
            u.is_active = True
        commit()
        from app.auth.sessions import revoke_user_sessions

        revoke_user_sessions(u.id)
        return u.id, password


def test_access_cookie_helpers():
    from fastapi import Response
    from app.auth.cookies import (
        access_cookie_name,
        clear_access_cookie,
        set_access_cookie,
    )

    resp = Response()
    set_access_cookie(resp, "tok-value")
    # Starlette stores cookies on raw_headers
    headers = {k.decode().lower(): v.decode() for k, v in resp.raw_headers if k}
    set_cookie = headers.get("set-cookie", "")
    assert access_cookie_name() in set_cookie
    assert "HttpOnly" in set_cookie or "httponly" in set_cookie.lower()
    assert "tok-value" in set_cookie

    clear_access_cookie(resp)


def test_login_sets_httpOnly_cookie_and_me_via_cookie():
    import base64
    import json
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding
    from app.auth_crypto import _private_key
    from app.config.settings import settings

    emp_id = "888877"
    _, password = _ensure_user(emp_id)

    prev_env, prev_flag = settings.APP_ENV, settings.CAPTCHA_ENABLED
    settings.APP_ENV = "dev"
    settings.CAPTCHA_ENABLED = "false"

    def encrypt_creds(payload: dict) -> str:
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

    try:
        cipher = encrypt_creds({"empId": emp_id, "password": password})
        resp = client.post("/api/v1/auth/login", json={"cipher": cipher})
        assert resp.status_code == 200, resp.text
        assert "access_token" in resp.json()
        assert client.cookies.get("rc_access") or any(
            "rc_access" in (c or "") for c in resp.headers.get_list("set-cookie")
        )

        # Cookie auth (TestClient keeps cookies)
        me = client.get("/api/v1/auth/me")
        assert me.status_code == 200
        assert me.json()["empId"] == emp_id

        out = client.post("/api/v1/auth/logout")
        assert out.status_code == 200
        me2 = client.get("/api/v1/auth/me")
        assert me2.status_code == 401
    finally:
        settings.APP_ENV = prev_env
        settings.CAPTCHA_ENABLED = prev_flag


def test_realtime_hub_publish():
    from app.realtime.hub import RealtimeHub

    class FakeWs:
        def __init__(self):
            self.messages = []

        async def send_json(self, msg):
            self.messages.append(msg)

    async def run():
        h = RealtimeHub()
        ws = FakeWs()
        # bypass accept
        h._rooms.setdefault(42, set()).add(ws)
        await h.publish(42, {"type": "notification", "item": {"id": 1}})
        assert ws.messages and ws.messages[0]["type"] == "notification"

    asyncio.run(run())


def test_session_create_and_revoke():
    from datetime import datetime, timedelta, timezone
    from app.auth.sessions import create_session, is_jti_active, revoke_jti
    import secrets

    uid, _ = _ensure_user("888866")
    jti = secrets.token_urlsafe(16)
    create_session(
        user_id=uid,
        access_jti=jti,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    assert is_jti_active(jti, uid)
    revoke_jti(jti)
    assert not is_jti_active(jti, uid)
