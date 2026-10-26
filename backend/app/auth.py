"""JWT auth with DB users — signup (empId, name, password) + login."""


import re
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Request, Response, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from pony.orm import db_session, select
from pydantic import BaseModel, Field

from app.auth_crypto import ALG as CREDS_ALG
from app.auth_crypto import decrypt_creds_cipher, public_key_info
from app.config.settings import settings
from app.input_safe import require_safe
from app.route_card.models import RcDepartment, RcUser
from app.security import hash_password, verify_password
from app.middleware.rate_limit import limiter
import secrets
from typing import Set
import base64

# In‑memory revocation store (shared across workers only if using a single process)
_revoked_tokens: Set[str] = set()

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])
security = HTTPBearer(auto_error=False)

# Public / managed accounts: exactly 6 digits. Seeded admin login id is the only letter exception.
_EMP_DIGITS_RE = re.compile(r"^\d{6}$")
_ADMIN_EMP_ID = "admin"


class SignupRequest(BaseModel):
    """name/dept stay plaintext; empId+password arrive in RSA cipher."""

    name: str = Field(..., min_length=1, max_length=255)
    dept: str = Field(..., min_length=1, max_length=128)
    cipher: str = Field(..., min_length=1)
    alg: str = Field(default=CREDS_ALG, max_length=64)


class LoginRequest(BaseModel):
    cipher: str = Field(..., min_length=1)
    alg: str = Field(default=CREDS_ALG, max_length=64)
    captchaId: Optional[str] = None
    captchaAnswer: Optional[str] = None


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: dict


def _normalize_emp_id(raw: str) -> str:
    return (raw or "").strip()


def validate_employee_id(raw: str, *, allow_admin_id: bool = False) -> str:
    """
    Enforce Employee ID rules:
    - Exactly 6 digits for all normal users
    - Literal ``admin`` allowed only when allow_admin_id=True (seeded admin account)
    """
    emp_id = _normalize_emp_id(raw)
    if not emp_id:
        raise HTTPException(400, "Employee ID is required")
    if allow_admin_id and emp_id.lower() == _ADMIN_EMP_ID:
        return _ADMIN_EMP_ID
    if _EMP_DIGITS_RE.fullmatch(emp_id):
        return emp_id
    raise HTTPException(
        400,
        "Employee ID must be exactly 6 digits (e.g. 112233). "
        "Only the admin account may use a non-numeric ID.",
    )


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
    jti = secrets.token_urlsafe(16)
    payload = {
        "sub": emp_id,
        "role": role,
        "uid": user_id,
        "exp": expire,
        "jti": jti,
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
    # Check token revocation
    jti = data.get("jti")
    if jti in _revoked_tokens:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token has been revoked")
    # Existing user lookup logic follows
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

@router.post("/logout")
@db_session
def logout(creds: HTTPAuthorizationCredentials = Depends(security)):
    if not creds or not creds.credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    payload = decode_token(creds.credentials)
    jti = payload.get("jti")
    if jti:
        _revoked_tokens.add(jti)
    return {"detail": "Logged out successfully"}



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


@router.get("/public-key")
def auth_public_key():
    """SPKI PEM for encrypting empId+password before login/signup."""
    return public_key_info()


@router.post("/signup", response_model=LoginResponse)
@db_session
def signup(body: SignupRequest):
    creds = decrypt_creds_cipher(body.cipher, body.alg)
    emp_id = validate_employee_id(
        require_safe(str(creds.get("empId") or ""), "empId", field="empId"),
        allow_admin_id=False,
    )
    password = require_safe(str(creds.get("password") or ""), "password", field="password")
    from app.password_policy import validate_password_complexity
    validate_password_complexity(password)
    name = require_safe((body.name or "").strip(), "personName", field="name")
    dept = require_safe((body.dept or "").strip(), "label", field="dept")
    if not name:
        raise HTTPException(400, "name is required")
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
        password_hash=hash_password(password),
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


@router.get("/captcha")
@limiter.limit(getattr(settings, "RATE_LIMIT_CAPTCHA", "30/min"))
def get_captcha(request: Request):
    """Generate a fresh offline CAPTCHA challenge for login."""
    from app.captcha import generate_captcha
    try:
        challenge_id, png_bytes = generate_captcha()
        b64_img = base64.b64encode(png_bytes).decode("ascii")
        return {
            "captchaId": challenge_id,
            "imageData": f"data:image/png;base64,{b64_img}",
        }
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate CAPTCHA: {exc}",
        )


@router.post("/login", response_model=LoginResponse)
@limiter.limit(getattr(settings, "RATE_LIMIT_LOGIN", "5/min"))
@db_session
def login(request: Request, body: LoginRequest = Body(...)):
    creds = decrypt_creds_cipher(body.cipher, body.alg)
    emp_id = require_safe(_normalize_emp_id(str(creds.get("empId") or "")), "empId", field="empId")
    password = require_safe(str(creds.get("password") or ""), "password", field="password")
    # CAPTCHA verification – accept from decrypted credentials or top-level request body
    captcha_id = creds.get("captchaId") or body.captchaId
    captcha_answer = creds.get("captchaAnswer") or body.captchaAnswer
    if not captcha_id or not captcha_answer:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="CAPTCHA required")
    from app.captcha import verify_captcha
    if not verify_captcha(captcha_id, captcha_answer):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired CAPTCHA")
    if emp_id.lower() == _ADMIN_EMP_ID:
        emp_id = _ADMIN_EMP_ID
    user = RcUser.get(emp_id=emp_id)
    if not user or not user.is_active or not verify_password(password, user.password_hash):
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
