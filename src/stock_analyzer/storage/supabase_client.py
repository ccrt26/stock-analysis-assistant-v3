from __future__ import annotations

from supabase import Client, create_client

from stock_analyzer.config import AppConfig


def create_supabase_client(config: AppConfig) -> Client:
    if not config.supabase_url or not config.supabase_service_role_key:
        raise ValueError(
            "SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are required for Supabase writes"
        )
    return create_client(config.supabase_url, config.supabase_service_role_key)
