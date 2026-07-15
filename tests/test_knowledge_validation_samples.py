from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import pytest

from stock_analyzer.data.research_contracts import FactBatch, ResearchDatasetId
from stock_analyzer.knowledge_validation.samples import (
    adjusted_future_price,
    build_study_sample,
    eligible_stock_rows,
    label_path,
    materialize_signal_snapshot,
    next_trading_sessions,
    split_signal_and_label_columns,
)
from stock_analyzer.knowledge_validation.spec_registry import load_validation_registry
from stock_analyzer.storage.research_query import ResearchQuery
from stock_analyzer.storage.research_warehouse import ResearchWarehouse


def test_adjusted_future_price_uses_both_factors():
    assert adjusted_future_price(55, future_factor=2, base_factor=1) == 110


@pytest.mark.parametrize(
    ("raw_price", "future_factor", "base_factor"),
    [(0, 1, 1), (10, 0, 1), (10, 1, 0), (10, -1, 1)],
)
def test_adjusted_future_price_rejects_nonpositive_inputs(
    raw_price: float,
    future_factor: float,
    base_factor: float,
):
    with pytest.raises(ValueError, match="positive"):
        adjusted_future_price(raw_price, future_factor, base_factor)


def test_high_can_touch_without_close_earning_target():
    future_high = [105.0] * 30
    future_high[4] = 121.0
    future_close = [101.0] * 30
    future_close[9] = 109.0
    future_close[19] = 112.0
    future_close[29] = 118.0

    labels = label_path(
        base_close=100,
        future_high=future_high,
        future_close=future_close,
        future_low=[95.0] * 30,
    )

    assert labels["touch_20pct_10d"] is True
    assert labels["close_return_1d"] == pytest.approx(0.01)
    assert labels["close_return_5d"] == pytest.approx(0.01)
    assert labels["close_return_10d"] == pytest.approx(0.09)
    assert labels["first_touch_20pct_session_10d"] == 5
    assert labels["close_return_10d"] < 0.20


def test_missing_future_horizon_is_explicitly_unlabelled():
    labels = label_path(
        base_close=100,
        future_high=[110.0] * 15,
        future_close=[105.0] * 15,
    )

    assert labels["close_return_10d"] == pytest.approx(0.05)
    assert labels["close_return_20d"] is None
    assert labels["touch_20pct_30d"] is None


def test_next_trading_sessions_uses_only_open_dates_after_analysis_day():
    calendar = pd.DataFrame(
        {
            "cal_date": [
                "2026-07-10",
                "2026-07-11",
                "2026-07-12",
                "2026-07-13",
                "2026-07-14",
            ],
            "is_open": [True, False, False, True, True],
        }
    )

    assert next_trading_sessions(calendar, date(2026, 7, 10), count=2) == (
        date(2026, 7, 13),
        date(2026, 7, 14),
    )


def test_eligible_stock_rows_excludes_future_listings_delisted_suspended_and_missing_close():
    securities = pd.DataFrame(
        [
            {"ts_code": "ELIGIBLE", "list_date": "2020-01-01", "delist_date": None},
            {"ts_code": "FUTURE", "list_date": "2026-07-11", "delist_date": None},
            {"ts_code": "DELISTED", "list_date": "2020-01-01", "delist_date": "2026-07-09"},
            {"ts_code": "SUSPENDED", "list_date": "2020-01-01", "delist_date": None},
            {"ts_code": "NO_CLOSE", "list_date": "2020-01-01", "delist_date": None},
        ]
    )
    daily = pd.DataFrame(
        [
            {"ts_code": "ELIGIBLE", "trade_date": "2026-07-10", "close": 10.0},
            {"ts_code": "FUTURE", "trade_date": "2026-07-10", "close": 10.0},
            {"ts_code": "DELISTED", "trade_date": "2026-07-10", "close": 10.0},
            {"ts_code": "SUSPENDED", "trade_date": "2026-07-10", "close": 10.0},
            {"ts_code": "NO_CLOSE", "trade_date": "2026-07-10", "close": None},
        ]
    )
    suspensions = pd.DataFrame(
        [{"ts_code": "SUSPENDED", "trade_date": "2026-07-10", "suspend_type": "全天"}]
    )

    result = eligible_stock_rows(
        securities,
        daily,
        suspensions,
        analysis_date=date(2026, 7, 10),
    )

    assert result["ts_code"].tolist() == ["ELIGIBLE"]


