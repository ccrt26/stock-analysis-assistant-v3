from __future__ import annotations

import json
from datetime import date, datetime, timezone

import pytest

from stock_analyzer.config import AppConfig
from stock_analyzer.ops.publish import (
    PublishCandidate,
    PublishConfig,
    PublishFailureClass,
    PublishMode,
    PublishPreflightError,
    PublishState,
    PublishStatus,
    load_publish_candidate,
    preflight_publish,
)
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
