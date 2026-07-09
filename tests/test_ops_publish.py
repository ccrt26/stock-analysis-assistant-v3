from __future__ import annotations

import json
import subprocess
from datetime import date, datetime, timezone
from pathlib import Path

import pytest
from typer.testing import CliRunner

from stock_analyzer.cli import app
from stock_analyzer.config import AppConfig
from stock_analyzer.ops.artifacts import DeployArtifactError
from stock_analyzer.ops.publish import (
    PublishCandidate,
    PublishConfig,
    PublishFailureClass,
    PublishMode,
    PublishPreflightError,
    PublishState,
    PublishStatus,
    WranglerResult,
    _extract_deployment_url,
    is_auto_publish_enabled,
    load_publish_candidate,
    prepare_publish_artifact,
    preflight_publish,
    publish_report_site,
    render_publish_status_page,
    run_wrangler_deploy,
    set_auto_publish_enabled,
)
from stock_analyzer.ops.smoke import SmokeResult
from stock_analyzer.storage.capacity_guard import CapacityStatus


def test_publish_state_write_json_redacts_secret_like_text(tmp_path):
    state = PublishState(
        trade_date=date(2026, 7, 9),
        status=PublishStatus.FAILED_NEEDS_HUMAN,
        mode=PublishMode.MANUAL_ONCE,
        started_at=datetime(2026, 7, 9, 12, 0, tzinfo=timezone.utc),
        finished_at=datetime(2026, 7, 9, 12, 1, tzinfo=timezone.utc),
        published_url=None,
        report_site_url="https://stock-analysis-assistant-v3.pages.dev",
        recommendations=3,
        failure_class=PublishFailureClass.CONFIG_MISSING,
        rollback_performed=False,
        auto_publish_enabled=False,
        last_known_good_path=None,
        summary_for_user="发布失败：CLOUDFLARE_API_TOKEN=secret-value",
        user_action_required="检查 Authorization: Bearer secret-token",
        error_message_redacted="REPORT_PASSWORD=secret-password",
        checks=("preflight",),
    )

    output_path = tmp_path / "logs" / "publish" / "latest-status.json"
    state.write_json(output_path)

    payload = json.loads(output_path.read_text(encoding="utf-8"))
    rendered = json.dumps(payload, ensure_ascii=False)
    assert payload["status"] == "failed_needs_human"
    assert payload["mode"] == "manual_once"
    assert "secret-value" not in rendered
    assert "secret-token" not in rendered
    assert "secret-password" not in rendered
    assert "[REDACTED]" in rendered


def test_publish_config_from_app_config_uses_local_paths(tmp_path):
    config = AppConfig.load(
        {
            "PROJECT_ROOT": str(tmp_path),
            "REPORT_SITE_URL": "https://stock-analysis-assistant-v3.pages.dev",
            "CLOUDFLARE_PAGES_PROJECT_NAME": "stock-analysis-assistant-v3",
        }
    )

    publish_config = PublishConfig.from_app_config(config)

    assert publish_config.project_root == tmp_path
    assert publish_config.report_site_url == "https://stock-analysis-assistant-v3.pages.dev"
    assert publish_config.cloudflare_pages_project_name == "stock-analysis-assistant-v3"
    assert publish_config.state_path == tmp_path / "logs" / "publish" / "latest-status.json"
    assert publish_config.status_page_path == tmp_path / "logs" / "publish" / "status.html"
    assert publish_config.last_known_good_dir == tmp_path / "local_archive" / "publish" / "last-known-good"
    assert publish_config.auto_publish_flag_path == tmp_path / "logs" / "publish" / "auto-publish-enabled.json"


