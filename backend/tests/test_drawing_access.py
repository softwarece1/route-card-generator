"""Legacy drawing routes are limited to the owner."""

from starlette.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_other_user_cannot_download_drawing():
    from pony.orm import commit, db_session

    from app.auth import create_access_token
    from app.database.connection import connect_to_db
    from app.route_card.models import RcUser
    from app.route_card.service import create_drawing
    from app.security import hash_password

    connect_to_db()
    password = hash_password("TestSecurePass2026!#")
    with db_session:
        owner = RcUser.get(emp_id="888001")
        if not owner:
            owner = RcUser(
                emp_id="888001",
                name="Drawing Owner",
                sbu="Software",
                password_hash=password,
                role="engineer",
                is_active=True,
            )
        other = RcUser.get(emp_id="888002")
        if not other:
            other = RcUser(
                emp_id="888002",
                name="Drawing Other",
                sbu="Software",
                password_hash=password,
                role="engineer",
                is_active=True,
            )
        commit()
        owner_id, other_id = owner.id, other.id

    created = create_drawing(
        b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF",
        "owned.pdf",
        ".pdf",
        uploaded_by="888001",
        user={"id": owner_id, "empId": "888001", "role": "engineer"},
    )
    drawing_id = created["id"]
    owner_token = create_access_token(emp_id="888001", role="engineer", user_id=owner_id)
    other_token = create_access_token(emp_id="888002", role="engineer", user_id=other_id)

    denied = client.get(
        f"/api/v1/route-card/drawings/{drawing_id}/file",
        headers={"Authorization": f"Bearer {other_token}"},
    )
    assert denied.status_code == 403

    allowed = client.get(
        f"/api/v1/route-card/drawings/{drawing_id}/file",
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert allowed.status_code == 200
    assert allowed.content.startswith(b"%PDF")
