from pathlib import Path

from stock_analyzer.config import AppConfig
from stock_analyzer.data.health import (
    HealthItem,
    HealthReport,
    HealthStatus,
    run_health_checks,
)


def test_config_uses_home_tushare_token_path_when_env_missing():
    config = AppConfig.load(env={})
    assert config.tushare_token_path == Path("/Users/ccrt/.tushare_token")
    assert config.supabase_url is None
    assert config.supabase_service_role_key is None


def test_health_report_has_four_required_categories():
    config = AppConfig.load(env={})
    report = run_health_checks(config)
    categories = {item.category for item in report.items}
    assert categories == {"credential", "network", "api_response", "field_consumability"}
    assert all(
        item.status in {HealthStatus.OK, HealthStatus.WARN, HealthStatus.FAIL} for item in report.items
    )


def test_health_report_as_lines_renders_status_values():
    report = HealthReport(
        items=[
            HealthItem(category="credential", status=HealthStatus.OK, message="checked local token path"),
            HealthItem(category="network", status=HealthStatus.WARN, message="network probe not executed in unit mode"),
            HealthItem(category="api_response", status=HealthStatus.FAIL, message="supabase env checked"),
        ]
    )
    lines = report.as_lines()
    assert lines == [
        "credential: ok - checked local token path",
        "network: warn - network probe not executed in unit mode",
        "api_response: fail - supabase env checked",
    ]
    assert all("HealthStatus." not in line for line in lines)