def test_render_publish_status_page_shows_only_user_summary(tmp_path):
    state = PublishState(
        trade_date=date(2026, 7, 9),
        status=PublishStatus.FAILED_NEEDS_HUMAN,
        mode=PublishMode.AUTO,
        published_url=None,
        report_site_url="https://stock-analysis-assistant-v3.pages.dev",
        recommendations=3,
        failure_class=PublishFailureClass.WRANGLER_AUTH_FAILURE,
        rollback_performed=True,
        auto_publish_enabled=True,
        last_known_good_path="/private/path/last-good",
        summary_for_user="发布失败，系统已回退上一版。",
        user_action_required="请检查 Cloudflare 凭据。",
        error_message_redacted="technical stderr should stay machine-only",
        checks=("wrangler_deployed", "smoke_failed"),
    )

    output = render_publish_status_page(state, tmp_path / "logs" / "publish" / "status.html")
    html = output.read_text(encoding="utf-8")

    assert "发布失败，系统已回退上一版。" in html
    assert "请检查 Cloudflare 凭据。" in html
    assert "https://stock-analysis-assistant-v3.pages.dev" in html
    assert "technical stderr" not in html
    assert "wrangler_deployed" not in html
    assert "/private/path" not in html


def test_render_publish_status_page_labels_ready_skipped_as_not_published(tmp_path):
    state = PublishState(
        trade_date=date(2026, 7, 11),
        status=PublishStatus.READY_SKIPPED,
        mode=PublishMode.AUTO,
        published_url=None,
        report_site_url="https://stock-analysis-assistant-v3.pages.dev",
        recommendations=None,
        failure_class=PublishFailureClass.NON_TRADING_DAY,
        rollback_performed=False,
        auto_publish_enabled=True,
        last_known_good_path=None,
        summary_for_user="今天不是交易日，不发布新报告。",
        user_action_required="今天不是交易日，不发布新报告；线上保留上一版。",
        error_message_redacted=None,
        checks=(),
    )

    output = render_publish_status_page(state, tmp_path / "status.html")
    html = output.read_text(encoding="utf-8")

    assert "最近一次发布：未发布" in html
    assert "最近一次发布：需要处理" not in html


def _write_job_status(root, payload):
    status_path = root / "logs" / "run-daily" / "latest-status.json"
    status_path.parent.mkdir(parents=True)
    status_path.write_text(json.dumps(payload), encoding="utf-8")
    return status_path


def _write_report(root, trade_date):
    reports = root / "reports"
    (reports / "daily" / trade_date.isoformat()).mkdir(parents=True)
    (reports / "index.html").write_text(f"<html>{trade_date.isoformat()}</html>", encoding="utf-8")
    (reports / "daily" / trade_date.isoformat() / "index.html").write_text(
        f"<html>{trade_date.isoformat()}</html>",
        encoding="utf-8",
    )


def _publish_config(root):
    return PublishConfig(
        project_root=root,
        report_site_url="https://stock-analysis-assistant-v3.pages.dev",
        cloudflare_pages_project_name="stock-analysis-assistant-v3",
        report_password_env="REPORT_PASSWORD",
        report_session_secret_env="REPORT_SESSION_SECRET",
        cloudflare_token_env="CLOUDFLARE_API_TOKEN",
        cloudflare_account_id_env="CLOUDFLARE_ACCOUNT_ID",
        auto_publish_flag_path=root / "logs" / "publish" / "auto-publish-enabled.json",
        state_path=root / "logs" / "publish" / "latest-status.json",
        status_page_path=root / "logs" / "publish" / "status.html",
        last_known_good_dir=root / "local_archive" / "publish" / "last-known-good",
    )


def test_load_publish_candidate_uses_today_success_with_recommendations(tmp_path):
    trade_date = date(2026, 7, 9)
    _write_report(tmp_path, trade_date)
    status_path = _write_job_status(
        tmp_path,
        {
            "trade_date": trade_date.isoformat(),
            "status": "success_with_recommendations",
            "recommendations": 3,
        },
    )

    candidate = load_publish_candidate(_publish_config(tmp_path), trade_date=trade_date)

    assert candidate == PublishCandidate(
        trade_date=trade_date,
        recommendations=3,
        job_status_path=status_path,
        reports_dir=tmp_path / "reports",
    )


def test_load_publish_candidate_accepts_ten_recommendations(tmp_path):
    trade_date = date(2026, 7, 9)
    _write_report(tmp_path, trade_date)
    _write_job_status(
        tmp_path,
        {
            "trade_date": trade_date.isoformat(),
            "status": "success_with_recommendations",
            "recommendations": 10,
        },
    )

    candidate = load_publish_candidate(_publish_config(tmp_path), trade_date=trade_date)

    assert candidate.recommendations == 10


