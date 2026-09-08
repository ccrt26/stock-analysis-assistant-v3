"""只读仓库入口与买入决策 prepare/calculate 的行为测试。

只读测试全部使用临时仓库，不触碰用户事实仓。
"""

from datetime import date, datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path

import pandas as pd
import pytest

from stock_analyzer.data.research_contracts import FactBatch, ResearchDatasetId
from stock_analyzer.storage.research_warehouse import (
    FactRecoveryError,
    ResearchWarehouse,
)
from stock_analyzer.storage.research_query import ResearchQuery
from stock_analyzer.ops.buy_decision import (
    BuyDecisionRequest,
    calculate_buy_decision,
    prepare_buy_decision,
)


def _equity_batch(
    *,
    close: float = 10.2,
    trade_date: date = date(2026, 7, 10),
    run_id: str = "run-1",
    available_at: datetime | None = None,
) -> FactBatch:
    return FactBatch(
        dataset_id=ResearchDatasetId.EQUITY_DAILY,
        partition_value=trade_date.isoformat(),
        source_name="tushare",
        source_endpoint="daily",
        ingestion_run_id=run_id,
        ingested_at=datetime(2026, 7, 10, 10, tzinfo=timezone.utc),
        default_available_at=(
            available_at
            or datetime(2026, 7, 10, 7, 1, tzinfo=timezone.utc)
        ),
        records=[
            {
                "trade_date": trade_date,
                "ts_code": "603969.SH",
                "open": 10.0,
                "high": max(10.5, close),
                "low": min(9.8, close),
                "close": close,
                "pre_close": 10.0,
                "change": close - 10.0,
                "pct_chg": (close / 10.0 - 1.0) * 100.0,
                "volume": 100.0,
                "amount": 1000.0,
            }
        ],
    )


def _snapshot_files(root: Path) -> dict[str, str]:
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_read_only_open_leaves_existing_warehouse_unchanged(tmp_path):
    warehouse = ResearchWarehouse(tmp_path)
    warehouse.commit_batch(_equity_batch())
    before = _snapshot_files(tmp_path)

    readonly = ResearchWarehouse(tmp_path, read_only=True)
    frame = readonly.read_current(ResearchDatasetId.EQUITY_DAILY)
    manifest = readonly.partition_manifest(ResearchDatasetId.EQUITY_DAILY)
    revisions = readonly.revision_rows(ResearchDatasetId.EQUITY_DAILY)

    assert len(frame) == 1
    assert len(manifest) == 1
    assert revisions == []
    assert _snapshot_files(tmp_path) == before


def test_read_only_reads_do_not_create_missing_lock_file(tmp_path):
    warehouse = ResearchWarehouse(tmp_path)
    warehouse.commit_batch(_equity_batch())
    lock_path = tmp_path / ".facts.lock"
    lock_path.unlink()

    readonly = ResearchWarehouse(tmp_path, read_only=True)
    assert readonly.read_current(ResearchDatasetId.EQUITY_DAILY).shape[0] == 1
    assert not lock_path.exists()


def test_read_only_missing_root_or_database_is_a_clear_error(tmp_path):
    with pytest.raises(FileNotFoundError):
        ResearchWarehouse(tmp_path / "absent", read_only=True)
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(FileNotFoundError):
        ResearchWarehouse(empty, read_only=True)


def test_read_only_write_methods_are_rejected_without_touching_warehouse(tmp_path):
    warehouse = ResearchWarehouse(tmp_path)
    warehouse.commit_batch(_equity_batch())
    before = _snapshot_files(tmp_path)
    readonly = ResearchWarehouse(tmp_path, read_only=True)

    with pytest.raises(PermissionError):
        readonly.commit_batch(_equity_batch(close=11.0, run_id="run-2"))
    with pytest.raises(PermissionError):
        readonly.replace_dataset_batches(ResearchDatasetId.EQUITY_DAILY, [])
    with pytest.raises(PermissionError):
        readonly.prune_partitions_before(ResearchDatasetId.EQUITY_DAILY, "2026-08")

    assert _snapshot_files(tmp_path) == before


def test_read_only_preserves_history_as_of_and_query_semantics(tmp_path):
    warehouse = ResearchWarehouse(tmp_path)
    warehouse.commit_batch(_equity_batch(close=10.2))
    warehouse.commit_batch(
        _equity_batch(
            close=10.4,
            run_id="run-2",
            available_at=datetime(2026, 7, 13, 7, 1, tzinfo=timezone.utc),
        ).model_copy(
            update={
                "ingested_at": datetime(2026, 7, 13, 10, tzinfo=timezone.utc),
            }
        )
    )
    readonly = ResearchWarehouse(tmp_path, read_only=True)
    query = ResearchQuery(readonly)

    early = query.dataset_as_of(
        ResearchDatasetId.EQUITY_DAILY,
        datetime(2026, 7, 11, tzinfo=timezone.utc),
    )
    later = query.dataset_as_of(
        ResearchDatasetId.EQUITY_DAILY,
        datetime(2026, 7, 14, tzinfo=timezone.utc),
    )
    assert early.iloc[0]["close"] == pytest.approx(10.2)
    assert later.iloc[0]["close"] == pytest.approx(10.4)
    snapshot = query.materialize_snapshot(
        {ResearchDatasetId.EQUITY_DAILY: ["2026-07-10"]},
        as_of=datetime(2026, 7, 14, tzinfo=timezone.utc),
    )
    assert snapshot.frame(ResearchDatasetId.EQUITY_DAILY).iloc[0][
        "close"
    ] == pytest.approx(10.4)
    assert snapshot.input_manifest["partitions"][0]["resolved_row_count"] == 1


