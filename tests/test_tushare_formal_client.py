from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from stock_analyzer.data.acquisition import PermanentRouteFailure, TransientRouteFailure
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
from stock_analyzer.data.tushare_formal_client import (
    TushareFormalEndpointClient,
    TushareRequestPacer,
)


TARGET = date(2026, 7, 10)
CUTOFF = datetime(2026, 7, 10, 16, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
NEXT_TARGET = date(2026, 7, 13)
CODES = ("600000.SH",)
INDEX_CODES = ("000001.SH", "399001.SZ", "899050.BJ")


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def request(codes: tuple[str, ...] = CODES) -> AcquisitionRequest:
    return AcquisitionRequest(
        run_id="formal-2026-07-10",
        trade_date=TARGET,
        report_cutoff=CUTOFF,
        target_codes=codes,
        contract_version=FORMAL_CONTRACT_VERSION,
    )


class RecordedTusharePro:
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
        if name == "trade_cal":
            return pd.DataFrame(
                [
                    {"cal_date": session.strftime("%Y%m%d"), "is_open": 1}
                    for session in JULY_10_OFFICIAL_SESSIONS
                ]
            )
        if name == "stock_basic":
            return pd.DataFrame(
                [
                    {
                        "ts_code": CODES[0],
                        "name": "浦发银行",
                        "exchange": "SSE",
                        "list_date": "19991110",
                    }
                ]
            )
        if name == "suspend_d":
            return pd.DataFrame(columns=["ts_code", "trade_date", "suspend_type"])
        if name == "anns_d":
            return pd.DataFrame(
                columns=["ann_date", "ts_code", "name", "title", "url", "rec_time"]
            )
        if name == "daily":
            return pd.DataFrame(
                [
                    {
                        "ts_code": CODES[0],
                        "trade_date": kwargs["trade_date"],
                        "open": 10.0,
                        "high": 11.0,
                        "low": 9.0,
                        "close": 10.5,
                        "vol": 1_000.0,
                        "amount": 10_500.0,
                    }
                ]
            )
        if name == "daily_basic":
            return pd.DataFrame(
                [
                    {
                        "ts_code": CODES[0],
                        "trade_date": kwargs["trade_date"],
                        "turnover_rate": 1.2,
                        "total_mv": 10_000_000.0,
                        "circ_mv": 8_000_000.0,
                        "pe_ttm": 9.5,
                        "pb": 1.1,
                    }
                ]
            )
        if name == "index_daily":
            return pd.DataFrame(
                [
                    {
                        "ts_code": kwargs["ts_code"],
                        "trade_date": session.strftime("%Y%m%d"),
                        "open": 3_000.0,
                        "high": 3_050.0,
                        "low": 2_990.0,
                        "close": 3_020.0,
                        "vol": 2_000.0,
                        "amount": 20_000.0,
                    }
                    for session in JULY_10_OFFICIAL_SESSIONS
                ]
            )
        if name == "index_classify":
            return pd.DataFrame(
                [{"index_code": "801780.SI", "industry_name": "银行", "level": "L3"}]
            )
        if name == "index_member_all":
            return pd.DataFrame(
                [
                    {
                        "l1_code": "801780.SI",
                        "l1_name": "银行",
                        "l2_code": "801780.SI",
                        "l2_name": "银行",
                        "l3_code": "801780.SI",
                        "l3_name": "银行",
                        "ts_code": CODES[0],
                        "name": "浦发银行",
                        "in_date": "19991110",
                        "out_date": None,
                    }
                ]
            )
        if name == "stock_company":
            return pd.DataFrame(
                [
                    {
                        "ts_code": kwargs["ts_code"],
                        "introduction": "全国性股份制商业银行",
                        "main_business": "商业银行业务",
                    }
                ]
            )
        if name == "fina_indicator":
            return pd.DataFrame(
                [
                    {
                        "ts_code": kwargs["ts_code"],
                        "end_date": "20260331",
                        "ann_date": "20260430",
                        "or_yoy": 5.0,
                        "netprofit_yoy": 4.0,
                        "grossprofit_margin": 35.0,
                        "ocf_to_or": 20.0,
                    },
                    {
                        "ts_code": kwargs["ts_code"],
                        "end_date": "20260630",
                        "ann_date": "20260711",
                        "or_yoy": 99.0,
                        "netprofit_yoy": 99.0,
                        "grossprofit_margin": 99.0,
                        "ocf_to_or": 99.0,
                    },
                    {
                        "ts_code": kwargs["ts_code"],
                        "end_date": "20201231",
                        "ann_date": "20210331",
                        "or_yoy": 1.0,
                        "netprofit_yoy": 1.0,
                        "grossprofit_margin": 1.0,
                        "ocf_to_or": 1.0,
                    },
                ]
            )
        if name == "cashflow":
            return pd.DataFrame(
                [
                    {
                        "ts_code": kwargs["ts_code"],
                        "end_date": "20260331",
                        "ann_date": "20260430",
                        "n_cashflow_act": 123_000_000.0,
                    },
                    {
                        "ts_code": kwargs["ts_code"],
                        "end_date": "20260630",
                        "ann_date": "20260711",
                        "n_cashflow_act": 999_000_000.0,
                    },
                    {
                        "ts_code": kwargs["ts_code"],
                        "end_date": "20201231",
                        "ann_date": "20210331",
                        "n_cashflow_act": 1_000_000.0,
                    },
                ]
            )
        if name == "forecast":
            return pd.DataFrame(
                [
                    {
                        "ts_code": kwargs["ts_code"],
                        "ann_date": "20260709",
                        "end_date": "20260630",
                        "type": "预增",
                        "p_change_min": 3.0,
                        "p_change_max": 8.0,
                    }
                ]
            )
        if name == "express":
            return pd.DataFrame(
                [
                    {
                        "ts_code": kwargs["ts_code"],
                        "ann_date": "20260709",
                        "end_date": "20260630",
                        "revenue": 1_000_000.0,
                        "n_income": 100_000.0,
                    }
                ]
            )
        if name == "fina_mainbz":
            return pd.DataFrame(
                [
                    {
                        "ts_code": kwargs["ts_code"],
                        "end_date": "20260331",
                        "bz_item": "公司金融",
                        "bz_sales": 500_000.0,
                    },
                    {
                        "ts_code": kwargs["ts_code"],
                        "end_date": "20260331",
                        "bz_item": "零售金融",
                        "bz_sales": 500_000.0,
                    },
                    {
                        "ts_code": kwargs["ts_code"],
                        "end_date": "20201231",
                        "bz_item": "历史缺失分项",
                        "bz_sales": None,
                    }
                ]
            )
        if name == "concept":
            return pd.DataFrame([{"code": "TS1", "name": "中特估"}])
        if name == "concept_detail":
            return pd.DataFrame(
                [{"id": kwargs["id"], "concept_name": "中特估", "ts_code": CODES[0]}]
            )
        raise AssertionError(f"unexpected Tushare endpoint: {name}")


def test_tushare_request_pacer_enforces_per_endpoint_sliding_window():
    clock = FakeClock()
    pacer = TushareRequestPacer(
        calls_per_minute={"index_member_all": 2},
        default_calls_per_minute=3,
        window_seconds=60.0,
        clock=clock,
        sleeper=clock.sleep,
    )

    pacer.wait("index_member_all")
    pacer.wait("index_member_all")
    pacer.wait("index_member_all")

    assert clock.sleeps == [60.0]


def test_tushare_rate_limit_response_cools_down_once_then_retries():
    class RateLimitedPro:
        def __init__(self) -> None:
            self.calls = 0

        def daily(self, **kwargs):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("访问接口频率超限")
            return pd.DataFrame(columns=["ts_code"])

    clock = FakeClock()
    pro = RateLimitedPro()
    pacer = TushareRequestPacer(clock=clock, sleeper=clock.sleep)

    result = TushareFormalEndpointClient(pro, request_pacer=pacer)._call("daily")

    assert result.empty
    assert pro.calls == 2
    assert clock.sleeps == [60.0]


def test_tushare_calendar_universe_calls_exact_endpoints_and_normalizes_verified_status():
    pro = RecordedTusharePro(
        {
            "suspend_d": pd.DataFrame(
                [
                    {
                        "ts_code": CODES[0],
                        "trade_date": "20260710",
                        "suspend_type": "S",
                        "name": "浦发银行",
                    }
                ]
            )
        }
    )

    response = TushareFormalEndpointClient(pro).fetch_calendar_universe(request())

    assert [name for name, _ in pro.calls] == ["trade_cal", "stock_basic", "suspend_d"]
    assert pro.calls[0][1] == {
        "exchange": "SSE",
        "start_date": "20260111",
        "end_date": "20260710",
        "fields": "cal_date,is_open",
    }
    assert {row["record_type"] for row in response.records} == {"calendar", "security"}
    security = next(row for row in response.records if row["record_type"] == "security")
    assert security["status_verified"] is True
    assert security["is_suspended"] is True
    assert security["hard_excluded"] is False
    assert response.coverage_proven is True
    assert response.covered_dates == JULY_10_OFFICIAL_SESSIONS


def test_tushare_suspend_route_accepts_documented_response_without_name():
    pro = RecordedTusharePro(
        {
            "suspend_d": pd.DataFrame(
                [
                    {
                        "ts_code": CODES[0],
                        "trade_date": "20260710",
                        "suspend_type": "S",
                    }
                ]
            )
        }
    )

    calendar = TushareFormalEndpointClient(pro).fetch_calendar_universe(request())
    events = TushareFormalEndpointClient(pro).fetch_official_events_risk(request())

    security = next(row for row in calendar.records if row["record_type"] == "security")
    suspension = next(row for row in events.records if row["event_type"] == "suspension")
    assert security["is_suspended"] is True
    assert CODES[0] in suspension["title"]


def test_tushare_market_fetches_each_of_82_sessions_daily_basic_and_indexes_with_declared_units():
    pro = RecordedTusharePro()

    response = TushareFormalEndpointClient(pro).fetch_market_decision(request())

    daily_calls = [kwargs for name, kwargs in pro.calls if name == "daily"]
    basic_calls = [kwargs for name, kwargs in pro.calls if name == "daily_basic"]
    index_calls = [kwargs for name, kwargs in pro.calls if name == "index_daily"]
    assert len(daily_calls) == 82
    assert [item["trade_date"] for item in daily_calls] == [
        session.strftime("%Y%m%d") for session in JULY_10_OFFICIAL_SESSIONS
    ]
    assert basic_calls == [{"trade_date": "20260710"}]
    assert index_calls == [
        {"ts_code": code, "start_date": "20260312", "end_date": "20260710"}
        for code in INDEX_CODES
    ]
    assert {row["record_type"] for row in response.records} == {
        "equity_bar",
        "daily_basic",
        "index_bar",
    }
    first_bar = next(row for row in response.records if row["record_type"] == "equity_bar")
    assert first_bar["volume"] == 100_000.0
    assert first_bar["amount"] == 10_500_000.0
    assert response.unit_metadata == {
        "volume": "shares",
        "amount": "CNY",
        "market_value": "CNY",
    }
    assert response.adjustment_basis == "unadjusted"


def test_tushare_market_uses_provider_calendar_for_next_trading_day_window():
    sessions = (*JULY_10_OFFICIAL_SESSIONS[1:], NEXT_TARGET)

    def next_index(kwargs):
        return pd.DataFrame(
            [
                {
                    "ts_code": kwargs["ts_code"],
                    "trade_date": value.strftime("%Y%m%d"),
                    "open": 3_000.0,
                    "high": 3_050.0,
                    "low": 2_990.0,
                    "close": 3_020.0,
                    "vol": 2_000.0,
                    "amount": 20_000.0,
                }
                for value in sessions
            ]
        )

    pro = RecordedTusharePro(
        {
            "trade_cal": pd.DataFrame(
                {
                    "cal_date": [value.strftime("%Y%m%d") for value in sessions],
                    "is_open": [1] * len(sessions),
                }
            ),
            "index_daily": next_index,
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

    response = TushareFormalEndpointClient(pro).fetch_market_decision(next_request)

    assert response.covered_dates == sessions
    assert pro.calls[0][0] == "trade_cal"
    daily_dates = [
        kwargs["trade_date"]
        for name, kwargs in pro.calls
        if name == "daily"
    ]
    assert daily_dates == [value.strftime("%Y%m%d") for value in sessions]


def test_historical_suspension_gap_is_valid_when_61_observations_and_target_exist():
    pro = RecordedTusharePro()
    missing_date = JULY_10_OFFICIAL_SESSIONS[-2].strftime("%Y%m%d")

    def missing_recent_bar(kwargs):
        if kwargs["trade_date"] == missing_date:
            return pd.DataFrame(
                columns=[
                    "ts_code",
                    "trade_date",
                    "open",
                    "high",
                    "low",
                    "close",
                    "vol",
                    "amount",
                ]
            )
        return pro._default("daily", kwargs)

    pro.overrides["daily"] = missing_recent_bar

    response = TushareFormalEndpointClient(pro).fetch_market_decision(request())

    equity = [row for row in response.records if row["record_type"] == "equity_bar"]
    assert len(equity) == len(JULY_10_OFFICIAL_SESSIONS) - 1


def test_eligible_code_with_only_60_observations_is_returned_for_feature_exclusion():
    pro = RecordedTusharePro()
    kept = {
        value.strftime("%Y%m%d")
        for value in JULY_10_OFFICIAL_SESSIONS[-60:]
    }

    def insufficient_history(kwargs):
        if kwargs["trade_date"] not in kept:
            return pd.DataFrame(
                columns=[
                    "ts_code",
                    "trade_date",
                    "open",
                    "high",
                    "low",
                    "close",
                    "vol",
                    "amount",
                ]
            )
        return pro._default("daily", kwargs)

    pro.overrides["daily"] = insufficient_history

    response = TushareFormalEndpointClient(pro).fetch_market_decision(request())

    equity = [row for row in response.records if row["record_type"] == "equity_bar"]
    assert len(equity) == 60


def test_index_and_board_history_must_cover_declared_windows():
    short_index = RecordedTusharePro()

    def missing_index_session(kwargs):
        return short_index._default("index_daily", kwargs).iloc[1:].reset_index(drop=True)

    short_index.overrides["index_daily"] = missing_index_session
    with pytest.raises(PermanentRouteFailure, match="declared 82 sessions"):
        TushareFormalEndpointClient(short_index).fetch_market_decision(request())

    short_board = RecordedTusharePro()

    def missing_board_session(kwargs):
        frame = short_board._default("index_daily", kwargs)
        return frame.iloc[-20:].reset_index(drop=True)

    short_board.overrides["index_daily"] = missing_board_session
    with pytest.raises(PermanentRouteFailure, match="board history lacks 21 sessions"):
        TushareFormalEndpointClient(short_board).fetch_board_industry(request())


def test_tushare_board_industry_maps_members_and_history_without_text_inference():
    pro = RecordedTusharePro()

    response = TushareFormalEndpointClient(pro).fetch_board_industry(request())

    assert [name for name, _ in pro.calls] == [
        "trade_cal",
        "index_member_all",
        "index_daily",
    ]
    assert pro.calls[1][1] == {"ts_code": CODES[0]}
    assert {row["record_type"] for row in response.records} == {
        "industry_mapping",
        "board_bar",
    }
    mapping = next(row for row in response.records if row["record_type"] == "industry_mapping")
    assert mapping["ts_code"] == CODES[0]
    assert mapping["industry_code"] == "801780.SI"
    assert mapping["industry_name"] == "银行"


def test_tushare_board_uses_active_parent_when_new_l3_lacks_21_sessions():
    pro = RecordedTusharePro(
        {
            "index_member_all": pd.DataFrame(
                [
                    {
                        "l1_code": "801780.SI",
                        "l1_name": "银行",
                        "l2_code": "801190.SI",
                        "l2_name": "银行业",
                        "l3_code": "857831.SI",
                        "l3_name": "新三级行业",
                        "ts_code": CODES[0],
                        "name": "浦发银行",
                        "in_date": "20260701",
                        "out_date": None,
                    }
                ]
            )
        }
    )

    def hierarchical_history(kwargs):
        frame = pro._default("index_daily", kwargs)
        if kwargs["ts_code"] == "857831.SI":
            return frame.tail(20).reset_index(drop=True)
        return frame

    pro.overrides["index_daily"] = hierarchical_history

    response = TushareFormalEndpointClient(pro).fetch_board_industry(request())

    mapping = next(row for row in response.records if row["record_type"] == "industry_mapping")
    assert mapping["industry_code"] == "801190.SI"
    assert mapping["industry_level"] == "L2"
    index_calls = [kwargs["ts_code"] for name, kwargs in pro.calls if name == "index_daily"]
    assert index_calls == ["857831.SI", "801190.SI"]


def test_tushare_candidate_fundamentals_filters_announcements_after_cutoff():
    pro = RecordedTusharePro()

    response = TushareFormalEndpointClient(pro).fetch_candidate_fundamentals(request())

    assert [name for name, _ in pro.calls] == [
        "stock_company",
        "fina_indicator",
        "cashflow",
        "forecast",
        "express",
        "fina_mainbz",
    ]
    assert {row["record_type"] for row in response.records} == {
        "company_profile",
        "financial_summary",
        "forecast",
        "express",
        "main_business",
    }
    financial = next(row for row in response.records if row["record_type"] == "financial_summary")
    assert financial["period_end"] == date(2026, 3, 31)
    assert financial["revenue_yoy"] == 5.0
    assert financial["operating_cashflow"] == 123_000_000.0
    assert financial["operating_cashflow"] != 20.0
    assert "tushare.cashflow" in response.source_names
    main_business = [row for row in response.records if row["record_type"] == "main_business"]
    assert sum(row["revenue_share"] for row in main_business) == pytest.approx(1.0)
    main_business_call = next(kwargs for name, kwargs in pro.calls if name == "fina_mainbz")
    assert main_business_call == {"ts_code": CODES[0], "type": "P"}
    assert all(value <= CUTOFF for value in response.publication_times.values())


def test_tushare_qualitative_forecast_has_explicit_null_range_reason():
    pro = RecordedTusharePro(
        {
            "forecast": pd.DataFrame(
                [
                    {
                        "ts_code": CODES[0],
                        "ann_date": "20260709",
                        "end_date": "20260630",
                        "type": "不确定",
                        "p_change_min": None,
                        "p_change_max": None,
                    }
                ]
            )
        }
    )

    response = TushareFormalEndpointClient(pro).fetch_candidate_fundamentals(request())
    forecast = next(row for row in response.records if row["record_type"] == "forecast")
    validation = validate_group_payload(
        build_target_contracts(TARGET, CODES)[AcquisitionGroupId.CANDIDATE_FUNDAMENTAL],
        request(),
        AcquisitionPayload(
            group_id=AcquisitionGroupId.CANDIDATE_FUNDAMENTAL,
            route_id="tushare.candidate_fundamental.v1",
            route_kind=RouteKind.PRIMARY,
            trade_date=TARGET,
            fetched_at=CUTOFF,
            source_names=response.source_names,
            records=response.records,
            covered_dates=response.covered_dates,
            coverage_codes=response.coverage_codes,
            coverage_proven=response.coverage_proven,
            field_coverage=response.field_coverage,
            publication_times=response.publication_times,
            contract_version=FORMAL_CONTRACT_VERSION,
        ),
    )

    assert forecast["min_change"] is None
    assert forecast["forecast_range_null_reason"].startswith("provider_reported")
    assert validation.complete, validation.reasons


def test_tushare_official_events_proves_empty_target_coverage_and_keeps_risks():
    empty = TushareFormalEndpointClient(RecordedTusharePro()).fetch_official_events_risk(request())

    assert empty.records == ()
    assert empty.coverage_codes == CODES
    assert empty.coverage_proven is True

    pro = RecordedTusharePro(
        {
            "stock_basic": pd.DataFrame(
                [
                    {
                        "ts_code": CODES[0],
                        "name": "ST浦发",
                        "exchange": "SSE",
                        "list_date": "19991110",
                    }
                ]
            )
        }
    )
    response = TushareFormalEndpointClient(pro).fetch_official_events_risk(request())
    risk = response.records[0]
    assert risk["record_type"] == "official_event"
    assert risk["event_type"] == "special_treatment"
    assert risk["hard_risk"] is True


def test_tushare_official_events_include_disclosures_and_filter_after_cutoff():
    pro = RecordedTusharePro(
        {
            "anns_d": pd.DataFrame(
                [
                    {
                        "ann_date": "20260709",
                        "ts_code": CODES[0],
                        "name": "浦发银行",
                        "title": "关于重大事项的公告",
                        "url": "https://example.invalid/official-1.pdf",
                        "rec_time": "2026-07-09 18:00:00",
                    },
                    {
                        "ann_date": "20260710",
                        "ts_code": CODES[0],
                        "name": "浦发银行",
                        "title": "截止时间之后的公告",
                        "url": "https://example.invalid/official-2.pdf",
                        "rec_time": "2026-07-10 17:00:00",
                    },
                ]
            )
        }
    )

    response = TushareFormalEndpointClient(pro).fetch_official_events_risk(request())

    assert [name for name, _ in pro.calls] == [
        "trade_cal",
        "suspend_d",
        "stock_basic",
        "anns_d",
    ]
    assert len(response.records) == 1
    event = response.records[0]
    assert event["event_id"] == "https://example.invalid/official-1.pdf"
    assert event["event_type"] == "company_announcement"
    assert event["title"] == "关于重大事项的公告"
    assert event["hard_risk"] is False
    assert response.source_names == (
        "tushare.anns_d",
        "tushare.suspend_d",
        "tushare.stock_basic",
    )
    assert all(value <= CUTOFF for value in response.publication_times.values())


def test_tushare_same_day_disclosure_without_rec_time_fails_closed():
    pro = RecordedTusharePro(
        {
            "anns_d": pd.DataFrame(
                [
                    {
                        "ann_date": "20260710",
                        "ts_code": CODES[0],
                        "name": "浦发银行",
                        "title": "当天公告",
                        "url": "https://example.invalid/same-day.pdf",
                        "rec_time": None,
                    }
                ]
            )
        }
    )

    with pytest.raises(
        PermanentRouteFailure,
        match="precise publication time",
    ) as raised:
        TushareFormalEndpointClient(pro).fetch_official_events_risk(request())

    assert raised.value.classification is FailureClassification.INVALID_SEMANTICS


def test_tushare_same_day_financial_ann_date_without_time_fails_closed():
    indicators = RecordedTusharePro()._default(
        "fina_indicator",
        {"ts_code": CODES[0]},
    )
    indicators.loc[0, "ann_date"] = "20260710"
    pro = RecordedTusharePro({"fina_indicator": indicators})

    with pytest.raises(
        PermanentRouteFailure,
        match="precise publication time",
    ) as raised:
        TushareFormalEndpointClient(pro).fetch_candidate_fundamentals(request())

    assert raised.value.classification is FailureClassification.INVALID_SEMANTICS


def test_tushare_concepts_returns_only_requested_codes():
    pro = RecordedTusharePro(
        {
            "concept_detail": pd.DataFrame(
                [
                    {"id": "TS1", "concept_name": "中特估", "ts_code": CODES[0]},
                    {"id": "TS1", "concept_name": "中特估", "ts_code": "000001.SZ"},
                ]
            )
        }
    )

    response = TushareFormalEndpointClient(pro).fetch_concepts(request())

    assert [row["ts_code"] for row in response.records] == [CODES[0]]
    assert {row["record_type"] for row in response.records} == {"concept_mapping"}


def test_tushare_schema_or_permission_error_is_classified_and_redacted():
    missing = RecordedTusharePro(
        {"stock_basic": pd.DataFrame([{"ts_code": CODES[0]}])}
    )
    with pytest.raises(PermanentRouteFailure) as schema_error:
        TushareFormalEndpointClient(missing).fetch_calendar_universe(request())
    assert schema_error.value.classification is FailureClassification.SCHEMA
    assert "name" in str(schema_error.value)

    invalid_code = RecordedTusharePro(
        {
            "stock_basic": pd.DataFrame(
                [
                    {
                        "ts_code": "600000",
                        "name": "浦发银行",
                        "exchange": "SSE",
                        "list_date": "19991110",
                    }
                ]
            )
        }
    )
    with pytest.raises(PermanentRouteFailure, match="invalid ts_code") as code_error:
        TushareFormalEndpointClient(invalid_code).fetch_calendar_universe(request())
    assert code_error.value.classification is FailureClassification.SCHEMA

    forbidden = RecordedTusharePro(
        {"trade_cal": RuntimeError("TOKEN=secret-sentinel permission denied")}
    )
    with pytest.raises(PermanentRouteFailure) as permission_error:
        TushareFormalEndpointClient(forbidden).fetch_calendar_universe(request())
    assert permission_error.value.classification is FailureClassification.PERMISSION
    assert "secret-sentinel" not in str(permission_error.value)
    assert "secret-sentinel" not in repr(permission_error.value)

    limited = RecordedTusharePro({"trade_cal": RuntimeError("rate limit exceeded")})
    clock = FakeClock()
    with pytest.raises(TransientRouteFailure) as rate_error:
        TushareFormalEndpointClient(
            limited,
            request_pacer=TushareRequestPacer(clock=clock, sleeper=clock.sleep),
        ).fetch_calendar_universe(request())
    assert rate_error.value.classification is FailureClassification.RATE_LIMIT
    assert clock.sleeps == [60.0]


def test_tushare_recorded_responses_satisfy_each_required_formal_v2_contract():
    client = TushareFormalEndpointClient(RecordedTusharePro())
    contracts = {
        **build_screening_contracts(TARGET, CODES),
        **build_target_contracts(TARGET, CODES),
    }
    methods = {
        AcquisitionGroupId.CALENDAR_UNIVERSE: client.fetch_calendar_universe,
        AcquisitionGroupId.MARKET_DECISION: client.fetch_market_decision,
        AcquisitionGroupId.BOARD_INDUSTRY: client.fetch_board_industry,
        AcquisitionGroupId.CANDIDATE_FUNDAMENTAL: client.fetch_candidate_fundamentals,
        AcquisitionGroupId.OFFICIAL_EVENTS_RISK: client.fetch_official_events_risk,
    }

    for group_id, method in methods.items():
        response = method(request())
        payload = AcquisitionPayload(
            group_id=group_id,
            route_id=f"tushare.{group_id.value}.v1",
            route_kind=RouteKind.PRIMARY,
            trade_date=TARGET,
            fetched_at=CUTOFF,
            contract_version=FORMAL_CONTRACT_VERSION,
            **response.model_dump(),
        )
        validation = validate_group_payload(contracts[group_id], request(), payload)

        assert validation.complete is True, (group_id, validation.reasons)
