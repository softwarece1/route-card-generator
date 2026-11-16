"""OpenAI-compatible vision client for the on-prem vLLM server.

The module name is historical (this used to call Ollama). Callers still import
``chat_vision``, ``ollama_reachable``, and ``unload_model`` from here.
"""

from __future__ import annotations

import json
import re
import threading
from typing import Any

import httpx

from app.route_card.analyze_jobs import AnalysisCancelled, check_cancelled, get_job

# Thinking models may leak reasoning into content; strip before JSON parse.
_THINK_BLOCK = re.compile(
    r"<think(?:ing)?>[\s\S]*?</think(?:ing)?>|"
    r"<\|?redacted_reasoning\|?>[\s\S]*?<\|?/redacted_reasoning\|?>",
    re.I,
)


class OllamaError(RuntimeError):
    """Raised when the vision server is unreachable or returns an error."""


def _base_url(url: str | None) -> str:
    base = (url or "http://172.195.132.152:8010").rstrip("/")
    if base.endswith("/v1"):
        base = base[:-3]
    return base


def _client(base_url: str | None, timeout: float) -> httpx.Client:
    # trust_env=False: ignore HTTP(S)_PROXY so the LAN vLLM host is not sent
    # through a corporate proxy (which often returns HTTP 407 and looks "down").
    return httpx.Client(
        base_url=_base_url(base_url),
        timeout=timeout,
        trust_env=False,
    )


def _clean_assistant_content(text: str) -> str:
    cleaned = _THINK_BLOCK.sub("", text or "").strip()
    return cleaned


def _text_from_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        bits: list[str] = []
        for part in content:
            if isinstance(part, str):
                bits.append(part)
            elif isinstance(part, dict):
                bits.append(str(part.get("text") or ""))
        return "".join(bits)
    return ""


def _image_part(b64: str, mime: str) -> dict[str, Any]:
    raw = (b64 or "").strip()
    if raw.startswith("data:"):
        url = raw
    else:
        url = f"data:{mime or 'image/jpeg'};base64,{raw}"
    return {"type": "image_url", "image_url": {"url": url}}


def vlm_status(
    base_url: str | None = None,
    model: str | None = None,
    timeout: float = 3.0,
) -> tuple[bool, str | None]:
    """Return (ok, error) for GET /v1/models, including a missing-model check."""
    from app.config.settings import settings

    url = base_url or getattr(settings, "OLLAMA_BASE_URL", None)
    name = (model if model is not None else getattr(settings, "OLLAMA_VLM_MODEL", "") or "").strip()
    try:
        with _client(url, timeout) as client:
            r = client.get("/v1/models")
            if r.status_code != 200:
                return False, f"HTTP {r.status_code}"
            if not name:
                return True, None
            try:
                payload = r.json()
                ids = [
                    str(item.get("id") or "")
                    for item in (payload.get("data") or [])
                    if isinstance(item, dict)
                ]
            except Exception:
                return True, None
            if ids and name not in ids:
                shown = ", ".join(i for i in ids[:4] if i)
                return False, f"model {name} not served (have {shown})"
            return True, None
    except Exception as exc:
        return False, str(exc)[:200]


def ollama_reachable(base_url: str | None = None, timeout: float = 3.0) -> bool:
    ok, _err = vlm_status(base_url, timeout=timeout)
    return ok


def unload_model(
    model: str | None = None,
    base_url: str | None = None,
    timeout: float = 60.0,
) -> None:
    """No-op on vLLM.

    The server keeps ``google/gemma-4-E4B-it`` loaded. Cancelling closes the
    streaming HTTP connection, which aborts the in-flight completion.
    """
    del model, base_url, timeout