def _announcement_batch(*, title: str, available_at: datetime, run_id: str) -> FactBatch:
    return FactBatch(
        dataset_id=ResearchDatasetId.ANNOUNCEMENT,
        partition_value="2026-07",
        source_name="cninfo",
        source_endpoint="new/hisAnnouncement/query",
        ingestion_run_id=run_id,
        ingested_at=available_at,
        default_available_at=available_at,
        records=[
            {
                "announcement_id": "ANN-1",
                "ts_code": "000001.SZ",
                "announcement_time": available_at,
                "title": title,
                "url": "https://example.invalid/ANN-1.pdf",
            }
        ],
    )


def test_signal_snapshot_uses_shanghai_close_and_excludes_later_revision(tmp_path):
    warehouse = ResearchWarehouse(tmp_path)
    first_time = datetime(2026, 7, 10, 6, tzinfo=timezone.utc)
    corrected_time = datetime(2026, 7, 10, 8, tzinfo=timezone.utc)
    warehouse.commit_batch(
        _announcement_batch(title="首次公告", available_at=first_time, run_id="r1")
    )
    warehouse.commit_batch(
        _announcement_batch(title="盘后更正", available_at=corrected_time, run_id="r2")
    )

    snapshot = materialize_signal_snapshot(
        ResearchQuery(warehouse),
        {ResearchDatasetId.ANNOUNCEMENT: ("2026-07",)},
        analysis_date=date(2026, 7, 10),
    )

    assert snapshot.input_manifest["as_of"] == "2026-07-10T07:01:00+00:00"
    assert snapshot.frame(ResearchDatasetId.ANNOUNCEMENT).iloc[0]["title"] == "首次公告"


def test_future_labels_are_kept_out_of_signal_inputs():
    panel = pd.DataFrame(
        {
            "ts_code": ["000001.SZ"],
            "prior_return_20d": [0.1],
            "future_high": [12.1],
            "close_return_10d": [0.09],
            "touch_20pct_10d": [True],
        }
    )

    signal, labels = split_signal_and_label_columns(panel)

    assert signal.columns.tolist() == ["ts_code", "prior_return_20d"]
    assert labels.columns.tolist() == [
        "ts_code",
        "future_high",
        "close_return_10d",
        "touch_20pct_10d",
    ]


class _FakeSnapshot:
    def __init__(self, frames, manifest_hash):
        self._frames = frames
        self.input_manifest = {
            "as_of": "fake",
            "partitions": [],
            "input_manifest_hash": manifest_hash,
        }

    def frame(self, dataset_id):
        return self._frames.get(ResearchDatasetId(dataset_id), pd.DataFrame()).copy()


class _FakeWarehouse:
    def __init__(self, partitions):
        self.partitions = partitions

    def partition_manifest(self, dataset_id, partition_values=None):
        values = self.partitions.get(ResearchDatasetId(dataset_id), ())
        return pd.DataFrame({"partition_value": values})


