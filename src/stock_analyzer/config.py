from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping, Optional

from pydantic import BaseModel


class AppConfig(BaseModel):
    project_root: Path = Path("/Users/ccrt/股票分析助手")
    tushare_token_path: Path = Path("/Users/ccrt/.tushare_token")
    supabase_url: Optional[str] = None
    supabase_service_role_key: Optional[str] = None
    reports_dir: Path = Path("/Users/ccrt/股票分析助手/reports")

    @classmethod
    def load(
        cls, env: Optional[Mapping[str, str]] = None
    ) -> "AppConfig":
        values = os.environ if env is None else env
        return cls(
            tushare_token_path=Path(
                values.get("TUSHARE_TOKEN_PATH", "/Users/ccrt/.tushare_token")
            ),
            supabase_url=values.get("SUPABASE_URL"),
            supabase_service_role_key=values.get("SUPABASE_SERVICE_ROLE_KEY"),
        )
