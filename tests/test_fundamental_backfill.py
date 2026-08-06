from datetime import date, datetime, timezone

import pandas as pd

from stock_analyzer.data.fundamental_backfill import FundamentalBackfillService
from stock_analyzer.data.research_contracts import FactBatch, ResearchDatasetId
from stock_analyzer.data.tushare_research_client import TushareResearchClient
from stock_analyzer.storage.research_query import ResearchQuery
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
    company = warehouse.read_current(ResearchDatasetId.COMPANY_PROFILE)
    assert company.iloc[0]["available_at"] == company.iloc[0]["ingested_at"]
    assert company.iloc[0]["availability_precision"] == "ingestion_cutoff"
    assert set(income["availability_precision"]) == {"date_conservative"}
    assert summary.failed == 0


def test_initial_backfill_reconstructs_dated_provider_revision_timeline(tmp_path):
    warehouse = ResearchWarehouse(tmp_path / "warehouse")
    service = FundamentalBackfillService(
        TushareResearchClient(FundamentalPro(), pacer=lambda method: None), warehouse
    )

    service.backfill(
        start=date(2021, 7, 14),
        through=date(2026, 7, 13),
        codes=("000001.SZ",),
        resume=False,
    )

    query = ResearchQuery(warehouse)
    after_first_publication = query.dataset_as_of(
        ResearchDatasetId.INCOME_STATEMENT,
        datetime(2026, 4, 21, 1, tzinfo=timezone.utc),
    )
    after_second_publication = query.dataset_as_of(
        ResearchDatasetId.INCOME_STATEMENT,
        datetime(2026, 4, 26, 1, tzinfo=timezone.utc),
    )
    assert after_first_publication.iloc[0]["total_revenue"] == 100.0
    assert after_second_publication.iloc[0]["total_revenue"] == 101.0


def test_same_time_provider_variants_converge_across_forced_refreshes(tmp_path):
    class SameTimeVariantPro(FundamentalPro):
        def income(self, **kwargs):
            self.calls.append(("income", kwargs))
            return pd.DataFrame(
                [
                    {
                        "ts_code": "000001.SZ",
                        "ann_date": "20260425",
                        "f_ann_date": "20260425",
                        "end_date": "20260331",
                        "report_type": "1",
                        "comp_type": "2",
                        "end_type": "1",
                        "total_revenue": 100.0,
                        "n_income_attr_p": 10.0,
                        "update_flag": "0",
                    },
                    {
                        "ts_code": "000001.SZ",
                        "ann_date": "20260425",
                        "f_ann_date": "20260425",
                        "end_date": "20260331",
                        "report_type": "1",
                        "comp_type": "2",
                        "end_type": "1",
                        "total_revenue": 101.0,
                        "n_income_attr_p": 10.0,
                        "update_flag": "1",
                    },
                ]
            )

    warehouse = ResearchWarehouse(tmp_path / "warehouse")
    service = FundamentalBackfillService(
        TushareResearchClient(SameTimeVariantPro(), pacer=lambda method: None),
        warehouse,
    )

    service.backfill(
        start=date(2021, 7, 14),
        through=date(2026, 7, 13),
        codes=("000001.SZ",),
        resume=False,
    )
    first_revision_count = warehouse.revision_count(
        ResearchDatasetId.INCOME_STATEMENT
    )
    service.backfill(
        start=date(2021, 7, 14),
        through=date(2026, 7, 13),
        codes=("000001.SZ",),
        resume=False,
    )

    income = warehouse.read_current(ResearchDatasetId.INCOME_STATEMENT)
    assert income.iloc[0]["total_revenue"] == 101.0
    assert income.iloc[0]["update_flag"] == "1"
    assert first_revision_count == 0
    assert warehouse.revision_count(ResearchDatasetId.INCOME_STATEMENT) == 0


