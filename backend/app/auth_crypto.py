"""RSA-OAEP helpers for encrypting login/signup credentials in transit.

Frontend encrypts a small JSON blob with the server public key (Web Crypto
RSA-OAEP SHA-256). Backend decrypts with the private key before password verify.
"""

from __future__ import annotations

import base64
import json
import logging
from functools import lru_cache
from pathlib import Path

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from fastapi import HTTPException

logger = logging.getLogger(__name__)

ALG = "RSA-OAEP-SHA256"
_KEY_BITS = 2048


def _default_key_path() -> Path:
    try:
        from app.config.settings import settings

        custom = (getattr(settings, "AUTH_RSA_PRIVATE_KEY_PATH", "") or "").strip()
        if custom:
            return Path(custom)
    except Exception:
        pass
    return Path(__file__).resolve().parents[1] / "data" / "auth_rsa_private.pem"


def _generate_and_save(path: Path) -> rsa.RSAPrivateKey:
    path.parent.mkdir(parents=True, exist_ok=True)
    key = rsa.generate_private_key(public_exponent=65537, key_size=_KEY_BITS)
    pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    path.write_bytes(pem)
    try:
        path.chmod(0o600)
    except Exception:
        pass
    logger.info("Generated auth RSA key pair at %s", path)
    return key


@lru_cache(maxsize=1)
def _private_key() -> rsa.RSAPrivateKey:
    path = _default_key_path()
    if path.is_file():
        data = path.read_bytes()
        return serialization.load_pem_private_key(data, password=None)
    return _generate_and_save(path)


def public_key_pem() -> str:
    pub = _private_key().public_key()
    return pub.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("ascii")


def public_key_info() -> dict:
    return {
        "alg": ALG,
        "publicKeyPem": public_key_pem(),
    }


def decrypt_creds_cipher(cipher_b64: str, alg: str | None = None) -> dict:
    """Decrypt base64 RSA-OAEP ciphertext → dict (must include empId + password)."""
    if alg and alg != ALG:
        raise HTTPException(400, f"Unsupported credential cipher alg: {alg}")
    raw = (cipher_b64 or "").strip()
    if not raw:
        raise HTTPException(400, "Missing encrypted credentials")
    try:
        ciphertext = base64.b64decode(raw, validate=True)
    except Exception as exc:
        raise HTTPException(400, "Invalid credential cipher encoding") from exc
    try:
        plain = _private_key().decrypt(
            ciphertext,
            padding.OAEP(
                mgf=padding.MGF1(algorithm=hashes.SHA256()),
                algorithm=hashes.SHA256(),
                label=None,
            ),
        )
    except Exception as exc:
        raise HTTPException(400, "Could not decrypt credentials") from exc
    try:
        payload = json.loads(plain.decode("utf-8"))
    except Exception as exc:
        raise HTTPException(400, "Decrypted credentials are not valid JSON") from exc
    if not isinstance(payload, dict):
        raise HTTPException(400, "Decrypted credentials must be an object")
    emp_id = str(payload.get("empId") or "").strip()
    password = str(payload.get("password") or "")
    if not emp_id or not password:
        raise HTTPException(400, "Encrypted payload must include empId and password")
    return payload
