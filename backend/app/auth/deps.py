"""Auth dependencies: current user + role guards (cookie or Bearer)."""

from __future__ import annotations

from typing import Optional

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pony.orm import db_session

from app.auth.cookies import access_cookie_name
from app.auth.sessions import active_jti_for_user, is_jti_active
from app.auth.tokens import decode_token
from app.config.settings import settings
from app.route_card.models import RcUser

security = HTTPBearer(auto_error=False)


def user_public(user: RcUser) -> dict:
    from app.route_card.departments import is_ied_department
    from app.route_card.plants import plant_id_for_dept

    sbu_name = user.sbu or ""
    dept_ent = getattr(user, "department", None)
    dept_code = (dept_ent.code if dept_ent else "") or ""
    dept_name = (dept_ent.name if dept_ent else "") or ""
    return {
        "id": user.id,
        "empId": user.emp_id,
        "username": user.emp_id,
        "name": user.name,
        "display_name": user.name,
        "sbu": sbu_name,
        "plantId": plant_id_for_dept(sbu_name),
        "role": user.role,
        "mustChangePassword": bool(getattr(user, "must_change_password", False)),
        "departmentId": dept_ent.id if dept_ent else None,
        "departmentCode": dept_code,
        "departmentName": dept_name,
        "isIedDept": is_ied_department(dept_ent)
        or (user.role or "").strip().lower() == "ied",
    }


# Back-compat name
_user_public = user_public


def get_current_user(
    request: Request,
    creds: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> dict:
    if not settings.AUTH_ENABLED:
        return {
            "id": 0,
            "empId": "dev",
            "username": "dev",
            "name": "Dev",
            "display_name": "Dev",
            "sbu": "IT",
            "plantId": "",
            "role": "admin",
            "mustChangePassword": False,
            "departmentId": None,
            "departmentCode": "",
            "departmentName": "",
            "isIedDept": False,
        }

    token = request.cookies.get(access_cookie_name())
    if not token and creds and creds.credentials:
        token = creds.credentials

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )

    data = decode_token(token)
    jti = data.get("jti")
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

        if not jti or not is_jti_active(jti, user.id):
            active = active_jti_for_user(user.id)
            if active and active != jti:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail=(
                        "Your account is signed in elsewhere. "
                        "This session was ended — sign in again and choose to terminate the other session."
                    ),
                )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token has been revoked",
            )

        return user_public(user)


def require_admin(current_user: dict = Depends(get_current_user)) -> dict:
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return current_user


def require_sbu_head_or_admin(current_user: dict = Depends(get_current_user)) -> dict:
    if current_user.get("role") not in {"admin", "sbu_head"}:
        raise HTTPException(
            status_code=403, detail="SBU head or admin access required"
        )
    return current_user


def require_user_manager(current_user: dict = Depends(get_current_user)) -> dict:
    """Admin, sbu_head, or dept_head may manage users in their scope."""
    if current_user.get("role") not in {"admin", "sbu_head", "dept_head"}:
        raise HTTPException(
            status_code=403, detail="Department head, SBU head, or admin access required"
        )
    return current_user


def require_template_manager(current_user: dict = Depends(get_current_user)) -> dict:
    """Admin, sbu_head, dept_head, or IED-dept users may manage operation templates."""
    role = current_user.get("role")
    if role in {"admin", "sbu_head", "dept_head"} or current_user.get("isIedDept"):
        return current_user
    raise HTTPException(
        status_code=403,
        detail="Department head, IED department, or admin access required",
    )
