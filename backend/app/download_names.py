"""Safe Content-Disposition values for uploaded filenames."""

from __future__ import annotations

from urllib.parse import quote


def content_disposition(filename: str, *, inline: bool) -> str:
    """Quote a stored filename so quotes and line breaks cannot inject headers."""
    raw = (filename or "download").replace("\\", "_").replace("/", "_")
    raw = raw.replace("\r", "").replace("\n", "").replace('"', "")
    raw = raw.strip() or "download"
    kind = "inline" if inline else "attachment"
    encoded = quote(raw, safe="")
    return f"{kind}; filename=\"{raw}\"; filename*=UTF-8''{encoded}"
