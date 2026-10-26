"""CAPTCHA utilities for offline-friendly generation and verification.

Generates a simple 6‑character alphanumeric challenge rendered as a PNG image.
Stores the expected answer as a SHA‑256 hash keyed by a secret.
Uses a TTLCache for expiration; the cache size is bounded to avoid unbounded memory.
"""
import secrets
import string
import hashlib
import io
from datetime import datetime
from typing import Tuple

from PIL import Image, ImageDraw, ImageFont
from cachetools import TTLCache

from app.config.settings import settings

# In‑memory store – limited size, TTL based on settings.CAPTCHA_TTL_SECONDS
_captcha_cache: TTLCache = TTLCache(maxsize=1024, ttl=getattr(settings, "CAPTCHA_TTL_SECONDS", 120))

def _random_code(length: int = 6) -> str:
    alphabet = string.ascii_uppercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))

def _hash_answer(answer: str) -> str:
    # Combine with secret key to avoid rainbow‑table attacks
    secret = getattr(settings, "SECRET_KEY", "default-secret")
    return hashlib.sha256((answer + secret).encode()).hexdigest()

def generate_captcha() -> Tuple[str, bytes]:
    """Create a new CAPTCHA challenge.

    Returns:
        challenge_id: UUID string used by the client to reference the challenge.
        png_bytes: PNG image data containing the rendered code.
    """
    code = _random_code()
    challenge_id = secrets.token_urlsafe(16)
    # Render image – using a basic built‑in font; Pillow will fall back to a default.
    img = Image.new("RGB", (200, 70), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("arial.ttf", 48)
    except Exception:
        font = ImageFont.load_default()
    # Add some noise lines
    for _ in range(5):
        start = (secrets.randbelow(200), secrets.randbelow(70))
        end = (secrets.randbelow(200), secrets.randbelow(70))
        draw.line([start, end], fill=(secrets.randbelow(256), secrets.randbelow(256), secrets.randbelow(256)), width=2)
    # Center the text safely across Pillow versions
    if hasattr(draw, "textbbox"):
        bbox = draw.textbbox((0, 0), code, font=font)
        w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    elif hasattr(draw, "textsize"):
        w, h = draw.textsize(code, font=font)
    else:
        w, h = len(code) * 20, 30
    position = ((200 - w) // 2, (70 - h) // 2)
    draw.text(position, code, font=font, fill=(0, 0, 0))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    png_bytes = buf.getvalue()
    # Store hashed answer with attempt counter
    _captcha_cache[challenge_id] = {"hash": _hash_answer(code), "code": code, "attempts": 0, "created": datetime.utcnow()}
    return challenge_id, png_bytes

def verify_captcha(challenge_id: str, answer: str) -> bool:
    """Validate a CAPTCHA response.

    Returns True if the answer matches and the challenge is still valid.
    Consumes the challenge (single‑use) and respects the attempt limit.
    """
    entry = _captcha_cache.get(challenge_id)
    if not entry:
        return False
    # Increment attempt counter
    entry["attempts"] += 1
    if entry["attempts"] > getattr(settings, "CAPTCHA_ATTEMPT_LIMIT", 5):
        # Exceeded attempts – invalidate
        _captcha_cache.pop(challenge_id, None)
        return False
    # Check answer
    if _hash_answer(answer.upper().strip()) == entry["hash"]:
        # Success – remove challenge
        _captcha_cache.pop(challenge_id, None)
        return True
    # Wrong answer – keep challenge until attempts exceed or TTL expires
    return False
