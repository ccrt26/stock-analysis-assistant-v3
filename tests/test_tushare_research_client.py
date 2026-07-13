from datetime import date

import pandas as pd
import pytest

from stock_analyzer.data.research_contracts import ResearchDatasetId
from stock_analyzer.data.tushare_research_client import (
    ResearchSourceError,
    TushareResearchClient,
)


class FakePro:
    def __init__(self):
        self.calls = []

    def daily(self, **kwargs):
        self.calls.append(("daily", kwargs))
        return pd.DataFrame(
            [
                {
                    "ts_code": "000001.SZ",
                    "trade_date": "20260710",
                    "open": 10.0,
                    "high": 10.5,
                    "low": 9.8,
                    "close": 10.2,
                    "pre_close": 10.0,
                    "change": 0.2,
                    "pct_chg": 2.0,
                    "vol": 123.0,
                    "amount": 456.0,
                }
            ]
        )

    def daily_basic(self, **kwargs):
        self.calls.append(("daily_basic", kwargs))
        return pd.DataFrame(
            [
                {
                    "ts_code": "000001.SZ",
                    "trade_date": "20260710",
                    "close": 10.2,
                    "turnover_rate": 1.2,
                    "turnover_rate_f": 2.3,
                    "volume_ratio": 1.1,
                    "pe": 5.0,
                    "pe_ttm": 5.2,
                    "pb": 0.8,
                    "ps": 1.0,
                    "ps_ttm": 1.1,
                    "dv_ratio": 3.0,
                    "dv_ttm": 3.1,
                    "total_share": 100.0,
                    "float_share": 80.0,
                    "free_share": 60.0,
                    "total_mv": 1020.0,
                    "circ_mv": 816.0,
                }
            ]
        )

    def adj_factor(self, **kwargs):
        self.calls.append(("adj_factor", kwargs))
        return pd.DataFrame(
            [{"ts_code": "000001.SZ", "trade_date": "20260710", "adj_factor": 2.0}]
        )

    def stk_limit(self, **kwargs):
        self.calls.append(("stk_limit", kwargs))
        return pd.DataFrame(
            [{"ts_code": "000001.SZ", "trade_date": "20260710", "up_limit": 11.0, "down_limit": 9.0}]
        )


def test_market_batches_normalize_units_and_business_fields():
    client = TushareResearchClient(FakePro(), pacer=lambda method: None)

    batches = client.fetch_market_date(date(2026, 7, 10), run_id="run-1")
    by_dataset = {batch.dataset_id: batch for batch in batches}

    daily = by_dataset[ResearchDatasetId.EQUITY_DAILY].records[0]
    valuation = by_dataset[ResearchDatasetId.DAILY_BASIC].records[0]
    assert daily["volume"] == 12_300.0
    assert daily["amount"] == 456_000.0
    assert valuation["total_mv"] == 10_200_000.0
    assert valuation["total_share"] == 1_000_000.0
    assert set(by_dataset) == {
        ResearchDatasetId.EQUITY_DAILY,
        ResearchDatasetId.ADJ_FACTOR,
        ResearchDatasetId.DAILY_BASIC,
        ResearchDatasetId.STOCK_LIMIT,
    }


def test_schema_change_fails_instead_of_guessing_column():
    pro = FakePro()
    pro.daily = lambda **kwargs: pd.DataFrame([{"code": "000001.SZ"}])
    client = TushareResearchClient(pro, pacer=lambda method: None)

    with pytest.raises(ResearchSourceError, match="missing columns") as exc:
        client.fetch_market_date(date(2026, 7, 10), run_id="run-1")
    assert exc.value.category == "schema"


def test_permission_error_is_distinguished_from_empty_upstream():
    pro = FakePro()

    def denied(**kwargs):
        raise Exception("抱歉，您没有接口访问权限")

    pro.daily = denied
    client = TushareResearchClient(pro, pacer=lambda method: None)
    with pytest.raises(ResearchSourceError) as exc:
        client.call("daily", trade_date="20260710")
    assert exc.value.category == "permission_denied"