def test_load_publish_candidate_rejects_more_than_ten_recommendations(tmp_path):
    trade_date = date(2026, 7, 9)
    _write_report(tmp_path, trade_date)
    _write_job_status(
        tmp_path,
        {
            "trade_date": trade_date.isoformat(),
            "status": "success_with_recommendations",
            "recommendations": 11,
        },
    )

    with pytest.raises(PublishPreflightError) as exc_info:
        load_publish_candidate(_publish_config(tmp_path), trade_date=trade_date)

    assert exc_info.value.failure_class is PublishFailureClass.NO_PUBLISHABLE_REPORT
    assert "推荐数" in exc_info.value.user_action_required
    assert "不要发布" in exc_info.value.user_action_required


def test_load_publish_candidate_rejects_zero_recommendations(tmp_path):
    trade_date = date(2026, 7, 9)
    _write_report(tmp_path, trade_date)
    _write_job_status(
        tmp_path,
        {
            "trade_date": trade_date.isoformat(),
            "status": "success_no_recommendations",
            "recommendations": 0,
        },
    )

    with pytest.raises(PublishPreflightError) as exc_info:
        load_publish_candidate(_publish_config(tmp_path), trade_date=trade_date)

    assert exc_info.value.failure_class is PublishFailureClass.ZERO_RECOMMENDATIONS
    assert "当天无推荐" in exc_info.value.user_action_required


def test_load_publish_candidate_rejects_non_trading_day(tmp_path):
    trade_date = date(2026, 7, 11)
    _write_job_status(
        tmp_path,
        {
            "trade_date": trade_date.isoformat(),
            "status": "skipped_non_trading_day",
            "recommendations": None,
        },
    )

    with pytest.raises(PublishPreflightError) as exc_info:
        load_publish_candidate(_publish_config(tmp_path), trade_date=trade_date)

    assert exc_info.value.failure_class is PublishFailureClass.NON_TRADING_DAY


def test_load_publish_candidate_rejects_failed_null_recommendations_as_no_publishable_report(tmp_path):
    trade_date = date(2026, 7, 9)
    _write_job_status(
        tmp_path,
        {
            "trade_date": trade_date.isoformat(),
            "status": "failed_needs_human",
            "recommendations": None,
        },
    )

    with pytest.raises(PublishPreflightError) as exc_info:
        load_publish_candidate(_publish_config(tmp_path), trade_date=trade_date)

    assert exc_info.value.failure_class is PublishFailureClass.NO_PUBLISHABLE_REPORT
    assert exc_info.value.failure_class is not PublishFailureClass.ZERO_RECOMMENDATIONS


def test_preflight_requires_local_publish_config_without_printing_secret_names(tmp_path):
    trade_date = date(2026, 7, 9)
    candidate = PublishCandidate(trade_date, 3, tmp_path / "status.json", tmp_path / "reports")

    with pytest.raises(PublishPreflightError) as exc_info:
        preflight_publish(_publish_config(tmp_path), candidate, env={})

    assert exc_info.value.failure_class is PublishFailureClass.CONFIG_MISSING
    assert "配置" in exc_info.value.user_action_required
    rendered_error = f"{exc_info.value} {exc_info.value.user_action_required}"
    assert "REPORT_PASSWORD" not in rendered_error
    assert "REPORT_SESSION_SECRET" not in rendered_error
    assert "CLOUDFLARE_API_TOKEN" not in rendered_error
    assert "CLOUDFLARE_ACCOUNT_ID" not in rendered_error


def test_preflight_requires_cloudflare_account_id_without_printing_env_name(tmp_path):
    trade_date = date(2026, 7, 9)
    candidate = PublishCandidate(trade_date, 3, tmp_path / "status.json", tmp_path / "reports")

    with pytest.raises(PublishPreflightError) as exc_info:
        preflight_publish(
            _publish_config(tmp_path),
            candidate,
            env={
                "REPORT_PASSWORD": "pw",
                "REPORT_SESSION_SECRET": "session",
                "CLOUDFLARE_API_TOKEN": "token",
            },
        )

    assert exc_info.value.failure_class is PublishFailureClass.CONFIG_MISSING
    rendered_error = f"{exc_info.value} {exc_info.value.user_action_required}"
    assert "CLOUDFLARE_ACCOUNT_ID" not in rendered_error


