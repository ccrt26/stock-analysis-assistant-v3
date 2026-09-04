import json
from datetime import datetime
from types import SimpleNamespace

import pandas as pd
import pytest

from stock_analyzer.ops import preopen_safety as safety


def _fixture(tmp_path, monkeypatch, *, open_day=True, trace=True, announcements=None, suspended=None, fail=False,
             checked_at="2026-09-07T08:45:00+08:00"):
    archive = tmp_path / "local_archive"
    root = archive / "forward_selection"
    root.mkdir(parents=True)
    config = SimpleNamespace(local_archive_dir=archive, local_warehouse_dir=tmp_path / "warehouse")
    original = {
        "trace_version": "daily-research-trace-v4",
        "formation_date": "2026-09-04", "action_date": "2026-09-07",
        "as_of": "2026-09-06T18:30:00+08:00",
        "research_result": {"selected_stocks": [
            {"ts_code": "000001.SZ", "name": "正式股"},
            {"ts_code": "600000.SH", "name": "条件股"},
        ]},
        "candidate_ledger": [
            {"ts_code": "000001.SZ", "final_fate": "selected", "research_thesis": {
                "engine_type": "event_repricing_confirmed", "engine_status": "active",
                "market_recognition": {"status": "confirmed"}}},
            {"ts_code": "600000.SH", "final_fate": "selected", "research_thesis": {
                "engine_type": "fresh_event_pending", "engine_status": "conditional",
                "market_recognition": {"status": "pending"}}},
        ],
    }
    if trace:
        (root / "research-trace-2026-09-04.json").write_text(json.dumps(original))
    (root / "forward.csv").write_text("immutable selection")
    monitor = archive / "forward_monitor"
    monitor.mkdir()
    (monitor / "monitor-report-2026-09-04.json").write_text("immutable review")
    before = {path: path.read_bytes() for path in archive.rglob("*") if path.is_file()}
    calls = []
    def endpoint(name, **kwargs):
        assert name == "suspend_d"
        assert kwargs == {"trade_date": "20260907"}
        calls.append(name)
        if fail:
            raise RuntimeError("suspension source unavailable")
        return pd.DataFrame(suspended or [])
    def backfill(**kwargs):
        calls.append("announcements")
        assert kwargs["start"].isoformat() == "2026-09-06"
        assert kwargs["through"].isoformat() == "2026-09-07"
        return SimpleNamespace(capabilities={"announcement_status": "cninfo_complete"})
    class Warehouse:
        def read_current(self, dataset):
            assert str(dataset.value) == "announcement"
            return pd.DataFrame(announcements or [])
        def commit_batch(self, *_):
            pytest.fail("safety must not write suspension facts")
    runtime = SimpleNamespace(
        warehouse=Warehouse(), tushare=SimpleNamespace(call=endpoint),
        cninfo=object(), exchange_announcements=None,
    )
    monkeypatch.setattr(safety, "LocalForwardData", lambda *args: SimpleNamespace(trading_day_status=lambda _: open_day))
    monkeypatch.setattr(safety, "EventBackfillService", lambda *args, **kwargs: SimpleNamespace(backfill_announcements=backfill))
    result = safety.prepare_preopen_safety(
        config, clock=lambda: datetime.fromisoformat(checked_at),
        build_runtime=lambda _: runtime,
    )
    assert all(path.read_bytes() == contents for path, contents in before.items())
    output = archive / "preopen_safety/preopen-safety-2026-09-07.json"
    assert json.loads(output.read_text()) == result
    assert result["output_path"] == str(output)
    return result, calls


@pytest.mark.parametrize("open_day,trace,status", [
    (False, True, "no_action_day"), (True, False, "no_formal_trace"),
    (True, True, "no_new_changes"), (None, True, "data_limited"),
])
def test_safety_status_and_no_unnecessary_fetch(tmp_path, monkeypatch, open_day, trace, status):
    result, calls = _fixture(tmp_path, monkeypatch, open_day=open_day, trace=trace)
    assert result["status"] == status
    if status != "no_new_changes":
        assert calls == []


def test_safety_reads_only_watched_new_announcements_and_current_suspensions(tmp_path, monkeypatch):
    rows = [{"ts_code": code, "available_at": at, "title": "公告", "announcement_time": at}
            for code, at in [
                ("000001.SZ", "2026-09-06T18:30:00+08:00"),
                ("000001.SZ", "2026-09-06T18:30:01+08:00"),
                ("600000.SH", "2026-09-07T08:45:00+08:00"),
                ("600000.SH", "2026-09-07T08:45:01+08:00"),
                ("999999.SZ", "2026-09-07T08:00:00+08:00"),
            ]]
    result, calls = _fixture(tmp_path, monkeypatch, announcements=rows, suspended=[
        {"ts_code": "000001.SZ", "suspend_type": "S"},
        {"ts_code": "600000.SH", "suspend_type": "R"},
        {"ts_code": "999999.SZ", "suspend_type": "S"},
    ])
    assert result["status"] == "changes_found"
    assert [row["ts_code"] for row in result["watched_stocks"]] == ["000001.SZ", "600000.SH"]
    assert [row["is_formal_recommendation"] for row in result["watched_stocks"]] == [True, False]
    assert len(result["new_announcements"]) == 2
    assert [row["ts_code"] for row in result["suspended_stocks"]] == ["000001.SZ"]
    assert calls == ["announcements", "suspend_d"]


def test_safety_source_failure_is_not_no_changes(tmp_path, monkeypatch):
    result, _ = _fixture(tmp_path, monkeypatch, fail=True)
    assert result["status"] == "data_limited"
    assert "suspension" in ";".join(result["limitations"])


def test_safety_allows_last_second_before_open(tmp_path, monkeypatch):
    result, calls = _fixture(tmp_path, monkeypatch, checked_at="2026-09-07T09:29:59+08:00")
    assert result["status"] == "no_new_changes"
    assert calls == ["announcements", "suspend_d"]


@pytest.mark.parametrize("checked_at", ["2026-09-07T09:30:00+08:00",
                                       "2026-09-07T10:00:00+08:00"])
@pytest.mark.parametrize("trace", [True, False])
def test_late_safety_is_invalid_without_fetch_or_formal_changes(tmp_path, monkeypatch, checked_at, trace):
    result, calls = _fixture(tmp_path, monkeypatch, checked_at=checked_at, trace=trace)
    assert result["status"] == "data_limited"
    assert "安全检查启动时已经开盘，不能作为开盘前提醒" in ";".join(result["limitations"])
    assert calls == []
    assert result["new_announcements"] == result["suspended_stocks"] == []


def test_closed_day_takes_precedence_over_late_safety(tmp_path, monkeypatch):
    result, calls = _fixture(tmp_path, monkeypatch, open_day=False,
                             checked_at="2026-09-07T10:00:00+08:00")
    assert result["status"] == "no_action_day"
    assert calls == []
    assert result["limitations"] == []
