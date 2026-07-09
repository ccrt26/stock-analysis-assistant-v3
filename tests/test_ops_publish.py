from __future__ import annotations

import json
from datetime import date, datetime, timezone

from stock_analyzer.config import AppConfig
from stock_analyzer.ops.publish import (
    PublishConfig,
    PublishFailureClass,
    PublishMode,
    PublishState,
    PublishStatus,
)


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
