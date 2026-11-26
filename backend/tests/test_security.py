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


def _cookie_token(resp) -> str:
    from app.auth.cookies import access_cookie_name

    name = access_cookie_name()
    for header in resp.headers.get_list("set-cookie"):
        part = header.split(";", 1)[0]
        key, _, val = part.partition("=")
        if key.strip() == name and val.strip():
            return val.strip()
    raise AssertionError(f"missing {name} cookie")

def test_security_headers_present():
    """Verify essential VAPT security headers are returned on all responses."""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert response.headers.get("X-Content-Type-Options") == "nosniff"
    assert response.headers.get("X-Frame-Options") == "DENY"
    assert response.headers.get("Referrer-Policy") == "no-referrer"
    assert "Content-Security-Policy" in response.headers
    csp = response.headers["Content-Security-Policy"]
    assert "default-src 'self'" in csp
    assert "script-src 'self'" in csp
    assert "unsafe-eval" not in csp
    assert "base-uri 'self'" in csp
    assert "object-src 'none'" in csp
    assert "form-action 'self'" in csp
    # PrimeReact still needs inline styles; scripts must not.
    assert "style-src 'self' 'unsafe-inline'" in csp
    assert "script-src 'self' 'unsafe-inline'" not in csp


def test_cors_headers_strict():
    """Verify CORS restricts allowed origins and does not expose wildcard."""
    # Request from configured origin
    origin = settings.CORS_ORIGINS[0] if settings.CORS_ORIGINS else "http://localhost:5173"
    response = client.get("/health", headers={"Origin": origin})
    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == origin
    assert response.headers.get("access-control-allow-credentials") == "true"

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
    from app.auth import create_access_token, decode_token
    from app.auth.sessions import is_jti_active
    from app.database.connection import connect_to_db
    from app.route_card.models import RcUser
    from app.security import hash_password
    from pony.orm import db_session, commit

    connect_to_db()
    with db_session:
        u = RcUser.get(emp_id="999998")
        if not u:
            u = RcUser(emp_id="999998",
                name="JWT Revoke Test",
                sbu="Software",
                password_hash=hash_password("TestSecurePass2026!#"),
                role="engineer",
                is_active=True,
            )
        else:
            u.is_active = True
        commit()
        uid = u.id

    token = create_access_token(emp_id="999998", role="engineer", user_id=uid)
    payload = decode_token(token)
    assert "jti" in payload
    assert len(payload["jti"]) > 10
    assert is_jti_active(payload["jti"], uid)

    resp = client.post("/api/v1/auth/logout", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert not is_jti_active(payload["jti"], uid)

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
    import app.captcha as captcha_mod

    orig_random_code = captcha_mod._random_code
    captcha_mod._random_code = lambda length=6: "AB12CD"
    from app.database.connection import connect_to_db

    connect_to_db()
    from app.config.settings import settings

    prev_env, prev_flag = settings.APP_ENV, settings.CAPTCHA_ENABLED
    settings.APP_ENV = "prod"
    settings.CAPTCHA_ENABLED = ""

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
    valid_code3 = "AB12CD"

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
            RcUser(emp_id="999999",
                name="Security Test User",
                sbu="Software",
                password_hash=hash_password("TestSecurePass2026!#"),
                role="engineer",
                is_active=True,
            )
        else:
            u.password_hash = hash_password("TestSecurePass2026!#")
            u.is_active = True
        commit()

    # Clear any prior active session so first login is not a concurrent conflict
    from app.auth.sessions import _pending_session_takeovers, revoke_user_sessions

    with db_session:
        test_user = RcUser.get(emp_id="999999")
        if test_user:
            revoke_user_sessions(test_user.id)

    r4 = client.get("/api/v1/auth/captcha")
    c4 = r4.json()
    valid_code4 = "AB12CD"

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
    assert "access_token" not in body
    assert body["user"]["empId"] == "999999"
    old_token = _cookie_token(resp)

    # 7. Second login without takeover → 409 concurrent session + resumeToken
    r5 = client.get("/api/v1/auth/captcha")
    c5 = r5.json()
    valid_code5 = "AB12CD"
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
    resp = client.post(
        "/api/v1/auth/login/takeover",
        json={"resumeToken": detail["resumeToken"]},
    )
    assert resp.status_code == 200
    assert "access_token" not in resp.json()
    assert resp.json()["replacedSession"] is True
    new_token = _cookie_token(resp)
    assert new_token != old_token

    me_old = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {old_token}"})
    assert me_old.status_code == 401
    me_new = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {new_token}"})
    assert me_new.status_code == 200
    _pending_session_takeovers.clear()
    settings.APP_ENV = prev_env
    settings.CAPTCHA_ENABLED = prev_flag
    captcha_mod._random_code = orig_random_code


def test_emp_status_omits_registered_and_works_without_captcha_in_dev():
    """Emp-status must not expose a registered flag; CAPTCHA optional in APP_ENV=dev."""
    from app.database.connection import connect_to_db

    connect_to_db()
    prev_env = settings.APP_ENV
    prev_flag = settings.CAPTCHA_ENABLED
    settings.APP_ENV = "dev"
    settings.CAPTCHA_ENABLED = "false"
    try:
        resp = client.get("/api/v1/auth/emp-status/112233")
        assert resp.status_code == 200
        body = resp.json()
        assert "registered" not in body
        assert set(body.keys()) >= {"empId", "available", "verified"}
        assert body["empId"] == "112233"
        assert isinstance(body["available"], bool)
    finally:
        settings.APP_ENV = prev_env
        settings.CAPTCHA_ENABLED = prev_flag


def test_emp_status_requires_captcha_when_enabled():
    prev_env = settings.APP_ENV
    prev_flag = settings.CAPTCHA_ENABLED
    settings.APP_ENV = "prod"
    settings.CAPTCHA_ENABLED = "true"
    try:
        resp = client.get("/api/v1/auth/emp-status/112233")
        assert resp.status_code == 401
        assert "CAPTCHA" in resp.json()["detail"]
    finally:
        settings.APP_ENV = prev_env
        settings.CAPTCHA_ENABLED = prev_flag


def test_signup_duplicate_emp_is_generic():
    """Duplicate empId signup must not say the ID is already registered."""
    import base64
    import json
    import secrets

    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding
    from pony.orm import commit, db_session, select

    from app.auth_crypto import ALG as CREDS_ALG
    from app.auth_crypto import _private_key
    from app.database.connection import connect_to_db
    from app.route_card.models import RcDepartment, RcSbu, RcUser
    from app.security import hash_password

    connect_to_db()
    emp_id = "778899"
    with db_session:
        sbu = select(x for x in RcSbu if x.is_active)[:1]
        if not sbu:
            pytest.skip("no SBU seed data")
        sbu = sbu[0]
        dept = select(d for d in RcDepartment if d.is_active and d.sbu.id == sbu.id)[:1]
        if not dept:
            pytest.skip("no department seed data")
        dept = dept[0]
        existing = RcUser.get(emp_id=emp_id)
        if not existing:
            RcUser(
                emp_id=emp_id,
                name="Existing User",
                sbu=sbu.name,
                department=dept,
                password_hash=hash_password(f"TempPass!{secrets.token_hex(4)}12"),
                role="engineer",
                is_active=True,
                approval_status="approved",
            )
            commit()
        dept_id = dept.id
        sbu_name = sbu.name

    pub = _private_key().public_key()
    raw = json.dumps(
        {"empId": emp_id, "password": f"ComplexPass!{secrets.token_hex(4)}"}
    ).encode("utf-8")
    cipher = base64.b64encode(
        pub.encrypt(
            raw,
            padding.OAEP(
                mgf=padding.MGF1(algorithm=hashes.SHA256()),
                algorithm=hashes.SHA256(),
                label=None,
            ),
        )
    ).decode("ascii")

    resp = client.post(
        "/api/v1/auth/signup",
        json={
            "name": "Dup Engineer",
            "sbu": sbu_name,
            "departmentId": dept_id,
            "cipher": cipher,
            "alg": CREDS_ALG,
        },
    )
    assert resp.status_code == 400
    detail = str(resp.json().get("detail", "")).lower()
    assert "already registered" not in detail
    assert "unable to complete signup" in detail


def test_oarc_to_sap_error_is_sanitized(monkeypatch):
    """Client must not receive exception internals from OARC→SAP mapping."""
    from fastapi import HTTPException

    from app.route_card.router import convert_oarc_to_sap
    from app.route_card.schemas import OarcToSapRequest

    def boom(_data):
        raise ValueError("sensitive internal mapping detail XYZ")

    monkeypatch.setattr("app.route_card.router.build_sap_payload", boom)
    with pytest.raises(HTTPException) as exc:
        convert_oarc_to_sap(OarcToSapRequest(source="test"))
    assert exc.value.status_code == 400
    assert exc.value.detail == "OARC to SAP mapping failed"
    assert "XYZ" not in str(exc.value.detail)
    assert "sensitive" not in str(exc.value.detail)

