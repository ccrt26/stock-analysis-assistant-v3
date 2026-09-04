"""update_monitor_web 的测试：日历闸门、增量检测、单地址 index.html 维护与状态自愈。"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from tools import render_monitor_web as renderer
from tools import update_monitor_web as updater


def _episode(episode_id: str, ts_code: str, name: str, analysis_date: str) -> dict:
    return {
        "episode_id": episode_id,
        "ts_code": ts_code,
        "name": name,
        "role": "selected",
        "selection_output_class": "confirmed_active",
        "original_opportunity_type": "sector_diffusion",
        "original_engine_type": "sector_broad_diffusion",
        "original_engine_status": "active",
        "original_priority": 1,
        "action_date": analysis_date,
        "formation_date": analysis_date,
        "analysis_date": analysis_date,
        "day_number": 1,
        "monitor_phase": "primary",
        "formal_return_started": False,
        "entry_open": None,
        "data_limitations": [],
        "new_announcements": [],
        "original_group_code": "",
        "previous_monitor_state": None,
        "previous_episode_review": None,
        "original_research_thesis": {},
        "frozen_twenty_day_review": None,
        "pair_context": None,
    }


def _write_day(monitor_dir: Path, day: str, *, with_ledger: bool = True) -> None:
    snapshot = {
        "snapshot_version": "forward-monitor-snapshot-v1",
        "analysis_date": day,
        "as_of": f"{day}T21:00:00+08:00",
        "episodes": [_episode("e1", "600000.SH", "示例股份", day)],
    }
    report = {
        "report_version": "daily-forward-monitor-report-v2",
        "analysis_date": day,
        "as_of": f"{day}T21:00:00+08:00",
        "alerts": [],
    }
    monitor_dir.mkdir(parents=True, exist_ok=True)
    (monitor_dir / f"snapshot-{day}.json").write_text(
        json.dumps(snapshot, ensure_ascii=False), encoding="utf-8"
    )
    (monitor_dir / f"monitor-report-{day}.json").write_text(
        json.dumps(report, ensure_ascii=False), encoding="utf-8"
    )
    if with_ledger:
        ledger = {
            "ledger_version": "daily-formal-reviews-v1",
            "analysis_date": day,
            "as_of": f"{day}T21:00:00+08:00",
            "reviews": [],
        }
        (monitor_dir / f"daily-formal-reviews-{day}.json").write_text(
            json.dumps(ledger, ensure_ascii=False), encoding="utf-8"
        )


def _write_calendar(root: Path, rows: list[tuple[str, bool]]) -> None:
    frame = pd.DataFrame(
        [
            {"exchange": "SSE", "cal_date": day, "is_open": is_open}
            for day, is_open in rows
        ]
    )
    for day, _ in rows:
        year = day[:4]
        day_dir = root / "local_warehouse" / "facts" / "trade_calendar" / f"cal_year={year}"
        day_dir.mkdir(parents=True, exist_ok=True)
        subset = frame[frame["cal_date"].str.startswith(year)]
        subset.to_parquet(day_dir / "data.parquet")


def _run(root: Path, today: str, *extra: str) -> int:
    return updater.main(
        ["--today", today, "--project-root", str(root), "--monitor-dir", str(root / "local_archive" / "forward_monitor"), *extra]
    )


def _index_date(monitor_dir: Path) -> str | None:
    html = (monitor_dir / updater.INDEX_NAME).read_text(encoding="utf-8")
    return json.loads(
        html.split("DATA = ", 1)[1].split(";\nconst DATES", 1)[0].replace("<\\/", "</")
    ).get("analysis_date")


@pytest.fixture(autouse=True)
def _hermetic_renderer(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(renderer, "PROJECT_ROOT", tmp_path)


def test_first_run_writes_single_index_for_latest_day(tmp_path: Path) -> None:
    monitor_dir = tmp_path / "local_archive" / "forward_monitor"
    _write_day(monitor_dir, "2026-09-01")
    _write_day(monitor_dir, "2026-09-02")
    _write_calendar(tmp_path, [("2026-09-03", True)])
    exit_code = _run(tmp_path, "2026-09-03")
    assert exit_code == 0
    # 只有一个 WEB 地址：index.html = 最新日期；不再生成日期命名页面
    assert _index_date(monitor_dir) == "2026-09-02"
    assert not (monitor_dir / "monitor-report-2026-09-01.html").exists()
    assert not (monitor_dir / "monitor-report-2026-09-02.html").exists()
    state = json.loads((monitor_dir / updater.STATE_NAME).read_text(encoding="utf-8"))
    assert sorted(state["published"]) == ["2026-09-01", "2026-09-02"]
    log_text = (monitor_dir / updater.LOG_NAME).read_text(encoding="utf-8")
    assert "status=ok" in log_text


def test_second_run_is_noop(tmp_path: Path) -> None:
    monitor_dir = tmp_path / "local_archive" / "forward_monitor"
    _write_day(monitor_dir, "2026-09-02")
    _write_calendar(tmp_path, [("2026-09-03", True)])
    assert _run(tmp_path, "2026-09-03") == 0
    index_path = monitor_dir / updater.INDEX_NAME
    first_mtime = index_path.stat().st_mtime_ns
    assert _run(tmp_path, "2026-09-03") == 0
    assert index_path.stat().st_mtime_ns == first_mtime
    log_text = (monitor_dir / updater.LOG_NAME).read_text(encoding="utf-8")
    assert log_text.rstrip().endswith("无新增日报，等待 codex 或手动处理")


def test_changed_old_date_rerenders_but_keeps_index_on_latest(tmp_path: Path) -> None:
    monitor_dir = tmp_path / "local_archive" / "forward_monitor"
    _write_day(monitor_dir, "2026-09-01")
    _write_day(monitor_dir, "2026-09-02")
    _write_calendar(tmp_path, [("2026-09-03", True)])
    assert _run(tmp_path, "2026-09-03") == 0
    index_path = monitor_dir / updater.INDEX_NAME
    index_mtime = index_path.stat().st_mtime_ns
    report_path = monitor_dir / "monitor-report-2026-09-01.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report["routine_summary"] = "修订内容"
    report_path.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
    assert _run(tmp_path, "2026-09-03") == 0
    log_text = (monitor_dir / updater.LOG_NAME).read_text(encoding="utf-8")
    assert log_text.count("rendered=2026-09-01") == 2
    assert log_text.count("rendered=2026-09-02") == 1
    # 旧日期修订不覆盖统一地址
    assert index_path.stat().st_mtime_ns == index_mtime
    assert _index_date(monitor_dir) == "2026-09-02"


def test_incomplete_latest_day_waits_for_manual(tmp_path: Path) -> None:
    monitor_dir = tmp_path / "local_archive" / "forward_monitor"
    _write_day(monitor_dir, "2026-09-01")
    _write_calendar(tmp_path, [("2026-09-02", True)])
    assert _run(tmp_path, "2026-09-02") == 0  # 先发布 09-01
    # 最新一天只有快照，没有报告：codex 未完成
    snapshot_only = {
        "snapshot_version": "forward-monitor-snapshot-v1",
        "analysis_date": "2026-09-02",
        "episodes": [],
    }
    (monitor_dir / "snapshot-2026-09-02.json").write_text(
        json.dumps(snapshot_only, ensure_ascii=False), encoding="utf-8"
    )
    assert _run(tmp_path, "2026-09-02") == 0
    log_text = (monitor_dir / updater.LOG_NAME).read_text(encoding="utf-8")
    assert "报告未完成" in log_text and "2026-09-02" in log_text
    assert _index_date(monitor_dir) == "2026-09-01"


def test_closed_calendar_day_skips(tmp_path: Path) -> None:
    monitor_dir = tmp_path / "local_archive" / "forward_monitor"
    _write_day(monitor_dir, "2026-09-02")
    _write_calendar(tmp_path, [("2026-09-02", True), ("2026-10-01", False)])
    assert _run(tmp_path, "2026-09-02") == 0  # 首跑发布
    assert _run(tmp_path, "2026-10-01") == 0  # 休市日
    log_text = (monitor_dir / updater.LOG_NAME).read_text(encoding="utf-8")
    assert "休市，不启动" in log_text


def test_calendar_uncovered_weekday_warns_and_proceeds(tmp_path: Path) -> None:
    monitor_dir = tmp_path / "local_archive" / "forward_monitor"
    _write_day(monitor_dir, "2026-09-02")
    _write_calendar(tmp_path, [("2026-08-31", True)])  # 日历不含 2026-09-02（周三）
    assert _run(tmp_path, "2026-09-02") == 0
    log_text = (monitor_dir / updater.LOG_NAME).read_text(encoding="utf-8")
    assert "gate=uncovered" in log_text and "周一至周五候选" in log_text


def test_corrupted_state_rebuilds(tmp_path: Path) -> None:
    monitor_dir = tmp_path / "local_archive" / "forward_monitor"
    _write_day(monitor_dir, "2026-09-02")
    _write_calendar(tmp_path, [("2026-09-03", True)])
    assert _run(tmp_path, "2026-09-03") == 0
    (monitor_dir / updater.STATE_NAME).write_text("{not-json", encoding="utf-8")
    assert _run(tmp_path, "2026-09-03") == 0  # 自愈：全量重渲染并重建状态
    state = json.loads((monitor_dir / updater.STATE_NAME).read_text(encoding="utf-8"))
    assert "2026-09-02" in state["published"]
    assert _index_date(monitor_dir) == "2026-09-02"


def test_render_failure_keeps_state_and_index(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monitor_dir = tmp_path / "local_archive" / "forward_monitor"
    _write_day(monitor_dir, "2026-09-01")
    _write_day(monitor_dir, "2026-09-02")
    _write_calendar(tmp_path, [("2026-09-03", True)])
    assert _run(tmp_path, "2026-09-03") == 0
    index_mtime = (monitor_dir / updater.INDEX_NAME).stat().st_mtime_ns

    def broken_render(argv):
        raise RuntimeError("renderer boom")

    monkeypatch.setattr(renderer, "main", broken_render)
    (monitor_dir / "snapshot-2026-09-04.json").write_text("{}", encoding="utf-8")
    (monitor_dir / "monitor-report-2026-09-04.json").write_text("{}", encoding="utf-8")
    assert _run(tmp_path, "2026-09-03") == 1  # 新日期渲染失败
    state = updater.load_state(monitor_dir / updater.STATE_NAME)
    assert "2026-09-04" not in state["published"]
    assert (monitor_dir / updater.INDEX_NAME).stat().st_mtime_ns == index_mtime
    assert not list(monitor_dir.glob("*.tmp"))  # 临时文件已清理
    log_text = (monitor_dir / updater.LOG_NAME).read_text(encoding="utf-8")
    assert "status=error" in log_text and "renderer boom" in log_text


def test_force_rerenders_published_dates(tmp_path: Path) -> None:
    monitor_dir = tmp_path / "local_archive" / "forward_monitor"
    _write_day(monitor_dir, "2026-09-02")
    _write_calendar(tmp_path, [("2026-09-03", True)])
    assert _run(tmp_path, "2026-09-03") == 0
    assert _run(tmp_path, "2026-09-03", "--force") == 0
    log_text = (monitor_dir / updater.LOG_NAME).read_text(encoding="utf-8")
    assert log_text.count("rendered=2026-09-02") == 2
    assert _index_date(monitor_dir) == "2026-09-02"


def test_index_self_heal_when_missing(tmp_path: Path) -> None:
    monitor_dir = tmp_path / "local_archive" / "forward_monitor"
    _write_day(monitor_dir, "2026-09-02")
    _write_calendar(tmp_path, [("2026-09-03", True)])
    assert _run(tmp_path, "2026-09-03") == 0
    (monitor_dir / updater.INDEX_NAME).unlink()
    assert _run(tmp_path, "2026-09-03") == 0  # 自愈：无新增也会重建统一地址
    assert _index_date(monitor_dir) == "2026-09-02"
    log_text = (monitor_dir / updater.LOG_NAME).read_text(encoding="utf-8")
    assert "rebuilt index.html" in log_text


def test_index_self_heal_failure_returns_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monitor_dir = tmp_path / "local_archive" / "forward_monitor"
    _write_day(monitor_dir, "2026-09-02")
    _write_calendar(tmp_path, [("2026-09-03", True)])
    assert _run(tmp_path, "2026-09-03") == 0
    (monitor_dir / updater.INDEX_NAME).unlink()

    def broken_render(argv):
        raise RuntimeError("renderer boom")

    monkeypatch.setattr(renderer, "main", broken_render)
    assert _run(tmp_path, "2026-09-03") == 1
    assert not (monitor_dir / updater.INDEX_NAME).exists()
    log_text = (monitor_dir / updater.LOG_NAME).read_text(encoding="utf-8")
    assert "index.html 重建失败" in log_text
