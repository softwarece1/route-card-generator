"""Server-side mirror of frontend inputSafe — reject unsafe free-text payloads."""

from __future__ import annotations

import re

from fastapi import HTTPException

_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_HTML_TAG = re.compile(r"</?[a-zA-Z][^>]*>")
_DANGEROUS = re.compile(
    r"(?:javascript|vbscript|data)\s*:|"
    r"on(?:error|load|click|mouse\w+|focus|blur|submit|toggle)\s*=|"
    r"<\s*(?:script|iframe|object|embed|link|meta|svg|img)\b",
    re.I,
)
_PATH = re.compile(r"(?:^|[/\\])\.\.(?:[/\\]|$)")

_PROFILES: dict[str, dict] = {
    "empId": {"max": 64, "allow": re.compile(r"[^0-9a-zA-Z]")},
    "personName": {"max": 255, "allow": re.compile(r"[^a-zA-Z\s.'\-]")},
    "label": {"max": 128, "allow": re.compile(r"[^a-zA-Z0-9\s.\-_/()#+&]")},
    "code": {"max": 200, "allow": re.compile(r"[^a-zA-Z0-9\s.\-_/()#+&,:%°]")},
    "password": {"max": 128, "allow": re.compile(r"[^\x20-\x7e]|[<>`]")},
    "search": {"max": 120, "allow": re.compile(r"[^a-zA-Z0-9\s.\-_/()#]")},
    "multiline": {"max": 8000, "allow": None},
    "text": {"max": 500, "allow": re.compile(r"[^a-zA-Z0-9\s.\-_/()#+&,:%°@']")},
}


def sanitize_text(raw: str | None, profile: str = "text") -> str:
    cfg = _PROFILES.get(profile) or _PROFILES["text"]
    s = str(raw or "")
    s = _CTRL.sub("", s)
    s = _HTML_TAG.sub("", s)
    s = _DANGEROUS.sub("", s)
    s = _PATH.sub("", s)
    s = s.replace("..", "")
    s = s.replace("<", "").replace(">", "").replace("`", "")
    allow = cfg.get("allow")
    if allow is not None:
        s = allow.sub("", s)
    return s[: int(cfg["max"])]


def require_safe(raw: str | None, profile: str = "text", *, field: str = "value") -> str:
    """Return sanitized text; 400 if the input was materially unsafe/altered."""
    original = str(raw or "")
    cleaned = sanitize_text(original, profile)
    if original != cleaned:
        raise HTTPException(
            400,
            f"{field} contains unsupported or unsafe characters",
        )
    return cleaned
