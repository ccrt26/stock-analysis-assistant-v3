from __future__ import annotations

from stock_analyzer.domain.models import StockSnapshot


def clean_stock_pool(stocks: list[StockSnapshot]) -> tuple[list[StockSnapshot], list[StockSnapshot]]:
    included: list[StockSnapshot] = []
    excluded: list[StockSnapshot] = []
    for stock in stocks:
        if stock.is_hard_excluded:
            excluded.append(stock)
        else:
            included.append(stock)
    return included, excluded
