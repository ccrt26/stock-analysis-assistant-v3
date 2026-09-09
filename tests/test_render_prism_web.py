"""render_prism_web 的最小充分测试：成品源文件完整性、渲染合同、市场附加与 CLI 输出。"""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import date
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PRISM_ROOT = PROJECT_ROOT / "tools" / "guanlan-prism"
SAMPLE_DATA = PRISM_ROOT / "data" / "snapshot.json"

# 展示层成品必须原样入库的源文件（.gitignore 只豁免 data/、dist/、index.html）。
PRISM_SOURCES = [
    "src/shell.html",
    "src/base.css",
    "src/prism.css",
    "src/v3.css",
    "src/core.js",
    "src/rules.js",
    "src/app.js",
    "src/effects.js",
    "tools/build.py",
    "tools/adapt_snapshot.py",
]


def _load_prism_builder():
    spec = importlib.util.spec_from_file_location(
        "guanlan_prism_build_test", PRISM_ROOT / "tools" / "build.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_prism_sources_present() -> None:
    for rel in PRISM_SOURCES:
        assert (PRISM_ROOT / rel).is_file(), f"missing vendored source: {rel}"
    builder = _load_prism_builder()
    html = builder.render_html({"analysis_date": "2026-09-07", "dates": ["09-07"],
                                "market": [3000.0], "stocks": []})
    # 单文件版内联资源，不残留外链；CSS 必须保持 base → prism → v3 的加载顺序。
    for ref in ("base.css", "prism.css", "v3.css", "rules.js", "app.js"):
        assert f'src="{ref}"' not in html and f'href="{ref}"' not in html
    base_marker = '--sans:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC"'
    prism_marker = "--bg: #070910"
    v3_marker = ".market-grid {grid-template-columns:repeat(var(--market-count,4)"
    assert base_marker in html and prism_marker in html and v3_marker in html
    assert html.index(base_marker) < html.index(prism_marker) < html.index(v3_marker)
    # 规则模块先于应用脚本注入。
    assert html.index("PRISM V3 · Display policy") < html.index("PRISM V3 standalone presentation")


@pytest.mark.skipif(
    not SAMPLE_DATA.is_file(), reason="sample snapshot stays local (git-ignored)"
)
def test_render_html_embeds_payload_verbatim() -> None:
    builder = _load_prism_builder()
    snapshot = json.loads(SAMPLE_DATA.read_text(encoding="utf-8"))
    html = builder.render_html(snapshot)
    assert "观澜 · 光场 PRISM" in html
    assert '<script id="snapshot" type="application/json">' in html
    # V3 无演示分支：输入按原样内联，不注入 demoShowcase 之类的展示偏好。
    assert "demoShowcase" not in html.split('<script id="snapshot"')[1].split("</script>")[0]


def test_cli_renders_with_market_enrichment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    """CLI 复用 build_payload 真实数据；无本地指数时如实缺失，不伪造行情。"""
    sys.path.insert(0, str(PROJECT_ROOT / "tools"))
    try:
        from tools import render_monitor_web as renderer
        from tools import render_prism_web as prism_cli
    except ImportError:
        import render_monitor_web as renderer  # type: ignore[no-redef]
        import render_prism_web as prism_cli  # type: ignore[no-redef]

    payload = {
        "analysis_date": "2026-01-05",
        "as_of": "2026-01-04T18:30:00+08:00",
        "market_name": "上证指数",
        # 跨年快照：完整 ISO sessionDates 定位（E1/T09）；dates 仅作旧布局显示。
        "sessionDates": ["2025-12-30", "2026-01-02", "2026-01-05"],
        "dates": ["12-30", "01-02", "01-05"],
        "market": [4000.0, 4010.0, None],
        "date_files": [],
        "review_dates": ["2026-01-05"],
        "stocks": [],
    }
    monkeypatch.setattr(renderer, "MONITOR_DIR", tmp_path)
    monkeypatch.setattr(renderer, "resolve_date", lambda monitor_dir, requested: date(2026, 1, 5))
    monkeypatch.setattr(
        renderer,
        "load_artifacts",
        lambda monitor_dir, day: ({}, {}, monitor_dir / "r.json", monitor_dir / "s.json"),
    )
    monkeypatch.setattr(renderer, "build_payload", lambda *args, **kwargs: payload)
    # 屏蔽本地事实仓读取：无数据时页面保持“快照未提供”。
    monkeypatch.setattr(renderer, "_read_day_frames", lambda root, name, day, cutoff: None)

    out = tmp_path / "prism-report-2026-01-05.html"
    rc = prism_cli.main(["--out", str(out)])
    assert rc == 0
    assert out.is_file()
    text = out.read_text(encoding="utf-8")
    embedded = json.loads(text.split('<script id="snapshot" type="application/json">')[1].split("</script>")[0])
    assert embedded["analysis_date"] == "2026-01-05"
    assert embedded["presentation"]["marketCodes"] == [
        "000001.SH", "399001.SZ", "399006.SZ", "000688.SH",
    ]
    assert embedded["presentation"]["deepLimit"] == 8
    # 无本地指数行时不得编造 marketIndices。
    assert "marketIndices" not in embedded
    printed = capsys.readouterr().out
    assert "market_rows_loaded=0" in printed
    assert "market_provided=0/4" in printed
    # 固定地址随渲染发布，与留档内容一致；重复运行幂等。
    fixed = tmp_path / "prism.html"
    assert fixed.is_file() and fixed.read_text(encoding="utf-8") == text
    first_fixed_mtime = fixed.stat().st_mtime_ns
    assert prism_cli.main(["--out", str(out)]) == 0
    capsys.readouterr()
    assert fixed.read_text(encoding="utf-8") == text
    assert fixed.stat().st_mtime_ns == first_fixed_mtime


@pytest.fixture
def completed_archive(tmp_path, monkeypatch):
    """独立的正式空日报；实际模型验证，事实仓读取隔离到临时目录。"""
    import pandas as pd

    from tools import render_monitor_web as renderer
    from tools import render_prism_web as cli

    monitor = tmp_path / "monitor"
    selection = tmp_path / "selection"
    monitor.mkdir()
    selection.mkdir()
    monkeypatch.setattr(renderer, "MONITOR_DIR", monitor)
    monkeypatch.setattr(renderer, "SELECTION_DIR", selection)
    monkeypatch.setattr(cli, "PROJECT_ROOT", tmp_path)
    # 临时交易日历（周一至周五开市）：build_payload 的交易日序列来源（F04/E2）。
    days = pd.date_range("2026-06-01", "2026-12-31", freq="D")
    calendar_frame = pd.DataFrame(
        {"exchange": "SSE", "cal_date": days.strftime("%Y-%m-%d"),
         "is_open": days.dayofweek < 5}
    )
    calendar_dir = (
        tmp_path / "local_warehouse" / "facts" / "trade_calendar" / "cal_year=2026"
    )
    calendar_dir.mkdir(parents=True)
    calendar_frame.to_parquet(calendar_dir / "data.parquet")
    day, action, cutoff = "2026-09-04", "2026-09-07", "2026-09-06T18:30:00+08:00"
    counts = dict.fromkeys(("open_episode_count", "distinct_stock_count", "selected_count",
                           "comparator_count", "primary_count", "passive_tail_count",
                           "attention_stock_count", "routine_stock_count"), 0)
    data = {
        "trace": {
            "trace_version": "daily-research-trace-v4", "formation_date": day,
            "action_date": action, "as_of": cutoff, "market_search_context": "无正式推荐。",
            "market_propagation_mode": "unclear", "market_risk_overlays": [],
            "candidate_ledger": [], "decision_trace": [],
            "research_result": {"research_completed": True, "point_in_time_evidence_verified": True,
                                "failure_reason": "", "skills_used": ["orchestrating-stock-research",
                                "interpreting-market-macro", "researching-sectors-industries",
                                "researching-company-events", "analyzing-price-trading"],
                                "selected_stocks": [], "nearest_nonselections": [], "empty_reason": "无合适机会。"},
        },
        "snapshot": {
            "snapshot_version": "forward-monitor-snapshot-v1", "analysis_date": day,
            "as_of": cutoff, "episodes": [], "daily_review_episode_ids": [],
            "checkpoint_review_episode_ids": [], "attention_stocks": [], "summary": counts,
        },
        "ledger": {"ledger_version": "daily-formal-reviews-v1", "analysis_date": day,
                   "as_of": cutoff, "reviews": []},
        "report": {
            "report_version": "daily-forward-monitor-report-v2", "analysis_date": day,
            "as_of": cutoff, "market_overview": {"market_propagation_mode": "unclear",
            "market_risk_overlays": [], "what_changed": "无新增可对。",
            "implication_for_monitored_stocks": "没有需复盘的股票。"}, "pool_summary": counts,
            "alerts": [], "unreported_attention_count": 0, "routine_summary": "无复盘记录。",
        },
    }
    paths = {"trace": selection / f"research-trace-{day}.json",
             "snapshot": monitor / f"snapshot-{day}.json",
             "ledger": monitor / f"daily-formal-reviews-{day}.json",
             "report": monitor / f"monitor-report-{day}.json",
             "markdown": monitor / f"monitor-report-{day}.md"}
    for key, value in data.items():
        paths[key].write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    paths["markdown"].write_text("当天没有需复盘的股票。", encoding="utf-8")
    return cli, paths, ["--date", day, "--action-date", action, "--as-of", cutoff]


def change_archive(path, **changes):
    data = json.loads(path.read_text(encoding="utf-8"))
    data.update(changes)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def test_completed_weekend_empty_report_sync_is_idempotent(completed_archive):
    cli, paths, args = completed_archive
    originals = {p: p.read_bytes() for p in paths.values()}
    assert cli.main(args) == 0
    fixed = paths["report"].parent / "prism.html"
    html = fixed.read_text(encoding="utf-8")
    payload = json.loads(html.split('<script id="snapshot" type="application/json">')[1].split("</script>")[0])
    assert payload["analysis_date"] == "2026-09-04"
    assert payload["as_of"] == "2026-09-06T18:30:00+08:00"
    assert payload["stocks"] == []
    stamp = fixed.stat().st_mtime_ns
    assert cli.main(args) == 0
    assert fixed.stat().st_mtime_ns == stamp
    assert {p: p.read_bytes() for p in paths.values()} == originals


@pytest.mark.parametrize("args", [
    ["--action-date", "2026-09-07"], ["--as-of", "2026-09-06T18:30:00+08:00"],
    ["--date", "2026-09-04", "--action-date", "2026-09-07"],
    ["--action-date", "2026-09-07", "--as-of", "2026-09-06T18:30:00+08:00"],
])
def test_strict_sync_requires_all_three_parameters(args):
    from tools import render_prism_web as cli
    with pytest.raises(SystemExit) as result:
        cli.main(args)
    assert result.value.code == 2


@pytest.mark.parametrize("missing", ["trace", "snapshot", "ledger", "report", "markdown"])
def test_missing_formal_archive_preserves_fixed_page(completed_archive, missing):
    cli, paths, args = completed_archive
    assert cli.main(args) == 0
    fixed = paths["report"].parent / "prism.html"
    old = fixed.read_bytes()
    paths[missing].unlink()
    assert cli.main(args) == 1
    assert fixed.read_bytes() == old


@pytest.mark.parametrize("key,field,value", [
    ("trace", "formation_date", "2026-09-03"), ("trace", "action_date", "2026-09-08"),
    ("report", "analysis_date", "2026-09-03"), ("snapshot", "analysis_date", "2026-09-03"),
    ("ledger", "analysis_date", "2026-09-03"),
    *[(key, "as_of", cutoff) for key in ("trace", "snapshot", "ledger", "report")
      for cutoff in ("2026-09-06T19:00:00+08:00", "2026-09-06T18:30:00")],
])
def test_archive_date_or_cutoff_mismatch_cannot_publish(completed_archive, key, field, value):
    cli, paths, args = completed_archive
    change_archive(paths[key], **{field: value})
    assert cli.main(args) == 1
    assert not (paths["report"].parent / "prism.html").exists()


def test_empty_markdown_and_naive_requested_cutoff_are_rejected(completed_archive):
    cli, paths, args = completed_archive
    assert cli.main(args[:-1] + ["2026-09-06T18:30:00"]) == 1
    paths["markdown"].write_text(" \n", encoding="utf-8")
    assert cli.main(args) == 1


def test_missing_daily_review_and_incorrect_summary_are_rejected(completed_archive):
    cli, paths, args = completed_archive
    change_archive(paths["snapshot"], daily_review_episode_ids=["not_recorded"])
    assert cli.main(args) == 1
    change_archive(paths["snapshot"], daily_review_episode_ids=[])
    change_archive(paths["report"], unreported_attention_count=1)
    assert cli.main(args) == 1


def add_daily_review(paths, *, kind="brief", day_number=2):
    episode = {"episode_id": "old-recommendation", "ts_code": "000001.SZ", "name": "示例股份",
               "role": "selected", "selection_output_class": "confirmed_active", "day_number": day_number,
               "formation_date": "2026-09-01", "action_date": "2026-09-02"}
    review = {"episode_id": episode["episode_id"], "day_number": day_number, "review_kind": kind,
              "current_assessment": "partly_supported", "current_path": "sideways",
              "best_supported_explanation": "unknown", "current_weak_or_failed_link": "none",
              "current_review": "尚无新的变化。" if kind == "brief" else None,
              "view_change": "unchanged", "view_change_reason": "没有新增可对。",
              "outlook_1_3d": "range_or_wait", "outlook_reason_plain_language": "走势暂未改变。",
              "tracking_decision": "keep_active_tracking", "tracking_decision_reason": "原条件仍待检验。",
              "review_origin": "live"}
    change_archive(paths["snapshot"], episodes=[episode], daily_review_episode_ids=[episode["episode_id"]])
    change_archive(paths["ledger"], reviews=[review])


def test_daily_review_identity_and_detail_coverage(completed_archive):
    from tools import render_monitor_web as renderer
    from datetime import datetime
    cli, paths, args = completed_archive
    add_daily_review(paths)
    # 原推荐日期与当日报告日期不同是正常的；只读归档检查接受它。
    cli.load_completed_archives(renderer, paths["report"].parent, date(2026, 9, 4),
                                date(2026, 9, 7), datetime.fromisoformat(args[-1]))
    add_daily_review(paths, kind="regular_detail")
    assert cli.main(args) == 1  # 正文尚未保存。
    add_daily_review(paths, day_number=3)
    assert cli.main(args) == 1  # 节点不能用简评替代。
    add_daily_review(paths)
    raw = json.loads(paths["snapshot"].read_text())
    raw["episodes"][0]["day_number"] = 4
    change_archive(paths["snapshot"], **raw)
    assert cli.main(args) == 1


def test_historical_render_never_downgrades_fixed_page(completed_archive):
    cli, paths, args = completed_archive
    _, _, builder = cli.load_modules()
    fixed = paths["report"].parent / "prism.html"
    newer = builder.render_html({"analysis_date": "2026-09-07", "as_of": "2026-09-07T18:30:00+08:00",
                                 "stocks": [], "dates": ["09-07"], "market": [3000.0]})
    fixed.write_text(newer, encoding="utf-8")
    assert cli.main(args) == 0
    assert fixed.read_text(encoding="utf-8") == newer
    assert (fixed.parent / "prism-report-2026-09-04.html").is_file()


def test_changed_archive_or_broken_render_keeps_previous_page(completed_archive, monkeypatch):
    cli, paths, args = completed_archive
    assert cli.main(args) == 0
    fixed = paths["report"].parent / "prism.html"
    old = fixed.read_bytes()
    renderer, adapt, builder = cli.load_modules()
    original_render = builder.render_html
    def changed(snapshot):
        paths["markdown"].write_text("归档被另一个运行更新。", encoding="utf-8")
        return original_render(snapshot)
    monkeypatch.setattr(builder, "render_html", changed)
    monkeypatch.setattr(cli, "load_modules", lambda: (renderer, adapt, builder))
    assert cli.main(args) == 1
    assert fixed.read_bytes() == old
    monkeypatch.setattr(builder, "render_html", lambda snapshot: "not a complete HTML snapshot")
    assert cli.main(args) == 1
    assert fixed.read_bytes() == old


def test_fixed_replace_failure_keeps_previous_page(completed_archive, monkeypatch):
    cli, paths, args = completed_archive
    assert cli.main(args) == 0
    fixed = paths["report"].parent / "prism.html"
    old = fixed.read_bytes()
    original_replace = cli.os.replace
    def fail_fixed(source, destination):
        if destination == fixed:
            raise OSError("simulated fixed-page replace failure")
        return original_replace(source, destination)
    monkeypatch.setattr(cli.os, "replace", fail_fixed)
    assert cli.main(args + ["--indices", "000001.SH,399001.SZ,399006.SZ"]) == 1
    assert fixed.read_bytes() == old
    assert not list(fixed.parent.glob("prism*.tmp-*"))


def test_repair_default_sync_updates_both_pages_without_changing_archives(completed_archive):
    from tools.update_monitor_web import parse_payload
    cli, paths, args = completed_archive
    original = {p: p.read_bytes() for p in paths.values()}
    assert cli.main(args) == 0
    monitor = paths["report"].parent
    index = monitor / "index.html"
    assert parse_payload(index.read_text())["analysis_date"] == "2026-09-04"
    stamp = index.stat().st_mtime_ns
    assert cli.main(args) == 0
    assert index.stat().st_mtime_ns == stamp
    assert {p: p.read_bytes() for p in paths.values()} == original
    renderer, _, _ = cli.load_modules()
    newer = {"analysis_date": "2026-09-07", "dates": [], "stocks": [], "market": []}
    index.write_text(renderer.render(newer))
    old_index = index.read_bytes()
    assert cli.main(args) == 0
    assert index.read_bytes() == old_index
    assert cli.main([*args, "--no-publish"]) == 0
    assert index.read_bytes() == old_index
    index.unlink()
    assert cli.main([*args, "--no-publish"]) == 0
    assert not index.exists()
    assert cli.main([*args, "--out", str(monitor / "custom.html")]) == 0
    assert not index.exists()
