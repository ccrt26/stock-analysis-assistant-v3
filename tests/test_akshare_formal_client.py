from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from stock_analyzer.data.acquisition import PermanentRouteFailure
from stock_analyzer.data.akshare_formal_client import AkshareFormalEndpointClient
from stock_analyzer.data.formal_contracts import (
    FORMAL_CONTRACT_VERSION,
    build_screening_contracts,
    build_target_contracts,
)
from stock_analyzer.data.readiness import (
    JULY_10_OFFICIAL_SESSIONS,
    AcquisitionGroupId,
    AcquisitionPayload,
    AcquisitionRequest,
    FailureClassification,
    RouteKind,
    validate_group_payload,
)


TARGET = date(2026, 7, 10)
CUTOFF = datetime(2026, 7, 10, 16, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
NEXT_TARGET = date(2026, 7, 13)
CODE = "600000.SH"


def request(codes=(CODE,)) -> AcquisitionRequest:
    return AcquisitionRequest(
        run_id="formal-2026-07-10",
        trade_date=TARGET,
        report_cutoff=CUTOFF,
        target_codes=tuple(codes),
        contract_version=FORMAL_CONTRACT_VERSION,
    )


class RecordedAkshare:
    def __init__(self, overrides=None) -> None:
        self.overrides = overrides or {}
        self.calls: list[tuple[str, dict[str, object]]] = []

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)

        def endpoint(**kwargs):
            self.calls.append((name, kwargs))
            override = self.overrides.get(name)
            if isinstance(override, Exception):
                raise override
            if callable(override):
                return override(kwargs)
            if override is not None:
                return override.copy()
            return self._default(name, kwargs)

        return endpoint

    def _default(self, name, kwargs):
        if name == "tool_trade_date_hist_sina":
            return pd.DataFrame({"trade_date": list(JULY_10_OFFICIAL_SESSIONS)})
        if name == "stock_info_sh_name_code":
            return pd.DataFrame(
                [{"证券代码": "600000", "证券简称": "浦发银行", "上市日期": "1999-11-10"}]
            )
        if name == "stock_info_sz_name_code":
            return pd.DataFrame(columns=["A股代码", "A股简称", "A股上市日期"])
        if name == "stock_info_bj_name_code":
            return pd.DataFrame(columns=["证券代码", "证券简称", "上市日期"])
        if name == "stock_info_sh_delist":
            return pd.DataFrame(columns=["公司代码", "公司简称", "终止上市日期"])
        if name == "stock_info_sz_delist":
            return pd.DataFrame(columns=["证券代码", "证券简称", "终止上市日期"])
        if name == "stock_zh_a_spot_em":
            return pd.DataFrame(
                [
                    {
                        "代码": "600000",
                        "名称": "浦发银行",
                        "最新价": 10.5,
                        "今开": 10.0,
                        "最高": 11.0,
                        "最低": 9.0,
                        "昨收": 10.0,
                        "成交量": 1_000_000.0,
                        "成交额": 10_500_000.0,
                        "换手率": 1.2,
                        "市盈率-动态": 9.5,
                        "市净率": 1.1,
                        "总市值": 100_000_000_000.0,
                        "流通市值": 80_000_000_000.0,
                    }
                ]
            )
        if name == "stock_zh_a_hist":
            return pd.DataFrame(
                [
                    {
                        "日期": session,
                        "开盘": 10.0,
                        "收盘": 10.5,
                        "最高": 11.0,
                        "最低": 9.0,
                        "成交量": 1_000_000.0,
                        "成交额": 10_500_000.0,
                        "振幅": 2.0,
                        "涨跌幅": 1.0,
                        "涨跌额": 0.1,
                        "换手率": 1.2,
                    }
                    for session in JULY_10_OFFICIAL_SESSIONS
                ]
            )
        if name == "stock_zh_index_daily_em":
            return pd.DataFrame(
                [
                    {
                        "date": session,
                        "open": 3_000.0,
                        "close": 3_020.0,
                        "high": 3_050.0,
                        "low": 2_990.0,
                        "volume": 2_000_000.0,
                        "amount": 20_000_000.0,
                    }
                    for session in JULY_10_OFFICIAL_SESSIONS
                ]
            )
        if name == "stock_board_industry_name_em":
            return pd.DataFrame([{"排名": 1, "板块名称": "银行", "板块代码": "BK0475"}])
        if name == "stock_board_industry_cons_em":
            return pd.DataFrame([{"序号": 1, "代码": "600000", "名称": "浦发银行"}])
        if name == "stock_board_industry_hist_em":
            return pd.DataFrame(
                [
                    {
                        "日期": session,
                        "开盘": 1_000.0,
                        "收盘": 1_010.0,
                        "最高": 1_020.0,
                        "最低": 990.0,
                        "成交量": 500_000.0,
                        "成交额": 5_000_000.0,
                    }
                    for session in JULY_10_OFFICIAL_SESSIONS[-21:]
                ]
            )
        if name == "stock_individual_info_em":
            return pd.DataFrame(
                [
                    {"item": "股票代码", "value": "600000"},
                    {"item": "股票简称", "value": "浦发银行"},
                    {"item": "行业", "value": "银行"},
                    {"item": "主营业务", "value": "商业银行业务"},
                ]
            )
        if name == "stock_financial_abstract_ths":
            return pd.DataFrame(
                [
                    {
                        "报告期": "2026-03-31",
                        "公告日期": "2026-04-30",
                        "营业总收入同比增长率": 5.0,
                        "净利润同比增长率": 4.0,
                        "销售毛利率": 35.0,
                        "经营活动产生的现金流量净额": 100_000_000.0,
                    }
                ]
            )
        if name == "stock_zh_a_disclosure_report_cninfo":
            columns = ("代码", "简称", "公告标题", "公告时间", "公告链接")
            category = kwargs.get("category", "")
            risk = {
                "代码": "600000",
                "简称": "浦发银行",
                "公告标题": "关于重大事项的风险提示",
                "公告时间": "2026-07-09 15:20:00",
                "公告链接": "https://example.invalid/notice-1",
            }
            if category == "风险提示":
                return pd.DataFrame([risk], columns=columns)
            if category:
                return pd.DataFrame(columns=columns)
            return pd.DataFrame(
                [
                    risk,
                    {
                        "代码": "600000",
                        "简称": "浦发银行",
                        "公告标题": "截止时间后的公告",
                        "公告时间": "2026-07-10 19:00:00",
                        "公告链接": "https://example.invalid/notice-after-cutoff",
                    },
                ],
                columns=columns,
            )
        if name == "stock_board_concept_name_em":
            return pd.DataFrame([{"排名": 1, "板块名称": "中特估", "板块代码": "BK1000"}])
        if name == "stock_board_concept_cons_em":
            return pd.DataFrame(
                [
                    {"序号": 1, "代码": "600000", "名称": "浦发银行"},
                    {"序号": 2, "代码": "000001", "名称": "平安银行"},
                ]
            )
        raise AssertionError(f"unexpected AKShare endpoint: {name}")