def test_preflight_blocks_supabase_capacity_stop(tmp_path):
    trade_date = date(2026, 7, 9)
    candidate = PublishCandidate(trade_date, 3, tmp_path / "status.json", tmp_path / "reports")
    env = {
        "REPORT_PASSWORD": "pw",
        "REPORT_SESSION_SECRET": "session",
        "CLOUDFLARE_API_TOKEN": "token",
        "CLOUDFLARE_ACCOUNT_ID": "account",
    }

    with pytest.raises(PublishPreflightError) as exc_info:
        preflight_publish(
            _publish_config(tmp_path),
            candidate,
            env=env,
            capacity_checker=lambda: CapacityStatus(size_mb=401.0, warn=True, stop_large_writes=True),
        )

    assert exc_info.value.failure_class is PublishFailureClass.SUPABASE_CAPACITY_STOP
    assert "401.0 MB" in exc_info.value.user_action_required


def test_prepare_publish_artifact_always_rebuilds_dist_pages(tmp_path):
    config = _publish_config(tmp_path)
    stale = tmp_path / "dist" / "pages" / "stale.txt"
    stale.parent.mkdir(parents=True)
    stale.write_text("stale", encoding="utf-8")

    def fake_prepare(project_root, output_dir):
        assert project_root == tmp_path
        assert output_dir == tmp_path / "dist" / "pages"
        assert not stale.exists()
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "index.html").write_text("fresh", encoding="utf-8")
        return output_dir

    artifact_dir = prepare_publish_artifact(config, prepare_artifact=fake_prepare)

    assert artifact_dir == tmp_path / "dist" / "pages"
    assert (artifact_dir / "index.html").read_text(encoding="utf-8") == "fresh"


def test_run_wrangler_deploy_invokes_official_command_without_printing_token(tmp_path):
    config = _publish_config(tmp_path)
    artifact_dir = tmp_path / "dist" / "pages"
    artifact_dir.mkdir(parents=True)
    calls = []

    def fake_runner(command, *, cwd, env, text, capture_output, check):
        calls.append((command, cwd, env, text, capture_output, check))
        return subprocess.CompletedProcess(
            command,
            0,
            stdout="Success: https://stock-analysis-assistant-v3.pages.dev",
            stderr="",
        )

    result = run_wrangler_deploy(
        config,
        artifact_dir,
        env={"CLOUDFLARE_API_TOKEN": "secret-token"},
        runner=fake_runner,
    )

    command, cwd, env, text, capture_output, check = calls[0]
    assert command == [
        "npx",
        "wrangler",
        "pages",
        "deploy",
        str(artifact_dir),
        "--project-name",
        "stock-analysis-assistant-v3",
    ]
    assert cwd == tmp_path
    assert env["CLOUDFLARE_API_TOKEN"] == "secret-token"
    assert text is True
    assert capture_output is True
    assert check is False
    assert result.exit_code == 0
    assert result.deployment_url == "https://stock-analysis-assistant-v3.pages.dev"
    assert "secret-token" not in result.stdout_redacted


def test_run_wrangler_deploy_classifies_auth_failure(tmp_path):
    config = _publish_config(tmp_path)
    artifact_dir = tmp_path / "dist" / "pages"
    artifact_dir.mkdir(parents=True)

    def fake_runner(command, *, cwd, env, text, capture_output, check):
        return subprocess.CompletedProcess(command, 1, stdout="", stderr="Authentication error")

    result = run_wrangler_deploy(
        config,
        artifact_dir,
        env={"CLOUDFLARE_API_TOKEN": "secret-token"},
        runner=fake_runner,
    )

    assert result.exit_code == 1
    assert "Authentication error" in result.stderr_redacted


def test_extract_deployment_url_prefers_pages_dev_and_ignores_docs_urls():
    text = (
        "See https://developers.cloudflare.com/pages for docs\n"
        "Published https://stock-analysis-assistant-v3.pages.dev"
    )

    assert _extract_deployment_url(text) == "https://stock-analysis-assistant-v3.pages.dev"
    assert _extract_deployment_url("See https://developers.cloudflare.com/pages") is None


