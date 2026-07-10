from pathlib import Path

from stock_analyzer.config import AppConfig
from stock_analyzer.data.health import (
    HealthItem,
    HealthReport,
    HealthStatus,
    run_health_checks,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def read_project_file(relative_path: str) -> str:
    return (PROJECT_ROOT / relative_path).read_text(encoding="utf-8")


def capability_level(capability_id: str) -> str:
    matrix = read_project_file("docs/operations/production-capability-matrix.md")
    prefix = f"| `{capability_id}` |"
    row = next(line for line in matrix.splitlines() if line.startswith(prefix))
    return row.split("|")[5].strip().strip("`")


def test_config_uses_home_tushare_token_path_when_env_missing():
    config = AppConfig.load(env={})
    expected_project_root = PROJECT_ROOT
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
    gitignore = read_project_file(".gitignore")
    entries = {line.strip() for line in gitignore.splitlines()}

    assert "logs/" in entries
    assert "dist/" in entries


def test_operations_docs_capture_phase1_runbook_requirements():
    runbook = read_project_file("docs/operations/runbook.md")
    cloudflare_pages = read_project_file("docs/operations/cloudflare-pages.md")
    capability_matrix = read_project_file("docs/operations/production-capability-matrix.md")
    combined_docs = "\n".join([runbook, cloudflare_pages, capability_matrix])

    assert "18:30" in combined_docs
    assert "19:00" in combined_docs
    assert "19:30" in combined_docs
    assert "cleanup-before-retry" in combined_docs
    assert "skipped_non_trading_day" in combined_docs
    assert "wrangler pages deploy dist/pages" in cloudflare_pages
    assert "`STRAT-001`" in capability_matrix
    assert "`SAFE-001`" in capability_matrix


def test_phase2_cloudflare_automation_docs_are_present():
    cloudflare_pages = read_project_file("docs/operations/cloudflare-pages.md")
    capability_matrix = read_project_file("docs/operations/production-capability-matrix.md")
    readme = read_project_file("README.md")

    assert "stock-analyzer-publish" in cloudflare_pages
    assert "第一次发布成功" in cloudflare_pages
    assert "自动转为全自动" in cloudflare_pages
    assert "last known good" in cloudflare_pages.lower()
    assert "不要打印、复制、提交或记录" in cloudflare_pages
    assert "`PUB-002`" in capability_matrix
    assert "`PUB-003`" in capability_matrix
    assert "Phase 2 Cloudflare automation" in readme


def test_operations_docs_link_from_readme_and_gate_manual_actions():
    readme = read_project_file("README.md")
    runbook = read_project_file("docs/operations/runbook.md")
    cloudflare_pages = read_project_file("docs/operations/cloudflare-pages.md")

    assert "docs/operations/runbook.md" in readme
    assert "docs/operations/cloudflare-pages.md" in readme
    assert "docs/operations/production-capability-matrix.md" in readme
    assert "Do not enable launchd without explicit approval." in runbook
    assert "Do not run a real production job without explicit approval." in runbook
    assert "Do not deploy Cloudflare Pages without explicit approval." in cloudflare_pages


def test_readme_links_only_canonical_current_status_and_active_runbooks():
    readme = read_project_file("README.md")

    assert "docs/operations/production-capability-matrix.md" in readme
    assert "mandatory-next-phases.md" not in readme


def test_historical_specs_and_plans_disclaim_current_status_authority():
    for directory in ("docs/superpowers/specs", "docs/superpowers/plans"):
        for path in (PROJECT_ROOT / directory).glob("*.md"):
            assert "production-capability-matrix.md" in path.read_text(encoding="utf-8")


def test_deprecated_mandatory_next_phases_file_is_removed():
    assert not (PROJECT_ROOT / "docs/operations/mandatory-next-phases.md").exists()


def test_active_docs_say_program_offline_ready_but_live_actions_not_executed():
    readme = read_project_file("README.md")
    runbook = read_project_file("docs/operations/runbook.md")
    design = read_project_file(
        "docs/superpowers/specs/2026-07-10-v3-formal-report-data-readiness-design.md"
    )

    for document in (readme, runbook, design):
        assert "正式生产程序已完成实现并通过默认入口离线验证" in document
        assert "尚未执行真实数据读取" in document


def test_matrix_default_factory_and_route_rows_match_verified_evidence():
    offline_verified = (
        "GOV-002",
        "GOV-003",
        "DATA-001",
        "DATA-002",
        "DATA-003",
        "DATA-004",
        "DATA-005",
        "DATA-006",
        "DATA-007",
        "DATA-008",
        "DATA-009",
        "DATA-010",
        "PIPE-002",
        "PIPE-006",
        "PIPE-007",
        "PIPE-008",
        "PIPE-009",
        "STORE-001",
        "ACT-001",
        "REPORT-001",
        "REPORT-002",
        "REPORT-003",
        "OPS-001",
        "OPS-003",
    )

    assert {capability_id: capability_level(capability_id) for capability_id in offline_verified} == {
        capability_id: "OFFLINE_VERIFIED" for capability_id in offline_verified
    }


def test_matrix_does_not_claim_live_read_supabase_write_launchd_or_publish():
    assert capability_level("DATA-011") == "BLOCKED"
    assert capability_level("STORE-002") == "IMPLEMENTED_UNVERIFIED"
    assert capability_level("STORE-003") == "IMPLEMENTED_UNVERIFIED"
    assert capability_level("OPS-002") == "BLOCKED"
    assert capability_level("PUB-003") == "BLOCKED"
    assert capability_level("SAFE-001") == "NOT_APPLICABLE"