def test_read_only_refuses_unreconciled_journals_without_repairing(tmp_path):
    warehouse = ResearchWarehouse(tmp_path)
    warehouse.commit_batch(_equity_batch())
    journal_root = tmp_path / ".fact-promotions"
    journal_root.mkdir(exist_ok=True)
    (journal_root / "interrupted.json").write_text("{}", encoding="utf-8")
    before = _snapshot_files(tmp_path)

    with pytest.raises(FactRecoveryError, match="journal"):
        ResearchWarehouse(tmp_path, read_only=True)
    assert _snapshot_files(tmp_path) == before


def test_read_only_refuses_unreconciled_backups_without_repairing(tmp_path):
    warehouse = ResearchWarehouse(tmp_path)
    warehouse.commit_batch(_equity_batch())
    backup = (
        tmp_path
        / "facts"
        / "equity_daily"
        / "trade_date=2026-07-10"
        / "data.parquet.previous"
    )
    backup.write_bytes(b"stale")
    before = _snapshot_files(tmp_path)

    with pytest.raises(FactRecoveryError, match="backup"):
        ResearchWarehouse(tmp_path, read_only=True)
    assert _snapshot_files(tmp_path) == before


def test_read_only_ignores_unpublished_journal_temp_files(tmp_path):
    warehouse = ResearchWarehouse(tmp_path)
    warehouse.commit_batch(_equity_batch())
    journal_root = tmp_path / ".fact-promotions"
    journal_root.mkdir(exist_ok=True)
    (journal_root / "leftover.json.tmp").write_text("{}", encoding="utf-8")

    readonly = ResearchWarehouse(tmp_path, read_only=True)
    assert readonly.read_current(ResearchDatasetId.EQUITY_DAILY).shape[0] == 1
    # 只读研究自身不修数据：临时文件保持原样。
    assert (journal_root / "leftover.json.tmp").exists()


def test_mid_state_partition_cannot_masquerade_as_one_snapshot(tmp_path):
    warehouse = ResearchWarehouse(tmp_path)
    warehouse.commit_batch(_equity_batch())
    partition_file = (
        tmp_path
        / "facts"
        / "equity_daily"
        / "trade_date=2026-07-10"
        / "data.parquet"
    )
    frame = pd.read_parquet(partition_file)
    frame.loc[:, "close"] = 99.0
    frame.to_parquet(partition_file)

    readonly = ResearchWarehouse(tmp_path, read_only=True)
    query = ResearchQuery(readonly)
    with pytest.raises(ValueError, match="SHA-256"):
        query.materialize_snapshot(
            {ResearchDatasetId.EQUITY_DAILY: ["2026-07-10"]},
            as_of=datetime(2026, 7, 14, tzinfo=timezone.utc),
        )


def test_default_write_mode_unchanged_after_read_only_exists(tmp_path):
    warehouse = ResearchWarehouse(tmp_path)
    readonly = ResearchWarehouse(tmp_path, read_only=True)
    assert readonly.read_current(ResearchDatasetId.EQUITY_DAILY).empty

    warehouse.commit_batch(_equity_batch())
    assert warehouse.read_current(ResearchDatasetId.EQUITY_DAILY).shape[0] == 1
    reopened_readonly = ResearchWarehouse(tmp_path, read_only=True)
    assert reopened_readonly.read_current(
        ResearchDatasetId.EQUITY_DAILY
    ).shape[0] == 1


# ---------------------------------------------------------------------------
# 买入决策 prepare / calculate（合成临时仓，不触碰用户事实仓）
# ---------------------------------------------------------------------------


def _synthetic_sessions() -> tuple[list[date], list[date]]:
    """历史会话（有行情）与日历会话（含未来），均为 2026 年工作日。"""

    def workdays(start: date, end: date) -> list[date]:
        days = []
        cursor = start
        while cursor <= end:
            if cursor.weekday() < 5:
                days.append(cursor)
            cursor += timedelta(days=1)
        return days

    history = workdays(date(2026, 6, 1), date(2026, 9, 7))
    calendar = workdays(date(2026, 6, 1), date(2026, 9, 30))
    return history, calendar


