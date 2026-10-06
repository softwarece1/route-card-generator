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
    DB_USER: str = "route_card"
    DB_PASSWORD: str = "route_card"

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

    # Drawing mind: cpu_spatial | local_vlm (Ollama vision)
    DRAWING_MIND_ENGINE: str = "cpu_spatial"
    DRAWING_MIND_SPATIAL_DPI: int = 200
    DRAWING_MIND_MAX_PAGES: int = 12

    # Local VLM via Ollama (Qwen3-VL / Qwen2.5-VL etc.) — used when DRAWING_MIND_ENGINE=local_vlm
    # Ensure `ollama serve` is running and the vision model is created before enabling.
    OLLAMA_BASE_URL: str = "http://127.0.0.1:11434"
    OLLAMA_VLM_MODEL: str = "qwen3.8-27b-vl:latest"
    OLLAMA_TIMEOUT_SEC: float = 900.0
    OLLAMA_VLM_DPI: int = 160
    OLLAMA_VLM_MAX_PAGES: int = 6
    OLLAMA_VLM_MAX_IMAGE_EDGE: int = 1600

    # Adaptive format templates (JSON on disk — no external LLM)
    # Empty = backend/data/format_templates.json
    FORMAT_TEMPLATES_PATH: str = ""

    # Auth
    SECRET_KEY: str = "route-card-dev-secret-change-me"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 480
    AUTH_ENABLED: bool = True

    # Optional outbound webhook for in-app notification events (offline LAN)
    # Empty = disabled. POST JSON {title, body, link, userEmpId, createdAt}
    NOTIFY_WEBHOOK_URL: str = ""

    # Analyze queue worker
    ANALYZE_QUEUE_ENABLED: bool = True
    ANALYZE_QUEUE_POLL_SEC: float = 2.0

    # Backup output directory (empty = <LOCAL_UPLOAD_ROOT>/../backups or cwd/backups)
    BACKUP_ROOT: str = ""


settings = Settings()

