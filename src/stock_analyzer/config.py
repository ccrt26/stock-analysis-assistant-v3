from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping, Optional

from pydantic import BaseModel, Field, field_serializer


def _default_project_root() -> Path:
    return Path(__file__).resolve().parents[2]


class AppConfig(BaseModel):
    project_root: Path = _default_project_root()
    tushare_token: Optional[str] = Field(default=None, repr=False)
    tushare_token_path: Path = Path("/Users/ccrt/.tushare_token")
    supabase_url: Optional[str] = None
    supabase_service_role_key: Optional[str] = Field(default=None, repr=False)
    reports_dir: Path = _default_project_root() / "reports"
    fixture_mode: bool = False

    @classmethod
    def load(
        cls, env: Optional[Mapping[str, str]] = None
    ) -> "AppConfig":
        values = os.environ if env is None else env
        project_root = Path(values.get("PROJECT_ROOT", _default_project_root())).expanduser()
        reports_dir = Path(values.get("REPORTS_DIR", project_root / "reports")).expanduser()
        return cls(
            project_root=project_root,
            tushare_token=values.get("TUSHARE_TOKEN"),
            tushare_token_path=Path(
                values.get("TUSHARE_TOKEN_PATH", "/Users/ccrt/.tushare_token")
            ).expanduser(),
            supabase_url=values.get("SUPABASE_URL"),
            supabase_service_role_key=values.get("SUPABASE_SERVICE_ROLE_KEY"),
            reports_dir=reports_dir,
            fixture_mode=_env_flag(values, "STOCK_ANALYZER_FIXTURE_MODE"),
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
