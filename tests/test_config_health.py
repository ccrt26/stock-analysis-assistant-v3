from pathlib import Path

from stock_analyzer.config import AppConfig


def test_config_loads_only_current_local_data_settings(tmp_path):
    project_root = tmp_path / "project"
    warehouse = tmp_path / "warehouse"
    archive = tmp_path / "archive"
    token_path = tmp_path / "tushare-token"

    config = AppConfig.load(
        {
            "PROJECT_ROOT": str(project_root),
            "LOCAL_WAREHOUSE_DIR": str(warehouse),
            "LOCAL_ARCHIVE_DIR": str(archive),
            "TUSHARE_TOKEN": "secret-token",
            "TUSHARE_TOKEN_PATH": str(token_path),
            "CNINFO_BASE_URL": "https://example.test",
            "CNINFO_TIMEOUT_SECONDS": "12.5",
            "CNINFO_MAX_RETRIES": "4",
        }
    )

    assert config.project_root == project_root
    assert config.local_warehouse_dir == warehouse
    assert config.local_archive_dir == archive
    assert config.tushare_token_path == token_path
    assert config.resolve_tushare_token() == "secret-token"
    assert config.cninfo_base_url == "https://example.test"
    assert config.cninfo_timeout_seconds == 12.5
    assert config.cninfo_max_retries == 4
    assert config.research_warehouse_path == warehouse / "research.duckdb"
    assert config.research_facts_dir == warehouse / "facts"


def test_config_has_no_retired_cloud_report_or_supabase_settings():
    config = AppConfig.load({"PROJECT_ROOT": str(Path("/tmp/project"))})

    retired_fields = {
        "supabase_url",
        "supabase_service_role_key",
        "supabase_warn_mb",
        "supabase_stop_mb",
        "reports_dir",
        "fixture_mode",
        "notify_mac",
        "report_site_url",
        "cloudflare_pages_project_name",
        "report_password_env",
        "report_session_secret_env",
        "cloudflare_token_env",
        "cloudflare_account_id_env",
        "cloudflare_pages_branch",
        "cninfo_calls_per_minute",
    }

    assert retired_fields.isdisjoint(type(config).model_fields)


def test_serialized_config_never_exposes_tushare_token():
    config = AppConfig.load(
        {
            "PROJECT_ROOT": "/tmp/project",
            "TUSHARE_TOKEN": "secret-token",
        }
    )

    assert config.model_dump()["tushare_token"] == "**********"
    assert "secret-token" not in config.model_dump_json()