def test_same_time_indicator_variants_keep_the_already_known_payload(tmp_path):
    class IndicatorVariantPro(FundamentalPro):
        def __init__(self):
            super().__init__()
            self.include_ambiguous_variant = False

        def fina_indicator(self, **kwargs):
            self.calls.append(("fina_indicator", kwargs))
            preferred = {
                "ts_code": "000001.SZ",
                "ann_date": "20260425",
                "end_date": "20260331",
                "roe": 3.0,
                "fcff": 4_607_674.0,
            }
            rows = [preferred]
            if self.include_ambiguous_variant:
                rows.insert(0, preferred | {"fcff": -146_205_000.0})
            return pd.DataFrame(rows)

    pro = IndicatorVariantPro()
    warehouse = ResearchWarehouse(tmp_path / "warehouse")
    service = FundamentalBackfillService(
        TushareResearchClient(pro, pacer=lambda method: None), warehouse
    )
    options = {
        "start": date(2021, 7, 14),
        "through": date(2026, 7, 13),
        "codes": ("000001.SZ",),
        "resume": False,
    }
    service.backfill(**options)
    pro.include_ambiguous_variant = True

    service.backfill(**options)

    indicator = warehouse.read_current(ResearchDatasetId.FINANCIAL_INDICATOR)
    assert indicator.iloc[0]["fcff"] == 4_607_674.0
    assert warehouse.revision_count(ResearchDatasetId.FINANCIAL_INDICATOR) == 0


def test_new_ambiguous_indicator_key_is_declared_unknown_without_losing_clear_key(
    tmp_path,
):
    class NewIndicatorVariantPro(FundamentalPro):
        def fina_indicator(self, **kwargs):
            self.calls.append(("fina_indicator", kwargs))
            base = {
                "ts_code": "000001.SZ",
                "ann_date": "20260425",
                "end_date": "20260331",
                "roe": 3.0,
            }
            return pd.DataFrame(
                [
                    base | {"fcff": -146_205_000.0},
                    base | {"fcff": 4_607_674.0},
                    {
                        "ts_code": "000001.SZ",
                        "ann_date": "20260330",
                        "end_date": "20251231",
                        "roe": 2.0,
                        "fcff": 1_000_000.0,
                    },
                ]
            )

    warehouse = ResearchWarehouse(tmp_path / "warehouse")
    service = FundamentalBackfillService(
        TushareResearchClient(
            NewIndicatorVariantPro(), pacer=lambda method: None
        ),
        warehouse,
    )

    summary = service.backfill(
        start=date(2021, 7, 14),
        through=date(2026, 7, 13),
        codes=("000001.SZ",),
        resume=False,
    )

    indicator = warehouse.read_current(ResearchDatasetId.FINANCIAL_INDICATOR)
    assert summary.failed == 0
    assert summary.limited == 1
    assert summary.limitations_checked is True
    assert any("2026-03-31" in issue for issue in summary.issues)
    assert pd.Timestamp(indicator.iloc[0]["report_period"]).date() == date(
        2025, 12, 31
    )


def test_main_business_uses_provider_type_code_in_business_key(tmp_path):
    class MainBusinessTypePro(FundamentalPro):
        def fina_mainbz(self, **kwargs):
            self.calls.append(("fina_mainbz", kwargs))
            base = {
                "ts_code": "000001.SZ",
                "end_date": "20260331",
                "bz_item": "租赁",
                "bz_sales": 30_874_361.5,
                "bz_profit": 20_305_768.33,
                "bz_cost": 10_568_593.17,
                "curr_type": "CNY",
            }
            return pd.DataFrame(
                [base | {"bz_code": "P"}, base | {"bz_code": "I"}]
            )

    warehouse = ResearchWarehouse(tmp_path / "warehouse")
    service = FundamentalBackfillService(
        TushareResearchClient(
            MainBusinessTypePro(), pacer=lambda method: None
        ),
        warehouse,
    )

    summary = service.backfill(
        start=date(2021, 7, 14),
        through=date(2026, 7, 13),
        codes=("000001.SZ",),
        resume=False,
    )

    main_business = warehouse.read_current(ResearchDatasetId.MAIN_BUSINESS)
    assert summary.limited == 0
    assert set(main_business["classification"]) == {"product", "industry"}
    assert main_business["business_key_hash"].nunique() == 2


