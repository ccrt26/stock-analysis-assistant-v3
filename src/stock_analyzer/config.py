from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping, Optional

from pydantic import BaseModel, Field, field_serializer

from stock_analyzer.data.formal_policy import (
    CNINFO_DEFAULT_CALLS_PER_MINUTE,
    CNINFO_DEFAULT_MAX_RETRIES,
    CNINFO_DEFAULT_TIMEOUT_SECONDS,
)


def _default_project_root() -> Path:
    return Path(__file__).resolve().parents[2]


class AppConfig(BaseModel):
    project_root: Path = _default_project_root()
    tushare_token: Optional[str] = Field(default=None, repr=False)
    tushare_token_path: Path = Path.home() / ".tushare_token"
    supabase_url: Optional[str] = None
    supabase_service_role_key: Optional[str] = Field(default=None, repr=False)
    reports_dir: Path = _default_project_root() / "reports"
    local_warehouse_dir: Path = _default_project_root() / "local_warehouse"
    local_archive_dir: Path = _default_project_root() / "local_archive"
    supabase_warn_mb: float = 350
    supabase_stop_mb: float = 400
    fixture_mode: bool = False
    notify_mac: bool = False
    report_site_url: Optional[str] = None
    cloudflare_pages_project_name: Optional[str] = None
    report_password_env: str = "REPORT_PASSWORD"
    report_session_secret_env: str = "REPORT_SESSION_SECRET"
    cloudflare_token_env: str = "CLOUDFLARE_API_TOKEN"
    cloudflare_account_id_env: str = "CLOUDFLARE_ACCOUNT_ID"
    cloudflare_pages_branch: str = "main"
    cninfo_base_url: str = "https://www.cninfo.com.cn"
    cninfo_calls_per_minute: int = Field(
        default=CNINFO_DEFAULT_CALLS_PER_MINUTE,
        gt=0,
    )
    cninfo_timeout_seconds: float = Field(
        default=CNINFO_DEFAULT_TIMEOUT_SECONDS,
        gt=0,
    )
    cninfo_max_retries: int = Field(
        default=CNINFO_DEFAULT_MAX_RETRIES,
        ge=0,
    )

    @classmethod
    def load(
        cls, env: Optional[Mapping[str, str]] = None
    ) -> "AppConfig":
        values = os.environ if env is None else env
        project_root = Path(values.get("PROJECT_ROOT", _default_project_root())).expanduser()
        reports_dir = Path(values.get("REPORTS_DIR", project_root / "reports")).expanduser()
        local_warehouse_dir = Path(
            values.get("LOCAL_WAREHOUSE_DIR", project_root / "local_warehouse")
        ).expanduser()
        local_archive_dir = Path(
            values.get("LOCAL_ARCHIVE_DIR", project_root / "local_archive")
        ).expanduser()
        return cls(
            project_root=project_root,
            tushare_token=values.get("TUSHARE_TOKEN"),
            tushare_token_path=Path(
                values.get("TUSHARE_TOKEN_PATH", Path.home() / ".tushare_token")
            ).expanduser(),
            supabase_url=values.get("SUPABASE_URL"),
            supabase_service_role_key=values.get("SUPABASE_SERVICE_ROLE_KEY"),
            reports_dir=reports_dir,
            local_warehouse_dir=local_warehouse_dir,
            local_archive_dir=local_archive_dir,
            supabase_warn_mb=float(values.get("SUPABASE_WARN_MB", 350)),
            supabase_stop_mb=float(values.get("SUPABASE_STOP_MB", 400)),
            fixture_mode=_env_flag(values, "STOCK_ANALYZER_FIXTURE_MODE"),
            notify_mac=_env_flag(values, "STOCK_ANALYZER_NOTIFY_MAC"),
            report_site_url=values.get("REPORT_SITE_URL"),
            cloudflare_pages_project_name=values.get("CLOUDFLARE_PAGES_PROJECT_NAME"),
            report_password_env=values.get("REPORT_PASSWORD_ENV", "REPORT_PASSWORD"),
            report_session_secret_env=values.get(
                "REPORT_SESSION_SECRET_ENV",
                "REPORT_SESSION_SECRET",
            ),
            cloudflare_token_env=values.get("CLOUDFLARE_TOKEN_ENV", "CLOUDFLARE_API_TOKEN"),
            cloudflare_account_id_env=values.get(
                "CLOUDFLARE_ACCOUNT_ID_ENV",
                "CLOUDFLARE_ACCOUNT_ID",
            ),
            cloudflare_pages_branch=values.get("CLOUDFLARE_PAGES_BRANCH", "main"),
            cninfo_base_url=values.get(
                "CNINFO_BASE_URL",
                "https://www.cninfo.com.cn",
            ),
            cninfo_calls_per_minute=int(
                values.get(
                    "CNINFO_CALLS_PER_MINUTE",
                    CNINFO_DEFAULT_CALLS_PER_MINUTE,
                )
            ),
            cninfo_timeout_seconds=float(
                values.get(
                    "CNINFO_TIMEOUT_SECONDS",
                    CNINFO_DEFAULT_TIMEOUT_SECONDS,
                )
            ),
            cninfo_max_retries=int(
                values.get("CNINFO_MAX_RETRIES", CNINFO_DEFAULT_MAX_RETRIES)
            ),
        )

    @property
    def has_supabase_config(self) -> bool:
        return bool(self.supabase_url and _clean_secret(self.supabase_service_role_key))

    def resolve_tushare_token(self) -> Optional[str]:
        env_token = _clean_secret(self.tushare_token)
        if env_token:
            return env_token
        if self.tushare_token_path.exists():
            token = self.tushare_token_path.read_text(encoding="utf-8").strip()
            return token or None
        return None

    def tushare_token_status(self) -> str:
        if _clean_secret(self.tushare_token):
            return "present:env"
        if self.tushare_token_path.exists() and self.tushare_token_path.read_text(
            encoding="utf-8"
        ).strip():
            return "present:file"
        return "missing"

    @field_serializer("tushare_token", "supabase_service_role_key")
    def _serialize_secret(self, value: Optional[str]) -> Optional[str]:
        return "**********" if _clean_secret(value) else None


def _env_flag(values: Mapping[str, str], name: str) -> bool:
    return str(values.get(name, "")).strip().lower() in {"1", "true", "yes", "on"}


def _clean_secret(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None
