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

    # Drawing mind: cpu_spatial (feasibility) | local_vlm (on-prem GPU later)
    DRAWING_MIND_ENGINE: str = "cpu_spatial"
    DRAWING_MIND_SPATIAL_DPI: int = 200
    DRAWING_MIND_MAX_PAGES: int = 12

    # Adaptive format templates (JSON on disk — no external LLM)
    # Empty = backend/data/format_templates.json
    FORMAT_TEMPLATES_PATH: str = ""

    # Auth
    SECRET_KEY: str = "route-card-dev-secret-change-me"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 480
    AUTH_ENABLED: bool = True


settings = Settings()

