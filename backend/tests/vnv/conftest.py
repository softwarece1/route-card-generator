"""Shared V&V personas: admin, sbu_head, dept_head, engineer (PMG), engineer_ied."""

from __future__ import annotations

import pytest
from pony.orm import commit, db_session, select
from starlette.testclient import TestClient

from app.auth import create_access_token
from app.database.connection import connect_to_db
from app.main import app
from app.route_card.models import RcDepartment, RcSbu, RcUser
from app.security import hash_password

VNV_PASSWORD = "VnVTestPass2026!#Aa"
SBU_NAME = "Software"

# Distinct 6-digit emp IDs reserved for V&V fixtures
PERSONAS = {
    "admin": {"emp_id": "810001", "role": "admin", "dept": "PMG"},
    "sbu_head": {"emp_id": "810002", "role": "sbu_head", "dept": "PMG"},
    "dept_head": {"emp_id": "810003", "role": "dept_head", "dept": "PMG"},
    "engineer": {"emp_id": "810004", "role": "engineer", "dept": "PMG"},
    "engineer_ied": {"emp_id": "810005", "role": "engineer", "dept": "IED"},
}


@pytest.fixture(scope="session")
def vnv_client():
    return TestClient(app)


@pytest.fixture(scope="session")
def vnv_db():
    connect_to_db()
    return True


@pytest.fixture(scope="session")
def vnv_sbu(vnv_db):
    with db_session:
        sbu = select(x for x in RcSbu if x.name == SBU_NAME)[:1]
        if not sbu:
            sbu = RcSbu(
                code="SFT_VNV",
                name=SBU_NAME,
                plant_id="1110",
                is_active=True,
                sort_order=50,
            )
            commit()
            sbu_id = sbu.id
        else:
            sbu = sbu[0]
            if not sbu.is_active:
                sbu.is_active = True
                commit()
            sbu_id = sbu.id
    return {"id": sbu_id, "name": SBU_NAME}


@pytest.fixture(scope="session")
def vnv_departments(vnv_sbu):
    out = {}
    with db_session:
        sbu = RcSbu.get(id=vnv_sbu["id"])
        for code in ("PMG", "IED"):
            dept = select(
                d for d in RcDepartment if d.sbu.id == sbu.id and d.code == code
            )[:1]
            if not dept:
                dept = RcDepartment(
                    sbu=sbu,
                    code=code,
                    name=code,
                    is_active=True,
                    sort_order=10 if code == "PMG" else 20,
                )
                commit()
                out[code] = dept.id
            else:
                dept = dept[0]
                if not dept.is_active:
                    dept.is_active = True
                    commit()
                out[code] = dept.id
    return out


@pytest.fixture(scope="session")
def vnv_users(vnv_sbu, vnv_departments):
    """Ensure persona users exist; return {persona: {id, emp_id, role, isIedDept}}."""
    pw = hash_password(VNV_PASSWORD)
    result = {}
    with db_session:
        for key, spec in PERSONAS.items():
            dept = RcDepartment.get(id=vnv_departments[spec["dept"]])
            user = RcUser.get(emp_id=spec["emp_id"])
            if not user:
                user = RcUser(
                    emp_id=spec["emp_id"],
                    name=f"V&V {key}",
                    sbu=vnv_sbu["name"],
                    department=dept,
                    password_hash=pw,
                    role=spec["role"],
                    is_active=True,
                    approval_status="approved",
                    must_change_password=False,
                )
            else:
                user.name = f"V&V {key}"
                user.sbu = vnv_sbu["name"]
                user.department = dept
                user.password_hash = pw
                user.role = spec["role"]
                user.is_active = True
                user.approval_status = "approved"
                user.must_change_password = False
            commit()
            result[key] = {
                "id": user.id,
                "emp_id": user.emp_id,
                "role": user.role,
                "dept": spec["dept"],
                "isIedDept": spec["dept"] == "IED",
                "password": VNV_PASSWORD,
            }
    return result


@pytest.fixture
def auth_header(vnv_users):
    """Mint a fresh bearer token per call (avoids JTI revoke collisions across tests)."""

    def _hdr(persona: str) -> dict:
        meta = vnv_users[persona]
        token = create_access_token(
            emp_id=meta["emp_id"],
            role=meta["role"],
            user_id=meta["id"],
        )
        return {"Authorization": f"Bearer {token}"}

    return _hdr


@pytest.fixture(autouse=True)
def _captcha_off_for_vnv(vnv_client):
    from app.config.settings import settings

    prev_env, prev_flag = settings.APP_ENV, settings.CAPTCHA_ENABLED
    settings.APP_ENV = "dev"
    settings.CAPTCHA_ENABLED = "false"
    vnv_client.cookies.clear()
    yield
    settings.APP_ENV = prev_env
    settings.CAPTCHA_ENABLED = prev_flag
    vnv_client.cookies.clear()
