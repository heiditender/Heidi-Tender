from __future__ import annotations

from functools import lru_cache
from pathlib import Path
import sys

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from .core_bridge import repo_root_from_here


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Heidi Tender API"
    api_prefix: str = "/api/v1"
    database_url: str = "postgresql+psycopg://suisse:suisse@postgres:5432/suisse_bid_match"

    project_root: Path = Field(default_factory=repo_root_from_here)
    core_main_path: Path | None = None
    core_pipeline_config_path: Path | None = None
    default_field_rules_path: Path | None = None
    core_python_executable: str = sys.executable

    jobs_root: Path | None = None

    upload_file_limit_bytes: int = 50 * 1024 * 1024
    upload_zip_limit_bytes: int = 200 * 1024 * 1024
    upload_uncompressed_limit_bytes: int = 500 * 1024 * 1024
    upload_max_files: int = 1000

    max_concurrent_jobs: int = 2
    scan_interval_seconds: float = 1.0
    sse_heartbeat_seconds: int = 15
    startup_retry_timeout_seconds: float = 45.0
    startup_retry_interval_seconds: float = 2.0

    # Core MySQL access (direct connection)
    pim_mysql_host: str = "127.0.0.1"
    pim_mysql_port: int = 3306
    pim_mysql_user: str = "root"
    pim_mysql_password: str = "root"
    pim_mysql_db: str = "pim_raw"
    pim_schema_tables: str = "vw_bid_products,vw_bid_specs"

    openai_api_key: str | None = None
    openai_base_url: str = "https://api.openai.com/v1"
    openai_model: str = "gpt-5-mini"

    core_skip_kb_bootstrap: bool = False

    cors_allowed_origins: str = "http://localhost:3000,http://127.0.0.1:3000,https://heiditender.ch,https://www.heiditender.ch"
    auth_session_cookie_name: str = "__Host-heidi_session"
    auth_oauth_cookie_name: str = "__Host-heidi_oauth"
    auth_session_secret: str = "change-me"
    auth_public_base_url: str = "http://localhost:8000"
    auth_frontend_base_url: str = "http://localhost:3000"
    auth_google_client_id: str | None = None
    auth_google_client_secret: str | None = None
    auth_google_redirect_uri: str | None = None
    auth_microsoft_client_id: str | None = None
    auth_microsoft_client_secret: str | None = None
    auth_microsoft_redirect_uri: str | None = None
    auth_magic_link_sender_email: str | None = None
    auth_resend_api_key: str | None = None
    auth_magic_link_base_url: str | None = None
    auth_magic_link_subject: str = "Your Heidi Tender sign-in link"
    auth_session_idle_timeout_seconds: int = 24 * 60 * 60
    auth_session_absolute_timeout_seconds: int = 14 * 24 * 60 * 60
    auth_magic_link_ttl_seconds: int = 15 * 60
    auth_magic_link_requests_per_email_window: int = 5
    auth_magic_link_requests_per_ip_window: int = 10
    auth_rate_limit_window_seconds: int = 15 * 60
    auth_http_timeout_seconds: float = 10.0

    @field_validator("project_root", mode="before")
    @classmethod
    def _normalize_project_root(cls, value: str | Path) -> Path:
        return Path(value).resolve()

    @field_validator("core_main_path", mode="before")
    @classmethod
    def _default_core_main(cls, value: str | Path | None, info) -> Path:
        if value:
            return Path(value).resolve()
        project_root = Path(info.data.get("project_root") or repo_root_from_here())
        return (project_root / "src" / "core" / "main.py").resolve()

    @field_validator("core_pipeline_config_path", mode="before")
    @classmethod
    def _default_pipeline_config(cls, value: str | Path | None, info) -> Path:
        if value:
            return Path(value).resolve()
        project_root = Path(info.data.get("project_root") or repo_root_from_here())
        return (project_root / "src" / "pipeline.yaml").resolve()

    @field_validator("default_field_rules_path", mode="before")
    @classmethod
    def _default_field_rules(cls, value: str | Path | None, info) -> Path:
        if value:
            return Path(value).resolve()
        project_root = Path(info.data.get("project_root") or repo_root_from_here())
        return (project_root / "src" / "field_rules.json").resolve()

    @field_validator("jobs_root", mode="before")
    @classmethod
    def _default_jobs_root(cls, value: str | Path | None, info) -> Path:
        if value:
            return Path(value).resolve()
        project_root = Path(info.data.get("project_root") or repo_root_from_here())
        return (project_root / "src" / "web" / "backend" / "data" / "jobs").resolve()

    @property
    def mysql_schema_tables(self) -> list[str]:
        tables = [item.strip() for item in self.pim_schema_tables.split(",") if item.strip()]
        # Force migration target tables even when a stale .env still points to legacy match_* tables.
        if any(name.startswith("match_") for name in tables):
            return ["vw_bid_products", "vw_bid_specs"]
        return tables

    @property
    def allowed_openai_models(self) -> list[str]:
        return ["gpt-5.4", "gpt-5-mini"]

    @property
    def cors_allowed_origin_list(self) -> list[str]:
        return [item.strip().rstrip("/") for item in self.cors_allowed_origins.split(",") if item.strip()]

    @property
    def trusted_web_origins(self) -> set[str]:
        origins = set(self.cors_allowed_origin_list)
        origins.add(self.auth_public_base_url.rstrip("/"))
        origins.add(self.auth_frontend_base_url.rstrip("/"))
        return {item for item in origins if item}

    @property
    def google_redirect_uri(self) -> str:
        if self.auth_google_redirect_uri:
            return self.auth_google_redirect_uri
        return f"{self.auth_public_base_url.rstrip('/')}{self.api_prefix}/auth/callback/google"

    @property
    def microsoft_redirect_uri(self) -> str:
        if self.auth_microsoft_redirect_uri:
            return self.auth_microsoft_redirect_uri
        return f"{self.auth_public_base_url.rstrip('/')}{self.api_prefix}/auth/callback/microsoft"

    @property
    def magic_link_base_url(self) -> str:
        if self.auth_magic_link_base_url:
            return self.auth_magic_link_base_url.rstrip("/")
        return self.auth_public_base_url.rstrip("/")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings()
    settings.jobs_root.mkdir(parents=True, exist_ok=True)
    return settings
