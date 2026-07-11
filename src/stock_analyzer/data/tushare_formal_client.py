from __future__ import annotations

from collections.abc import Iterable
from datetime import date, datetime, time, timedelta
from typing import Any

import pandas as pd

from stock_analyzer.data.acquisition import (
    PermanentRouteFailure,
    RouteFailure,
    TransientRouteFailure,
)
from stock_analyzer.data.formal_contracts import (
    build_screening_contracts,
    build_target_contracts,
)
from stock_analyzer.data.formal_policy import (
    FORMAL_BOARD_SESSION_COUNT,
    FORMAL_CALENDAR_LOOKBACK_DAYS,
    FORMAL_EQUITY_FEATURE_SESSION_COUNT,
    FORMAL_PRIMARY_INDEX_CODES,
    FORMAL_SCREENING_SESSION_COUNT,
)
from stock_analyzer.data.formal_routes import EndpointResponse
from stock_analyzer.data.readiness import (
    AcquisitionGroupId,
    AcquisitionRequest,
    FailureClassification,
)


class TushareFormalEndpointClient:
    def __init__(
        self,
        pro: object,
        *,
        required_index_codes: tuple[str, ...] = FORMAL_PRIMARY_INDEX_CODES,
    ) -> None:
        self.pro = pro
        self.required_index_codes = required_index_codes

    def fetch_calendar_universe(self, request: AcquisitionRequest) -> EndpointResponse:
        sessions = self._required_sessions(request.trade_date)
        securities = self._call(
            "stock_basic",
            exchange="",
            list_status="L",
            fields="ts_code,name,exchange,list_date",
        )
        _require_columns(
            securities,
            ("ts_code", "name", "exchange", "list_date"),
            "stock_basic",
        )
        suspensions = self._call(
            "suspend_d",
            trade_date=_yyyymmdd(request.trade_date),
            fields="ts_code,trade_date,suspend_type,name",
        )
        _require_columns(
            suspensions,
            ("ts_code", "trade_date", "suspend_type", "name"),
            "suspend_d",
        )
        special_treatment = self._call(
            "stock_st",
            trade_date=_yyyymmdd(request.trade_date),
        )
        _require_columns(
            special_treatment,
            ("ts_code", "trade_date", "name"),
            "stock_st",
        )

        open_dates = sessions
        suspended_codes = {
            _ts_code(row.ts_code) for row in suspensions.itertuples(index=False)
        }
        special_codes = {
            _ts_code(row.ts_code) for row in special_treatment.itertuples(index=False)
        }
        records: list[dict[str, Any]] = [
            {
                "record_type": "calendar",
                "trade_date": session,
                "is_open": True,
                "source_name": "tushare.trade_cal",
            }
            for session in sessions
        ]
        records.extend(
            {
                "record_type": "security",
                "trade_date": request.trade_date,
                "ts_code": _ts_code(row.ts_code),
                "name": str(row.name),
                "exchange": str(row.exchange),
                "list_date": _parse_yyyymmdd(row.list_date),
                "status_verified": True,
                "is_suspended": _ts_code(row.ts_code) in suspended_codes,
                "hard_excluded": _ts_code(row.ts_code) in special_codes,
                "source_name": "tushare.stock_basic+suspend_d+stock_st",
            }
            for row in securities.itertuples(index=False)
            if _parse_yyyymmdd(row.list_date) <= request.trade_date
        )
        coverage_codes = tuple(
            sorted(
                _ts_code(row.ts_code)
                for row in securities.itertuples(index=False)
                if _parse_yyyymmdd(row.list_date) <= request.trade_date
            )
        )
        return EndpointResponse(
            records=tuple(records),
            covered_dates=open_dates,
            coverage_codes=coverage_codes,
            coverage_proven=True,
            field_coverage=_field_coverage(
                request,
                AcquisitionGroupId.CALENDAR_UNIVERSE,
            ),
            source_names=(
                "tushare.trade_cal",
                "tushare.stock_basic",
                "tushare.suspend_d",
                "tushare.stock_st",
            ),
        )

    def fetch_market_decision(self, request: AcquisitionRequest) -> EndpointResponse:
        sessions = self._required_sessions(request.trade_date)
        expected_codes = set(request.target_codes)
        records: list[dict[str, Any]] = []
        dates_by_code: dict[str, set[date]] = {}
        for session in sessions:
            frame = self._call("daily", trade_date=_yyyymmdd(session))
            _require_columns(
                frame,
                (
                    "ts_code",
                    "trade_date",
                    "open",
                    "high",
                    "low",
                    "close",
                    "vol",
                    "amount",
                ),
                "daily",
            )
            for row in frame.itertuples(index=False):
                code = _ts_code(row.ts_code)
                if expected_codes and code not in expected_codes:
                    continue
                trade_date = _parse_yyyymmdd(row.trade_date)
                dates_by_code.setdefault(code, set()).add(trade_date)
                records.append(
                    {
                        "record_type": "equity_bar",
                        "trade_date": trade_date,
                        "ts_code": code,
                        "open": _safe_float(row.open),
                        "high": _safe_float(row.high),
                        "low": _safe_float(row.low),
                        "close": _safe_float(row.close),
                        "volume": _safe_float(row.vol, multiplier=100.0),
                        "amount": _safe_float(row.amount, multiplier=1_000.0),
                        "source_name": "tushare.daily",
                    }
                )

        required_feature_dates = set(
            sessions[-FORMAL_EQUITY_FEATURE_SESSION_COUNT:]
        )
        incomplete_codes = sorted(
            code
            for code in expected_codes
            if not required_feature_dates <= dates_by_code.get(code, set())
        )
        if incomplete_codes:
            raise PermanentRouteFailure(
                "Tushare daily response lacks the latest "
                f"{FORMAL_EQUITY_FEATURE_SESSION_COUNT} sessions for: "
                + ", ".join(incomplete_codes),
                FailureClassification.INCOMPLETE_UNIVERSE,
            )

        daily_basic = self._call(
            "daily_basic",
            trade_date=_yyyymmdd(request.trade_date),
        )
        _require_columns(
            daily_basic,
            (
                "ts_code",
                "trade_date",
                "turnover_rate",
                "total_mv",
                "circ_mv",
                "pe_ttm",
                "pb",
            ),
            "daily_basic",
        )
        for row in daily_basic.itertuples(index=False):
            code = _ts_code(row.ts_code)
            if expected_codes and code not in expected_codes:
                continue
            pe_ttm = _safe_float(row.pe_ttm)
            pb = _safe_float(row.pb)
            records.append(
                {
                    "record_type": "daily_basic",
                    "trade_date": _parse_yyyymmdd(row.trade_date),
                    "ts_code": code,
                    "turnover_rate": _safe_float(row.turnover_rate),
                    "total_mv": _safe_float(row.total_mv, multiplier=10_000.0),
                    "circ_mv": _safe_float(row.circ_mv, multiplier=10_000.0),
                    "pe_ttm": pe_ttm,
                    "pb": pb,
                    **(
                        {
                            "valuation_null_reason":
                            "provider_reported_not_applicable"
                        }
                        if pe_ttm is None or pb is None
                        else {}
                    ),
                    "source_name": "tushare.daily_basic",
                }
            )

        found_indexes: set[str] = set()
        index_dates_by_code: dict[str, set[date]] = {}
        for index_code in self.required_index_codes:
            frame = self._call(
                "index_daily",
                ts_code=index_code,
                start_date=_yyyymmdd(sessions[0]),
                end_date=_yyyymmdd(request.trade_date),
            )
            _require_columns(
                frame,
                (
                    "ts_code",
                    "trade_date",
                    "open",
                    "high",
                    "low",
                    "close",
                    "vol",
                    "amount",
                ),
                "index_daily",
            )
            for row in frame.itertuples(index=False):
                normalized_index = _ts_code(row.ts_code)
                index_date = _parse_yyyymmdd(row.trade_date)
                found_indexes.add(normalized_index)
                index_dates_by_code.setdefault(normalized_index, set()).add(index_date)
                records.append(
                    {
                        "record_type": "index_bar",
                        "trade_date": index_date,
                        "ts_code": normalized_index,
                        "open": _safe_float(row.open),
                        "high": _safe_float(row.high),
                        "low": _safe_float(row.low),
                        "close": _safe_float(row.close),
                        "volume": _safe_float(row.vol, multiplier=100.0),
                        "amount": _safe_float(row.amount, multiplier=1_000.0),
                        "source_name": "tushare.index_daily",
                    }
                )
        missing_indexes = sorted(set(self.required_index_codes) - found_indexes)
        if missing_indexes:
            raise PermanentRouteFailure(
                "Tushare index_daily response missing required indexes: "
                + ", ".join(missing_indexes),
                FailureClassification.INCOMPLETE_UNIVERSE,
            )
        incomplete_indexes = sorted(
            code
            for code in self.required_index_codes
            if not set(sessions) <= index_dates_by_code.get(code, set())
        )
        if incomplete_indexes:
            raise PermanentRouteFailure(
                "Tushare index_daily lacks the declared "
                f"{FORMAL_SCREENING_SESSION_COUNT} sessions for: "
                + ", ".join(incomplete_indexes),
                FailureClassification.INCOMPLETE_UNIVERSE,
            )

        covered_dates = sessions
        return EndpointResponse(
            records=tuple(records),
            covered_dates=covered_dates,
            coverage_codes=tuple(sorted(expected_codes | found_indexes)),
            coverage_proven=len(covered_dates) == len(sessions),
            field_coverage=_field_coverage(
                request,
                AcquisitionGroupId.MARKET_DECISION,
            ),
            source_names=(
                "tushare.daily",
                "tushare.daily_basic",
                "tushare.index_daily",
            ),
            unit_metadata={
                "volume": "shares",
                "amount": "CNY",
                "market_value": "CNY",
            },
            adjustment_basis="unadjusted",
        )

    def fetch_board_industry(self, request: AcquisitionRequest) -> EndpointResponse:
        sessions = self._required_sessions(request.trade_date)
        classifications = self._call("index_classify", level="L3", src="SW2021")
        _require_columns(
            classifications,
            ("index_code", "industry_name", "level"),
            "index_classify",
        )
        requested = set(request.target_codes)
        records: list[dict[str, Any]] = []
        relevant_boards: dict[str, str] = {}
        for classification in classifications.itertuples(index=False):
            board_code = str(classification.index_code)
            board_name = str(classification.industry_name)
            members = self._call("index_member_all", l3_code=board_code)
            _require_columns(
                members,
                ("l3_code", "l3_name", "ts_code", "name"),
                "index_member_all",
            )
            for member in members.itertuples(index=False):
                code = _ts_code(member.ts_code)
                if code not in requested:
                    continue
                relevant_boards[board_code] = board_name
                records.append(
                    {
                        "record_type": "industry_mapping",
                        "trade_date": request.trade_date,
                        "ts_code": code,
                        "industry_code": board_code,
                        "industry_name": board_name,
                        "source_name": "tushare.index_classify+index_member_all",
                    }
                )

        covered_dates: set[date] = {request.trade_date}
        for board_code, board_name in relevant_boards.items():
            history = self._call(
                "index_daily",
                ts_code=board_code,
                start_date=_yyyymmdd(sessions[0]),
                end_date=_yyyymmdd(request.trade_date),
            )
            _require_columns(
                history,
                (
                    "ts_code",
                    "trade_date",
                    "open",
                    "high",
                    "low",
                    "close",
                    "vol",
                    "amount",
                ),
                "index_daily",
            )
            board_dates: set[date] = set()
            for row in history.itertuples(index=False):
                trade_date = _parse_yyyymmdd(row.trade_date)
                board_dates.add(trade_date)
                covered_dates.add(trade_date)
                records.append(
                    {
                        "record_type": "board_bar",
                        "trade_date": trade_date,
                        "board_code": board_code,
                        "board_name": board_name,
                        "open": _safe_float(row.open),
                        "high": _safe_float(row.high),
                        "low": _safe_float(row.low),
                        "close": _safe_float(row.close),
                        "volume": _safe_float(row.vol, multiplier=100.0),
                        "amount": _safe_float(row.amount, multiplier=1_000.0),
                        "source_name": "tushare.index_daily",
                    }
                )
            if not set(sessions[-FORMAL_BOARD_SESSION_COUNT:]) <= board_dates:
                raise PermanentRouteFailure(
                    "Tushare board history lacks "
                    f"{FORMAL_BOARD_SESSION_COUNT} sessions for {board_code}",
                    FailureClassification.INCOMPLETE_UNIVERSE,
                )
        return EndpointResponse(
            records=tuple(records),
            covered_dates=tuple(sorted(covered_dates)),
            coverage_codes=tuple(sorted(requested)),
            coverage_proven=True,
            field_coverage=_field_coverage(
                request,
                AcquisitionGroupId.BOARD_INDUSTRY,
            ),
            source_names=(
                "tushare.index_classify",
                "tushare.index_member_all",
                "tushare.index_daily",
            ),
            unit_metadata={"volume": "shares", "amount": "CNY"},
            adjustment_basis="unadjusted",
        )

    def fetch_candidate_fundamentals(
        self,
        request: AcquisitionRequest,
    ) -> EndpointResponse:
        records: list[dict[str, Any]] = []
        publication_times: dict[str, datetime] = {}
        for code in request.target_codes:
            company = self._call("stock_company", ts_code=code)
            _require_columns(
                company,
                ("ts_code", "introduction", "main_business"),
                "stock_company",
            )
            for row in company.itertuples(index=False):
                if _ts_code(row.ts_code) != code:
                    continue
                summary = str(row.introduction).strip() or str(row.main_business).strip()
                records.append(
                    {
                        "record_type": "company_profile",
                        "trade_date": request.trade_date,
                        "ts_code": code,
                        "business_summary": summary,
                        "source_name": "tushare.stock_company",
                    }
                )
                break

            indicators = self._call("fina_indicator", ts_code=code)
            _require_columns(
                indicators,
                (
                    "ts_code",
                    "end_date",
                    "ann_date",
                    "or_yoy",
                    "netprofit_yoy",
                    "grossprofit_margin",
                ),
                "fina_indicator",
            )
            valid_indicators = [
                row
                for row in _published_rows(indicators, "ann_date", request)
                if _ts_code(row.ts_code) == code
            ]
            valid_indicators.sort(
                key=lambda row: (_text(row.end_date), _text(row.ann_date)),
                reverse=True,
            )
            cashflows = self._call("cashflow", ts_code=code)
            _require_columns(
                cashflows,
                ("ts_code", "end_date", "ann_date", "n_cashflow_act"),
                "cashflow",
            )
            valid_cashflows = [
                row
                for row in _published_rows(cashflows, "ann_date", request)
                if _ts_code(row.ts_code) == code
            ]
            valid_cashflows.sort(
                key=lambda row: (_text(row.end_date), _text(row.ann_date)),
                reverse=True,
            )
            cashflow_by_period: dict[date, tuple[float | None, datetime]] = {}
            for row in valid_cashflows:
                period_end = _parse_yyyymmdd(row.end_date)
                cashflow_by_period.setdefault(
                    period_end,
                    (
                        _safe_float(row.n_cashflow_act),
                        _publication_time(row.ann_date, request),
                    ),
                )
            announcement_by_period: dict[date, datetime] = {}
            for row in valid_indicators:
                period_end = _parse_yyyymmdd(row.end_date)
                announcement = _publication_time(row.ann_date, request)
                announcement_by_period[period_end] = announcement
            if valid_indicators:
                row = valid_indicators[0]
                period_end = _parse_yyyymmdd(row.end_date)
                announcement = announcement_by_period[period_end]
                cashflow_value, cashflow_announcement = cashflow_by_period.get(
                    period_end,
                    (None, announcement),
                )
                announcement = max(announcement, cashflow_announcement)
                identifier = f"{code}:financial_summary:{period_end.isoformat()}"
                publication_times[identifier] = announcement
                revenue_yoy = _safe_float(row.or_yoy)
                profit_yoy = _safe_float(row.netprofit_yoy)
                gross_margin = _safe_float(row.grossprofit_margin)
                records.append(
                    {
                        "record_type": "financial_summary",
                        "trade_date": request.trade_date,
                        "ts_code": code,
                        "period_end": period_end,
                        "announcement_time": announcement,
                        "revenue_yoy": revenue_yoy,
                        "profit_yoy": profit_yoy,
                        "gross_margin": gross_margin,
                        "operating_cashflow": cashflow_value,
                        **(
                            {
                                "fundamental_null_reason":
                                "provider_reported_not_available_as_of_cutoff"
                            }
                            if any(
                                value is None
                                for value in (
                                    revenue_yoy,
                                    profit_yoy,
                                    gross_margin,
                                    cashflow_value,
                                )
                            )
                            else {}
                        ),
                        "source_name": "tushare.fina_indicator+tushare.cashflow",
                    }
                )

            forecasts = self._call("forecast", ts_code=code)
            _require_columns(
                forecasts,
                ("ts_code", "ann_date", "type", "p_change_min", "p_change_max"),
                "forecast",
            )
            for row in _published_rows(forecasts, "ann_date", request):
                announcement = _publication_time(row.ann_date, request)
                identifier = f"{code}:forecast:{_text(row.ann_date)}:{_text(row.type)}"
                publication_times[identifier] = announcement
                records.append(
                    {
                        "record_type": "forecast",
                        "trade_date": request.trade_date,
                        "ts_code": code,
                        "announcement_time": announcement,
                        "forecast_type": str(row.type),
                        "min_change": _safe_float(row.p_change_min),
                        "max_change": _safe_float(row.p_change_max),
                        "source_name": "tushare.forecast",
                    }
                )

            expresses = self._call("express", ts_code=code)
            _require_columns(
                expresses,
                ("ts_code", "ann_date", "revenue", "n_income"),
                "express",
            )
            for row in _published_rows(expresses, "ann_date", request):
                announcement = _publication_time(row.ann_date, request)
                identifier = f"{code}:express:{_text(row.ann_date)}"
                publication_times[identifier] = announcement
                records.append(
                    {
                        "record_type": "express",
                        "trade_date": request.trade_date,
                        "ts_code": code,
                        "announcement_time": announcement,
                        "revenue": _safe_float(row.revenue),
                        "profit": _safe_float(row.n_income),
                        "source_name": "tushare.express",
                    }
                )

            main_business = self._call("fina_mainbz", ts_code=code)
            _require_columns(
                main_business,
                (
                    "ts_code",
                    "end_date",
                    "bz_item",
                    "bz_sales",
                    "bz_sales_ratio",
                ),
                "fina_mainbz",
            )
            for row in main_business.itertuples(index=False):
                period_end = _parse_yyyymmdd(row.end_date)
                if _ts_code(row.ts_code) != code or period_end not in announcement_by_period:
                    continue
                records.append(
                    {
                        "record_type": "main_business",
                        "trade_date": request.trade_date,
                        "ts_code": code,
                        "period_end": period_end,
                        "business_line": str(row.bz_item),
                        "revenue_share": _safe_float(row.bz_sales_ratio),
                        "source_name": "tushare.fina_mainbz",
                    }
                )

        return EndpointResponse(
            records=tuple(records),
            covered_dates=(request.trade_date,),
            coverage_codes=tuple(sorted(request.target_codes)),
            coverage_proven=True,
            field_coverage=_field_coverage(
                request,
                AcquisitionGroupId.CANDIDATE_FUNDAMENTAL,
            ),
            source_names=(
                "tushare.stock_company",
                "tushare.fina_indicator",
                "tushare.cashflow",
                "tushare.forecast",
                "tushare.express",
                "tushare.fina_mainbz",
            ),
            publication_times=publication_times,
        )

    def fetch_official_events_risk(
        self,
        request: AcquisitionRequest,
    ) -> EndpointResponse:
        sessions = self._required_sessions(request.trade_date)
        suspensions = self._call(
            "suspend_d",
            trade_date=_yyyymmdd(request.trade_date),
            fields="ts_code,trade_date,suspend_type,name",
        )
        _require_columns(
            suspensions,
            ("ts_code", "trade_date", "suspend_type", "name"),
            "suspend_d",
        )
        special_treatment = self._call(
            "stock_st",
            trade_date=_yyyymmdd(request.trade_date),
        )
        _require_columns(
            special_treatment,
            ("ts_code", "trade_date", "name"),
            "stock_st",
        )
        requested = set(request.target_codes)
        announcements: list[Any] = []
        for code in request.target_codes:
            frame = self._call(
                "anns_d",
                ts_code=code,
                start_date=_yyyymmdd(sessions[-2]),
                end_date=_yyyymmdd(request.trade_date),
                fields="ann_date,ts_code,name,title,url,rec_time",
            )
            _require_columns(
                frame,
                ("ann_date", "ts_code", "name", "title", "url", "rec_time"),
                "anns_d",
            )
            announcements.extend(frame.itertuples(index=False))
        publication = datetime.combine(
            request.trade_date,
            time.min,
            tzinfo=request.report_cutoff.tzinfo,
        )
        records: list[dict[str, Any]] = []
        publication_times: dict[str, datetime] = {}
        for row in suspensions.itertuples(index=False):
            code = _ts_code(row.ts_code)
            if code not in requested:
                continue
            event_id = f"suspend:{code}:{_text(row.trade_date)}"
            publication_times[event_id] = publication
            records.append(
                _event_record(
                    request,
                    code,
                    event_id,
                    "suspension",
                    f"{str(row.name)} {_text(row.suspend_type)}",
                    publication,
                    hard_risk=True,
                    source_name="tushare.suspend_d",
                )
            )
        for row in special_treatment.itertuples(index=False):
            code = _ts_code(row.ts_code)
            if code not in requested:
                continue
            event_id = f"stock_st:{code}:{_text(row.trade_date)}"
            publication_times[event_id] = publication
            records.append(
                _event_record(
                    request,
                    code,
                    event_id,
                    "special_treatment",
                    str(row.name),
                    publication,
                    hard_risk=True,
                    source_name="tushare.stock_st",
                )
            )
        for row in announcements:
            code = _ts_code(row.ts_code)
            if code not in requested:
                continue
            announcement_time = _provider_datetime(
                row.rec_time,
                fallback_date=row.ann_date,
                request=request,
            )
            if announcement_time > request.report_cutoff:
                continue
            event_id = _text(row.url)
            title = _text(row.title)
            if not event_id or event_id.lower() == "nan" or not title:
                raise PermanentRouteFailure(
                    "Tushare anns_d response lacks a stable URL or title",
                    FailureClassification.SCHEMA,
                )
            publication_times[event_id] = announcement_time
            records.append(
                _event_record(
                    request,
                    code,
                    event_id,
                    "company_announcement",
                    title,
                    announcement_time,
                    hard_risk=False,
                    source_name="tushare.anns_d",
                )
            )
        return EndpointResponse(
            records=tuple(records),
            covered_dates=(request.trade_date,),
            coverage_codes=tuple(sorted(requested)),
            coverage_proven=True,
            field_coverage=_field_coverage(
                request,
                AcquisitionGroupId.OFFICIAL_EVENTS_RISK,
            ),
            source_names=(
                "tushare.anns_d",
                "tushare.suspend_d",
                "tushare.stock_st",
            ),
            publication_times=publication_times,
        )

    def _required_sessions(self, trade_date: date) -> tuple[date, ...]:
        calendar = self._call(
            "trade_cal",
            exchange="SSE",
            start_date=_yyyymmdd(
                trade_date - timedelta(days=FORMAL_CALENDAR_LOOKBACK_DAYS)
            ),
            end_date=_yyyymmdd(trade_date),
            fields="cal_date,is_open",
        )
        _require_columns(calendar, ("cal_date", "is_open"), "trade_cal")
        sessions = tuple(
            sorted(
                {
                    _parse_yyyymmdd(row.cal_date)
                    for row in calendar.itertuples(index=False)
                    if int(row.is_open) == 1
                    and _parse_yyyymmdd(row.cal_date) <= trade_date
                }
            )[-FORMAL_SCREENING_SESSION_COUNT:]
        )
        if (
            len(sessions) != FORMAL_SCREENING_SESSION_COUNT
            or sessions[-1] != trade_date
        ):
            raise PermanentRouteFailure(
                "provider calendar does not prove the latest "
                f"{FORMAL_SCREENING_SESSION_COUNT}-session window",
                FailureClassification.STALE_DATA,
            )
        return sessions

    def fetch_concepts(self, request: AcquisitionRequest) -> EndpointResponse:
        concepts = self._call("concept")
        _require_columns(concepts, ("code", "name"), "concept")
        requested = set(request.target_codes)
        records: list[dict[str, Any]] = []
        for concept in concepts.itertuples(index=False):
            concept_code = str(concept.code)
            concept_name = str(concept.name)
            members = self._call("concept_detail", id=concept_code)
            _require_columns(
                members,
                ("id", "concept_name", "ts_code"),
                "concept_detail",
            )
            for member in members.itertuples(index=False):
                code = _ts_code(member.ts_code)
                if code not in requested:
                    continue
                records.append(
                    {
                        "record_type": "concept_mapping",
                        "trade_date": request.trade_date,
                        "ts_code": code,
                        "concept_code": concept_code,
                        "concept_name": concept_name,
                        "source_name": "tushare.concept+concept_detail",
                    }
                )
        return EndpointResponse(
            records=tuple(records),
            covered_dates=(request.trade_date,),
            coverage_codes=tuple(sorted(requested)),
            coverage_proven=True,
            field_coverage=_field_coverage(
                request,
                AcquisitionGroupId.CONCEPT_THEME,
                include_concepts=True,
            ),
            source_names=("tushare.concept", "tushare.concept_detail"),
        )

    def _call(self, method: str, **kwargs: Any) -> pd.DataFrame:
        try:
            frame = getattr(self.pro, method)(**kwargs)
        except RouteFailure:
            raise
        except Exception as exc:
            _raise_provider_error(method, exc)
        if not isinstance(frame, pd.DataFrame):
            raise PermanentRouteFailure(
                f"Tushare {method} response is not a DataFrame",
                FailureClassification.SCHEMA,
            )
        return frame


