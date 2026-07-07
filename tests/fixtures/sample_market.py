from datetime import date

from stock_analyzer.domain.models import StockSnapshot


def sample_stocks() -> list[StockSnapshot]:
    trade_date = date(2026, 7, 7)
    return [
        StockSnapshot(
            trade_date=trade_date,
            ts_code="600000.SH",
            name="稳健样本",
            listing_days=3000,
            turnover_rate=1.1,
            amount=400_000_000,
        ),
        StockSnapshot(
            trade_date=trade_date,
            ts_code="000001.SZ",
            name="*ST 风险",
            is_st=True,
            listing_days=3000,
            turnover_rate=1.1,
            amount=400_000_000,
        ),
        StockSnapshot(
            trade_date=trade_date,
            ts_code="300001.SZ",
            name="次新样本",
            listing_days=60,
            turnover_rate=3.0,
            amount=500_000_000,
        ),
        StockSnapshot(
            trade_date=trade_date,
            ts_code="600001.SH",
            name="低流动性",
            listing_days=3000,
            turnover_rate=0.1,
            amount=20_000_000,
        ),
    ]
