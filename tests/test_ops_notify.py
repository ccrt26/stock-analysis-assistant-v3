from __future__ import annotations

import plistlib
from importlib import import_module
from datetime import date
from pathlib import Path

import pytest

from stock_analyzer.ops.status import JobStatus, RunStatus


PROJECT_ROOT = Path(__file__).resolve().parents[1]
LAUNCHD_TEMPLATE = (
    PROJECT_ROOT / "ops" / "launchd" / "com.ccrt.stock-analysis-assistant.daily.plist.example"
)


def _status(run_status: RunStatus) -> JobStatus:
    return JobStatus(
        trade_date=date(2026, 7, 9),
        attempt=1,
        scheduled_slot="18:30",
        status=run_status,
        stage="complete",
    )


def _notify_module():
    try:
        return import_module("stock_analyzer.ops.notify")
    except ModuleNotFoundError as exc:
        pytest.fail(f"stock_analyzer.ops.notify must exist: {exc}")


def test_should_notify_only_for_human_intervention_failure():
    notify = _notify_module()

    assert notify.should_notify(_status(RunStatus.FAILED_NEEDS_HUMAN)) is True

    quiet_statuses = [
        RunStatus.SUCCESS_WITH_RECOMMENDATIONS,
        RunStatus.SUCCESS_NO_RECOMMENDATIONS,
        RunStatus.WARNING,
        RunStatus.FAILED_RETRYABLE,
        RunStatus.SKIPPED_NON_TRADING_DAY,
    ]

    for run_status in quiet_statuses:
        assert notify.should_notify(_status(run_status)) is False


def test_notify_mac_disabled_does_not_call_osascript(monkeypatch):
    notify = _notify_module()

    def forbidden_run(*args, **kwargs):
        raise AssertionError("unit tests must not call osascript")

    monkeypatch.setattr("subprocess.run", forbidden_run)

    notify.notify_mac("Title", "Message", enabled=False)


def test_notify_mac_redacts_text_before_invoking_osascript(monkeypatch):
    notify = _notify_module()
    calls = []

    def capture_run(args, **kwargs):
        calls.append((args, kwargs))

    monkeypatch.setattr("subprocess.run", capture_run)

    notify.notify_mac(
        "API_KEY=service-role-secret",
        "Authorization: Bearer bearer-secret ACCESS_TOKEN=tushare-secret",
        enabled=True,
    )

    assert len(calls) == 1
    args, kwargs = calls[0]
    rendered = " ".join(args)
    assert args[:2] == ["osascript", "-e"]
    assert kwargs["check"] is False
    assert "service-role-secret" not in rendered
    assert "bearer-secret" not in rendered
    assert "tushare-secret" not in rendered
    assert "[REDACTED]" in rendered


def test_launchd_template_is_example_only_and_covers_daily_slots():
    assert LAUNCHD_TEMPLATE.exists()

    payload = plistlib.loads(LAUNCHD_TEMPLATE.read_bytes())

    assert LAUNCHD_TEMPLATE.name.endswith(".plist.example")
    assert payload["Label"] == "com.ccrt.stock-analysis-assistant.daily"
    assert payload.get("RunAtLoad") is False
    assert payload.get("KeepAlive") in (None, False)

    schedule = {
        (entry["Hour"], entry["Minute"])
        for entry in payload["StartCalendarInterval"]
    }
    assert schedule == {(18, 30), (19, 0), (19, 30)}


def test_launchd_template_uses_project_root_and_env_contract_without_secrets():
    assert LAUNCHD_TEMPLATE.exists()

    template = LAUNCHD_TEMPLATE.read_text(encoding="utf-8")

    assert "__PROJECT_ROOT__" in template
    assert "/Users/" not in template
    assert ".env.local" in template
    assert "service-role-secret" not in template
    assert "tushare-secret" not in template
    assert "cloudflare-secret" not in template
    assert "report-password-secret" not in template
    assert "session-secret" not in template
