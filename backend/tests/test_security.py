"""Security, VAPT compliance, and vulnerability remediation tests."""
import io
import pytest
from starlette.testclient import TestClient

from app.main import app
from app.config.settings import settings
from app.captcha import generate_captcha, verify_captcha
from app.password_policy import validate_password_complexity
from fastapi import HTTPException, UploadFile
from app.route_card.service import read_upload
import asyncio

client = TestClient(app)

def test_security_headers_present():
    """Verify essential VAPT security headers are returned on all responses."""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.headers.get("X-Content-Type-Options") == "nosniff"
    assert response.headers.get("X-Frame-Options") == "DENY"
    assert response.headers.get("Referrer-Policy") == "no-referrer"
    assert "Content-Security-Policy" in response.headers
    assert "default-src 'self'" in response.headers["Content-Security-Policy"]


def test_cors_headers_strict():
    """Verify CORS restricts allowed origins and does not expose wildcard."""
    # Request from configured origin
    origin = settings.CORS_ORIGINS[0] if settings.CORS_ORIGINS else "http://localhost:5173"
    response = client.get("/health", headers={"Origin": origin})
    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == origin

    # Request from untrusted origin
    untrusted = "http://evil-attacker.com"
    response = client.get("/health", headers={"Origin": untrusted})
    assert response.headers.get("access-control-allow-origin") != untrusted


def test_captcha_generation_and_verification():
    """Verify CAPTCHA challenge creation, format, single-use, and attempt limit."""
    cid, img_bytes = generate_captcha()
    assert cid and len(cid) > 8
    assert img_bytes.startswith(b"\x89PNG")  # Valid PNG signature

    # Verify via endpoint
    resp = client.get("/api/v1/auth/captcha")
    assert resp.status_code == 200
    data = resp.json()
    assert "captchaId" in data
    assert "imageData" in data
    assert data["imageData"].startswith("data:image/png;base64,")

    # Invalidate after excessive attempts
    cid2, _ = generate_captcha()
    for _ in range(getattr(settings, "CAPTCHA_ATTEMPT_LIMIT", 5)):
        verify_captcha(cid2, "WRONG")
    # Exceeded attempt limit
    assert verify_captcha(cid2, "WRONG") is False


def test_password_policy_enforcement():
    """Verify password policy checks: min 12 chars, complexity, dictionary."""
    # Too short (<12)
    with pytest.raises(HTTPException) as exc:
        validate_password_complexity("Abc1!")
    assert exc.value.status_code == 400
    assert "at least 12 characters" in exc.value.detail

    # Missing uppercase
    with pytest.raises(HTTPException) as exc:
        validate_password_complexity("lowercase123!@#")
    assert "uppercase" in exc.value.detail

    # Missing lowercase
    with pytest.raises(HTTPException) as exc:
        validate_password_complexity("UPPERCASE123!@#")
    assert "lowercase" in exc.value.detail

    # Missing digit
    with pytest.raises(HTTPException) as exc:
        validate_password_complexity("NoDigitsHere!@#")
    assert "digit" in exc.value.detail

    # Missing special char
    with pytest.raises(HTTPException) as exc:
        validate_password_complexity("NoSpecialChar123")
    assert "special character" in exc.value.detail

    # Breached / common password
    with pytest.raises(HTTPException) as exc:
        validate_password_complexity("Password123!")
    assert "too common" in exc.value.detail

    # Passwords containing spaces (internal, leading, trailing, tabs)
    for bad_pwd in ["Admin1 @2345678", " Admin12345678!", "Admin12345678! ", "Admin1\t2345678!"]:
        with pytest.raises(HTTPException) as exc:
            validate_password_complexity(bad_pwd)
        assert exc.value.status_code == 400
        assert "spaces or whitespace" in exc.value.detail

    # Multiple requirements failed together (e.g. 'admin')
    with pytest.raises(HTTPException) as exc:
        validate_password_complexity("admin")
    assert "at least 12 characters" in exc.value.detail
    assert "uppercase" in exc.value.detail
    assert "digit" in exc.value.detail
    assert "special character" in exc.value.detail

    # Valid complex password
    validate_password_complexity("StrongSecurePass2026!#")


