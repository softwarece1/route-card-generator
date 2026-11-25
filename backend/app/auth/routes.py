"""Auth HTTP routes: login / signup / logout / me / takeover / captcha (no refresh)."""

import base64
import re
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Request, Response, status
from pony.orm import commit, db_session, select
from pydantic import BaseModel, Field

from app.auth.cookies import clear_access_cookie, read_access_token, set_access_cookie
from app.auth.deps import get_current_user, user_public
from app.auth.sessions import (
    consume_takeover_resume,
    create_session,
    has_active_session,
    issue_takeover_resume,
    revoke_jti,
)
from app.auth.tokens import create_access_token as _mint_token
from app.auth.tokens import decode_token
from app.auth_crypto import ALG as CREDS_ALG
from app.auth_crypto import decrypt_creds_cipher, public_key_info
from app.config.settings import settings
from app.input_safe import require_safe
from app.middleware.rate_limit import limiter
from app.route_card.models import RcSbu, RcUser
from app.security import hash_password, verify_password

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

_EMP_DIGITS_RE = re.compile(r"^\d{6}$")
_ADMIN_EMP_ID = "admin"


class SignupRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    sbu: str = Field(..., min_length=1, max_length=128)
    cipher: str = Field(..., min_length=1)
    alg: str = Field(default=CREDS_ALG, max_length=64)


class LoginRequest(BaseModel):
    cipher: str = Field(..., min_length=1)
    alg: str = Field(default=CREDS_ALG, max_length=64)
    captchaId: Optional[str] = None
    captchaAnswer: Optional[str] = None
    terminateExistingSession: bool = False
    resumeToken: Optional[str] = None


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: dict
    replacedSession: bool = False


class SignupPendingResponse(BaseModel):
    status: str = "pending_approval"
    message: str
    user: dict


class SessionTakeoverRequest(BaseModel):
    resumeToken: str = Field(..., min_length=8, max_length=128)


class ChangePasswordRequest(BaseModel):
    currentPassword: str = Field(..., min_length=1, max_length=128)
    newPassword: str = Field(..., min_length=1, max_length=128)


def _normalize_emp_id(raw: str) -> str:
    return (raw or "").strip()


def validate_employee_id(raw: str, *, allow_admin_id: bool = False) -> str:
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


def _assert_login_allowed(user: RcUser) -> None:
    """Block pending/rejected self-signups with clear 403; then require is_active."""
    approval = (getattr(user, "approval_status", None) or "approved").strip().lower()
    if approval == "pending":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "SIGNUP_PENDING",
                "message": (
                    "Your signup is awaiting SBU head approval. "
                    "You can sign in after it is approved."
                ),
            },
        )
    if approval == "rejected":
        remark = (getattr(user, "approval_remark", None) or "").strip()
        msg = "Your signup was rejected."
        if remark:
            msg = f"{msg} Remark: {remark}"
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "SIGNUP_REJECTED",
                "message": msg,
                "remark": remark,
            },
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive",
        )


def _notify_signup_approvers(*, emp_id: str, name: str, dept: str, user_id: int) -> None:
    from app.route_card.sbus import sbu_heads_for_sbu
    from app.route_card.notifications import create_notification
    from app.route_card.models import RcUser as _RcUser
    from pony.orm import select as _select

    title = f"Signup approval: {name} ({emp_id})"
    body = f"{name} ({emp_id}) requested access for department {dept}."
    link = "/users?tab=pending"
    heads = sbu_heads_for_sbu(dept)
    notified = 0
    for h in heads:
        hid = h.get("id")
        if hid:
            create_notification(
                user_id=int(hid),
                title=title,
                body=body,
                link=link,
            )
            notified += 1
    if notified == 0:
        for admin in _select(u for u in _RcUser if u.is_active and u.role == "admin")[:]:
            create_notification(
                user_id=admin.id,
                title=title,
                body=body,
                link=link,
            )


