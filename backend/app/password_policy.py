"""Password policy validation for enterprise and VAPT compliance.

Requirements:
- Minimum length: 12 characters
- Maximum length: 64 characters
- At least one uppercase letter
- At least one lowercase letter
- At least one digit
- At least one special character
- Not in common/breached password dictionary
"""
import os
import re
from fastapi import HTTPException, status
from app.config.settings import settings

_COMMON_PASSWORDS: set[str] = set()

def _load_common_passwords():
    global _COMMON_PASSWORDS
    if _COMMON_PASSWORDS:
        return
    path = getattr(settings, "COMMON_PASSWORDS_PATH", "backend/data/common_passwords.txt")
    # Resolve relative path against backend directory if needed
    candidates = [
        path,
        os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "common_passwords.txt"),
        os.path.join(os.getcwd(), path),
    ]
    for p in candidates:
        if os.path.exists(p):
            try:
                with open(p, "r", encoding="utf-8", errors="ignore") as f:
                    _COMMON_PASSWORDS = {line.strip().lower() for line in f if line.strip()}
                return
            except Exception:
                pass
    # Built-in minimal fallback list of high-frequency breached passwords
    _COMMON_PASSWORDS = {
        "password", "password123", "admin123456", "123456789012",
        "welcome12345", "qwerty123456", "routecard123", "administrator",
    }

def check_password_complexity(password: str) -> list[str]:
    """Check password against all complexity rules and return all unmet requirements."""
    errors: list[str] = []
    if len(password) < 12:
        errors.append("Password must be at least 12 characters long")
    if len(password) > 64:
        errors.append("Password must not exceed 64 characters")
    if re.search(r"\s", password):
        errors.append("Password must not contain spaces or whitespace characters")
    if not re.search(r"[A-Z]", password):
        errors.append("Password must contain at least one uppercase letter")
    if not re.search(r"[a-z]", password):
        errors.append("Password must contain at least one lowercase letter")
    if not re.search(r"\d", password):
        errors.append("Password must contain at least one digit")
    if not re.search(r"[!@#$%^&*()_+\-=\[\]{};':\"\\|,.<>\/?]", password):
        errors.append("Password must contain at least one special character")

    _load_common_passwords()
    if password.lower() in _COMMON_PASSWORDS:
        errors.append("This password is too common or known to be breached. Please choose a more secure password.")

    return errors


def validate_password_complexity(password: str) -> None:
    """Validate password against complexity and breach-list rules.

    Raises HTTPException(400) if invalid, containing all unmet requirements.
    """
    errors = check_password_complexity(password)
    if errors:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="\n".join(errors) if len(errors) > 1 else errors[0],
        )


def check_password_history(user, new_password: str, history_limit: int = 5) -> None:
    """Ensure new password is not the current password and not in recent password history."""
    from app.security import verify_password
    from pony.orm import desc

    if getattr(user, "password_hash", None) and verify_password(new_password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="New password cannot be the same as your current or temporary password.",
        )

    if hasattr(user, "password_history"):
        from app.route_card.models import RcPasswordHistory
        past = user.password_history.select().order_by(desc(RcPasswordHistory.created_at))[:history_limit]
        for item in past:
            if verify_password(new_password, item.password_hash):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"You cannot reuse any of your last {history_limit} passwords. Please choose a new password.",
                )