def test_password_history_prevent_reuse():
    """Verify that password history checks prevent reusing current and recent passwords."""
    from app.password_policy import check_password_history
    from app.security import hash_password

    class MockHistoryItem:
        def __init__(self, pwd):
            self.password_hash = hash_password(pwd)

    class MockUserWithHistory:
        def __init__(self, current_pwd, past_pwds):
            self.password_hash = hash_password(current_pwd)
            self._past = [MockHistoryItem(p) for p in past_pwds]

        @property
        def password_history(self):
            class Query:
                def __init__(self, items):
                    self.items = items
                def select(self):
                    return self
                def order_by(self, *args):
                    return self
                def __getitem__(self, sl):
                    return self.items[sl]
            return Query(self._past)

    user = MockUserWithHistory(
        current_pwd="CurrentPass2026!#",
        past_pwds=["OldPassOne2025!#", "OldPassTwo2025!#", "OldPassThree2025!#"],
    )

    # Reusing current/temporary password must be rejected
    with pytest.raises(HTTPException) as exc:
        check_password_history(user, "CurrentPass2026!#")
    assert exc.value.status_code == 400
    assert "current or temporary password" in exc.value.detail

    # Reusing any recent password in history must be rejected
    for past_pwd in ["OldPassOne2025!#", "OldPassTwo2025!#", "OldPassThree2025!#"]:
        with pytest.raises(HTTPException) as exc:
            check_password_history(user, past_pwd)
        assert exc.value.status_code == 400
        assert "cannot reuse" in exc.value.detail

    # A brand new strong password passes without exception
    check_password_history(user, "BrandNewSecurePass2026!#")




def test_upload_file_hardening():
    """Verify upload validation rejects dangerous extensions, invalid MIME, and invalid headers."""
    # Test double extension rejection
    dummy_exe = UploadFile(
        filename="drawing.pdf.exe",
        file=io.BytesIO(b"%PDF-1.5 test"),
        headers={"content-type": "application/pdf"},
    )
    with pytest.raises(HTTPException) as exc:
        asyncio.run(read_upload(dummy_exe, role="drawing"))
    assert exc.value.status_code == 400
    assert "multiple or dangerous" in exc.value.detail

    # Test PDF header magic check
    fake_pdf = UploadFile(
        filename="test.pdf",
        file=io.BytesIO(b"NOT_A_REAL_PDF_DATA"),
        headers={"content-type": "application/pdf"},
    )
    with pytest.raises(HTTPException) as exc:
        asyncio.run(read_upload(fake_pdf, role="drawing"))
    assert exc.value.status_code == 400
    assert "Invalid PDF file header" in exc.value.detail

    # Test MIME mismatch
    mismatch_file = UploadFile(
        filename="test.pdf",
        file=io.BytesIO(b"%PDF-1.5 valid"),
        headers={"content-type": "application/x-msdownload"},
    )
    with pytest.raises(HTTPException) as exc:
        asyncio.run(read_upload(mismatch_file, role="drawing"))
    assert exc.value.status_code == 400
    assert "MIME type mismatch" in exc.value.detail


