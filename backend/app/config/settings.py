# Existing settings file
"""Auth settings + login credentials for standalone app."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    # Database — local PostgreSQL 18 (pgAdmin / offline PC)
    DB_HOST: str = "localhost"
    DB_PORT: int = 5432
    DB_NAME: str = "route_card"
    DB_USER: str = "postgres"
    DB_PASSWORD: str = "postgres"

    # MinIO (optional — service.py falls back to local uploads/)
    MINIO_ENDPOINT: str = "localhost:9000"
    MINIO_ACCESS_KEY: str = "minioadmin"
    MINIO_SECRET_KEY: str = "minioadmin"
    MINIO_BUCKET_NAME: str = "oarc-extractions"
    MINIO_SECURE: bool = False
    # auto = try MinIO then local; local = skip MinIO; minio = MinIO only
    # Default local until MinIO is intentionally enabled in deployment.
    STORAGE_BACKEND: str = "local"
    # Absolute or relative path for local file storage (GA/PL/WL).
    # Empty = <backend cwd>/uploads/route-card
    # Example: D:/RouteCardData/uploads
    LOCAL_UPLOAD_ROOT: str = ""
    # Fail fast when MinIO is down (otherwise TCP wait can be ~60s+ per upload)
    MINIO_CONNECT_TIMEOUT_SEC: float = 2.0
    MINIO_READ_TIMEOUT_SEC: float = 10.0
    MINIO_DOWN_CACHE_SEC: float = 60.0

    # Optional DWG → DXF converter
    ODA_CONVERTER_PATH: str = ""

    # Offline PDF ingest / OCR (CPU — no GPU/LLM)
    OCR_ENABLED: bool = True
    TESSERACT_CMD: str = ""  # e.g. C:\Program Files\Tesseract-OCR\tesseract.exe
    OCR_DPI: int = 200
    OCR_MAX_PAGES: int = 12

    # Drawing mind: cpu_spatial | local_vlm (on-prem vLLM vision)
    DRAWING_MIND_ENGINE: str = "cpu_spatial"
    DRAWING_MIND_SPATIAL_DPI: int = 200
    DRAWING_MIND_MAX_PAGES: int = 12

    # Local VLM via an OpenAI-compatible vLLM server — used when DRAWING_MIND_ENGINE=local_vlm.
    # Names stay OLLAMA_* so existing env files keep working.
    # Server exposes GET /v1/models and POST /v1/chat/completions. Context window is 8192.
    OLLAMA_BASE_URL: str = "http://172.195.132.152:8010"
    OLLAMA_VLM_MODEL: str = "google/gemma-4-E4B-it"
    OLLAMA_TIMEOUT_SEC: float = 1800.0
    OLLAMA_VLM_MAX_TOKENS: int = 2048
    OLLAMA_VLM_DPI: int = 160
    OLLAMA_VLM_MAX_PAGES: int = 6
    OLLAMA_VLM_MAX_IMAGE_EDGE: int = 1600
    # High-res NOTE-band crop (verbatim transcription)
    OLLAMA_VLM_NOTE_DPI: int = 360
    OLLAMA_VLM_NOTE_MAX_EDGE: int = 2800

    # Adaptive format templates (JSON on disk — no external LLM)
    # Empty = backend/data/format_templates.json
    FORMAT_TEMPLATES_PATH: str = ""

    # Auth
    SECRET_KEY: str = "route-card-dev-secret-change-me"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 480
    AUTH_ENABLED: bool = True
    # RSA private key PEM for decrypting login/signup credentials (empty = auto-generate under backend/data/)
    AUTH_RSA_PRIVATE_KEY_PATH: str = ""
    # httpOnly access cookie (LAN HTTP → COOKIE_SECURE=false)
    AUTH_COOKIE_NAME: str = "rc_access"
    # Empty = auto: Secure only when APP_ENV is prod/production
    COOKIE_SECURE: str = ""
    # Extra CORS/CSRF origins for LAN static IP (comma-separated), e.g. http://172.16.0.10:8003
    CORS_EXTRA_ORIGINS: str = ""
    # Allow clients that open the UI via IP / loopback (http://<server-ip>:5174).
    # Covers RFC1918 and non-RFC1918 corporate IPs (e.g. 172.195.x.x). Domain names
    # still require CORS_ORIGINS / CORS_EXTRA_ORIGINS.
    CORS_ALLOW_PRIVATE_NETWORK: bool = True

    # Optional outbound webhook for in-app notification events (offline LAN)
    # Empty = disabled. POST JSON {title, body, link, userEmpId, createdAt}
    NOTIFY_WEBHOOK_URL: str = ""

    # Analyze queue worker
    ANALYZE_QUEUE_ENABLED: bool = True
    ANALYZE_QUEUE_POLL_SEC: float = 2.0

    # When True, resolve extracted ops against dept WorkCenter/Machine master
    WC_RESOLVER_ENABLED: bool = True

    # SAP Zppfm001 organization, work-centre and machine service.
    SAP_USERNAME: str = ""
    SAP_PASSWORD: str = ""
    SAP_VERIFY_SSL: bool = True
    SAP_TRUST_ENV: bool = True
    SAP_TIMEOUT_SEC: int = 60
    SAP_ORG_DETAILS_WSDL: str = ""

    # Backup output directory (empty = <LOCAL_UPLOAD_ROOT>/../backups or cwd/backups)
    BACKUP_ROOT: str = ""

    # API error log directory (empty = <backend>/.logs)
    ERROR_LOG_DIR: str = ""

    # --- Security enhancements ---
    # dev hides login CAPTCHA; prod (or production) shows and requires it.
    # CAPTCHA_ENABLED=true/false overrides APP_ENV when set.
    APP_ENV: str = "dev"
    CAPTCHA_ENABLED: str = ""
    # CAPTCHA configuration
    CAPTCHA_TTL_SECONDS: int = 120  # challenge lives for 2 minutes by default
    CAPTCHA_ATTEMPT_LIMIT: int = 5  # max attempts per challenge
    # Rate limiting (requests per minute)
    RATE_LIMIT_LOGIN: str = "5/min"  # five login attempts per minute per IP
    RATE_LIMIT_CAPTCHA: str = "30/min"  # thirty captcha requests per minute per IP
    # Idle session timeout (minutes of inactivity)
    IDLE_TIMEOUT_MINUTES: int = 15
    # Maximum upload size (megabytes)
    MAX_UPLOAD_SIZE_MB: int = 10
    # Common password list path (bundled file)
    COMMON_PASSWORDS_PATH: str = "backend/data/common_passwords.txt"
    # First-boot admin password. Used only when the users table is empty.
    # Leave empty to skip seeding. Must satisfy the password policy.
    ADMIN_INITIAL_PASSWORD: str = ""

    # CORS allowed origins (frontend Vite dev server or production URL)
    CORS_ORIGINS: list[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:5174",
        "http://127.0.0.1:5174",
        "http://localhost:8003",
        "http://127.0.0.1:8003",
    ]
    # Built SPA directory for same-origin LAN deploy (empty = skip StaticFiles)
    # Example: ../frontend/dist relative to backend cwd, or absolute path
    FRONTEND_DIST: str = ""
    # Encryption key for server‑side file‑at‑rest encryption (base64‑encoded 32‑byte key).
    # Set via environment variable FILE_ENCRYPTION_KEY. Empty means encryption disabled.
    FILE_ENCRYPTION_KEY: str = ""
    # ... existing settings unchanged ...

settings = Settings()


def cookie_secure() -> bool:
    """Secure cookie flag: explicit COOKIE_SECURE, else True only in prod."""
    raw = (getattr(settings, "COOKIE_SECURE", "") or "").strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    return (getattr(settings, "APP_ENV", "dev") or "dev").strip().lower() in {
        "prod",
        "production",
    }


def cors_allow_origins() -> list[str]:
    """CORS / CSRF origins: settings list + CORS_EXTRA_ORIGINS."""
    origins = [str(o).strip().rstrip("/") for o in (settings.CORS_ORIGINS or []) if str(o).strip()]
    extra = (getattr(settings, "CORS_EXTRA_ORIGINS", "") or "").strip()
    if extra:
        for part in extra.split(","):
            o = part.strip().rstrip("/")
            if o and o not in origins:
                origins.append(o)
    return origins


# Loopback UI hosts on any port. A server IP is allowed only when it matches
# the request Host (see origin_is_allowed), not every address on the network.
_LOOPBACK_ORIGIN_RE = r"^https?://(localhost|127\.0\.0\.1|\[::1\])(?::\d+)?$"


def cors_allow_private_network() -> bool:
    return bool(getattr(settings, "CORS_ALLOW_PRIVATE_NETWORK", True))


def cors_origin_regex() -> str | None:
    """Starlette CORSMiddleware allow_origin_regex for loopback UI hosts."""
    return _LOOPBACK_ORIGIN_RE


def _hostname(value: str) -> str:
    raw = (value or "").strip().lower()
    if not raw:
        return ""
    if "://" in raw:
        from urllib.parse import urlparse

        return (urlparse(raw).hostname or "").lower()
    if raw.startswith("["):
        end = raw.find("]")
        return raw[1:end].lower() if end > 1 else ""
    return raw.split(":")[0]


def origin_is_allowed(origin: str | None, request_host: str | None = None) -> bool:
    """True for an allow-listed origin, loopback, or the same host as this request.

    ``request_host`` is the Host header (port ignored). Without it, a bare IP
    origin is rejected so a page on another machine cannot pass the check.
    """
    o = (origin or "").strip().rstrip("/")
    if not o:
        return False
    allow = {a.rstrip("/") for a in cors_allow_origins()}
    if o in allow:
        return True
    import re

    if re.match(_LOOPBACK_ORIGIN_RE, o, flags=re.I):
        return True
    if not request_host or not cors_allow_private_network():
        return False
    origin_host = _hostname(o)
    return bool(origin_host) and origin_host == _hostname(request_host)


def captcha_required() -> bool:
    """Login CAPTCHA is off in dev and on in prod, unless CAPTCHA_ENABLED overrides."""
    raw = (getattr(settings, "CAPTCHA_ENABLED", "") or "").strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    return (getattr(settings, "APP_ENV", "dev") or "dev").strip().lower() in {
        "prod",
        "production",
    }
