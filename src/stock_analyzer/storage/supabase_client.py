from __future__ import annotations

from typing import Any, TYPE_CHECKING

from stock_analyzer.config import AppConfig

if TYPE_CHECKING:
    from supabase import Client


def create_supabase_client(config: AppConfig) -> Any:
    if not config.supabase_url or not config.supabase_service_role_key:
        raise ValueError(
            "SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are required for Supabase writes"
        )

    from supabase import create_client

    return create_client(config.supabase_url, config.supabase_service_role_key)
