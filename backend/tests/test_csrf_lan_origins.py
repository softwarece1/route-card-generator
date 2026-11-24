"""CSRF / CORS allow private LAN IP origins for server hosting."""

from __future__ import annotations

import sys
from pathlib import Path

from starlette.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config.settings import origin_is_allowed, settings
from app.main import app

client = TestClient(app)


def test_origin_is_allowed_localhost_and_lan_ip():
    assert origin_is_allowed("http://localhost:5174")
    assert origin_is_allowed("http://127.0.0.1:5174")
    assert origin_is_allowed("http://172.16.69.164:5174")
    assert origin_is_allowed("http://172.195.126.179:5174")  # non-RFC1918 server IP
    assert origin_is_allowed("http://192.168.1.10:8003")
    assert origin_is_allowed("http://10.0.0.5")
    assert not origin_is_allowed("http://evil-attacker.com")
    assert not origin_is_allowed("https://example.com")


def test_cors_reflects_lan_ip_origin():
    origin = "http://172.195.126.179:5174"
    resp = client.get("/health", headers={"Origin": origin})
    assert resp.status_code == 200
    assert resp.headers.get("access-control-allow-origin") == origin
    assert resp.headers.get("access-control-allow-credentials") == "true"


def test_csrf_allows_lan_ip_origin_with_cookie():
    from app.auth.cookies import access_cookie_name

    name = access_cookie_name()
    origin = "http://172.195.126.179:5174"
    # Mutating request with cookie + LAN Origin must not 403 on CSRF
    resp = client.post(
        "/api/v1/route-card/signup-approvals/1/approve",
        headers={"Origin": origin},
        cookies={name: "dummy-token"},
        json={"remark": ""},
    )
    # May be 401/404/422 from auth/business logic — but not CSRF 403
    assert resp.status_code != 403 or "Origin not allowed" not in str(resp.json())


def test_csrf_still_blocks_public_evil_origin():
    from app.auth.cookies import access_cookie_name

    prev = settings.CORS_ALLOW_PRIVATE_NETWORK
    settings.CORS_ALLOW_PRIVATE_NETWORK = True
    try:
        name = access_cookie_name()
        resp = client.post(
            "/api/v1/route-card/signup-approvals/1/approve",
            headers={"Origin": "http://evil-attacker.com"},
            cookies={name: "dummy-token"},
            json={"remark": ""},
        )
        assert resp.status_code == 403
        assert "Origin not allowed" in str(resp.json().get("detail") or resp.json())
    finally:
        settings.CORS_ALLOW_PRIVATE_NETWORK = prev


if __name__ == "__main__":
    test_origin_is_allowed_localhost_and_lan_ip()
    test_cors_reflects_lan_ip_origin()
    test_csrf_allows_lan_ip_origin_with_cookie()
    test_csrf_still_blocks_public_evil_origin()
    print("test_csrf_lan_origins: OK")
