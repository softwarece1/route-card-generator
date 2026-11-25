"""Modular auth package — httpOnly access cookie + DB sessions (no refresh)."""

from app.auth.cookies import (
    clear_access_cookie,
    read_access_token,
    set_access_cookie,
)
from app.auth.deps import (
    get_current_user,
    require_admin,
    require_sbu_head_or_admin,
    require_template_manager,
    require_user_manager,
    user_public,
)
from app.auth.routes import (
    create_access_token,
    router,
    validate_employee_id,
)
from app.auth.sessions import (
    _pending_session_takeovers,
    consume_takeover_resume,
    create_session,
    has_active_session,
    issue_takeover_resume,
    revoke_jti,
    revoke_user_sessions,
)
from app.auth.tokens import decode_token

# Compatibility shims for older tests that poked in-memory maps
_revoked_tokens: set[str] = set()
_active_sessions: dict[int, str] = {}


def _sync_compat_revoke(jti: str | None) -> None:
    if jti:
        _revoked_tokens.add(jti)


__all__ = [
    "router",
    "get_current_user",
    "require_admin",
    "require_sbu_head_or_admin",
    "require_user_manager",
    "require_template_manager",
    "create_access_token",
    "decode_token",
    "validate_employee_id",
    "user_public",
    "set_access_cookie",
    "clear_access_cookie",
    "read_access_token",
    "create_session",
    "revoke_jti",
    "revoke_user_sessions",
    "has_active_session",
    "issue_takeover_resume",
    "consume_takeover_resume",
    "_pending_session_takeovers",
    "_revoked_tokens",
    "_active_sessions",
]
