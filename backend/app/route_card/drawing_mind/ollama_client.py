"""Minimal Ollama HTTP client for vision chat (local VLM)."""

from __future__ import annotations

import json
import re
import threading
from typing import Any

import httpx

from app.route_card.analyze_jobs import AnalysisCancelled, check_cancelled, get_job

# Qwen3 / thinking models may leak reasoning into content; strip before JSON parse.
_THINK_BLOCK = re.compile(
    r"<think(?:ing)?>[\s\S]*?</think(?:ing)?>|"
    r"<\|?redacted_reasoning\|?>[\s\S]*?<\|?/redacted_reasoning\|?>",
    re.I,
)


class OllamaError(RuntimeError):
    """Raised when Ollama is unreachable or returns an error."""


def _base_url(url: str | None) -> str:
    return (url or "http://127.0.0.1:11434").rstrip("/")


def _client(base_url: str | None, timeout: float) -> httpx.Client:
    # trust_env=False: ignore HTTP(S)_PROXY so localhost Ollama is not sent
    # through a corporate proxy (which often returns HTTP 407 and looks "down").
    return httpx.Client(
        base_url=_base_url(base_url),
        timeout=timeout,
        trust_env=False,
    )


def _clean_assistant_content(text: str) -> str:
    cleaned = _THINK_BLOCK.sub("", text or "").strip()
    return cleaned


def ollama_reachable(base_url: str | None = None, timeout: float = 3.0) -> bool:
    try:
        with _client(base_url, timeout) as client:
            r = client.get("/api/tags")
            return r.status_code == 200
    except Exception:
        return False


def unload_model(
    model: str | None = None,
    base_url: str | None = None,
    timeout: float = 60.0,
) -> None:
    """Ask Ollama to drop the model from memory (keep_alive=0).

    Closing the chat stream stops generation on the client side, but the weights
    often stay resident. Call this after cancel so CPU/RAM/VRAM can settle.
    """
    from app.config.settings import settings

    name = (model or getattr(settings, "OLLAMA_VLM_MODEL", "") or "").strip()
    if not name:
        return
    url = base_url or getattr(settings, "OLLAMA_BASE_URL", None)
    try:
        with _client(url, timeout) as client:
            # Empty chat + keep_alive 0 is the supported unload path
            client.post(
                "/api/chat",
                json={
                    "model": name,
                    "messages": [],
                    "keep_alive": 0,
                    "stream": False,
                },
            )
    except Exception:
        # Best-effort — cancel must not fail because unload failed
        pass


def chat_vision(
    *,
    prompt: str,
    images_b64: list[str],
    model: str,
    base_url: str | None = None,
    timeout: float = 180.0,
    temperature: float = 0.1,
    system: str | None = None,
    cancel_event: threading.Event | None = None,
) -> str:
    """
    Call Ollama ``/api/chat`` with one or more base64 images (no data-URI prefix).

    Streams the response so cancel can close the connection and stop GPU inference.
    Uses ``think: false`` so Qwen3-style models skip reasoning traces for JSON extraction.
    """
    if not images_b64:
        raise OllamaError("chat_vision requires at least one image")
    if not (model or "").strip():
        raise OllamaError("chat_vision requires a model name")

    check_cancelled(cancel_event)

    messages: list[dict[str, Any]] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append(
        {
            "role": "user",
            "content": prompt,
            "images": list(images_b64),
        }
    )

    payload = {
        "model": model.strip(),
        "stream": True,
        # Prefer direct answer for structured JSON (faster on 27B thinking VLMs).
        "think": False,
        "messages": messages,
        "options": {
            "temperature": float(temperature),
        },
    }

    job = get_job()
    client = _client(base_url, timeout)
    if job is not None:
        job.attach_client(client)

    parts: list[str] = []
    try:
        check_cancelled(cancel_event)
        with client.stream("POST", "/api/chat", json=payload) as resp:
            if job is not None:
                job.attach_response(resp)
            if resp.status_code >= 400:
                detail = (resp.read().decode("utf-8", errors="replace") or "")[:400]
                raise OllamaError(f"Ollama HTTP {resp.status_code}: {detail}")

            for line in resp.iter_lines():
                check_cancelled(cancel_event)
                if not line:
                    continue
                try:
                    chunk = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if chunk.get("error"):
                    raise OllamaError(str(chunk.get("error"))[:400])
                msg = chunk.get("message") or {}
                piece = msg.get("content")
                if isinstance(piece, str) and piece:
                    parts.append(piece)
                # Non-stream fallback shape
                if isinstance(chunk.get("response"), str) and chunk.get("response"):
                    parts.append(chunk["response"])
    except AnalysisCancelled:
        try:
            unload_model(model=model.strip(), base_url=base_url)
        except Exception:
            pass
        raise
    except httpx.TimeoutException as exc:
        check_cancelled(cancel_event)
        raise OllamaError(f"Ollama timed out after {timeout}s") from exc
    except httpx.HTTPError as exc:
        check_cancelled(cancel_event)
        # Closed by cancel often surfaces as a generic HTTP/transport error
        if cancel_event is not None and cancel_event.is_set():
            try:
                unload_model(model=model.strip(), base_url=base_url)
            except Exception:
                pass
            raise AnalysisCancelled("Analysis cancelled") from exc
        if job is not None and job.cancel.is_set():
            try:
                unload_model(model=model.strip(), base_url=base_url)
            except Exception:
                pass
            raise AnalysisCancelled("Analysis cancelled") from exc
        raise OllamaError(f"Ollama request failed: {exc}") from exc
    finally:
        if job is not None:
            job.clear_http()
        try:
            client.close()
        except Exception:
            pass

    content = "".join(parts).strip()
    if not content:
        raise OllamaError("Ollama returned empty assistant content")
    cleaned = _clean_assistant_content(content)
    if not cleaned:
        raise OllamaError("Ollama returned empty assistant content after stripping thinking")
    return cleaned