class _FakeQuery:
    def __init__(self, dates):
        self.dates = dates
        self.warehouse = _FakeWarehouse(
            {
                ResearchDatasetId.TRADE_CALENDAR: tuple(
                    sorted({str(item.year) for item in dates})
                ),
                ResearchDatasetId.SECURITY_MASTER: ("security-master",),
                ResearchDatasetId.EQUITY_DAILY: tuple(item.isoformat() for item in dates),
                ResearchDatasetId.ADJ_FACTOR: tuple(item.isoformat() for item in dates),
                ResearchDatasetId.DAILY_BASIC: tuple(item.isoformat() for item in dates),
                ResearchDatasetId.INDEX_DAILY: tuple(item.isoformat() for item in dates),
                ResearchDatasetId.INDUSTRY_MEMBER: ("SW2021",),
                ResearchDatasetId.INDUSTRY_DAILY: tuple(item.isoformat() for item in dates),
                ResearchDatasetId.SUSPENSION: tuple(item.isoformat() for item in dates),
            }
        )
        self.calls = []

    def materialize_snapshot(self, dataset_partitions, *, as_of):
        self.calls.append((dataset_partitions, as_of))
        frames = {}
        requested_dates = {
            date.fromisoformat(value)
            for values in dataset_partitions.values()
            for value in ([values] if isinstance(values, str) else values)
            if len(str(value)) == 10 and str(value)[4] == "-"
        }
        if ResearchDatasetId.TRADE_CALENDAR in dataset_partitions:
            frames[ResearchDatasetId.TRADE_CALENDAR] = pd.DataFrame(
                {"cal_date": self.dates, "is_open": [True] * len(self.dates)}
            )
        if ResearchDatasetId.SECURITY_MASTER in dataset_partitions:
            frames[ResearchDatasetId.SECURITY_MASTER] = pd.DataFrame(
                [
                    {
                        "ts_code": "000001.SZ",
                        "list_date": "2000-01-01",
                        "delist_date": None,
                        "exchange": "SZSE",
                        "market": "主板",
                    }
                ]
            )
        if ResearchDatasetId.EQUITY_DAILY in dataset_partitions:
            rows = []
            for index, session in enumerate(self.dates):
                if session not in requested_dates:
                    continue
                close = 10.0 + index * 0.1
                rows.append(
                    {
                        "trade_date": session,
                        "ts_code": "000001.SZ",
                        "open": close,
                        "high": close * 1.01,
                        "low": close * 0.99,
                        "close": close,
                        "volume": 100.0,
                    }
                )
            frames[ResearchDatasetId.EQUITY_DAILY] = pd.DataFrame(rows)
        if ResearchDatasetId.ADJ_FACTOR in dataset_partitions:
            frames[ResearchDatasetId.ADJ_FACTOR] = pd.DataFrame(
                [
                    {"trade_date": session, "ts_code": "000001.SZ", "adj_factor": 1.0}
                    for session in self.dates
                    if session in requested_dates
                ]
            )
        if ResearchDatasetId.DAILY_BASIC in dataset_partitions:
            frames[ResearchDatasetId.DAILY_BASIC] = pd.DataFrame(
                [
                    {
                        "trade_date": session,
                        "ts_code": "000001.SZ",
                        "pe_ttm": 10.0,
                        "circ_mv": 100.0,
                    }
                    for session in self.dates
                    if session in requested_dates
                ]
            )
        if ResearchDatasetId.INDEX_DAILY in dataset_partitions:
            frames[ResearchDatasetId.INDEX_DAILY] = pd.DataFrame(
                [
                    {
                        "trade_date": session,
                        "index_code": "399001.SZ",
                        "close": 1000.0 + index,
                    }
                    for index, session in enumerate(self.dates)
                    if session in requested_dates
                ]
            )
        if ResearchDatasetId.INDUSTRY_MEMBER in dataset_partitions:
            frames[ResearchDatasetId.INDUSTRY_MEMBER] = pd.DataFrame(
                [
                    {
                        "ts_code": "000001.SZ",
                        "industry_system": "SW2021",
                        "level": "L1",
                        "industry_code": "I1",
                        "valid_from": "2020-01-01",
                        "valid_to": None,
                    }
                ]
            )
        if ResearchDatasetId.INDUSTRY_DAILY in dataset_partitions:
            frames[ResearchDatasetId.INDUSTRY_DAILY] = pd.DataFrame(
                [
                    {
                        "trade_date": session,
                        "industry_code": "I1",
                        "open": 100.0 + index,
                        "high": 101.0 + index,
                        "low": 99.0 + index,
                        "close": 100.0 + index,
                    }
                    for index, session in enumerate(self.dates)
                    if session in requested_dates
                ]
            )
        if ResearchDatasetId.SUSPENSION in dataset_partitions:
            frames[ResearchDatasetId.SUSPENSION] = pd.DataFrame()
        return _FakeSnapshot(frames, f"{'a' if len(self.calls) == 1 else 'b'}" * 64)


def test_build_price_study_sample_materializes_signal_and_future_paths_separately():
    start = date(2026, 1, 1)
    dates = tuple(start + timedelta(days=index) for index in range(51))
    query = _FakeQuery(dates)
    spec_path = (
        Path(__file__).parents[1]
        / "src"
        / "stock_analyzer"
        / "knowledge_validation"
        / "studies.yaml"
    )
    spec = load_validation_registry(spec_path).studies[0]

    sample = build_study_sample(spec, query)

    assert sample.analysis_dates == (dates[20],)
    assert sample.input_manifest_hashes
    assert sample.label_manifest_hashes
    assert sample.panel_row_count == 1
    assert "prior_return_20d" in sample.signal_inputs
    assert not any(column.startswith("future_") for column in sample.signal_inputs)
    assert sample.future_labels.loc[0, "close_return_30d"] is not None
    assert "market_excess_return_20d" in sample.future_labels
    assert query.calls[1][1].astimezone(timezone.utc).hour == 7


def test_build_industry_study_sample_uses_industry_units_and_separate_conditions():
    start = date(2026, 1, 1)
    dates = tuple(start + timedelta(days=index) for index in range(51))
    query = _FakeQuery(dates)
    spec_path = (
        Path(__file__).parents[1]
        / "src"
        / "stock_analyzer"
        / "knowledge_validation"
        / "studies.yaml"
    )
    spec = load_validation_registry(spec_path).studies[3]

    sample = build_study_sample(spec, query)

    assert sample.signal_inputs["industry_code"].tolist() == ["I1"]
    assert sample.signal_inputs.loc[0, "breadth_20d"] == 1.0
    assert "top_contribution_share_20d" in sample.signal_inputs
    assert sample.future_labels.loc[0, "close_return_30d"] is not None
