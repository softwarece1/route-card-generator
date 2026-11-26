"""API gate: a file that fails BEL-structure validation is rejected with 422 and never stored."""

from __future__ import annotations

from pathlib import Path

import pytest
from pony.orm import db_session, select

from app.route_card.models import RcDocument

pytestmark = [pytest.mark.vnv, pytest.mark.workflow]

SAMPLES = Path(__file__).resolve().parents[3] / "sample_drawings" / "night_vision_camera"
GA_PDF = SAMPLES / "112199000101 - GA.pdf"
PL_XLSX = SAMPLES / "112199000101 - PL.xlsx"
WL_XLSX = SAMPLES / "112199000101 - WL.xlsx"

UPLOAD = "/api/v1/route-card/sessions/{sid}/documents/{role}"


def _sample(path: Path) -> bytes:
    if not path.is_file():
        pytest.skip(f"sample missing: {path}")
    return path.read_bytes()


def _new_session(vnv_client, auth_header) -> int:
    resp = vnv_client.post("/api/v1/route-card/sessions", headers=auth_header("engineer"))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    return int(body.get("id") or body.get("sessionId"))


def _docs_for(session_id: int, role: str) -> list[tuple[int, str]]:
    with db_session:
        rows = select(
            (d.id, d.filename)
            for d in RcDocument
            if d.session.id == session_id and d.role == role
        )[:]
    return list(rows)


def test_wrong_content_rejected_with_422_and_nothing_stored(vnv_client, auth_header):
    sid = _new_session(vnv_client, auth_header)
    # WL workbook uploaded into the Parts List slot: extension is valid, content is not.
    resp = vnv_client.post(
        UPLOAD.format(sid=sid, role="partslist"),
        headers=auth_header("engineer"),
        files={"file": (WL_XLSX.name, _sample(WL_XLSX), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert resp.status_code == 422, resp.text
    assert "Wire List" in resp.json().get("detail", "")
    assert _docs_for(sid, "partslist") == []


def test_rejected_upload_keeps_existing_parts_list(vnv_client, auth_header):
    sid = _new_session(vnv_client, auth_header)
    xlsx_mime = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    ok = vnv_client.post(
        UPLOAD.format(sid=sid, role="partslist"),
        headers=auth_header("engineer"),
        files={"file": (PL_XLSX.name, _sample(PL_XLSX), xlsx_mime)},
    )
    assert ok.status_code == 200, ok.text
    before = _docs_for(sid, "partslist")
    assert len(before) == 1

    bad = vnv_client.post(
        UPLOAD.format(sid=sid, role="partslist"),
        headers=auth_header("engineer"),
        files={"file": (GA_PDF.name, _sample(GA_PDF), "application/pdf")},
    )
    assert bad.status_code == 422, bad.text
    # The good PL must survive: validation runs before the single-slot replace.
    assert _docs_for(sid, "partslist") == before