def _client_meta(request: Optional[Request]) -> tuple:
    if request is None:
        return "", ""
    ua = (request.headers.get("user-agent") or "")[:512]
    ip = ""
    if request.client:
        ip = (request.client.host or "")[:64]
    return ua, ip


def issue_access(
    *,
    emp_id: str,
    role: str,
    user_id: int,
    response: Optional[Response] = None,
    request: Optional[Request] = None,
) -> str:
    """Mint JWT, persist session (revokes prior), optionally set cookie."""
    token, jti, expires_at = _mint_token(emp_id=emp_id, role=role, user_id=user_id)
    ua, ip = _client_meta(request)
    create_session(
        user_id=user_id,
        access_jti=jti,
        expires_at=expires_at,
        user_agent=ua,
        ip=ip,
        revoke_others=True,
    )
    if response is not None:
        set_access_cookie(response, token)
    return token


def create_access_token(*, emp_id: str, role: str, user_id: int) -> str:
    """Public helper for tests / scripts (registers DB session, no cookie)."""
    return issue_access(emp_id=emp_id, role=role, user_id=user_id)


@router.post("/logout")
@db_session
def logout(request: Request, response: Response):
    token = read_access_token(request)
    if not token:
        clear_access_cookie(response)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    payload = decode_token(token)
    revoke_jti(payload.get("jti"))
    clear_access_cookie(response)
    return {"detail": "Logged out successfully"}


@router.get("/sbus")
@db_session
def list_sbus():
    rows = select(d for d in RcSbu if d.is_active).order_by(
        RcSbu.plant_id, RcSbu.name
    )[:]
    return [
        {
            "id": d.id,
            "code": d.code,
            "name": d.name,
            "plantId": (d.plant_id or "").strip(),
            "label": d.name,
            "value": d.name,
        }
        for d in rows
    ]


@router.get("/emp-status/{emp_id}")
@db_session
def emp_status(emp_id: str):
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
    return public_key_info()


@router.post("/signup", response_model=SignupPendingResponse)
@db_session
def signup(request: Request, response: Response, body: SignupRequest):
    creds = decrypt_creds_cipher(body.cipher, body.alg)
    emp_id = validate_employee_id(
        require_safe(str(creds.get("empId") or ""), "empId", field="empId"),
        allow_admin_id=False,
    )
    password = require_safe(str(creds.get("password") or ""), "password", field="password")
    from app.password_policy import validate_password_complexity

    validate_password_complexity(password)
    name = require_safe((body.name or "").strip(), "personName", field="name")
    sbu = require_safe((body.sbu or "").strip(), "label", field="sbu")
    if not name:
        raise HTTPException(400, "name is required")
    if not sbu:
        raise HTTPException(400, "sbu is required")

    master = select(d for d in RcSbu if d.is_active and d.name == sbu)[:1]
    if not master:
        raise HTTPException(400, "Select a valid SBU")

    if RcUser.get(emp_id=emp_id):
        raise HTTPException(400, f"Employee ID '{emp_id}' is already registered")

    user = RcUser(
        emp_id=emp_id,
        name=name,
        sbu=sbu,
        password_hash=hash_password(password),
        role="engineer",
        is_active=False,
        approval_status="pending",
        approval_remark="",
    )
    commit()
    try:
        _notify_signup_approvers(
            emp_id=user.emp_id, name=user.name, dept=user.sbu or sbu, user_id=user.id
        )
    except Exception:
        pass
    return {
        "status": "pending_approval",
        "message": (
            "Signup submitted. Awaiting SBU head approval. "
            "You can sign in after it is approved."
        ),
        "user": {
            "empId": user.emp_id,
            "name": user.name,
            "sbu": user.sbu or "",
        },
    }


@router.get("/config")
def auth_config():
    from app.config.settings import captcha_required

    return {"captchaRequired": captcha_required()}


