from datetime import date

import pandas as pd

from stock_analyzer.data.fundamental_backfill import FundamentalBackfillService
from stock_analyzer.data.research_contracts import ResearchDatasetId
from stock_analyzer.data.tushare_research_client import TushareResearchClient
from stock_analyzer.storage.research_warehouse import ResearchWarehouse


class FundamentalPro:
    def __init__(self):
        self.calls = []

    def stock_company(self, **kwargs):
        self.calls.append(("stock_company", kwargs))
        if kwargs["exchange"] != "SZSE":
            return pd.DataFrame(columns=[
                "ts_code", "com_name", "com_id", "chairman", "manager", "secretary",
                "reg_capital", "setup_date", "province", "city", "introduction", "website",
                "email", "office", "business_scope", "employees", "main_business", "exchange"
            ])
        return pd.DataFrame([{
            "ts_code": "000001.SZ", "com_name": "平安银行", "com_id": "id",
            "chairman": "A", "manager": "B", "secretary": "C", "reg_capital": 1.0,
            "setup_date": "19871222", "province": "广东", "city": "深圳",
            "introduction": "银行业务", "website": "x", "email": "x", "office": "x",
            "business_scope": "银行", "employees": 1, "main_business": "银行业务",
            "exchange": "SZSE",
        }])

    def income(self, **kwargs):
        self.calls.append(("income", kwargs))
        return pd.DataFrame([
            {"ts_code": "000001.SZ", "ann_date": "20260420", "f_ann_date": "20260420",
             "end_date": "20260331", "report_type": "1", "comp_type": "2", "end_type": "1",
             "total_revenue": 100.0, "n_income_attr_p": 10.0, "update_flag": "0"},
            {"ts_code": "000001.SZ", "ann_date": "20260425", "f_ann_date": "20260425",
             "end_date": "20260331", "report_type": "1", "comp_type": "2", "end_type": "1",
             "total_revenue": 101.0, "n_income_attr_p": 10.0, "update_flag": "1"},
        ])

    def balancesheet(self, **kwargs):
        self.calls.append(("balancesheet", kwargs))
        return pd.DataFrame([{
            "ts_code": "000001.SZ", "ann_date": "20260425", "f_ann_date": "20260425",
            "end_date": "20260331", "report_type": "1", "comp_type": "2", "end_type": "1",
            "total_assets": 1000.0, "total_liab": 900.0, "update_flag": "1",
        }])

    def cashflow(self, **kwargs):
        self.calls.append(("cashflow", kwargs))
        return pd.DataFrame([{
            "ts_code": "000001.SZ", "ann_date": "20260425", "f_ann_date": "20260425",
            "end_date": "20260331", "report_type": "1", "comp_type": "2", "end_type": "1",
            "n_cashflow_act": 12.0, "update_flag": "1",
        }])

    def fina_indicator(self, **kwargs):
        self.calls.append(("fina_indicator", kwargs))
        return pd.DataFrame([{
            "ts_code": "000001.SZ", "ann_date": "20260425", "end_date": "20260331",
            "roe": 3.0, "grossprofit_margin": 20.0,
        }])

    def fina_mainbz(self, **kwargs):
        self.calls.append(("fina_mainbz", kwargs))
        return pd.DataFrame([{
            "ts_code": "000001.SZ", "end_date": "20260331", "bz_item": "零售银行(产品)",
            "bz_code": "1", "bz_sales": 80.0, "bz_profit": 20.0, "bz_cost": 60.0,
            "curr_type": "CNY",
        }])

    def forecast(self, **kwargs):
        self.calls.append(("forecast", kwargs))
        return pd.DataFrame(columns=[
            "ts_code", "ann_date", "end_date", "type", "p_change_min", "p_change_max",
            "net_profit_min", "net_profit_max", "last_parent_net", "first_ann_date", "summary",
            "change_reason", "update_flag"
        ])

    def express(self, **kwargs):
        self.calls.append(("express", kwargs))
        return pd.DataFrame([{
            "ts_code": "000001.SZ", "ann_date": "20260410", "end_date": "20260331",
            "revenue": 99.0, "n_income": 9.0, "update_flag": "0",
        }])