def test_akshare_calendar_universe_uses_exchange_lists_and_refuses_unproven_missing_spot_row():
    ak = RecordedAkshare()
    response = AkshareFormalEndpointClient(ak).fetch_calendar_universe(request())

    assert [name for name, _ in ak.calls] == [
        "tool_trade_date_hist_sina",
        "stock_info_sh_name_code",
        "stock_info_sz_name_code",
        "stock_info_bj_name_code",
        "stock_zh_a_spot_em",
    ]
    security = next(row for row in response.records if row["record_type"] == "security")
    assert security["ts_code"] == CODE
    assert security["status_verified"] is True
    assert security["is_suspended"] is False

    missing_spot = RecordedAkshare(
        {"stock_zh_a_spot_em": pd.DataFrame(columns=RecordedAkshare()._default("stock_zh_a_spot_em", {}).columns)}
    )
    missing_response = AkshareFormalEndpointClient(missing_spot).fetch_calendar_universe(request())
    missing_security = next(row for row in missing_response.records if row["record_type"] == "security")
    assert missing_security["status_verified"] is False
    assert missing_security["is_suspended"] is False


def test_akshare_market_builds_whole_82_session_group_without_primary_records():
    primary_sentinel = {"record_type": "equity_bar", "source_name": "primary-sentinel"}
    ak = RecordedAkshare()

    response = AkshareFormalEndpointClient(ak).fetch_market_decision(request())

    assert len(response.covered_dates) == 82
    assert response.covered_dates == JULY_10_OFFICIAL_SESSIONS
    serialized = response.model_dump_json()
    assert primary_sentinel["source_name"] not in serialized
    assert all("tushare" not in source for source in response.source_names)