@router.get("/captcha")
@limiter.limit(getattr(settings, "RATE_LIMIT_CAPTCHA", "30/min"))
def get_captcha(request: Request):
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
def login(request: Request, response: Response, body: LoginRequest = Body(...)):
    if body.terminateExistingSession and (body.resumeToken or "").strip():
        pending = consume_takeover_resume(body.resumeToken)
        user = RcUser.get(id=int(pending["user_id"]))
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User not found or inactive",
            )
        _assert_login_allowed(user)
        token = issue_access(
            emp_id=user.emp_id,
            role=user.role,
            user_id=user.id,
            response=response,
            request=request,
        )
        return {
            "access_token": token,
            "token_type": "bearer",
            "user": user_public(user),
            "replacedSession": True,
        }

    creds = decrypt_creds_cipher(body.cipher, body.alg)
    emp_id = require_safe(_normalize_emp_id(str(creds.get("empId") or "")), "empId", field="empId")
    password = require_safe(str(creds.get("password") or ""), "password", field="password")
    from app.config.settings import captcha_required

    if captcha_required():
        captcha_id = creds.get("captchaId") or body.captchaId
        captcha_answer = creds.get("captchaAnswer") or body.captchaAnswer
        if not captcha_id or not captcha_answer:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="CAPTCHA required"
            )
        from app.captcha import verify_captcha

        if not verify_captcha(captcha_id, captcha_answer):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired CAPTCHA",
            )
    if emp_id.lower() == _ADMIN_EMP_ID:
        emp_id = _ADMIN_EMP_ID
    user = RcUser.get(emp_id=emp_id)
    if not user or not verify_password(password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid empId or password",
        )
    _assert_login_allowed(user)

    existing = has_active_session(user.id)
    if existing and not body.terminateExistingSession:
        resume = issue_takeover_resume(
            user_id=user.id, emp_id=user.emp_id, role=user.role
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "CONCURRENT_SESSION",
                "message": (
                    "This account is already signed in elsewhere. "
                    "Terminate that session to continue here?"
                ),
                "resumeToken": resume,
            },
        )

    replaced = bool(existing)
    token = issue_access(
        emp_id=user.emp_id,
        role=user.role,
        user_id=user.id,
        response=response,
        request=request,
    )
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": user_public(user),
        "replacedSession": replaced,
    }


@router.post("/login/takeover", response_model=LoginResponse)
@limiter.limit(getattr(settings, "RATE_LIMIT_LOGIN", "5/min"))
@db_session
def login_takeover(request: Request, response: Response, body: SessionTakeoverRequest = Body(...)):
    pending = consume_takeover_resume(body.resumeToken)
    user = RcUser.get(id=int(pending["user_id"]))
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive",
        )
    _assert_login_allowed(user)
    token = issue_access(
        emp_id=user.emp_id,
        role=user.role,
        user_id=user.id,
        response=response,
        request=request,
    )
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": user_public(user),
        "replacedSession": True,
    }


@router.get("/me")
def me(current_user: dict = Depends(get_current_user)):
    return current_user


@router.post("/change-password")
@db_session
def change_password(
    body: ChangePasswordRequest,
    current_user: dict = Depends(get_current_user),
):
    user = RcUser.get(id=current_user["id"])
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="User not found or inactive")

    current_pass = require_safe(body.currentPassword, "password", field="currentPassword")
    new_pass = require_safe(body.newPassword, "password", field="newPassword")

    if not verify_password(current_pass, user.password_hash):
        raise HTTPException(status_code=400, detail="Current password is incorrect")

    from app.password_policy import check_password_history, validate_password_complexity

    validate_password_complexity(new_pass)
    check_password_history(user, new_pass, history_limit=5)

    from app.route_card.models import RcPasswordHistory

    RcPasswordHistory(
        user=user,
        password_hash=user.password_hash,
        created_at=datetime.utcnow(),
    )

    user.password_hash = hash_password(new_pass)
    user.must_change_password = False
    commit()

    return {
        "detail": "Password updated successfully",
        "user": user_public(user),
    }
