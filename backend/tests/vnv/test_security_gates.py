"""Security regression gates for V&V (CSRF smoke + Bandit medium+)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from app.config.settings import settings

pytestmark = [pytest.mark.vnv, pytest.mark.security]


def test_csrf_blocks_evil_origin(vnv_client, auth_header):
    """TEST-SEC-CSRF — REQ-SEC-02"""
    from app.auth.cookies import access_cookie_name

    headers = auth_header("admin")
    token = headers["Authorization"].split(" ", 1)[1]
    name = access_cookie_name()
    try:
        resp = vnv_client.post(
            "/api/v1/route-card/sessions",
            cookies={name: token},
            headers={
                "Origin": "http://evil-attacker.example",
                "Content-Type": "application/json",
            },
        )
        # CSRF middleware should reject cross-site cookie POSTs
        assert resp.status_code in (403, 401)
    finally:
        vnv_client.cookies.clear()


def test_bandit_medium_clean(tmp_path):
    """TEST-SEC-BANDIT — REQ-SEC-04"""
    app_root = Path(__file__).resolve().parents[2] / "app"
    out = tmp_path / "bandit.json"
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "bandit",
            "-r",
            str(app_root),
            "-f",
            "json",
            "-o",
            str(out),
            "-ll",
            "-ii",
            "-q",
        ],
        capture_output=True,
        text=True,
        cwd=str(app_root.parent),
        check=False,
    )
    if not out.exists():
        pytest.fail(
            f"Bandit wrote no file: rc={proc.returncode} err={proc.stderr[:500]}"
        )
    data = json.loads(out.read_text(encoding="utf-8"))
    results = data.get("results") or []
    assert results == [], f"Bandit medium+ findings: {results[:3]}"
