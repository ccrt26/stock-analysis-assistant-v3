from datetime import date

import pytest

from stock_analyzer.domain.models import ActionLabel, Recommendation, StockSnapshot


def test_recommendation_allows_only_approved_action_labels():
    rec = Recommendation(
        trade_date=date(2026, 7, 7),
        ts_code="600000.SH",
        name="浦发银行",
        action=ActionLabel.ENTER_OBSERVATION,
        score=72.5,
        reasons=["趋势改善", "流动性充足"],
        risks=["银行板块弹性有限"],
    )
    assert rec.action.value == "进入观察"


def test_stock_snapshot_flags_st_stock():
    stock = StockSnapshot(
        trade_date=date(2026, 7, 7),
        ts_code="000001.SZ",
        name="*ST 示例",
        is_st=True,
        is_suspended=False,
        listing_days=500,
        turnover_rate=1.2,
        amount=300_000_000,
    )
    assert stock.is_hard_excluded is True


def test_invalid_action_label_rejected():
    with pytest.raises(ValueError):
        Recommendation(
            trade_date=date(2026, 7, 7),
            ts_code="600000.SH",
            name="浦发银行",
            action="买入",
            score=88,
            reasons=[],
            risks=[],
        )