def test_fundamental_backfill_preserves_statement_revision_and_full_business_context(tmp_path):
    warehouse = ResearchWarehouse(tmp_path / "warehouse")
    service = FundamentalBackfillService(
        TushareResearchClient(FundamentalPro(), pacer=lambda method: None), warehouse
    )

    summary = service.backfill(
        start=date(2021, 7, 14), through=date(2026, 7, 13),
        codes=("000001.SZ",), resume=True,
    )

    income = warehouse.read_current(ResearchDatasetId.INCOME_STATEMENT)
    main_business = warehouse.read_current(ResearchDatasetId.MAIN_BUSINESS)
    assert income.iloc[0]["total_revenue"] == 101.0
    assert warehouse.revision_count(ResearchDatasetId.INCOME_STATEMENT) == 1
    assert main_business.iloc[0]["classification"] == "product"
    assert main_business.iloc[0]["item_name"] == "零售银行(产品)"
    express_manifest = warehouse.partition_manifest(
        ResearchDatasetId.EARNINGS_EXPRESS
    )
    assert express_manifest["partition_value"].tolist() == ["2026-04"]
    assert summary.failed == 0


def test_fundamental_watermark_includes_the_requested_company_scope(tmp_path):
    pro = FundamentalPro()
    warehouse = ResearchWarehouse(tmp_path / "warehouse")
    service = FundamentalBackfillService(
        TushareResearchClient(pro, pacer=lambda method: None), warehouse
    )
    service.backfill(
        start=date(2021, 7, 14), through=date(2026, 7, 13),
        codes=("000001.SZ",), resume=True,
    )
    first_income_calls = len([method for method, _ in pro.calls if method == "income"])

    service.backfill(
        start=date(2021, 7, 14), through=date(2026, 7, 13),
        codes=("000002.SZ",), resume=True,
    )

    income_calls = [kwargs for method, kwargs in pro.calls if method == "income"]
    assert len(income_calls) == first_income_calls + 1
    assert income_calls[-1]["ts_code"] == "000002.SZ"


def test_fundamental_storage_keeps_12_quarters_plus_5_annual_periods(tmp_path):
    class LongHistoryPro(FundamentalPro):
        def income(self, **kwargs):
            current = super().income(**kwargs)
            older = pd.DataFrame(
                [
                    {
                        "ts_code": "000001.SZ",
                        "ann_date": "20230320",
                        "f_ann_date": "20230320",
                        "end_date": "20221231",
                        "report_type": "1",
                        "comp_type": "2",
                        "end_type": "1",
                        "total_revenue": 80.0,
                        "n_income_attr_p": 8.0,
                        "update_flag": "0",
                    },
                    {
                        "ts_code": "000001.SZ",
                        "ann_date": "20221020",
                        "f_ann_date": "20221020",
                        "end_date": "20220930",
                        "report_type": "1",
                        "comp_type": "2",
                        "end_type": "1",
                        "total_revenue": 70.0,
                        "n_income_attr_p": 7.0,
                        "update_flag": "0",
                    },
                ]
            )
            return pd.concat([current, older], ignore_index=True)

    warehouse = ResearchWarehouse(tmp_path / "warehouse")
    service = FundamentalBackfillService(
        TushareResearchClient(LongHistoryPro(), pacer=lambda method: None), warehouse
    )

    service.backfill(
        start=date(2021, 7, 14),
        through=date(2026, 7, 13),
        codes=("000001.SZ",),
        resume=True,
    )

    periods = set(
        pd.to_datetime(
            warehouse.read_current(ResearchDatasetId.INCOME_STATEMENT)[
                "report_period"
            ]
        ).dt.date
    )
    assert date(2022, 12, 31) in periods
    assert date(2022, 9, 30) not in periods
