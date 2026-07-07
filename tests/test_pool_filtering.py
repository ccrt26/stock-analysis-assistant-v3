from stock_analyzer.analysis.pool import clean_stock_pool
from tests.fixtures.sample_market import sample_stocks


def test_clean_stock_pool_excludes_hard_risks():
    included, excluded = clean_stock_pool(sample_stocks())
    assert [stock.ts_code for stock in included] == ["600000.SH"]
    assert {stock.ts_code for stock in excluded} == {
        "000001.SZ",
        "300001.SZ",
        "600001.SH",
    }
