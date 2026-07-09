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


def test_storage_governance_paths_and_thresholds_default_to_project_root(tmp_path):
    config = AppConfig.load({"PROJECT_ROOT": str(tmp_path)})

    assert config.local_warehouse_dir == tmp_path / "local_warehouse"
    assert config.local_archive_dir == tmp_path / "local_archive"
    assert config.supabase_warn_mb == 350
    assert config.supabase_stop_mb == 400


def test_storage_governance_paths_can_be_overridden(tmp_path):
    config = AppConfig.load(
        {
            "PROJECT_ROOT": str(tmp_path),
            "LOCAL_WAREHOUSE_DIR": str(tmp_path / "warehouse-custom"),
            "LOCAL_ARCHIVE_DIR": str(tmp_path / "archive-custom"),
            "SUPABASE_WARN_MB": "321",
            "SUPABASE_STOP_MB": "399",
        }
    )

    assert config.local_warehouse_dir == tmp_path / "warehouse-custom"
    assert config.local_archive_dir == tmp_path / "archive-custom"
    assert config.supabase_warn_mb == 321
    assert config.supabase_stop_mb == 399


def test_config_supports_explicit_fixture_mode_env():
    config = AppConfig.load(env={"STOCK_ANALYZER_FIXTURE_MODE": "1"})

    assert config.fixture_mode is True


def test_health_report_has_four_required_categories():
    config = AppConfig.load(env={})
    report = run_health_checks(config)
    categories = {item.category for item in report.items}
    assert categories == {"credential", "network", "api_response", "field_consumability"}
    assert all(
        item.status in {HealthStatus.OK, HealthStatus.WARN, HealthStatus.FAIL} for item in report.items
    )


def test_health_report_accepts_env_tushare_token_without_exposing_value(tmp_path):
    config = AppConfig.load(
        env={
            "TUSHARE_TOKEN": "env-token-456",
            "TUSHARE_TOKEN_PATH": str(tmp_path / "missing-token"),
        }
    )

    report = run_health_checks(config)
    credential_item = next(item for item in report.items if item.category == "credential")
    rendered = "\n".join(report.as_lines())

    assert credential_item.status is HealthStatus.OK
    assert "present:env" in credential_item.message
    assert "env-token-456" not in rendered


def test_health_check_masks_tushare_token_without_resolving(monkeypatch):
    monkeypatch.setenv("TUSHARE_TOKEN", "secret-token-value")

    def forbidden_resolve(self):
        raise AssertionError("default health checks must not resolve the Tushare token")

    monkeypatch.setattr(AppConfig, "resolve_tushare_token", forbidden_resolve)

    report = run_health_checks(AppConfig.load())
    lines = "\n".join(report.as_lines())

    assert "tushare_token: present:env" in lines
    assert "secret-token-value" not in lines


def test_health_check_reports_token_file_without_reading_secret(monkeypatch, tmp_path):
    token_path = tmp_path / "token"
    token_path.write_text("file-secret-token", encoding="utf-8")
    config = AppConfig.load(env={"TUSHARE_TOKEN_PATH": str(token_path)})
    original_read_text = Path.read_text

    def forbidden_read_text(self, *args, **kwargs):
        if self == token_path:
            raise AssertionError("default health checks must not read the Tushare token file")
        return original_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", forbidden_read_text)

    report = run_health_checks(config)
    lines = "\n".join(report.as_lines())

    assert "tushare_token: present:file" in lines
    assert "file-secret-token" not in lines


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


def test_generated_operation_artifacts_are_gitignored():
    gitignore = (Path(__file__).resolve().parents[1] / ".gitignore").read_text(encoding="utf-8")
    entries = {line.strip() for line in gitignore.splitlines()}

    assert "logs/" in entries
    assert "dist/" in entries