def test_akshare_market_uses_provider_calendar_for_next_trading_day_window():
    sessions = (*JULY_10_OFFICIAL_SESSIONS[1:], NEXT_TARGET)

    def next_history(kwargs):
        return pd.DataFrame(
            [
                {
                    "日期": session,
                    "开盘": 10.0,
                    "收盘": 10.5,
                    "最高": 11.0,
                    "最低": 9.0,
                    "成交量": 1_000_000.0,
                    "成交额": 10_500_000.0,
                    "振幅": 2.0,
                    "涨跌幅": 1.0,
                    "涨跌额": 0.1,
                    "换手率": 1.2,
                }
                for session in sessions
            ]
        )

    def next_index(kwargs):
        return pd.DataFrame(
            [
                {
                    "date": session,
                    "open": 3_000.0,
                    "close": 3_020.0,
                    "high": 3_050.0,
                    "low": 2_990.0,
                    "volume": 2_000_000.0,
                    "amount": 20_000_000.0,
                }
                for session in sessions
            ]
        )

    ak = RecordedAkshare(
        {
            "tool_trade_date_hist_sina": pd.DataFrame({"trade_date": sessions}),
            "stock_zh_a_hist": next_history,
            "stock_zh_index_daily_em": next_index,
        }
    )
    next_request = request().model_copy(
        update={
            "trade_date": NEXT_TARGET,
            "report_cutoff": datetime(
                2026,
                7,
                13,
                16,
                0,
                tzinfo=ZoneInfo("Asia/Shanghai"),
            ),
        }
    )

    response = AkshareFormalEndpointClient(ak).fetch_market_decision(next_request)

    assert response.covered_dates == sessions
    assert ak.calls[0][0] == "tool_trade_date_hist_sina"


def test_akshare_historical_suspension_gap_keeps_route_with_61_observations():
    history = RecordedAkshare()._default("stock_zh_a_hist", {})
    history = history.drop(index=history.index[-2]).reset_index(drop=True)
    ak = RecordedAkshare({"stock_zh_a_hist": history})

    response = AkshareFormalEndpointClient(ak).fetch_market_decision(request())

    equity = [row for row in response.records if row["record_type"] == "equity_bar"]
    assert len(equity) == len(JULY_10_OFFICIAL_SESSIONS) - 1


def test_akshare_only_60_observations_is_returned_for_feature_exclusion():
    history = RecordedAkshare()._default("stock_zh_a_hist", {}).tail(60)
    ak = RecordedAkshare({"stock_zh_a_hist": history})

    response = AkshareFormalEndpointClient(ak).fetch_market_decision(request())

    equity = [row for row in response.records if row["record_type"] == "equity_bar"]
    assert len(equity) == 60