def _event_record(
    request: AcquisitionRequest,
    code: str,
    event_id: str,
    event_type: str,
    title: str,
    publication: datetime,
    *,
    hard_risk: bool,
    source_name: str,
) -> dict[str, Any]:
    return {
        "record_type": "official_event",
        "trade_date": request.trade_date,
        "ts_code": code,
        "event_id": event_id,
        "event_type": event_type,
        "title": title,
        "publication_time": publication,
        "source_reliability": "official_provider",
        "is_new_information": True,
        "hard_risk": hard_risk,
        "source_name": source_name,
    }


def _field_coverage(
    request: AcquisitionRequest,
    group_id: AcquisitionGroupId,
    *,
    include_concepts: bool = False,
) -> dict[str, bool]:
    if group_id in {
        AcquisitionGroupId.CALENDAR_UNIVERSE,
        AcquisitionGroupId.MARKET_DECISION,
    }:
        contract = build_screening_contracts(
            request.trade_date,
            request.target_codes,
        )[group_id]
    else:
        contract = build_target_contracts(
            request.trade_date,
            request.target_codes,
            include_concepts=include_concepts,
        )[group_id]
    return {
        field: True
        for record_type in contract.record_types
        for field in record_type.required_fields
    }


def _require_columns(
    frame: pd.DataFrame,
    names: Iterable[str],
    stage: str,
) -> None:
    missing = [name for name in names if name not in frame.columns]
    if missing:
        raise PermanentRouteFailure(
            f"Tushare {stage} response missing fields: {', '.join(missing)}",
            FailureClassification.SCHEMA,
        )