def test_company_profile_refreshes_and_unchanged_observation_converges(tmp_path):
    pro = FundamentalPro()
    warehouse = ResearchWarehouse(tmp_path / "warehouse")
    service = FundamentalBackfillService(
        TushareResearchClient(pro, pacer=lambda method: None), warehouse
    )

    for through in (date(2026, 7, 13), date(2026, 7, 14)):
        service.backfill(
            start=date(2021, 7, 14),
            through=through,
            codes=("000001.SZ",),
            resume=True,
        )

    profiles = warehouse.read_current(ResearchDatasetId.COMPANY_PROFILE)
    company_calls = [method for method, _ in pro.calls if method == "stock_company"]
    assert len(company_calls) == 6
    assert len(profiles) == 1
    assert pd.Timestamp(profiles.iloc[0]["valid_from"]).date() == date(2026, 7, 13)
    assert warehouse.revision_count(ResearchDatasetId.COMPANY_PROFILE) == 0


def test_company_profile_change_closes_old_observation_period(tmp_path):
    class ChangingProfilePro(FundamentalPro):
        introduction = "银行业务"

        def stock_company(self, **kwargs):
            frame = super().stock_company(**kwargs)
            if not frame.empty:
                frame.loc[:, "introduction"] = self.introduction
            return frame

    pro = ChangingProfilePro()
    warehouse = ResearchWarehouse(tmp_path / "warehouse")
    service = FundamentalBackfillService(
        TushareResearchClient(pro, pacer=lambda method: None), warehouse
    )
    service.backfill(
        start=date(2021, 7, 14),
        through=date(2026, 7, 13),
        codes=("000001.SZ",),
        resume=True,
    )
    pro.introduction = "银行与综合金融服务"

    service.backfill(
        start=date(2021, 7, 14),
        through=date(2026, 7, 15),
        codes=("000001.SZ",),
        resume=True,
    )

    profiles = warehouse.read_current(ResearchDatasetId.COMPANY_PROFILE)
    profiles = profiles.sort_values("valid_from").reset_index(drop=True)
    assert len(profiles) == 2
    assert pd.Timestamp(profiles.iloc[0]["valid_to"]).date() == date(2026, 7, 14)
    assert pd.isna(profiles.iloc[1]["valid_to"])
    assert profiles.iloc[1]["introduction"] == "银行与综合金融服务"
    assert warehouse.revision_count(ResearchDatasetId.COMPANY_PROFILE) == 1


def test_targeted_fundamental_retry_ignores_unrelated_staging_files(tmp_path):
    warehouse = ResearchWarehouse(tmp_path / "warehouse")
    unrelated = FundamentalPro().income().copy()
    unrelated["ts_code"] = "000002.SZ"
    unrelated_path = (
        warehouse.root
        / ".backfill_staging"
        / "fundamentals"
        / ResearchDatasetId.INCOME_STATEMENT.value
        / "000002.SZ.parquet"
    )
    unrelated_path.parent.mkdir(parents=True, exist_ok=True)
    unrelated.to_parquet(unrelated_path, index=False)
    service = FundamentalBackfillService(
        TushareResearchClient(FundamentalPro(), pacer=lambda method: None), warehouse
    )

    service.backfill(
        start=date(2021, 7, 14),
        through=date(2026, 7, 13),
        codes=("000001.SZ",),
        resume=True,
    )

    income = warehouse.read_current(ResearchDatasetId.INCOME_STATEMENT)
    assert set(income["ts_code"]) == {"000001.SZ"}


def test_fundamental_staging_from_another_date_scope_is_not_reused(tmp_path):
    warehouse = ResearchWarehouse(tmp_path / "warehouse")
    stale = FundamentalPro().income().copy()
    stale.loc[:, "total_revenue"] = 999.0
    stale_path = (
        warehouse.root
        / ".backfill_staging"
        / "fundamentals"
        / ResearchDatasetId.INCOME_STATEMENT.value
        / "000001.SZ.parquet"
    )
    stale_path.parent.mkdir(parents=True, exist_ok=True)
    stale.to_parquet(stale_path, index=False)
    pro = FundamentalPro()
    service = FundamentalBackfillService(
        TushareResearchClient(pro, pacer=lambda method: None), warehouse
    )

    service.backfill(
        start=date(2021, 7, 14),
        through=date(2026, 7, 13),
        codes=("000001.SZ",),
        resume=True,
    )

    assert len([method for method, _ in pro.calls if method == "income"]) == 1
    income = warehouse.read_current(ResearchDatasetId.INCOME_STATEMENT)
    assert income.iloc[0]["total_revenue"] == 101.0


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


