"""JWT auth with DB users — signup (empId, name, password) + login."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from pony.orm import db_session, select
from pydantic import BaseModel, Field

from app.config.settings import settings
from app.route_card.models import RcDepartment, RcUser
from app.security import hash_password, verify_password

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])
security = HTTPBearer(auto_error=False)


class SignupRequest(BaseModel):
    empId: str = Field(..., min_length=1, max_length=64)
    name: str = Field(..., min_length=1, max_length=255)
    dept: str = Field(..., min_length=1, max_length=128)
    password: str = Field(..., min_length=4, max_length=128)


class LoginRequest(BaseModel):
    empId: str = Field(..., min_length=1, max_length=64)
    password: str = Field(..., min_length=1, max_length=128)


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: dict


def _normalize_emp_id(raw: str) -> str:
    return (raw or "").strip()


def _user_public(user: RcUser) -> dict:
    return {
        "id": user.id,
        "empId": user.emp_id,
        "username": user.emp_id,  # backward compatible with UI
        "name": user.name,
        "display_name": user.name,
        "dept": user.dept or "",
        "role": user.role,
    }


def create_access_token(*, emp_id: str, role: str, user_id: int) -> str:
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES
    )
    payload = {
        "sub": emp_id,
        "role": role,
        "uid": user_id,
        "exp": expire,
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    except JWTError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        ) from e


@db_session
def _get_user_by_emp_id(emp_id: str) -> RcUser | None:
    return RcUser.get(emp_id=_normalize_emp_id(emp_id))


@db_session
def _get_user_by_id(user_id: int) -> RcUser | None:
    return RcUser.get(id=user_id)


def get_current_user(
    creds: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> dict:
    if not settings.AUTH_ENABLED:
        return {
            "id": 0,
            "empId": "dev",
            "username": "dev",
            "name": "Dev",
            "display_name": "Dev",
            "dept": "IT",
            "role": "admin",
        }

    if not creds or not creds.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )

    data = decode_token(creds.credentials)
    emp_id = data.get("sub")
    user_id = data.get("uid")
    with db_session:
        user = None
        if user_id:
            user = RcUser.get(id=int(user_id))
        if not user and emp_id:
            user = RcUser.get(emp_id=str(emp_id))
        if not user or not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User not found or inactive",
            )
        return _user_public(user)


def require_admin(current_user: dict = Depends(get_current_user)) -> dict:
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return current_user


def require_dept_head_or_admin(current_user: dict = Depends(get_current_user)) -> dict:
    if current_user.get("role") not in {"admin", "dept_head"}:
        raise HTTPException(
            status_code=403, detail="Department head or admin access required"
        )
    return current_user


@router.get("/departments")
@db_session
def list_departments():
    """Public department master for signup dropdown."""
    rows = select(d for d in RcDepartment if d.is_active).order_by(
        RcDepartment.sort_order, RcDepartment.name
    )[:]
    return [
        {"id": d.id, "code": d.code, "name": d.name, "label": d.name, "value": d.name}
        for d in rows
    ]


@router.get("/emp-status/{emp_id}")
@db_session
def emp_status(emp_id: str):
    """
    Public signup helper: whether empId is already registered.
    No Employee Master exists in this app — name/dept stay user-entered.
    """
    normalized = _normalize_emp_id(emp_id)
    if not normalized:
        return {
            "empId": "",
            "registered": False,
            "available": False,
            "verified": False,
            "employee": None,
        }
    existing = RcUser.get(emp_id=normalized)
    return {
        "empId": normalized,
        "registered": bool(existing),
        "available": not bool(existing),
        "verified": False,
        "employee": None,
    }


@router.post("/signup", response_model=LoginResponse)
@db_session
def signup(body: SignupRequest):
    emp_id = _normalize_emp_id(body.empId)
    name = (body.name or "").strip()
    dept = (body.dept or "").strip()
    if not emp_id or not name:
        raise HTTPException(400, "empId and name are required")
    if not dept:
        raise HTTPException(400, "dept is required")

    master = select(d for d in RcDepartment if d.is_active and d.name == dept)[:1]
    if not master:
        raise HTTPException(400, "Select a valid department")

    if RcUser.get(emp_id=emp_id):
        raise HTTPException(400, f"Employee ID '{emp_id}' is already registered")

    user = RcUser(
        emp_id=emp_id,
        name=name,
        dept=dept,
        password_hash=hash_password(body.password),
        role="engineer",
        is_active=True,
    )
    from pony.orm import commit

    commit()
    token = create_access_token(emp_id=user.emp_id, role=user.role, user_id=user.id)
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": _user_public(user),
    }


@router.post("/login", response_model=LoginResponse)
@db_session
def login(body: LoginRequest):
    emp_id = _normalize_emp_id(body.empId)
    user = RcUser.get(emp_id=emp_id)
    if not user or not user.is_active or not verify_password(body.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid empId or password",
        )
    token = create_access_token(emp_id=user.emp_id, role=user.role, user_id=user.id)
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": _user_public(user),
    }


@router.get("/me")
def me(current_user: dict = Depends(get_current_user)):
    return current_user