def _stream_chat_completions(
    *,
    messages: list[dict[str, Any]],
    model: str,
    base_url: str | None,
    timeout: float,
    temperature: float,
    max_tokens: int,
    cancel_event: threading.Event | None,
) -> str:
    payload = {
        "model": model.strip(),
        "stream": True,
        "temperature": float(temperature),
        "max_tokens": int(max_tokens),
        "messages": messages,
    }

    job = get_job()
    client = _client(base_url, timeout)
    if job is not None:
        job.attach_client(client)

    parts: list[str] = []
    try:
        check_cancelled(cancel_event)
        with client.stream("POST", "/v1/chat/completions", json=payload) as resp:
            if job is not None:
                job.attach_response(resp)
            if resp.status_code >= 400:
                detail = (resp.read().decode("utf-8", errors="replace") or "")[:400]
                raise OllamaError(f"Vision server HTTP {resp.status_code}: {detail}")

            for line in resp.iter_lines():
                check_cancelled(cancel_event)
                if not line:
                    continue
                data = line[5:].strip() if line.startswith("data:") else line.strip()
                if not data or data == "[DONE]":
                    if data == "[DONE]":
                        break
                    continue
                try:
                    chunk = json.loads(data)
                except json.JSONDecodeError:
                    continue
                if chunk.get("error"):
                    err = chunk.get("error")
                    msg = err.get("message") if isinstance(err, dict) else str(err)
                    raise OllamaError(str(msg)[:400])
                choices = chunk.get("choices") or []
                if not choices or not isinstance(choices[0], dict):
                    continue
                choice = choices[0]
                delta = choice.get("delta") or {}
                piece = _text_from_content(delta.get("content"))
                if piece:
                    parts.append(piece)
                message = choice.get("message") or {}
                full = _text_from_content(message.get("content"))
                if full:
                    parts.append(full)
    except AnalysisCancelled:
        raise
    except httpx.TimeoutException as exc:
        check_cancelled(cancel_event)
        raise OllamaError(f"Vision server timed out after {timeout}s") from exc
    except httpx.HTTPError as exc:
        check_cancelled(cancel_event)
        if cancel_event is not None and cancel_event.is_set():
            raise AnalysisCancelled("Analysis cancelled") from exc
        if job is not None and job.cancel.is_set():
            raise AnalysisCancelled("Analysis cancelled") from exc
        raise OllamaError(f"Vision server request failed: {exc}") from exc
    finally:
        if job is not None:
            job.clear_http()
        try:
            client.close()
        except Exception:
            pass

    content_text = "".join(parts).strip()
    if not content_text:
        raise OllamaError("Vision server returned empty assistant content")
    cleaned = _clean_assistant_content(content_text)
    if not cleaned:
        raise OllamaError("Vision server returned empty assistant content after stripping thinking")
    return cleaned


def chat_text(
    *,
    prompt: str,
    model: str,
    base_url: str | None = None,
    timeout: float = 180.0,
    temperature: float = 0.0,
    system: str | None = None,
    cancel_event: threading.Event | None = None,
    max_tokens: int | None = None,
) -> str:
    """Text-only ``POST /v1/chat/completions`` (no images)."""
    if not (model or "").strip():
        raise OllamaError("chat_text requires a model name")
    check_cancelled(cancel_event)
    if max_tokens is None:
        from app.config.settings import settings

        max_tokens = int(getattr(settings, "OLLAMA_VLM_MAX_TOKENS", 2048) or 2048)

    messages: list[dict[str, Any]] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    return _stream_chat_completions(
        messages=messages,
        model=model,
        base_url=base_url,
        timeout=timeout,
        temperature=temperature,
        max_tokens=max_tokens,
        cancel_event=cancel_event,
    )


def chat_vision(
    *,
    prompt: str,
    images_b64: list[str],
    model: str,
    base_url: str | None = None,
    timeout: float = 180.0,
    temperature: float = 0.0,
    system: str | None = None,
    cancel_event: threading.Event | None = None,
    image_mime: str = "image/jpeg",
    max_tokens: int | None = None,
) -> str:
    """
    Call ``POST /v1/chat/completions`` with one or more base64 images.

    Streams the response so cancel can close the connection and stop inference.
    """
    if not images_b64:
        raise OllamaError("chat_vision requires at least one image")
    if not (model or "").strip():
        raise OllamaError("chat_vision requires a model name")

    check_cancelled(cancel_event)

    if max_tokens is None:
        from app.config.settings import settings

        max_tokens = int(getattr(settings, "OLLAMA_VLM_MAX_TOKENS", 2048) or 2048)

    content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
    for img in images_b64:
        content.append(_image_part(img, image_mime))

    messages: list[dict[str, Any]] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": content})

    return _stream_chat_completions(
        messages=messages,
        model=model,
        base_url=base_url,
        timeout=timeout,
        temperature=temperature,
        max_tokens=max_tokens,
        cancel_event=cancel_event,
    )