def test_expected_core_financial_empty_result_is_retried_not_watermarked(tmp_path):
    class EmptyIncomePro(FundamentalPro):
        def income(self, **kwargs):
            self.calls.append(("income", kwargs))
            return pd.DataFrame()

    pro = EmptyIncomePro()
    warehouse = ResearchWarehouse(tmp_path / "warehouse")
    service = FundamentalBackfillService(
        TushareResearchClient(pro, pacer=lambda method: None), warehouse
    )

    first = service.backfill(
        start=date(2021, 7, 14),
        through=date(2026, 7, 13),
        codes=("000001.SZ",),
        resume=True,
    )
    second = service.backfill(
        start=date(2021, 7, 14),
        through=date(2026, 7, 13),
        codes=("000001.SZ",),
        resume=True,
    )

    income_calls = [method for method, _ in pro.calls if method == "income"]
    assert len(income_calls) == 2
    assert first.waiting_upstream == 1
    assert second.waiting_upstream == 1
    assert first.retry_codes == ["000001.SZ"]
    assert second.retry_codes == ["000001.SZ"]
    assert not (
        warehouse.root
        / ".backfill_staging"
        / "fundamentals"
        / ResearchDatasetId.INCOME_STATEMENT.value
        / "000001.SZ.parquet"
    ).exists()


def test_provider_error_keeps_the_exact_fundamental_code_for_retry(tmp_path):
    class FailingIncomePro(FundamentalPro):
        def income(self, **kwargs):
            raise RuntimeError("temporary provider failure")

    warehouse = ResearchWarehouse(tmp_path / "warehouse")
    service = FundamentalBackfillService(
        TushareResearchClient(FailingIncomePro(), pacer=lambda method: None),
        warehouse,
    )

    summary = service.backfill(
        start=date(2021, 7, 14),
        through=date(2026, 7, 13),
        codes=("000001.SZ",),
        resume=True,
    )

    assert summary.failed == 1
    assert summary.retry_codes == ["000001.SZ"]


def test_recent_listing_without_due_periodic_report_can_complete_empty(tmp_path):
    class EmptyIncomePro(FundamentalPro):
        def income(self, **kwargs):
            self.calls.append(("income", kwargs))
            return pd.DataFrame()

    pro = EmptyIncomePro()
    warehouse = ResearchWarehouse(tmp_path / "warehouse")
    available_at = datetime(2026, 7, 13, 10, tzinfo=timezone.utc)
    warehouse.commit_batch(
        FactBatch(
            dataset_id=ResearchDatasetId.SECURITY_MASTER,
            partition_value="security-master",
            source_name="test",
            source_endpoint="stock_basic",
            ingestion_run_id="security-master",
            ingested_at=available_at,
            default_available_at=available_at,
            records=[
                {
                    "ts_code": "000001.SZ",
                    "valid_from": date(2026, 4, 1),
                    "list_date": date(2026, 4, 1),
                    "list_status": "L",
                }
            ],
        )
    )
    service = FundamentalBackfillService(
        TushareResearchClient(pro, pacer=lambda method: None), warehouse
    )

    first = service.backfill(
        start=date(2021, 7, 14),
        through=date(2026, 7, 13),
        codes=("000001.SZ",),
        resume=True,
    )
    second = service.backfill(
        start=date(2021, 7, 14),
        through=date(2026, 7, 13),
        codes=("000001.SZ",),
        resume=True,
    )

    income_calls = [method for method, _ in pro.calls if method == "income"]
    assert len(income_calls) == 1
    assert first.waiting_upstream == 0
    assert second.skipped == 1