def _successful_smoke(url, password, *, expected_trade_date=None):
    return SmokeResult(
        base_url=url,
        passed=True,
        checks=("redirect_to_login", "password_login", "report_date_matches"),
        failures=(),
    )


def test_auto_publish_flag_helpers_default_false_and_persist_enabled(tmp_path):
    config = _publish_config(tmp_path)

    assert is_auto_publish_enabled(config) is False

    set_auto_publish_enabled(config, True)

    assert is_auto_publish_enabled(config) is True
    assert json.loads(config.auto_publish_flag_path.read_text(encoding="utf-8")) == {"enabled": True}


def test_publish_report_site_success_saves_last_known_good_and_enables_auto(tmp_path):
    trade_date = date(2026, 7, 9)
    _write_report(tmp_path, trade_date)
    _write_job_status(
        tmp_path,
        {
            "trade_date": trade_date.isoformat(),
            "status": "success_with_recommendations",
            "recommendations": 3,
        },
    )
    config = _publish_config(tmp_path)

    def fake_prepare(project_root, output_dir):
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "index.html").write_text("fresh", encoding="utf-8")
        (output_dir / "functions").mkdir()
        (output_dir / "functions" / "_middleware.ts").write_text("export {}", encoding="utf-8")
        return output_dir

    def fake_deploy(config_arg, artifact_dir, *, env=None):
        return WranglerResult(
            0,
            "ok https://stock-analysis-assistant-v3.pages.dev",
            "",
            "https://stock-analysis-assistant-v3.pages.dev",
        )

    state = publish_report_site(
        config,
        mode=PublishMode.MANUAL_ONCE,
        trade_date=trade_date,
        env={
            "REPORT_PASSWORD": "pw",
            "REPORT_SESSION_SECRET": "session",
            "CLOUDFLARE_API_TOKEN": "token",
            "CLOUDFLARE_ACCOUNT_ID": "account",
        },
        prepare_artifact=fake_prepare,
        deploy_runner=fake_deploy,
        smoke_func=_successful_smoke,
    )

    assert state.status is PublishStatus.SUCCESS
    assert state.auto_publish_enabled is True
    assert is_auto_publish_enabled(config) is True
    assert (config.last_known_good_dir / "index.html").read_text(encoding="utf-8") == "fresh"
    assert config.state_path.exists()


@pytest.mark.parametrize(
    "leaked_content",
    [
        "<html>SUPABASE_SERVICE_ROLE_KEY</html>",
        "<html>Authorization: Bearer fake-token</html>",
    ],
)
def test_publish_report_site_blocks_secret_like_artifact_before_deploy(
    tmp_path,
    leaked_content,
):
    trade_date = date(2026, 7, 9)
    _write_report(tmp_path, trade_date)
    _write_job_status(
        tmp_path,
        {
            "trade_date": trade_date.isoformat(),
            "status": "success_with_recommendations",
            "recommendations": 3,
        },
    )
    config = _publish_config(tmp_path)
    deploy_calls = []

    def fake_prepare(project_root, output_dir):
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "index.html").write_text(leaked_content, encoding="utf-8")
        return output_dir

    def fake_deploy(config_arg, artifact_dir, *, env=None):
        deploy_calls.append(artifact_dir)
        return WranglerResult(0, "ok", "", config.report_site_url)

    state = publish_report_site(
        config,
        mode=PublishMode.MANUAL_ONCE,
        trade_date=trade_date,
        env={
            "REPORT_PASSWORD": "pw",
            "REPORT_SESSION_SECRET": "session",
            "CLOUDFLARE_API_TOKEN": "token",
            "CLOUDFLARE_ACCOUNT_ID": "account",
        },
        prepare_artifact=fake_prepare,
        deploy_runner=fake_deploy,
        smoke_func=_successful_smoke,
    )

    assert state.status is PublishStatus.FAILED_NEEDS_HUMAN
    assert state.failure_class is PublishFailureClass.SECRET_LEAK_BLOCKED
    assert deploy_calls == []
    assert config.state_path.exists()
    assert config.status_page_path.exists()
    state_text = config.state_path.read_text(encoding="utf-8")
    assert "fake-token" not in state_text
    assert "SUPABASE_SERVICE_ROLE_KEY" not in state_text
    assert "凭据" in state.user_action_required


