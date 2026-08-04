from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping

from pydantic import BaseModel, Field, field_serializer


_CNINFO_DEFAULT_TIMEOUT_SECONDS = 20.0
_CNINFO_DEFAULT_MAX_RETRIES = 2


def _default_project_root() -> Path:
    return Path(__file__).resolve().parents[2]


class AppConfig(BaseModel):
    project_root: Path = _default_project_root()
    tushare_token: str | None = Field(default=None, repr=False)
    tushare_token_path: Path = Path.home() / ".tushare_token"
    local_warehouse_dir: Path = _default_project_root() / "local_warehouse"
    local_archive_dir: Path = _default_project_root() / "local_archive"
    cninfo_base_url: str = "https://www.cninfo.com.cn"
    cninfo_timeout_seconds: float = Field(
        default=_CNINFO_DEFAULT_TIMEOUT_SECONDS,
        gt=0,
    )
    cninfo_max_retries: int = Field(
        default=_CNINFO_DEFAULT_MAX_RETRIES,
        ge=0,
    )

    @classmethod
    def load(cls, env: Mapping[str, str] | None = None) -> "AppConfig":
        values = os.environ if env is None else env
        project_root = Path(
            values.get("PROJECT_ROOT", _default_project_root())
        ).expanduser()
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
            local_warehouse_dir=local_warehouse_dir,
            local_archive_dir=local_archive_dir,
            cninfo_base_url=values.get(
                "CNINFO_BASE_URL",
                "https://www.cninfo.com.cn",
            ),
            cninfo_timeout_seconds=float(
                values.get(
                    "CNINFO_TIMEOUT_SECONDS",
                    _CNINFO_DEFAULT_TIMEOUT_SECONDS,
                )
            ),
            cninfo_max_retries=int(
                values.get("CNINFO_MAX_RETRIES", _CNINFO_DEFAULT_MAX_RETRIES)
            ),
        )

    @property
    def research_warehouse_path(self) -> Path:
        return self.local_warehouse_dir / "research.duckdb"

    @property
    def research_facts_dir(self) -> Path:
        return self.local_warehouse_dir / "facts"

    def resolve_tushare_token(self) -> str | None:
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

    @field_serializer("tushare_token")
    def _serialize_secret(self, value: str | None) -> str | None:
        return "**********" if _clean_secret(value) else None


def _clean_secret(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None
