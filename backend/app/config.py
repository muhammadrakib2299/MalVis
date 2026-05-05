"""Runtime configuration. Read once at startup, frozen for the process lifetime."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    host: str = "0.0.0.0"
    port: int = 8000
    log_level: str = "info"
    environment: str = "development"

    cors_allowed_origins: str = "http://localhost:3000"

    max_upload_bytes: int = 10 * 1024 * 1024
    rate_limit_scan: str = "10/minute"
    rate_limit_global: str = "100/day"

    model_manifest_path: Path = Path("../artifacts/MANIFEST.json")
    artifacts_dir: Path = Path("../artifacts")
    use_mock_models: bool = True

    hash_cache_max_entries: int = 1000
    hash_cache_ttl_seconds: int = 3600

    # Extractor strategy: "inprocess" (default — fastest, no isolation) or
    # "subprocess" (forks the worker per request, OS-level isolation, ~30 ms
    # extra latency). Production deploy is "subprocess" with the worker
    # running inside the hardened sidecar container; tests stay "inprocess".
    extractor_strategy: str = "inprocess"
    extractor_timeout_seconds: int = 30
    extractor_memory_mb: int = 512
    extractor_cpu_seconds: int = 30

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_allowed_origins.split(",") if o.strip()]

    @property
    def is_production(self) -> bool:
        return self.environment.lower() == "production"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
