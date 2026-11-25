"""Process-start checks that keep development defaults out of a prod intranet host."""

from __future__ import annotations

import logging

from app.config.settings import settings

logger = logging.getLogger("route_card.security")

DEFAULT_SECRET = "route-card-dev-secret-change-me"
_KNOWN_ADMIN_PASSWORD = "admin123"


def is_prod() -> bool:
    return (getattr(settings, "APP_ENV", "") or "dev").strip().lower() in {
        "prod",
        "production",
    }


def assert_runtime_secrets() -> None:
    if (settings.SECRET_KEY or "") == DEFAULT_SECRET:
        if is_prod():
            raise RuntimeError(
                "SECRET_KEY is the development placeholder. "
                "Set a unique SECRET_KEY when APP_ENV is prod."
            )
        logger.warning(
            "SECRET_KEY is the development placeholder. Set a unique value before production."
        )
    if is_prod() and not (getattr(settings, "FILE_ENCRYPTION_KEY", "") or "").strip():
        logger.warning(
            "FILE_ENCRYPTION_KEY is empty; uploaded files are stored without encryption."
        )


def flag_known_admin_password() -> None:
    """Force a password change when the seeded admin password is still in use."""
    from pony.orm import commit, db_session

    from app.route_card.models import RcUser
    from app.security import verify_password

    with db_session:
        user = RcUser.get(emp_id="admin")
        if not user or not user.password_hash:
            return
        if not verify_password(_KNOWN_ADMIN_PASSWORD, user.password_hash):
            return
        if not user.must_change_password:
            user.must_change_password = True
            commit()
            logger.warning(
                "Admin account is still using the known default password. "
                "A password change is required at next login."
            )
