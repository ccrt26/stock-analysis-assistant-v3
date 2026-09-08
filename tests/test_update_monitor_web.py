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


def _write_calendar(root: Path, rows: list[tuple[str, bool]], *, full: bool = True) -> None:
    """写本地 SSE 交易日历；full=True 时先给 2026 年全年周一至周五开市的底表，
    再用 rows 覆盖。full=False 用于构造覆盖不足的场景（T14）。"""
    base_rows: list[tuple[str, bool]] = []
    if full:
        from datetime import date as _date, timedelta as _timedelta

        day = _date(2026, 6, 1)
        while day <= _date(2026, 12, 31):
            base_rows.append((day.isoformat(), day.weekday() < 5))
            day += _timedelta(days=1)
    base_rows.extend(rows)
    frame = pd.DataFrame(
        [
            {"exchange": "SSE", "cal_date": day, "is_open": is_open}
            for day, is_open in base_rows
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
    payload = updater.parse_payload(html)
    return None if payload is None else payload.get("analysis_date")


@pytest.fixture(autouse=True)
def _hermetic_renderer(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(renderer, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        renderer, "SELECTION_DIR", tmp_path / "local_archive" / "forward_selection"
    )


def test_trace_change_triggers_rerender(tmp_path: Path) -> None:
    monitor_dir = tmp_path / "local_archive" / "forward_monitor"
    selection_dir = tmp_path / "local_archive" / "forward_selection"
    _write_day(monitor_dir, "2026-09-02")
    _write_calendar(tmp_path, [("2026-09-03", True)])
    assert _run(tmp_path, "2026-09-03") == 0
    selection_dir.mkdir(parents=True, exist_ok=True)
    trace_path = selection_dir / "research-trace-2026-09-02.json"
    trace_path.write_text('{"formation_date": "2026-09-02"}', encoding="utf-8")
    assert _run(tmp_path, "2026-09-03") == 0  # 轨迹纳入哈希：变化触发重渲染
    log_text = (monitor_dir / updater.LOG_NAME).read_text(encoding="utf-8")
    assert log_text.count("rendered=2026-09-02") == 2


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


def test_calendar_coverage_gap_fails_render(tmp_path: Path) -> None:
    """T14：日历覆盖不足 → 渲染明确失败（exit 1），不发布页面，不拿行情目录补日历。"""
    monitor_dir = tmp_path / "local_archive" / "forward_monitor"
    _write_day(monitor_dir, "2026-09-02")
    _write_calendar(tmp_path, [("2026-08-31", True)], full=False)  # 只有一条，覆盖不足
    assert _run(tmp_path, "2026-09-02") == 1
    log_text = (monitor_dir / updater.LOG_NAME).read_text(encoding="utf-8")
    assert "交易日历" in log_text and "status=error" in log_text
    assert not (monitor_dir / updater.INDEX_NAME).exists()


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


def test_renderer_source_change_rebuilds_latest_only(tmp_path: Path) -> None:
    """T47：渲染源码变化 → 只重建最新入口，不重算历史日（F12）。"""
    monitor_dir = tmp_path / "local_archive" / "forward_monitor"
    _write_day(monitor_dir, "2026-09-01")
    _write_day(monitor_dir, "2026-09-02")
    _write_calendar(tmp_path, [("2026-09-03", True)])
    assert _run(tmp_path, "2026-09-03") == 0
    log_text = (monitor_dir / updater.LOG_NAME).read_text(encoding="utf-8")
    baseline_counts = {d: log_text.count(f"rendered={d}") for d in ("2026-09-01", "2026-09-02")}
    assert baseline_counts == {"2026-09-01": 1, "2026-09-02": 1}
    # 模拟源码签名变化：直接改状态文件中记录的签名（不真的改源码）。
    state_path = monitor_dir / updater.STATE_NAME
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["renderer_sha256"] = "stale-signature"
    state_path.write_text(json.dumps(state), encoding="utf-8")
    assert _run(tmp_path, "2026-09-03") == 0
    log_text = (monitor_dir / updater.LOG_NAME).read_text(encoding="utf-8")
    # 只有最新日期 2026-09-02 重渲染一次；历史日不重做。
    assert log_text.count("rendered=2026-09-02") == 2
    assert log_text.count("rendered=2026-09-01") == 1
    # 最新 index 已更新，历史日期未发布新页面。
    assert _index_date(monitor_dir) == "2026-09-02"
    assert not (monitor_dir / "monitor-report-2026-09-01.html").exists()


def test_validate_rendered_parses_reformatted_payload(tmp_path: Path) -> None:
    """T46：模板排版/换行变化但 JSON 不变 → 载荷校验仍正确，不依赖 `;\\nconst DATES`。"""
    day = date(2026, 9, 2)
    payload = {"analysis_date": "2026-09-02", "stocks": [{"code": "600000.SH"}]}
    page_json = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    reformatted = (
        "<html><body><script>\n  const   DATA =\n" + page_json + "\n;\n\n"
        "  const   DATES   =  DATA.dates ;\n</script></body></html>"
    )
    html_path = tmp_path / "index.html"
    html_path.write_text(reformatted, encoding="utf-8")
    ok, stocks = updater.validate_rendered(html_path, day)
    assert ok is True and stocks == 1
    broken = html_path.read_text(encoding="utf-8").replace("2026-09-02", "2026-09-01")
    html_path.write_text(broken, encoding="utf-8")
    assert updater.validate_rendered(html_path, day)[0] is False