def test_akshare_market_preserves_spot_valuation_units_and_unadjusted_history():
    ak = RecordedAkshare()

    response = AkshareFormalEndpointClient(ak).fetch_market_decision(request())

    assert [name for name, _ in ak.calls] == [
        "tool_trade_date_hist_sina",
        "stock_zh_a_hist",
        "stock_zh_a_spot_em",
        "stock_zh_index_daily_em",
        "stock_zh_index_daily_em",
        "stock_zh_index_daily_em",
    ]
    assert ak.calls[1][1] == {
        "symbol": "600000",
        "period": "daily",
        "start_date": "20260312",
        "end_date": "20260710",
        "adjust": "",
    }
    basic = next(row for row in response.records if row["record_type"] == "daily_basic")
    assert basic["total_mv"] == 100_000_000_000.0
    assert response.unit_metadata == {
        "volume": "shares",
        "amount": "CNY",
        "market_value": "CNY",
    }
    assert response.adjustment_basis == "unadjusted"


def test_akshare_board_industry_calls_name_constituent_and_history_endpoints():
    ak = RecordedAkshare()

    response = AkshareFormalEndpointClient(ak).fetch_board_industry(request())

    assert [name for name, _ in ak.calls] == [
        "tool_trade_date_hist_sina",
        "stock_board_industry_name_em",
        "stock_board_industry_cons_em",
        "stock_board_industry_hist_em",
    ]
    assert {row["record_type"] for row in response.records} == {
        "industry_mapping",
        "board_bar",
    }
    assert response.records[0]["industry_code"] == "BK0475"


def test_akshare_candidate_fundamentals_normalizes_profile_and_financial_abstract():
    ak = RecordedAkshare()

    response = AkshareFormalEndpointClient(ak).fetch_candidate_fundamentals(request())

    assert [name for name, _ in ak.calls] == [
        "stock_individual_info_em",
        "stock_financial_abstract_ths",
    ]
    assert {row["record_type"] for row in response.records} == {
        "company_profile",
        "financial_summary",
    }
    summary = next(row for row in response.records if row["record_type"] == "financial_summary")
    assert summary["period_end"] == date(2026, 3, 31)
    assert summary["announcement_time"] <= CUTOFF
    assert summary["revenue_yoy"] == 5.0


def test_akshare_same_day_financial_date_without_precise_time_fails_closed():
    financial = RecordedAkshare()._default("stock_financial_abstract_ths", {})
    financial.loc[0, "公告日期"] = TARGET.isoformat()
    ak = RecordedAkshare({"stock_financial_abstract_ths": financial})

    with pytest.raises(
        PermanentRouteFailure,
        match="precise publication time",
    ) as raised:
        AkshareFormalEndpointClient(ak).fetch_candidate_fundamentals(request())

    assert raised.value.classification is FailureClassification.INVALID_SEMANTICS


def test_cninfo_disclosure_uses_precise_time_categories_and_cutoff():
    ak = RecordedAkshare()

    response = AkshareFormalEndpointClient(ak).fetch_official_events_risk(request())

    assert [name for name, _ in ak.calls] == [
        "tool_trade_date_hist_sina",
        "stock_zh_a_disclosure_report_cninfo",
        "stock_zh_a_disclosure_report_cninfo",
        "stock_zh_a_disclosure_report_cninfo",
        "stock_zh_a_disclosure_report_cninfo",
    ]
    assert [kwargs["category"] for _, kwargs in ak.calls[1:]] == [
        "",
        "风险提示",
        "特别处理和退市",
        "退市整理期",
    ]
    assert len(response.records) == 1
    event = response.records[0]
    assert event["ts_code"] == CODE
    assert event["event_type"] == "风险提示"
    assert event["hard_risk"] is True
    assert event["publication_time"].hour == 15
    assert response.source_names == (
        "akshare.stock_zh_a_disclosure_report_cninfo",
    )
    assert all(value <= CUTOFF for value in response.publication_times.values())