def test_publish_report_site_writes_failure_state_for_artifact_preparation_error(tmp_path):
    trade_date = date(2026, 7, 9)
    _write_report(tmp_path, trade_date)
    _write_job_status(
        tmp_path,
        {
            "trade_date": trade_date.isoformat(),
            "status": "success_with_recommendations",
            "recommendations": 3,
        },
    )
    config = _publish_config(tmp_path)
    deploy_calls = []

    def fake_prepare(project_root, output_dir):
        raise DeployArtifactError("REPORT_PASSWORD=secret-password")

    def fake_deploy(config_arg, artifact_dir, *, env=None):
        deploy_calls.append(artifact_dir)
        return WranglerResult(0, "ok", "", config.report_site_url)

    state = publish_report_site(
        config,
        mode=PublishMode.MANUAL_ONCE,
        trade_date=trade_date,
        env={
            "REPORT_PASSWORD": "pw",
            "REPORT_SESSION_SECRET": "session",
            "CLOUDFLARE_API_TOKEN": "token",
            "CLOUDFLARE_ACCOUNT_ID": "account",
        },
        prepare_artifact=fake_prepare,
        deploy_runner=fake_deploy,
        smoke_func=_successful_smoke,
    )

    assert state.status is PublishStatus.FAILED_NEEDS_HUMAN
    assert state.failure_class is PublishFailureClass.ARTIFACT_INVALID
    assert deploy_calls == []
    assert "secret-password" not in config.state_path.read_text(encoding="utf-8")
    assert config.status_page_path.exists()


@pytest.mark.parametrize(
    "payload",
    [
        "{not valid json",
        json.dumps(
            {
                "trade_date": "2026-99-99",
                "status": "success_with_recommendations",
                "recommendations": 3,
            }
        ),
    ],
)
def test_publish_report_site_writes_failure_state_for_malformed_status_payload(
    tmp_path,
    payload,
):
    trade_date = date(2026, 7, 9)
    _write_report(tmp_path, trade_date)
    status_path = tmp_path / "logs" / "run-daily" / "latest-status.json"
    status_path.parent.mkdir(parents=True)
    status_path.write_text(payload, encoding="utf-8")
    config = _publish_config(tmp_path)
    deploy_calls = []

    def fake_deploy(config_arg, artifact_dir, *, env=None):
        deploy_calls.append(artifact_dir)
        return WranglerResult(0, "ok", "", config.report_site_url)

    state = publish_report_site(
        config,
        mode=PublishMode.AUTO,
        trade_date=trade_date,
        env={
            "REPORT_PASSWORD": "pw",
            "REPORT_SESSION_SECRET": "session",
            "CLOUDFLARE_API_TOKEN": "token",
            "CLOUDFLARE_ACCOUNT_ID": "account",
        },
        deploy_runner=fake_deploy,
        smoke_func=_successful_smoke,
    )

    assert state.status is PublishStatus.FAILED_NEEDS_HUMAN
    assert state.failure_class is PublishFailureClass.ARTIFACT_INVALID
    assert deploy_calls == []
    assert config.state_path.exists()
    assert config.status_page_path.exists()


def test_publish_report_site_rolls_back_last_known_good_when_smoke_fails(tmp_path):
    trade_date = date(2026, 7, 9)
    _write_report(tmp_path, trade_date)
    _write_job_status(
        tmp_path,
        {
            "trade_date": trade_date.isoformat(),
            "status": "success_with_recommendations",
            "recommendations": 3,
        },
    )
    config = _publish_config(tmp_path)
    config.last_known_good_dir.mkdir(parents=True)
    (config.last_known_good_dir / "index.html").write_text("last good", encoding="utf-8")
    deploy_calls = []
    smoke_calls = []

    def fake_prepare(project_root, output_dir):
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "index.html").write_text("new", encoding="utf-8")
        return output_dir

    def fake_deploy(config_arg, artifact_dir, *, env=None):
        deploy_calls.append(artifact_dir)
        return WranglerResult(0, "ok", "", config.report_site_url)

    def fake_smoke(url, password, *, expected_trade_date=None):
        smoke_calls.append(expected_trade_date)
        if len(smoke_calls) == 1:
            return SmokeResult(url, False, ("redirect_to_login",), ())
        return SmokeResult(url, True, ("redirect_to_login",), ())

    state = publish_report_site(
        config,
        mode=PublishMode.AUTO,
        trade_date=trade_date,
        env={
            "REPORT_PASSWORD": "pw",
            "REPORT_SESSION_SECRET": "session",
            "CLOUDFLARE_API_TOKEN": "token",
            "CLOUDFLARE_ACCOUNT_ID": "account",
        },
        prepare_artifact=fake_prepare,
        deploy_runner=fake_deploy,
        smoke_func=fake_smoke,
    )

    assert state.status is PublishStatus.FAILED_NEEDS_HUMAN
    assert state.failure_class is PublishFailureClass.SMOKE_FAILED
    assert state.rollback_performed is True
    assert deploy_calls[-1] == config.last_known_good_dir
    assert "已回退" in state.summary_for_user