def test_jwt_session_idle_and_revocation():
    """Verify JWT contains jti, revocation prevents access, and logout invalidates token."""
    from app.auth import create_access_token, decode_token, _revoked_tokens
    token = create_access_token(emp_id="999999", role="engineer", user_id=999)
    payload = decode_token(token)
    assert "jti" in payload
    assert len(payload["jti"]) > 10

    # Test logout endpoint
    resp = client.post("/api/v1/auth/logout", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert payload["jti"] in _revoked_tokens

    # Accessing protected route with revoked token should be rejected
    resp = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401
    assert "revoked" in resp.json()["detail"].lower()


def test_login_captcha_scenarios():
    """Verify all CAPTCHA scenarios during login:
    1. Refresh CAPTCHA changes image and ID
    2. Missing CAPTCHA blocked
    3. Incorrect CAPTCHA rejected
    4. Expired/reused CAPTCHA rejected
    5. Valid CAPTCHA with wrong credentials rejected safely
    6. Valid CAPTCHA with valid credentials succeeds
    """
    import base64
    import json
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding
    from app.auth_crypto import _private_key
    from app.captcha import _captcha_cache
    from app.database.connection import connect_to_db

    connect_to_db()

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

    # 1. Refresh CAPTCHA changes image and ID
    r1 = client.get("/api/v1/auth/captcha")
    assert r1.status_code == 200
    c1 = r1.json()

    r2 = client.get("/api/v1/auth/captcha")
    assert r2.status_code == 200
    c2 = r2.json()

    assert c1["captchaId"] != c2["captchaId"]

    # 2. Submit login without CAPTCHA -> blocked (401 CAPTCHA required)
    cipher_no_captcha = encrypt_creds({"empId": "admin", "password": "admin123"})
    resp = client.post("/api/v1/auth/login", json={"cipher": cipher_no_captcha})
    assert resp.status_code == 401
    assert "CAPTCHA required" in resp.json()["detail"]

    # 3. Submit login with incorrect CAPTCHA -> rejected (401 Invalid or expired CAPTCHA)
    resp = client.post(
        "/api/v1/auth/login",
        json={
            "cipher": cipher_no_captcha,
            "captchaId": c1["captchaId"],
            "captchaAnswer": "INCORRECT",
        },
    )
    assert resp.status_code == 401
    assert "Invalid or expired CAPTCHA" in resp.json()["detail"]

    # 4. Submit login with valid CAPTCHA and incorrect credentials -> rejected (401 Invalid empId or password)
    r3 = client.get("/api/v1/auth/captcha")
    c3 = r3.json()
    valid_code3 = _captcha_cache[c3["captchaId"]]["code"]

    cipher_wrong_pass = encrypt_creds({"empId": "admin", "password": "WrongPassword!@#123"})
    resp = client.post(
        "/api/v1/auth/login",
        json={
            "cipher": cipher_wrong_pass,
            "captchaId": c3["captchaId"],
            "captchaAnswer": valid_code3,
        },
    )
    assert resp.status_code == 401
    assert "Invalid empId or password" in resp.json()["detail"]

    # 5. Reusing the consumed CAPTCHA -> rejected (401 Invalid or expired CAPTCHA)
    resp = client.post(
        "/api/v1/auth/login",
        json={
            "cipher": cipher_wrong_pass,
            "captchaId": c3["captchaId"],
            "captchaAnswer": valid_code3,
        },
    )
    assert resp.status_code == 401
    assert "Invalid or expired CAPTCHA" in resp.json()["detail"]

    # 6. Submit login with valid CAPTCHA and valid credentials -> 200, returns token & user
    from app.route_card.models import RcUser
    from app.security import hash_password
    from pony.orm import db_session, commit
    with db_session:
        u = RcUser.get(emp_id="999999")
        if not u:
            RcUser(
                emp_id="999999",
                name="Security Test User",
                dept="Software",
                password_hash=hash_password("TestSecurePass2026!#"),
                role="engineer",
                is_active=True,
            )
        else:
            u.password_hash = hash_password("TestSecurePass2026!#")
            u.is_active = True
        commit()

    # Clear any prior active session so first login is not a concurrent conflict
    from app.auth import _active_sessions, _pending_session_takeovers

    with db_session:
        test_user = RcUser.get(emp_id="999999")
        if test_user:
            _active_sessions.pop(test_user.id, None)

    r4 = client.get("/api/v1/auth/captcha")
    c4 = r4.json()
    valid_code4 = _captcha_cache[c4["captchaId"]]["code"]

    cipher_valid = encrypt_creds({"empId": "999999", "password": "TestSecurePass2026!#"})
    resp = client.post(
        "/api/v1/auth/login",
        json={
            "cipher": cipher_valid,
            "captchaId": c4["captchaId"],
            "captchaAnswer": valid_code4,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "access_token" in body
    assert body["user"]["empId"] == "999999"

    # 7. Second login without takeover → 409 concurrent session + resumeToken
    r5 = client.get("/api/v1/auth/captcha")
    c5 = r5.json()
    valid_code5 = _captcha_cache[c5["captchaId"]]["code"]
    resp = client.post(
        "/api/v1/auth/login",
        json={
            "cipher": cipher_valid,
            "captchaId": c5["captchaId"],
            "captchaAnswer": valid_code5,
        },
    )
    assert resp.status_code == 409
    detail = resp.json()["detail"]
    assert detail["code"] == "CONCURRENT_SESSION"
    assert detail.get("resumeToken")

    # 8. Takeover ends prior session and issues a new token
    old_token = body["access_token"]
    resp = client.post(
        "/api/v1/auth/login/takeover",
        json={"resumeToken": detail["resumeToken"]},
    )
    assert resp.status_code == 200
    assert resp.json()["replacedSession"] is True
    new_token = resp.json()["access_token"]
    assert new_token != old_token

    me_old = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {old_token}"})
    assert me_old.status_code == 401
    me_new = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {new_token}"})
    assert me_new.status_code == 200
    _pending_session_takeovers.clear()