def _commit_price_data(warehouse: ResearchWarehouse, ts_code: str) -> None:
    history, calendar = _synthetic_sessions()
    # 交易日历：像真实仓一样，每日行在该日收盘后可用。
    warehouse.commit_batch(
        FactBatch(
            dataset_id=ResearchDatasetId.TRADE_CALENDAR,
            partition_value="2026",
            source_name="tushare",
            source_endpoint="trade_cal",
            ingestion_run_id="calendar-1",
            ingested_at=datetime(2026, 9, 8, 2, tzinfo=timezone.utc),
            default_available_at=datetime(2026, 9, 8, 2, tzinfo=timezone.utc),
            records=[
                {
                    "exchange": "SSE",
                    "cal_date": day,
                    "is_open": day in set(calendar),
                    "available_at": datetime(
                        day.year, day.month, day.day, 15, 1,
                        tzinfo=timezone(timedelta(hours=8)),
                    ),
                }
                for day in calendar
            ],
        )
    )
    for index, day in enumerate(history):
        close = 10.0 + index * 0.01
        open_value = 10.0 + (index - 1) * 0.01 if index else 10.0
        available = datetime(
            day.year, day.month, day.day, 15, 5, tzinfo=timezone(timedelta(hours=8))
        )
        warehouse.commit_batch(
            FactBatch(
                dataset_id=ResearchDatasetId.EQUITY_DAILY,
                partition_value=day.isoformat(),
                source_name="tushare",
                source_endpoint="daily",
                ingestion_run_id=f"equity-{day.isoformat()}",
                ingested_at=available,
                default_available_at=available,
                records=[
                    {
                        "trade_date": day,
                        "ts_code": ts_code,
                        "open": round(open_value, 4),
                        "high": round(max(open_value, close) + 0.05, 4),
                        "low": round(min(open_value, close) - 0.05, 4),
                        "close": round(close, 4),
                        "pre_close": round(open_value, 4),
                        "change": round(close - open_value, 4),
                        "pct_chg": round((close / open_value - 1) * 100, 4),
                        "volume": 1000.0 + index,
                        "amount": 10000.0 + index,
                        "available_at": available,
                    }
                ],
            )
        )
        warehouse.commit_batch(
            FactBatch(
                dataset_id=ResearchDatasetId.ADJ_FACTOR,
                partition_value=day.isoformat(),
                source_name="tushare",
                source_endpoint="adj_factor",
                ingestion_run_id=f"factor-{day.isoformat()}",
                ingested_at=available,
                default_available_at=available,
                records=[
                    {
                        "trade_date": day,
                        "ts_code": ts_code,
                        "adj_factor": 4.0,
                        "available_at": available,
                    }
                ],
            )
        )
        warehouse.commit_batch(
            FactBatch(
                dataset_id=ResearchDatasetId.INDEX_DAILY,
                partition_value=day.isoformat(),
                source_name="tushare",
                source_endpoint="index_daily",
                ingestion_run_id=f"index-{day.isoformat()}",
                ingested_at=available,
                default_available_at=available,
                records=[
                    {
                        "trade_date": day,
                        "index_code": "000300.SH",
                        "open": 3900.0 + max(index - 1, 0),
                        "high": 3901.0 + index,
                        "low": 3899.0 + max(index - 1, 0),
                        "close": 3900.0 + index,
                        "pre_close": 3900.0 + max(index - 1, 0),
                        "change": 1.0,
                        "pct_chg": 0.03,
                        "volume": 1.0,
                        "amount": 1.0,
                        "available_at": available,
                    }
                ],
            )
        )
    latest = history[-1]
    warehouse.commit_batch(
        FactBatch(
            dataset_id=ResearchDatasetId.DAILY_BASIC,
            partition_value=latest.isoformat(),
            source_name="tushare",
            source_endpoint="daily_basic",
            ingestion_run_id="basic-1",
            ingested_at=datetime(2026, 9, 7, 16, tzinfo=timezone(timedelta(hours=8))),
            default_available_at=datetime(2026, 9, 7, 16, tzinfo=timezone(timedelta(hours=8))),
            records=[
                {
                    "trade_date": latest,
                    "ts_code": ts_code,
                    "close": 10.0 + (len(history) - 1) * 0.01,
                    "pe_ttm": 18.5,
                    "pb": 1.6,
                    "total_mv": 500000.0,
                    "available_at": datetime(2026, 9, 7, 16, tzinfo=timezone(timedelta(hours=8))),
                }
            ],
        )
    )
    warehouse.commit_batch(
        FactBatch(
            dataset_id=ResearchDatasetId.SECURITY_MASTER,
            partition_value="security-master",
            source_name="tushare",
            source_endpoint="stock_basic",
            ingestion_run_id="master-1",
            ingested_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
            default_available_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
            records=[
                {
                    "ts_code": ts_code,
                    "name": "银龙股份",
                    "area": "天津",
                    "industry": "通用设备",
                    "market": "主板",
                    "list_date": date(2015, 2, 11),
                    "valid_from": date(2015, 2, 11),
                    "available_at": datetime(2026, 9, 1, tzinfo=timezone.utc),
                }
            ],
        )
    )
    warehouse.commit_batch(
        FactBatch(
            dataset_id=ResearchDatasetId.INCOME_STATEMENT,
            partition_value="2026-06-30",
            source_name="tushare",
            source_endpoint="income",
            ingestion_run_id="income-1",
            ingested_at=datetime(2026, 8, 19, 16, tzinfo=timezone(timedelta(hours=8))),
            default_available_at=datetime(2026, 8, 19, 16, tzinfo=timezone(timedelta(hours=8))),
            records=[
                {
                    "ts_code": ts_code,
                    "report_period": "20260630",
                    "report_type": "1",
                    "statement_type": "1",
                    "total_revenue": 159060000.0,
                    "n_income_attr_p": 24100000.0,
                    "ann_date": date(2026, 8, 19),
                    "f_ann_date": date(2026, 8, 19),
                    "available_at": datetime(2026, 8, 19, 16, tzinfo=timezone(timedelta(hours=8))),
                }
            ],
        )
    )
    warehouse.commit_batch(
        FactBatch(
            dataset_id=ResearchDatasetId.FINANCIAL_INDICATOR,
            partition_value="2026-06-30",
            source_name="tushare",
            source_endpoint="fina_indicator",
            ingestion_run_id="fina-1",
            ingested_at=datetime(2026, 8, 19, 16, tzinfo=timezone(timedelta(hours=8))),
            default_available_at=datetime(2026, 8, 19, 16, tzinfo=timezone(timedelta(hours=8))),
            records=[
                {
                    "ts_code": ts_code,
                    "report_period": "20260630",
                    "report_type": "1",
                    "ann_date": date(2026, 8, 19),
                    "roe": 5.2,
                    "debt_to_assets": 41.0,
                    "available_at": datetime(2026, 8, 19, 16, tzinfo=timezone(timedelta(hours=8))),
                }
            ],
        )
    )


