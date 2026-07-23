from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="CARIVYO_",
        env_file=".env",
        extra="ignore",
    )

    project_root: Path = Field(
        default_factory=lambda: Path(__file__).resolve().parents[2]
    )
    data_dir: Optional[Path] = None
    host: str = "127.0.0.1"
    port: int = 8420
    bootstrap_token: Optional[str] = None
    frontend_origins: str = (
        "http://127.0.0.1:5173,http://localhost:5173,"
        "http://127.0.0.1:4173,http://localhost:4173"
    )
    max_upload_bytes: int = 10 * 1024 * 1024
    request_timeout_seconds: float = 15.0
    runtime_timeout_seconds: int = 120
    max_chat_input_tokens: int = 6000
    max_chat_output_tokens: int = 900
    max_jobs_per_source: int = 80
    connector_concurrency: int = 6
    connector_min_interval_seconds: float = 0.15
    connector_deadline_seconds: float = 60.0
    api_requests_per_minute: int = 600
    fixture_jobs_path: Optional[Path] = None
    codex_model: str = "gpt-5.6-terra"
    ollama_model: Optional[str] = None
    local_hiring_agent_enabled: bool = True
    enhancv_email: Optional[str] = None
    enhancv_password: Optional[SecretStr] = None
    enhancv_use_keychain: bool = False
    enhancv_script_path: Optional[Path] = None
    enhancv_playwright_repo: Optional[Path] = None
    enhancv_profile_dir: Optional[Path] = None
    enhancv_timeout_seconds: int = 540
    enhancv_headless: bool = False
    log_level: str = "INFO"

    @field_validator("host")
    @classmethod
    def require_loopback_host(cls, value: str) -> str:
        if value not in {"127.0.0.1", "::1", "localhost"}:
            raise ValueError("Carivyo must bind to a loopback host")
        return value

    @property
    def resolved_data_dir(self) -> Path:
        return (self.data_dir or self.project_root / ".carivyo").resolve()

    @property
    def database_path(self) -> Path:
        return self.resolved_data_dir / "carivyo.sqlite3"

    @property
    def artifacts_dir(self) -> Path:
        return self.resolved_data_dir / "artifacts"

    @property
    def runtime_dir(self) -> Path:
        return self.resolved_data_dir / "runtime"

    @property
    def resolved_enhancv_profile_dir(self) -> Path:
        return (
            self.enhancv_profile_dir
            or self.runtime_dir / "enhancv-browser-profile"
        ).expanduser().resolve()

    @property
    def resolved_enhancv_playwright_repo(self) -> Path:
        return (
            self.enhancv_playwright_repo or self.project_root / "frontend"
        ).expanduser().resolve()

    @property
    def backups_dir(self) -> Path:
        return self.resolved_data_dir / "backups"

    @property
    def allowed_origins(self) -> List[str]:
        return [item.strip() for item in self.frontend_origins.split(",") if item.strip()]

    def ensure_directories(self) -> None:
        for directory in (
            self.resolved_data_dir,
            self.artifacts_dir,
            self.runtime_dir,
            self.backups_dir,
            self.resolved_enhancv_profile_dir,
        ):
            directory.mkdir(parents=True, exist_ok=True, mode=0o700)
            directory.chmod(0o700)
