"""Application settings — 12-factor, env-driven (prefix ``PULSEOS_``).

Defaults target the local docker-compose stack (infra/docker-compose.yml) so a fresh
checkout runs with no .env at all. Every variable is documented in the root .env.example.
Secrets never get real defaults.
"""

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="PULSEOS_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "PulseOS"
    environment: Literal["local", "test", "staging", "production"] = "local"
    debug: bool = True
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    database_url: str = "postgresql+asyncpg://pulseos:pulseos@localhost:5432/pulseos"
    redis_url: str = "redis://localhost:6379/0"

    # Path to a Firebase service-account JSON (ADR-011). None -> Application Default
    # Credentials. Without either, auth endpoints answer 503; the rest of the API works.
    firebase_credentials_file: str | None = None

    # Browser origins allowed to call the API (the three portal dev servers by default).
    # Env format is JSON: PULSEOS_CORS_ORIGINS=["https://patient.example.com"]
    cors_origins: list[str] = [
        "http://localhost:5173",
        "http://localhost:5174",
        "http://localhost:5175",
    ]

    s3_endpoint_url: str = "http://localhost:9000"
    s3_access_key: str = "pulseos"
    s3_secret_key: str = "pulseos-local-secret"
    s3_bucket_records: str = "pulseos-records"
    # MinIO ignores the region but boto3 requires one; real S3 uses it for signing.
    s3_region: str = "us-east-1"
    # Presigned download URLs are short-lived by design (docs/SECURITY.md: minutes).
    s3_presign_ttl_seconds: int = 300

    # Record uploads: hard size cap enforced before anything is stored (15 MiB).
    records_max_upload_bytes: int = 15 * 1024 * 1024

    # Rate limiting (ADR-024). Off installs a limiter that allows everything, which is what
    # tests and credential-free dev use; bucket names are still validated either way.
    rate_limit_enabled: bool = True
    # Overrides for app/core/ratelimit.py's DEFAULT_LIMITS, as "limit/window-seconds" per
    # bucket. Env format is JSON, like cors_origins:
    #   PULSEOS_RATE_LIMITS={"patient_lookup":"40/60"}
    # Only the named buckets change; the rest keep their defaults.
    rate_limits: dict[str, str] = {}

    # AI Provider configuration (ADR-007)
    ai_provider: Literal["fake", "gemini"] = "fake"
    ai_model: str = "gemini-3.8-flash"
    gemini_api_key: str | None = None
    gemini_timeout_seconds: float = 30.0


@lru_cache
def get_settings() -> Settings:
    return Settings()