def _write_registry(project_root: Path, ts_code: str = "603969.SH") -> None:
    monitor_dir = project_root / "local_archive" / "forward_monitor"
    monitor_dir.mkdir(parents=True, exist_ok=True)
    (monitor_dir / "registered-episodes.json").write_text(
        json.dumps(
            {
                "registry_version": "registered-forward-monitor-episodes-v1",
                "episodes": [
                    {
                        "episode_id": "v4-replay-2026-08-20:2026-08-20:%s:selected" % ts_code,
                        "ts_code": ts_code,
                        "name": "测试股",
                        "formation_date": "2026-08-20",
                        "action_date": "2026-08-21",
                        "role": "selected",
                        "source_as_of": "2026-08-21T09:10:00+08:00",
                        "original_selection_reason": "低位放量启动。",
                        "original_strongest_counterevidence": "行业未配合。",
                        # 模拟旧口径字段：修改它不得影响新买入几何。
                        "legacy_target_label": "20%",
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (monitor_dir / "snapshot-2026-09-07.json").write_text(
        json.dumps(
            {
                "snapshot_version": "forward-monitor-snapshot-v1",
                "analysis_date": "2026-09-07",
                "episodes": [
                    {
                        "episode_id": "v4-replay-2026-08-20:2026-08-20:%s:selected" % ts_code,
                        "ts_code": ts_code,
                        "day_number": 12,
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def _write_request(
    path: Path,
    *,
    ts_code: str = "603969.SH",
    as_of: str = "2026-09-08T10:00:00+08:00",
    **overrides,
) -> None:
    request = {
        "ts_code": ts_code,
        "position_status": "not_bought",
        "as_of": as_of,
        "objective": "near_term_profit_without_fixed_target",
        "horizon_sessions": 10,
        "horizon_is_hard_deadline": False,
        "reference_entry_price": None,
        "reference_entry_source": None,
        "assumed_entry_date": None,
        "max_tolerable_loss_pct": None,
        "round_trip_cost_bps": None,
        "related_episode_ids": [],
    }
    request.update(overrides)
    path.write_text(json.dumps(request, ensure_ascii=False), encoding="utf-8")


@pytest.fixture()
def prepared_run(tmp_path):
    warehouse_root = tmp_path / "warehouse"
    warehouse_root.mkdir()
    project_root = tmp_path / "project"
    project_root.mkdir()
    _commit_price_data(ResearchWarehouse(warehouse_root), "603969.SH")
    _write_registry(project_root)
    run_dir = tmp_path / "runs" / "run-1"
    request_path = tmp_path / "request.json"
    _write_request(request_path)
    summary = prepare_buy_decision(
        request_path=request_path,
        output_dir=run_dir,
        warehouse_root=warehouse_root,
        project_root=project_root,
    )
    context = json.loads((run_dir / "context.json").read_text(encoding="utf-8"))
    return {
        "warehouse_root": warehouse_root,
        "project_root": project_root,
        "run_dir": run_dir,
        "summary": summary,
        "context": context,
        "request_path": request_path,
    }


def test_request_contract_rejects_wrong_status_timezone_horizon_and_prefix(tmp_path):
    with pytest.raises(ValueError, match="position_status"):
        BuyDecisionRequest(
            ts_code="603969.SH",
            position_status="bought",
            as_of="2026-09-08T10:00:00+08:00",
            objective="near_term_profit_without_fixed_target",
            horizon_sessions=10,
        )
    with pytest.raises(ValueError, match="timezone"):
        BuyDecisionRequest(
            ts_code="603969.SH",
            position_status="not_bought",
            as_of="2026-09-08T10:00:00",
            objective="near_term_profit_without_fixed_target",
            horizon_sessions=10,
        )
    with pytest.raises(ValueError, match="horizon_sessions"):
        BuyDecisionRequest(
            ts_code="603969.SH",
            position_status="not_bought",
            as_of="2026-09-08T10:00:00+08:00",
            objective="near_term_profit_without_fixed_target",
            horizon_sessions=0,
        )
    with pytest.raises(ValueError, match="reference_entry"):
        BuyDecisionRequest(
            ts_code="603969.SH",
            position_status="not_bought",
            as_of="2026-09-08T10:00:00+08:00",
            objective="near_term_profit_without_fixed_target",
            horizon_sessions=10,
            reference_entry_price=8.0,
        )
    for bad_code in ("688001.SH", "830001.BJ", "510300.SH", "430047.BJ"):
        with pytest.raises(ValueError, match="ts_code"):
            BuyDecisionRequest(
                ts_code=bad_code,
                position_status="not_bought",
                as_of="2026-09-08T10:00:00+08:00",
                objective="near_term_profit_without_fixed_target",
                horizon_sessions=10,
            )
    assert BuyDecisionRequest(
        ts_code="603969.SH",
        position_status="not_bought",
        as_of="2026-09-08T10:00:00+08:00",
        objective="near_term_profit_without_fixed_target",
        horizon_sessions=10,
    ).ts_code == "603969.SH"


def test_prepare_builds_context_with_two_calendar_lanes(prepared_run):
    context = prepared_run["context"]
    raw = context["market_sessions"]["raw_calendar_sessions"]
    visible = context["market_sessions"]["as_of_visible_sessions"]
    # as_of 快照会话不含 9-8（当日行收盘后才可用），原始日历含未来会话。
    assert max(visible) == "2026-09-07"
    assert "2026-09-08" in raw["sessions"]
    assert raw["coverage_end"] == "2026-09-30"


def test_prepare_states_price_data_cutoff_and_normalization(prepared_run):
    context = prepared_run["context"]
    assert context["price_daily"]["data_cutoff_date"] == "2026-09-07"
    assert context["price_daily"]["price_basis"] == (
        "raw_times_day_factor_div_latest_factor"
    )
    assert context["price_daily"]["normalization_factor"] == 4.0


def test_prepare_computes_neutral_observations(prepared_run):
    observations = prepared_run["context"]["neutral_observations"]
    assert observations["last_close"] == pytest.approx(10.70, abs=1e-6)
    assert observations["atr20"] is not None and observations["atr20"] > 0
    assert observations["benchmark"]["code"] == "000300.SH"
    assert observations["return_5d"] is not None
    assert "atr20_note" in observations


def test_prepare_missing_optional_dataset_is_a_gap_not_a_failure(tmp_path):
    warehouse_root = tmp_path / "warehouse"
    warehouse_root.mkdir()
    project_root = tmp_path / "project"
    project_root.mkdir()
    _commit_price_data(ResearchWarehouse(warehouse_root), "603969.SH")
    _write_registry(project_root)
    run_dir = tmp_path / "runs" / "run-gap"
    request_path = tmp_path / "request.json"
    _write_request(request_path)
    summary = prepare_buy_decision(
        request_path=request_path,
        output_dir=run_dir,
        warehouse_root=warehouse_root,
        project_root=project_root,
    )
    context = json.loads((run_dir / "context.json").read_text(encoding="utf-8"))
    gap_datasets = {gap["dataset"] for gap in context["gaps"]}
    assert "announcement" in gap_datasets
    assert summary["status"] == "prepared"


def test_prepare_fails_when_required_price_data_missing(tmp_path):
    warehouse_root = tmp_path / "warehouse"
    warehouse_root.mkdir()
    project_root = tmp_path / "project"
    project_root.mkdir()
    ResearchWarehouse(warehouse_root)  # 空仓：无任何行情分区
    _write_registry(project_root)
    request_path = tmp_path / "request.json"
    _write_request(request_path)
    with pytest.raises(ValueError, match="equity_daily"):
        prepare_buy_decision(
            request_path=request_path,
            output_dir=tmp_path / "runs" / "run-empty",
            warehouse_root=warehouse_root,
            project_root=project_root,
        )


def test_prepare_does_not_overwrite_existing_run_dir(prepared_run):
    with pytest.raises(ValueError, match="already exists"):
        prepare_buy_decision(
            request_path=prepared_run["request_path"],
            output_dir=prepared_run["run_dir"],
            warehouse_root=prepared_run["warehouse_root"],
            project_root=prepared_run["project_root"],
        )


def test_prepare_keeps_original_recommendation_background_only(prepared_run):
    original = prepared_run["context"]["original_recommendation"]
    assert original["background_only"] is True
    assert original["episodes"][0]["legacy_target_label"] == "20%"
    assert original["latest_observation"]["day_number"] == 12
    assert "target_price" not in json.dumps(original)
    assert "remaining_return_to_target" not in json.dumps(original)


def test_prepare_ignores_original_snapshots_after_as_of(prepared_run, tmp_path):
    monitor_dir = prepared_run["project_root"] / "local_archive" / "forward_monitor"
    (monitor_dir / "snapshot-2026-09-09.json").write_text(
        json.dumps(
            {
                "snapshot_version": "forward-monitor-snapshot-v1",
                "analysis_date": "2026-09-09",
                "episodes": [
                    {
                        "episode_id": "v4-replay-2026-08-20:2026-08-20:603969.SH:selected",
                        "ts_code": "603969.SH",
                        "day_number": 14,
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    run_dir = tmp_path / "runs" / "run-future"
    request_path = tmp_path / "request-2.json"
    _write_request(request_path)
    prepare_buy_decision(
        request_path=request_path,
        output_dir=run_dir,
        warehouse_root=prepared_run["warehouse_root"],
        project_root=prepared_run["project_root"],
    )
    context = json.loads((run_dir / "context.json").read_text(encoding="utf-8"))
    assert context["original_recommendation"]["latest_observation"][
        "analysis_date"
    ] == "2026-09-07"


def test_prepare_without_recommendation_archive_still_builds_context(tmp_path):
    warehouse_root = tmp_path / "warehouse"
    warehouse_root.mkdir()
    project_root = tmp_path / "project"
    project_root.mkdir()
    _commit_price_data(ResearchWarehouse(warehouse_root), "000002.SZ")
    request_path = tmp_path / "request.json"
    _write_request(request_path, ts_code="000002.SZ")
    run_dir = tmp_path / "runs" / "run-norec"
    summary = prepare_buy_decision(
        request_path=request_path,
        output_dir=run_dir,
        warehouse_root=warehouse_root,
        project_root=project_root,
    )
    context = json.loads((run_dir / "context.json").read_text(encoding="utf-8"))
    assert summary["status"] == "prepared"
    assert context["original_recommendation"]["episodes"] == []


def test_prepare_marks_st_stock_out_of_v1_scope(tmp_path):
    warehouse_root = tmp_path / "warehouse"
    warehouse_root.mkdir()
    project_root = tmp_path / "project"
    project_root.mkdir()
    _commit_price_data(ResearchWarehouse(warehouse_root), "000003.SZ")
    master = ResearchWarehouse(warehouse_root)
    master.commit_batch(
        FactBatch(
            dataset_id=ResearchDatasetId.SECURITY_MASTER,
            partition_value="security-master-st",
            source_name="tushare",
            source_endpoint="stock_basic",
            ingestion_run_id="master-st",
            ingested_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
            default_available_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
            records=[
                {
                    "ts_code": "000004.SZ",
                    "name": "ST测试",
                    "area": "测试",
                    "industry": "测试",
                    "market": "主板",
                    "list_date": date(2015, 2, 11),
                    "valid_from": date(2015, 2, 11),
                    "available_at": datetime(2026, 9, 1, tzinfo=timezone.utc),
                }
            ],
        )
    )
    request_path = tmp_path / "request.json"
    _write_request(request_path, ts_code="000004.SZ")
    run_dir = tmp_path / "runs" / "run-st"
    prepare_buy_decision(
        request_path=request_path,
        output_dir=run_dir,
        warehouse_root=warehouse_root,
        project_root=project_root,
    )
    context = json.loads((run_dir / "context.json").read_text(encoding="utf-8"))
    assert context["identity"]["in_v1_scope"] is False


def test_prepare_excludes_intraday_snapshot_available_after_as_of(tmp_path):
    warehouse_root = tmp_path / "warehouse"
    warehouse_root.mkdir()
    project_root = tmp_path / "project"
    project_root.mkdir()
    _commit_price_data(ResearchWarehouse(warehouse_root), "603969.SH")
    late_session = date(2026, 9, 8)
    ResearchWarehouse(warehouse_root).commit_batch(
        FactBatch(
            dataset_id=ResearchDatasetId.MINUTE_BAR,
            partition_value=late_session.isoformat(),
            source_name="tushare",
            source_endpoint="stk_mins",
            ingestion_run_id="minute-late",
            ingested_at=datetime(2026, 9, 8, 3, 30, tzinfo=timezone.utc),
            default_available_at=datetime(2026, 9, 8, 3, 30, tzinfo=timezone.utc),
            records=[
                {
                    "trade_date": late_session,
                    "instrument_code": "603969.SH",
                    "minute": "2026-09-08 10:30:00",
                    "frequency": "1min",
                    "open": 10.8,
                    "high": 10.9,
                    "low": 10.7,
                    "close": 10.85,
                    "volume": 100.0,
                    "amount": 1085.0,
                    "available_at": datetime(2026, 9, 8, 3, 30, tzinfo=timezone.utc),
                }
            ],
        )
    )
    _write_registry(tmp_path / "project")
    request_path = tmp_path / "request.json"
    _write_request(request_path)
    run_dir = tmp_path / "runs" / "run-minute"
    prepare_buy_decision(
        request_path=request_path,
        output_dir=run_dir,
        warehouse_root=warehouse_root,
        project_root=project_root,
    )
    context = json.loads((run_dir / "context.json").read_text(encoding="utf-8"))
    minute = context["minute_snapshot"]
    assert minute["rows"] == []
    assert any(
        gap["gap"] == "minute_snapshot_not_available_at_as_of"
        for gap in context["gaps"]
    )


def test_changing_legacy_target_label_does_not_change_buy_geometry(prepared_run, tmp_path):
    # 只改旧推荐档案中的 20% 标签：上下文背景变化，但新买入几何不变。
    monitor_dir = prepared_run["project_root"] / "local_archive" / "forward_monitor"
    registry = json.loads(
        (monitor_dir / "registered-episodes.json").read_text(encoding="utf-8")
    )
    registry["episodes"][0]["legacy_target_label"] = "30%"
    variant_root = tmp_path / "project-variant"
    variant_monitor = variant_root / "local_archive" / "forward_monitor"
    variant_monitor.mkdir(parents=True)
    (variant_monitor / "registered-episodes.json").write_text(
        json.dumps(registry, ensure_ascii=False), encoding="utf-8"
    )
    (variant_monitor / "snapshot-2026-09-07.json").write_text(
        (monitor_dir / "snapshot-2026-09-07.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    run_dir = tmp_path / "runs" / "run-variant"
    request_path = tmp_path / "request-variant.json"
    _write_request(request_path)
    prepare_buy_decision(
        request_path=request_path,
        output_dir=run_dir,
        warehouse_root=prepared_run["warehouse_root"],
        project_root=variant_root,
    )
    variant_context = json.loads(
        (run_dir / "context.json").read_text(encoding="utf-8")
    )
    base_context = prepared_run["context"]
    assert (
        variant_context["original_recommendation"]["episodes"][0][
            "legacy_target_label"
        ]
        == "30%"
    )
    assert (
        variant_context["neutral_observations"] == base_context["neutral_observations"]
    )
    input_payload = {"external_evidence": [], "interpretations": [], "plans": []}
    input_path = tmp_path / "analysis-input.json"
    input_path.write_text(json.dumps(input_payload), encoding="utf-8")
    first = calculate_buy_decision(
        run_dir=prepared_run["run_dir"], analysis_input_path=input_path
    )
    second = calculate_buy_decision(run_dir=run_dir, analysis_input_path=input_path)
    assert first["analysis_file"] != second["analysis_file"]
    first_analysis = json.loads(
        Path(first["analysis_file"]).read_text(encoding="utf-8")
    )
    second_analysis = json.loads(
        Path(second["analysis_file"]).read_text(encoding="utf-8")
    )
    assert first_analysis["plans_computed"] == second_analysis["plans_computed"]


def test_changing_legacy_observation_days_does_not_change_horizon(prepared_run, tmp_path):
    monitor_dir = prepared_run["project_root"] / "local_archive" / "forward_monitor"
    snapshot = json.loads(
        (monitor_dir / "snapshot-2026-09-07.json").read_text(encoding="utf-8")
    )
    snapshot["episodes"][0]["day_number"] = 30
    variant_root = tmp_path / "project-days"
    variant_monitor = variant_root / "local_archive" / "forward_monitor"
    variant_monitor.mkdir(parents=True)
    (variant_monitor / "registered-episodes.json").write_text(
        (monitor_dir / "registered-episodes.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (variant_monitor / "snapshot-2026-09-07.json").write_text(
        json.dumps(snapshot, ensure_ascii=False), encoding="utf-8"
    )
    run_dir = tmp_path / "runs" / "run-days"
    request_path = tmp_path / "request-days.json"
    _write_request(request_path)
    prepare_buy_decision(
        request_path=request_path,
        output_dir=run_dir,
        warehouse_root=prepared_run["warehouse_root"],
        project_root=variant_root,
    )
    variant_context = json.loads(
        (run_dir / "context.json").read_text(encoding="utf-8")
    )
    base_context = prepared_run["context"]
    assert (
        variant_context["original_recommendation"]["latest_observation"][
            "day_number"
        ]
        == 30
    )
    assert variant_context["horizon"] == base_context["horizon"]


def test_calculate_computes_geometry_at_new_price_and_preserves_inputs(prepared_run):
    input_payload = {
        "external_evidence": [
            {
                "title": "2026年半年度报告",
                "publisher": "天津银龙集团股份有限公司",
                "url": "https://example.invalid/report.pdf",
                "published_at": "2026-08-19T16:00:00+00:00",
                "published_at_precision": "minute",
                "fetched_at": "2026-09-08T10:20:00+08:00",
                "supports": "半年报收入与利润",
                "locator": "第4页",
                "excerpt": "……",
            }
        ],
        "interpretations": [
            {"claim": "低位放量启动后出现回调", "based_on": "context.price_daily"}
        ],
        "plans": [
            {
                "plan_id": "pullback_example",
                "entry_price": 8.0,
                "upside_levels": {"first_observation_area": 8.41},
                "invalidation_price": 7.8,
                "atr": 0.2,
                "round_trip_cost_bps": None,
                "level_basis": "近期高点位置，归一口径",
                "signal_known_when": "某日收盘后确认回落企稳信号",
                "entry_window": "信号确认后次一交易日竞价时段",
                "entry_expiry": "信号后第三个交易日收盘前",
                "gap_or_no_fill_action": "高开越过上限则放弃本次参与",
                "invalidation_observation": "收盘价跌破失效位即判断失效",
            }
        ],
    }
    input_path = prepared_run["run_dir"].parent / "analysis-input.json"
    input_path.write_text(json.dumps(input_payload, ensure_ascii=False), encoding="utf-8")
    summary = calculate_buy_decision(
        run_dir=prepared_run["run_dir"], analysis_input_path=input_path
    )
    analysis = json.loads(
        Path(summary["analysis_file"]).read_text(encoding="utf-8")
    )
    assert analysis["input"] == input_payload
    computed = analysis["plans_computed"][0]
    geometry = computed["geometry"]
    assert geometry["entry_price"] == pytest.approx(8.0)
    assert geometry["levels"]["first_observation_area"][
        "gross_return_fraction"
    ] == pytest.approx(0.05125)
    assert analysis["as_of"] == "2026-09-08T10:00:00+08:00"


def test_calculate_holding_window_uses_raw_calendar_lane(prepared_run, tmp_path):
    request_with_entry = tmp_path / "request-entry.json"
    _write_request(request_with_entry, assumed_entry_date="2026-09-09")
    run_dir = tmp_path / "runs" / "run-entry"
    prepare_buy_decision(
        request_path=request_with_entry,
        output_dir=run_dir,
        warehouse_root=prepared_run["warehouse_root"],
        project_root=prepared_run["project_root"],
    )
    context = json.loads((run_dir / "context.json").read_text(encoding="utf-8"))
    assert context["horizon"]["window_end_date"] is not None
    input_path = tmp_path / "analysis-input.json"
    input_path.write_text(json.dumps({"plans": []}), encoding="utf-8")
    summary = calculate_buy_decision(
        run_dir=run_dir, analysis_input_path=input_path
    )
    analysis = json.loads(
        Path(summary["analysis_file"]).read_text(encoding="utf-8")
    )
    assert analysis["holding_window"]["window_end_date"] == (
        context["horizon"]["window_end_date"]
    )
    assert analysis["plans_computed"] == []


def test_calculate_rejects_placeholder_plan_text(prepared_run, tmp_path):
    input_payload = {
        "plans": [
            {
                "plan_id": "placeholder",
                "entry_price": 8.0,
                "upside_levels": {"first_observation_area": 8.41},
                "invalidation_price": 7.8,
                "atr": None,
                "round_trip_cost_bps": None,
                "level_basis": "由本次研究写明",
                "signal_known_when": "由本次研究写明",
                "entry_window": "由本次研究写明",
                "entry_expiry": "由本次研究写明",
                "gap_or_no_fill_action": "由本次研究写明",
                "invalidation_observation": "由本次研究写明",
            }
        ]
    }
    input_path = tmp_path / "placeholder.json"
    input_path.write_text(json.dumps(input_payload, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError, match="placeholder"):
        calculate_buy_decision(
            run_dir=prepared_run["run_dir"], analysis_input_path=input_path
        )


def test_calculate_flags_invalidation_not_below_entry(prepared_run, tmp_path):
    input_payload = {
        "plans": [
            {
                "plan_id": "bad_invalidation",
                "entry_price": 8.0,
                "upside_levels": {"level": 8.41},
                "invalidation_price": 8.5,
                "atr": 0.2,
                "round_trip_cost_bps": None,
                "level_basis": "研究依据",
                "signal_known_when": "信号说明",
                "entry_window": "时段说明",
                "entry_expiry": "有效期说明",
                "gap_or_no_fill_action": "跳空处理",
                "invalidation_observation": "失效观察",
            }
        ]
    }
    input_path = tmp_path / "invalidation.json"
    input_path.write_text(json.dumps(input_payload, ensure_ascii=False), encoding="utf-8")
    summary = calculate_buy_decision(
        run_dir=prepared_run["run_dir"], analysis_input_path=input_path
    )
    analysis = json.loads(
        Path(summary["analysis_file"]).read_text(encoding="utf-8")
    )
    assert analysis["plans_computed"][0]["geometry"]["invalidation"][
        "below_entry"
    ] is False
    assert analysis["plans_computed"][0]["warnings"]


def test_calculate_requires_matching_request_and_context(prepared_run, tmp_path):
    run_dir = prepared_run["run_dir"]
    request = json.loads(
        (run_dir / "request.json").read_text(encoding="utf-8")
    )
    request["as_of"] = "2026-09-09T10:00:00+08:00"
    (run_dir / "request.json").write_text(
        json.dumps(request, ensure_ascii=False), encoding="utf-8"
    )
    input_path = tmp_path / "analysis-input.json"
    input_path.write_text(json.dumps({"plans": []}), encoding="utf-8")
    with pytest.raises(ValueError, match="as_of"):
        calculate_buy_decision(run_dir=run_dir, analysis_input_path=input_path)


def test_cli_prepare_and_calculate_run_end_to_end(tmp_path, capsys):
    from stock_analyzer.ops.buy_decision import main

    warehouse_root = tmp_path / "warehouse"
    warehouse_root.mkdir()
    project_root = tmp_path / "project"
    project_root.mkdir()
    _commit_price_data(ResearchWarehouse(warehouse_root), "603969.SH")
    _write_registry(project_root)
    request_path = tmp_path / "request.json"
    _write_request(request_path)
    run_dir = tmp_path / "runs" / "run-cli"
    exit_code = main(
        [
            "prepare",
            "--request",
            str(request_path),
            "--output-dir",
            str(run_dir),
            "--warehouse-root",
            str(warehouse_root),
            "--project-root",
            str(project_root),
        ]
    )
    assert exit_code == 0
    assert (run_dir / "context.json").is_file()
    input_path = tmp_path / "analysis-input.json"
    input_path.write_text(json.dumps({"plans": []}), encoding="utf-8")
    exit_code = main(
        [
            "calculate",
            "--run-dir",
            str(run_dir),
            "--analysis-input",
            str(input_path),
        ]
    )
    assert exit_code == 0
    assert (run_dir / "analysis.json").is_file()
    exit_code = main(
        [
            "prepare",
            "--request",
            str(request_path),
            "--output-dir",
            str(run_dir),
            "--warehouse-root",
            str(warehouse_root),
            "--project-root",
            str(project_root),
        ]
    )
    assert exit_code == 2