def _yyyymmdd(value: date) -> str:
    return value.strftime("%Y%m%d")


def _parse_yyyymmdd(value: Any) -> date:
    text = _text(value)
    try:
        return date(int(text[0:4]), int(text[4:6]), int(text[6:8]))
    except (TypeError, ValueError) as exc:
        raise PermanentRouteFailure(
            "Tushare response contains an invalid YYYYMMDD date",
            FailureClassification.SCHEMA,
        ) from exc


def _safe_float(value: Any, *, multiplier: float = 1.0) -> float | None:
    if pd.isna(value):
        return None
    try:
        return float(value) * multiplier
    except (TypeError, ValueError) as exc:
        raise PermanentRouteFailure(
            "Tushare response contains a non-numeric value",
            FailureClassification.SCHEMA,
        ) from exc


def _publication_time(value: Any, request: AcquisitionRequest) -> datetime:
    return datetime.combine(
        _parse_yyyymmdd(value),
        time.min,
        tzinfo=request.report_cutoff.tzinfo,
    )


def _provider_datetime(
    value: Any,
    *,
    fallback_date: Any,
    request: AcquisitionRequest,
) -> datetime:
    if value is None or pd.isna(value):
        return _publication_time(fallback_date, request)
    try:
        parsed = pd.Timestamp(value).to_pydatetime()
    except (TypeError, ValueError) as exc:
        raise PermanentRouteFailure(
            "Tushare response contains an invalid publication time",
            FailureClassification.SCHEMA,
        ) from exc
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=request.report_cutoff.tzinfo)
    return parsed.astimezone(request.report_cutoff.tzinfo)