def test_publish_report_site_retries_wrangler_once_for_temporary_failure(tmp_path):
    trade_date = date(2026, 7, 9)
    _write_report(tmp_path, trade_date)
    _write_job_status(
        tmp_path,
        {
            "trade_date": trade_date.isoformat(),
            "status": "success_with_recommendations",
            "recommendations": 3,
        },
    )
    config = _publish_config(tmp_path)
    calls = []

    def fake_prepare(project_root, output_dir):
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "index.html").write_text("fresh", encoding="utf-8")
        return output_dir

    def flaky_deploy(config_arg, artifact_dir, *, env=None):
        calls.append(artifact_dir)
        if len(calls) == 1:
            return WranglerResult(1, "", "Network timeout", None)
        return WranglerResult(0, "ok", "", config.report_site_url)

    state = publish_report_site(
        config,
        mode=PublishMode.AUTO,
        trade_date=trade_date,
        env={
            "REPORT_PASSWORD": "pw",
            "REPORT_SESSION_SECRET": "session",
            "CLOUDFLARE_API_TOKEN": "token",
            "CLOUDFLARE_ACCOUNT_ID": "account",
        },
        prepare_artifact=fake_prepare,
        deploy_runner=flaky_deploy,
        smoke_func=_successful_smoke,
    )

    assert len(calls) == 2
    assert state.status is PublishStatus.SUCCESS


def test_ops_publish_report_site_cli_outputs_simple_success(monkeypatch, tmp_path):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv(
        "REPORT_SITE_URL",
        "https://stock-analysis-assistant-v3.pages.dev",
    )
    monkeypatch.setenv(
        "CLOUDFLARE_PAGES_PROJECT_NAME",
        "stock-analysis-assistant-v3",
    )
    sentinel_capacity_checker = object()
    monkeypatch.setattr(
        "stock_analyzer.cli.build_publish_capacity_checker",
        lambda config: sentinel_capacity_checker,
        raising=False,
    )

    def fake_publish(config, *, mode, trade_date=None, notify_enabled=False, **kwargs):
        assert kwargs["capacity_checker"] is sentinel_capacity_checker
        return PublishState(
            trade_date=date(2026, 7, 9),
            status=PublishStatus.SUCCESS,
            mode=mode,
            published_url=config.report_site_url,
            report_site_url=config.report_site_url,
            recommendations=3,
            failure_class=None,
            rollback_performed=False,
            auto_publish_enabled=True,
            last_known_good_path=str(config.last_known_good_dir),
            summary_for_user=(
                "发布成功：线上报告 2026-07-09，"
                "链接：https://stock-analysis-assistant-v3.pages.dev"
            ),
            user_action_required=None,
            error_message_redacted=None,
            checks=("ok",),
        )

    monkeypatch.setattr("stock_analyzer.cli.publish_report_site", fake_publish)

    result = CliRunner().invoke(app, ["ops", "publish-report-site"])

    assert result.exit_code == 0
    assert "发布成功：线上报告 2026-07-09" in result.output
    assert "checks" not in result.output


def test_pyproject_registers_stock_analyzer_publish_command():
    pyproject = Path("pyproject.toml").read_text(encoding="utf-8")

    assert "stock-analyzer-publish" in pyproject
    assert "stock_analyzer.cli:stock_analyzer_publish" in pyproject