def test_cninfo_known_zero_announcement_keyerror_is_proven_empty():
    empty_selection = KeyError(
        "None of [Index(['代码', '简称', '公告标题', '公告时间', "
        "'announcementId', 'orgId'], dtype='str')] are in the [columns]"
    )
    ak = RecordedAkshare(
        {"stock_zh_a_disclosure_report_cninfo": empty_selection}
    )

    response = AkshareFormalEndpointClient(ak).fetch_official_events_risk(request())

    assert response.records == ()
    assert response.coverage_codes == (CODE,)
    assert response.coverage_proven is True


def test_cninfo_unrecognized_keyerror_still_fails_schema():
    ak = RecordedAkshare(
        {"stock_zh_a_disclosure_report_cninfo": KeyError("new schema")}
    )

    with pytest.raises(PermanentRouteFailure) as raised:
        AkshareFormalEndpointClient(ak).fetch_official_events_risk(request())

    assert raised.value.classification is FailureClassification.SCHEMA


def test_cninfo_date_only_publication_value_fails_point_in_time_semantics():
    notices = RecordedAkshare()._default(
        "stock_zh_a_disclosure_report_cninfo",
        {"category": ""},
    )
    notices["公告时间"] = "2026-07-09"
    ak = RecordedAkshare(
        {"stock_zh_a_disclosure_report_cninfo": notices}
    )

    with pytest.raises(
        PermanentRouteFailure,
        match="precise publication time",
    ) as raised:
        AkshareFormalEndpointClient(ak).fetch_official_events_risk(request())

    assert raised.value.classification is FailureClassification.INVALID_SEMANTICS


def test_akshare_concept_mapping_is_structured_not_inferred_from_text():
    ak = RecordedAkshare()

    response = AkshareFormalEndpointClient(ak).fetch_concepts(request())

    assert [name for name, _ in ak.calls] == [
        "stock_board_concept_name_em",
        "stock_board_concept_cons_em",
    ]
    assert len(response.records) == 1
    assert response.records[0]["concept_code"] == "BK1000"
    assert response.records[0]["concept_name"] == "中特估"


def test_akshare_changed_column_name_fails_schema_instead_of_guessing():
    changed = RecordedAkshare()._default("stock_zh_a_spot_em", {}).rename(
        columns={"最新价": "现价"}
    )
    ak = RecordedAkshare({"stock_zh_a_spot_em": changed})

    with pytest.raises(PermanentRouteFailure, match="最新价") as raised:
        AkshareFormalEndpointClient(ak).fetch_market_decision(request())

    assert raised.value.classification is FailureClassification.SCHEMA


def test_akshare_recorded_responses_satisfy_each_required_formal_v2_contract():
    client = AkshareFormalEndpointClient(RecordedAkshare())
    contracts = {
        **build_screening_contracts(TARGET, ()),
        **build_target_contracts(TARGET, (CODE,)),
    }
    methods_and_requests = {
        AcquisitionGroupId.CALENDAR_UNIVERSE: (client.fetch_calendar_universe, request(())),
        AcquisitionGroupId.MARKET_DECISION: (client.fetch_market_decision, request()),
        AcquisitionGroupId.BOARD_INDUSTRY: (client.fetch_board_industry, request()),
        AcquisitionGroupId.CANDIDATE_FUNDAMENTAL: (
            client.fetch_candidate_fundamentals,
            request(),
        ),
        AcquisitionGroupId.OFFICIAL_EVENTS_RISK: (
            client.fetch_official_events_risk,
            request(),
        ),
    }

    for group_id, (method, group_request) in methods_and_requests.items():
        response = method(group_request)
        payload = AcquisitionPayload(
            group_id=group_id,
            route_id=f"eastmoney.{group_id.value}.v1",
            route_kind=RouteKind.BACKUP,
            trade_date=TARGET,
            fetched_at=CUTOFF,
            contract_version=FORMAL_CONTRACT_VERSION,
            **response.model_dump(),
        )
        validation = validate_group_payload(contracts[group_id], group_request, payload)

        assert validation.complete is True, (group_id, validation.reasons)
