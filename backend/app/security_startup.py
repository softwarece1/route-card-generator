"""Process-start checks that keep development defaults out of a prod intranet host."""

from __future__ import annotations

import logging
import secrets

from app.config.settings import settings

logger = logging.getLogger("route_card.security")

_HISTORICAL_PLACEHOLDER_SECRET = "route-card-dev-secret-change-me"


def is_prod() -> bool:
    return (getattr(settings, "APP_ENV", "") or "dev").strip().lower() in {
        "prod",
        "production",
    }


def is_dev() -> bool:
    return (getattr(settings, "APP_ENV", "") or "dev").strip().lower() == "dev"


def assert_runtime_secrets() -> None:
    key = (settings.SECRET_KEY or "").strip()
    if key == _HISTORICAL_PLACEHOLDER_SECRET and not is_dev():
        raise RuntimeError(
            "SECRET_KEY is the historical development placeholder. "
            "Set a unique SECRET_KEY for non-dev environments."
        )
    if not key:
        if is_dev():
            generated = secrets.token_urlsafe(32)
            settings.SECRET_KEY = generated
            logger.warning(
                "SECRET_KEY was empty; generated an ephemeral in-process key for APP_ENV=dev. "
                "Sessions will not survive a restart. Set SECRET_KEY in .env for stable local auth."
            )
        else:
            raise RuntimeError(
                "SECRET_KEY is required when APP_ENV is not dev. "
                "Set a unique SECRET_KEY in the environment."
            )
    elif key == _HISTORICAL_PLACEHOLDER_SECRET and is_dev():
        logger.warning(
            "SECRET_KEY is the historical development placeholder. "
            "Set a unique value before any shared or production deploy."
        )

    if is_prod() and not (getattr(settings, "FILE_ENCRYPTION_KEY", "") or "").strip():
        logger.warning(
            "FILE_ENCRYPTION_KEY is empty; uploaded files are stored without encryption."
        )


def flag_known_admin_password() -> None:
    """Force a password change when a configured legacy weak admin password is still in use."""
    weak = (getattr(settings, "LEGACY_WEAK_ADMIN_PASSWORD", "") or "").strip()
    if not weak:
        return

    from pony.orm import commit, db_session

    from app.route_card.models import RcUser
    from app.security import verify_password

    with db_session:
        user = RcUser.get(emp_id="admin")
        if not user or not user.password_hash:
            return
        if not verify_password(weak, user.password_hash):
            return
        if not user.must_change_password:
            user.must_change_password = True
            commit()
            logger.warning(
                "Admin account still matches LEGACY_WEAK_ADMIN_PASSWORD. "
                "A password change is required at next login."
            )