def _published_rows(
    frame: pd.DataFrame,
    field: str,
    request: AcquisitionRequest,
) -> list[Any]:
    return [
        row
        for row in frame.itertuples(index=False)
        if _publication_time(getattr(row, field), request) <= request.report_cutoff
    ]


def _raise_provider_error(method: str, exc: Exception) -> None:
    classification, transient = _classify_provider_error(exc)
    error_type = TransientRouteFailure if transient else PermanentRouteFailure
    raise error_type(
        f"Tushare {method} failed: {exc}",
        classification,
    ) from exc


def _classify_provider_error(
    exc: Exception,
) -> tuple[FailureClassification, bool]:
    text = str(exc).lower()
    if any(marker in text for marker in ("permission", "token", "权限", "unauthorized")):
        return FailureClassification.PERMISSION, False
    if any(marker in text for marker in ("rate limit", "frequency", "频率", "too many")):
        return FailureClassification.RATE_LIMIT, True
    if any(marker in text for marker in ("timeout", "network", "connection", "连接")):
        return FailureClassification.TRANSPORT, True
    return FailureClassification.SCHEMA, False


def _text(value: Any) -> str:
    return str(value).strip()


def _ts_code(value: Any) -> str:
    code = _text(value).upper()
    if not code or "." not in code:
        raise PermanentRouteFailure(
            "Tushare response contains an invalid ts_code",
            FailureClassification.SCHEMA,
        )
    return code


__all__ = ["TushareFormalEndpointClient"]
