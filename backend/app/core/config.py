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


@lru_cache
def get_settings() -> Settings:
    return Settings()
