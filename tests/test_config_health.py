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
    expected_project_root = Path(__file__).resolve().parents[1]
    assert config.project_root == expected_project_root
    assert config.reports_dir == expected_project_root / "reports"
    assert config.tushare_token_path == Path.home() / ".tushare_token"
    assert config.supabase_url is None
    assert config.supabase_service_role_key is None


def test_config_supports_project_root_and_reports_dir_overrides(tmp_path):
    project_root = tmp_path / "project"
    reports_dir = tmp_path / "custom-reports"

    config = AppConfig.load(
        env={
            "PROJECT_ROOT": str(project_root),
            "REPORTS_DIR": str(reports_dir),
            "TUSHARE_TOKEN_PATH": str(tmp_path / "token"),
        }
    )

    assert config.project_root == project_root
    assert config.reports_dir == reports_dir
    assert config.tushare_token_path == tmp_path / "token"


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
