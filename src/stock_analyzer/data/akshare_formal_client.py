from __future__ import annotations

from collections.abc import Iterable
from datetime import date, datetime, time
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
    FORMAL_BACKUP_INDEX_SYMBOLS,
    FORMAL_BOARD_SESSION_COUNT,
    FORMAL_SCREENING_SESSION_COUNT,
)
from stock_analyzer.data.formal_routes import EndpointResponse
from stock_analyzer.data.readiness import (
    AcquisitionGroupId,
    AcquisitionRequest,
    FailureClassification,
)


SPOT_COLUMNS = {
    "代码": "symbol",
    "名称": "name",
    "最新价": "close",
    "今开": "open",
    "最高": "high",
    "最低": "low",
    "昨收": "pre_close",
    "成交量": "volume",
    "成交额": "amount",
    "换手率": "turnover_rate",
    "市盈率-动态": "pe_ttm",
    "市净率": "pb",
    "总市值": "total_mv",
    "流通市值": "circ_mv",
}

CNINFO_HARD_RISK_CATEGORIES = (
    "风险提示",
    "特别处理和退市",
    "退市整理期",
)
CNINFO_DISCLOSURE_COLUMNS = (
    "代码",
    "简称",
    "公告标题",
    "公告时间",
    "公告链接",
)

HISTORY_COLUMNS = {
    "日期": "trade_date",
    "开盘": "open",
    "收盘": "close",
    "最高": "high",
    "最低": "low",
    "成交量": "volume",
    "成交额": "amount",
    "振幅": "amplitude",
    "涨跌幅": "pct_chg",
    "涨跌额": "change",
    "换手率": "turnover_rate",
}

INDEX_COLUMNS = {
    "date": "trade_date",
    "open": "open",
    "close": "close",
    "high": "high",
    "low": "low",
    "volume": "volume",
    "amount": "amount",
}

BOARD_HISTORY_COLUMNS = {
    "日期": "trade_date",
    "开盘": "open",
    "收盘": "close",
    "最高": "high",
    "最低": "low",
    "成交量": "volume",
    "成交额": "amount",
}


class AkshareFormalEndpointClient:
    def __init__(
        self,
        ak: object,
        *,
        required_index_symbols: tuple[str, ...] = FORMAL_BACKUP_INDEX_SYMBOLS,
    ) -> None:
        self.ak = ak
        self.required_index_symbols = required_index_symbols

    def live_capability_block_reason(
        self,
        group_id: AcquisitionGroupId,
    ) -> str | None:
        if group_id is AcquisitionGroupId.OFFICIAL_EVENTS_RISK:
            return (
                "CNINFO public disclosure results do not guarantee "
                "sub-day publication timestamps"
            )
        return None

    def fetch_calendar_universe(self, request: AcquisitionRequest) -> EndpointResponse:
        sessions = self._required_sessions(request.trade_date)
        sh = self._call("stock_info_sh_name_code")
        _require_columns(sh, ("证券代码", "证券简称", "上市日期"), "stock_info_sh_name_code")
        sz = self._call("stock_info_sz_name_code")
        _require_columns(sz, ("A股代码", "A股简称", "A股上市日期"), "stock_info_sz_name_code")
        bj = self._call("stock_info_bj_name_code")
        _require_columns(bj, ("证券代码", "证券简称", "上市日期"), "stock_info_bj_name_code")
        spot = self._call("stock_zh_a_spot_em")
        _require_column_map(spot, SPOT_COLUMNS, "stock_zh_a_spot_em")

        listed: list[tuple[str, str, str, date]] = []
        listed.extend(
            (
                _to_ts_code(row.证券代码, exchange="SH"),
                str(row.证券简称),
                "SSE",
                _parse_date(row.上市日期),
            )
            for row in sh.itertuples(index=False)
        )
        listed.extend(
            (
                _to_ts_code(row.A股代码, exchange="SZ"),
                str(row.A股简称),
                "SZSE",
                _parse_date(row.A股上市日期),
            )
            for row in sz.itertuples(index=False)
        )
        listed.extend(
            (
                _to_ts_code(row.证券代码, exchange="BJ"),
                str(row.证券简称),
                "BSE",
                _parse_date(row.上市日期),
            )
            for row in bj.itertuples(index=False)
        )
        spot_by_code = {
            _to_ts_code(getattr(row, "代码")): row
            for row in spot.itertuples(index=False)
        }
        covered_dates = sessions
        records: list[dict[str, Any]] = [
            {
                "record_type": "calendar",
                "trade_date": session,
                "is_open": True,
                "source_name": "akshare.tool_trade_date_hist_sina",
            }
            for session in covered_dates
        ]
        for code, name, exchange, list_date in listed:
            if list_date > request.trade_date:
                continue
            spot_row = spot_by_code.get(code)
            verified = spot_row is not None and _finite(getattr(spot_row, "最新价"))
            records.append(
                {
                    "record_type": "security",
                    "trade_date": request.trade_date,
                    "ts_code": code,
                    "name": name,
                    "exchange": exchange,
                    "list_date": list_date,
                    "status_verified": verified,
                    "is_suspended": False,
                    "hard_excluded": _is_special_treatment_name(name),
                    "source_name": "akshare.exchange_lists+eastmoney_spot",
                }
            )
        return EndpointResponse(
            records=tuple(records),
            covered_dates=covered_dates,
            coverage_codes=tuple(
                sorted(
                    code
                    for code, _, _, list_date in listed
                    if list_date <= request.trade_date
                )
            ),
            coverage_proven=True,
            field_coverage=_field_coverage(request, AcquisitionGroupId.CALENDAR_UNIVERSE),
            source_names=(
                "akshare.tool_trade_date_hist_sina",
                "akshare.stock_info_sh_name_code",
                "akshare.stock_info_sz_name_code",
                "akshare.stock_info_bj_name_code",
                "akshare.stock_zh_a_spot_em",
            ),
        )

    def fetch_market_decision(self, request: AcquisitionRequest) -> EndpointResponse:
        sessions = self._required_sessions(request.trade_date)
        requested = set(request.target_codes)
        records: list[dict[str, Any]] = []
        dates_by_code: dict[str, set[date]] = {}
        for code in request.target_codes:
            frame = self._call(
                "stock_zh_a_hist",
                symbol=_bare_code(code),
                period="daily",
                start_date=_yyyymmdd(sessions[0]),
                end_date=_yyyymmdd(request.trade_date),
                adjust="",
            )
            _require_column_map(frame, HISTORY_COLUMNS, "stock_zh_a_hist")
            for row in frame.itertuples(index=False):
                trade_date = _parse_date(getattr(row, "日期"))
                dates_by_code.setdefault(code, set()).add(trade_date)
                records.append(
                    {
                        "record_type": "equity_bar",
                        "trade_date": trade_date,
                        "ts_code": code,
                        "open": _safe_float(getattr(row, "开盘")),
                        "high": _safe_float(getattr(row, "最高")),
                        "low": _safe_float(getattr(row, "最低")),
                        "close": _safe_float(getattr(row, "收盘")),
                        "volume": _safe_float(getattr(row, "成交量")),
                        "amount": _safe_float(getattr(row, "成交额")),
                        "source_name": "akshare.stock_zh_a_hist",
                    }
                )

        incomplete_codes = sorted(
            code
            for code in requested
            if request.trade_date not in dates_by_code.get(code, set())
        )
        if incomplete_codes:
            raise PermanentRouteFailure(
                "AKShare history lacks the target bar for: "
                + ", ".join(incomplete_codes),
                FailureClassification.INCOMPLETE_UNIVERSE,
            )

        spot = self._call("stock_zh_a_spot_em")
        _require_column_map(spot, SPOT_COLUMNS, "stock_zh_a_spot_em")
        for row in spot.to_dict(orient="records"):
            code = _to_ts_code(row["代码"])
            if code not in requested:
                continue
            pe_ttm = _safe_float(row["市盈率-动态"])
            pb = _safe_float(row["市净率"])
            records.append(
                {
                    "record_type": "daily_basic",
                    "trade_date": request.trade_date,
                    "ts_code": code,
                    "turnover_rate": _safe_float(row["换手率"]),
                    "total_mv": _safe_float(row["总市值"]),
                    "circ_mv": _safe_float(row["流通市值"]),
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
                    "source_name": "akshare.stock_zh_a_spot_em",
                }
            )

        found_indexes: set[str] = set()
        index_dates_by_code: dict[str, set[date]] = {}
        for symbol in self.required_index_symbols:
            frame = self._call("stock_zh_index_daily_em", symbol=symbol)
            _require_column_map(frame, INDEX_COLUMNS, "stock_zh_index_daily_em")
            index_code = _index_ts_code(symbol)
            for row in frame.itertuples(index=False):
                found_indexes.add(index_code)
                index_date = _parse_date(row.date)
                index_dates_by_code.setdefault(index_code, set()).add(index_date)
                records.append(
                    {
                        "record_type": "index_bar",
                        "trade_date": index_date,
                        "ts_code": index_code,
                        "open": _safe_float(row.open),
                        "high": _safe_float(row.high),
                        "low": _safe_float(row.low),
                        "close": _safe_float(row.close),
                        "volume": _safe_float(row.volume),
                        "amount": _safe_float(row.amount),
                        "source_name": "akshare.stock_zh_index_daily_em",
                    }
                )
        required_indexes = {_index_ts_code(symbol) for symbol in self.required_index_symbols}
        missing_indexes = sorted(required_indexes - found_indexes)
        if missing_indexes:
            raise PermanentRouteFailure(
                "AKShare index response missing required indexes: " + ", ".join(missing_indexes),
                FailureClassification.INCOMPLETE_UNIVERSE,
            )
        incomplete_indexes = sorted(
            code
            for code in required_indexes
            if not set(sessions) <= index_dates_by_code.get(code, set())
        )
        if incomplete_indexes:
            raise PermanentRouteFailure(
                "AKShare index history lacks the declared "
                f"{FORMAL_SCREENING_SESSION_COUNT} sessions for: "
                + ", ".join(incomplete_indexes),
                FailureClassification.INCOMPLETE_UNIVERSE,
            )
        covered_dates = sessions
        return EndpointResponse(
            records=tuple(records),
            covered_dates=covered_dates,
            coverage_codes=tuple(sorted(requested | found_indexes)),
            coverage_proven=len(covered_dates) == len(sessions),
            field_coverage=_field_coverage(request, AcquisitionGroupId.MARKET_DECISION),
            source_names=(
                "akshare.stock_zh_a_hist",
                "akshare.stock_zh_a_spot_em",
                "akshare.stock_zh_index_daily_em",
            ),
            unit_metadata={"volume": "shares", "amount": "CNY", "market_value": "CNY"},
            adjustment_basis="unadjusted",
        )

    def fetch_board_industry(self, request: AcquisitionRequest) -> EndpointResponse:
        sessions = self._required_sessions(request.trade_date)
        names = self._call("stock_board_industry_name_em")
        _require_columns(names, ("排名", "板块名称", "板块代码"), "stock_board_industry_name_em")
        requested = set(request.target_codes)
        records: list[dict[str, Any]] = []
        covered_dates: set[date] = {request.trade_date}
        for board in names.itertuples(index=False):
            board_name = str(getattr(board, "板块名称"))
            board_code = str(getattr(board, "板块代码"))
            members = self._call("stock_board_industry_cons_em", symbol=board_name)
            _require_columns(members, ("序号", "代码", "名称"), "stock_board_industry_cons_em")
            matched = False
            for member in members.itertuples(index=False):
                code = _to_ts_code(getattr(member, "代码"))
                if code not in requested:
                    continue
                matched = True
                records.append(
                    {
                        "record_type": "industry_mapping",
                        "trade_date": request.trade_date,
                        "ts_code": code,
                        "industry_code": board_code,
                        "industry_name": board_name,
                        "source_name": "akshare.stock_board_industry_cons_em",
                    }
                )
            if not matched:
                continue
            history = self._call(
                "stock_board_industry_hist_em",
                symbol=board_name,
                start_date=_yyyymmdd(sessions[0]),
                end_date=_yyyymmdd(request.trade_date),
                period="日k",
                adjust="",
            )
            _require_column_map(history, BOARD_HISTORY_COLUMNS, "stock_board_industry_hist_em")
            board_dates: set[date] = set()
            for row in history.itertuples(index=False):
                trade_date = _parse_date(getattr(row, "日期"))
                board_dates.add(trade_date)
                covered_dates.add(trade_date)
                records.append(
                    {
                        "record_type": "board_bar",
                        "trade_date": trade_date,
                        "board_code": board_code,
                        "board_name": board_name,
                        "open": _safe_float(getattr(row, "开盘")),
                        "high": _safe_float(getattr(row, "最高")),
                        "low": _safe_float(getattr(row, "最低")),
                        "close": _safe_float(getattr(row, "收盘")),
                        "volume": _safe_float(getattr(row, "成交量")),
                        "amount": _safe_float(getattr(row, "成交额")),
                        "source_name": "akshare.stock_board_industry_hist_em",
                    }
                )
            if not set(sessions[-FORMAL_BOARD_SESSION_COUNT:]) <= board_dates:
                raise PermanentRouteFailure(
                    "AKShare board history lacks "
                    f"{FORMAL_BOARD_SESSION_COUNT} sessions for {board_code}",
                    FailureClassification.INCOMPLETE_UNIVERSE,
                )
        return EndpointResponse(
            records=tuple(records),
            covered_dates=tuple(sorted(covered_dates)),
            coverage_codes=tuple(sorted(requested)),
            coverage_proven=True,
            field_coverage=_field_coverage(request, AcquisitionGroupId.BOARD_INDUSTRY),
            source_names=(
                "akshare.stock_board_industry_name_em",
                "akshare.stock_board_industry_cons_em",
                "akshare.stock_board_industry_hist_em",
            ),
            unit_metadata={"volume": "shares", "amount": "CNY"},
            adjustment_basis="unadjusted",
        )

    def fetch_candidate_fundamentals(self, request: AcquisitionRequest) -> EndpointResponse:
        records: list[dict[str, Any]] = []
        publication_times: dict[str, datetime] = {}
        for code in request.target_codes:
            profile = self._call("stock_individual_info_em", symbol=_bare_code(code))
            _require_columns(profile, ("item", "value"), "stock_individual_info_em")
            values = {str(row.item): row.value for row in profile.itertuples(index=False)}
            if "主营业务" not in values:
                raise PermanentRouteFailure(
                    "AKShare stock_individual_info_em response missing item: 主营业务",
                    FailureClassification.MISSING_FIELDS,
                )
            records.append(
                {
                    "record_type": "company_profile",
                    "trade_date": request.trade_date,
                    "ts_code": code,
                    "business_summary": str(values["主营业务"]),
                    "source_name": "akshare.stock_individual_info_em",
                }
            )
            financial = self._call("stock_financial_abstract_ths", symbol=_bare_code(code))
            _require_columns(
                financial,
                (
                    "报告期",
                    "公告日期",
                    "营业总收入同比增长率",
                    "净利润同比增长率",
                    "销售毛利率",
                    "经营活动产生的现金流量净额",
                ),
                "stock_financial_abstract_ths",
            )
            valid_rows = [
                row
                for row in financial.itertuples(index=False)
                if _publication_time(getattr(row, "公告日期"), request) <= request.report_cutoff
            ]
            valid_rows.sort(
                key=lambda row: (
                    _parse_date(getattr(row, "报告期")),
                    _parse_date(getattr(row, "公告日期")),
                ),
                reverse=True,
            )
            if valid_rows:
                row = valid_rows[0]
                period_end = _parse_date(getattr(row, "报告期"))
                announcement = _publication_time(getattr(row, "公告日期"), request)
                publication_times[f"{code}:financial_summary:{period_end.isoformat()}"] = announcement
                revenue_yoy = _safe_float(getattr(row, "营业总收入同比增长率"))
                profit_yoy = _safe_float(getattr(row, "净利润同比增长率"))
                gross_margin = _safe_float(getattr(row, "销售毛利率"))
                operating_cashflow = _safe_float(
                    getattr(row, "经营活动产生的现金流量净额")
                )
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
                        "operating_cashflow": operating_cashflow,
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
                                    operating_cashflow,
                                )
                            )
                            else {}
                        ),
                        "source_name": "akshare.stock_financial_abstract_ths",
                    }
                )
        return EndpointResponse(
            records=tuple(records),
            covered_dates=(request.trade_date,),
            coverage_codes=tuple(sorted(request.target_codes)),
            coverage_proven=True,
            field_coverage=_field_coverage(request, AcquisitionGroupId.CANDIDATE_FUNDAMENTAL),
            source_names=(
                "akshare.stock_individual_info_em",
                "akshare.stock_financial_abstract_ths",
            ),
            publication_times=publication_times,
        )

    def fetch_official_events_risk(self, request: AcquisitionRequest) -> EndpointResponse:
        sessions = self._required_sessions(request.trade_date)
        requested_by_bare = {_bare_code(code): code for code in request.target_codes}
        records_by_id: dict[str, dict[str, Any]] = {}
        publication_times: dict[str, datetime] = {}
        for bare_code, expected_code in requested_by_bare.items():
            for category in ("", *CNINFO_HARD_RISK_CATEGORIES):
                notices = self._call(
                    "stock_zh_a_disclosure_report_cninfo",
                    symbol=bare_code,
                    market="沪深京",
                    keyword="",
                    category=category,
                    start_date=_yyyymmdd(sessions[-2]),
                    end_date=_yyyymmdd(request.trade_date),
                )
                _require_columns(
                    notices,
                    CNINFO_DISCLOSURE_COLUMNS,
                    "stock_zh_a_disclosure_report_cninfo",
                )
                for row in notices.itertuples(index=False):
                    raw_code = str(getattr(row, "代码")).strip().zfill(6)
                    code = requested_by_bare.get(raw_code)
                    if code is None or code != expected_code:
                        continue
                    publication = _precise_publication_time(
                        getattr(row, "公告时间"),
                        request,
                    )
                    if publication > request.report_cutoff:
                        continue
                    url = str(getattr(row, "公告链接")).strip()
                    title = str(getattr(row, "公告标题")).strip()
                    if not url or url.lower() == "nan" or not title:
                        raise PermanentRouteFailure(
                            "CNINFO disclosure lacks a stable URL or title",
                            FailureClassification.SCHEMA,
                        )
                    event_id = f"{code}:{url}"
                    hard_risk = bool(category)
                    if event_id in records_by_id and not hard_risk:
                        continue
                    publication_times[event_id] = publication
                    records_by_id[event_id] = {
                        "record_type": "official_event",
                        "trade_date": request.trade_date,
                        "ts_code": code,
                        "event_id": event_id,
                        "event_type": category or "official_disclosure",
                        "title": title,
                        "publication_time": publication,
                        "source_reliability": "official_disclosure",
                        "is_new_information": True,
                        "hard_risk": hard_risk,
                        "source_name": (
                            "akshare.stock_zh_a_disclosure_report_cninfo"
                        ),
                    }
        records = tuple(
            sorted(
                records_by_id.values(),
                key=lambda item: (item["publication_time"], item["event_id"]),
            )
        )
        return EndpointResponse(
            records=records,
            covered_dates=(request.trade_date,),
            coverage_codes=tuple(sorted(request.target_codes)),
            coverage_proven=True,
            field_coverage=_field_coverage(request, AcquisitionGroupId.OFFICIAL_EVENTS_RISK),
            source_names=("akshare.stock_zh_a_disclosure_report_cninfo",),
            publication_times=publication_times,
        )

    def fetch_concepts(self, request: AcquisitionRequest) -> EndpointResponse:
        names = self._call("stock_board_concept_name_em")
        _require_columns(names, ("排名", "板块名称", "板块代码"), "stock_board_concept_name_em")
        requested = set(request.target_codes)
        records: list[dict[str, Any]] = []
        for board in names.itertuples(index=False):
            concept_name = str(getattr(board, "板块名称"))
            concept_code = str(getattr(board, "板块代码"))
            members = self._call("stock_board_concept_cons_em", symbol=concept_name)
            _require_columns(members, ("序号", "代码", "名称"), "stock_board_concept_cons_em")
            for member in members.itertuples(index=False):
                code = _to_ts_code(getattr(member, "代码"))
                if code not in requested:
                    continue
                records.append(
                    {
                        "record_type": "concept_mapping",
                        "trade_date": request.trade_date,
                        "ts_code": code,
                        "concept_code": concept_code,
                        "concept_name": concept_name,
                        "source_name": "akshare.stock_board_concept_cons_em",
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
            source_names=(
                "akshare.stock_board_concept_name_em",
                "akshare.stock_board_concept_cons_em",
            ),
        )

    def _required_sessions(self, trade_date: date) -> tuple[date, ...]:
        calendar = self._call("tool_trade_date_hist_sina")
        _require_columns(calendar, ("trade_date",), "tool_trade_date_hist_sina")
        sessions = tuple(
            sorted(
                {
                    parsed
                    for value in calendar["trade_date"]
                    if (parsed := _parse_date(value)) <= trade_date
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

    def _call(self, method: str, **kwargs: Any) -> pd.DataFrame:
        try:
            frame = getattr(self.ak, method)(**kwargs)
        except RouteFailure:
            raise
        except Exception as exc:
            if method == "stock_zh_a_disclosure_report_cninfo" and (
                _is_cninfo_zero_announcement_error(exc)
            ):
                return pd.DataFrame(columns=CNINFO_DISCLOSURE_COLUMNS)
            _raise_provider_error(method, exc)
        if not isinstance(frame, pd.DataFrame):
            raise PermanentRouteFailure(
                f"AKShare {method} response is not a DataFrame",
                FailureClassification.SCHEMA,
            )
        return frame


def _field_coverage(
    request: AcquisitionRequest,
    group_id: AcquisitionGroupId,
    *,
    include_concepts: bool = False,
) -> dict[str, bool]:
    if group_id in {AcquisitionGroupId.CALENDAR_UNIVERSE, AcquisitionGroupId.MARKET_DECISION}:
        contract = build_screening_contracts(request.trade_date, request.target_codes)[group_id]
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


def _require_columns(frame: pd.DataFrame, names: Iterable[str], stage: str) -> None:
    missing = [name for name in names if name not in frame.columns]
    if missing:
        raise PermanentRouteFailure(
            f"AKShare {stage} response missing fields: {', '.join(missing)}",
            FailureClassification.SCHEMA,
        )


def _require_column_map(frame: pd.DataFrame, mapping: dict[str, str], stage: str) -> None:
    _require_columns(frame, tuple(mapping), stage)


def _parse_date(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip().replace("/", "-")
    try:
        if len(text) == 8 and text.isdigit():
            return date(int(text[:4]), int(text[4:6]), int(text[6:8]))
        return date.fromisoformat(text[:10])
    except ValueError as exc:
        raise PermanentRouteFailure(
            "AKShare response contains an invalid date",
            FailureClassification.SCHEMA,
        ) from exc


def _publication_time(value: Any, request: AcquisitionRequest) -> datetime:
    publication_date = _parse_date(value)
    if publication_date == request.report_cutoff.date():
        raise PermanentRouteFailure(
            "AKShare date-only response lacks a precise publication time "
            "for a same-day fact",
            FailureClassification.INVALID_SEMANTICS,
        )
    return datetime.combine(
        publication_date,
        time.min,
        tzinfo=request.report_cutoff.tzinfo,
    )


def _precise_publication_time(
    value: Any,
    request: AcquisitionRequest,
) -> datetime:
    if not isinstance(value, datetime):
        text = str(value).strip()
        if len(text) <= 11 or text[10] not in {" ", "T"} or ":" not in text[11:]:
            raise PermanentRouteFailure(
                "CNINFO disclosure lacks a precise publication time",
                FailureClassification.INVALID_SEMANTICS,
            )
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        raise PermanentRouteFailure(
            "CNINFO disclosure contains an invalid publication time",
            FailureClassification.SCHEMA,
        )
    timestamp = pd.Timestamp(parsed)
    if timestamp.tzinfo is None:
        timestamp = timestamp.tz_localize(request.report_cutoff.tzinfo)
    else:
        timestamp = timestamp.tz_convert(request.report_cutoff.tzinfo)
    return timestamp.to_pydatetime()


def _is_cninfo_zero_announcement_error(exc: Exception) -> bool:
    if not isinstance(exc, KeyError):
        return False
    message = str(exc)
    return all(
        marker in message
        for marker in (
            "None of [Index(",
            "代码",
            "公告时间",
            "announcementId",
            "orgId",
            "are in the [columns]",
        )
    )


def _safe_float(value: Any) -> float | None:
    if pd.isna(value) or str(value).strip().lower() in {"", "-", "--", "none", "null"}:
        return None
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise PermanentRouteFailure(
            "AKShare response contains a non-numeric value",
            FailureClassification.SCHEMA,
        ) from exc


def _finite(value: Any) -> bool:
    result = _safe_float(value)
    return result is not None


def _to_ts_code(value: Any, *, exchange: str | None = None) -> str:
    raw = str(value).strip().upper()
    if "." in raw:
        code, suffix = raw.split(".", 1)
        if len(code) == 6 and suffix in {"SH", "SZ", "BJ"}:
            return f"{code}.{suffix}"
        raise PermanentRouteFailure(
            "AKShare response contains an invalid security code",
            FailureClassification.SCHEMA,
        )
    code = raw.zfill(6)
    if len(code) != 6 or not code.isdigit():
        raise PermanentRouteFailure(
            "AKShare response contains an invalid security code",
            FailureClassification.SCHEMA,
        )
    suffix = exchange or _infer_exchange(code)
    return f"{code}.{suffix}"


def _infer_exchange(code: str) -> str:
    if code.startswith(("4", "8", "92")):
        return "BJ"
    if code.startswith(("0", "3")):
        return "SZ"
    if code.startswith(("5", "6", "9")):
        return "SH"
    raise PermanentRouteFailure(
        "AKShare response contains an unrecognized exchange code",
        FailureClassification.SCHEMA,
    )


def _is_special_treatment_name(value: Any) -> bool:
    name = str(value).strip().upper()
    return name.startswith(("ST", "*ST", "S*ST", "SST"))


def _bare_code(code: str) -> str:
    normalized = _to_ts_code(code)
    return normalized.split(".", 1)[0]


def _index_ts_code(symbol: str) -> str:
    lowered = symbol.lower()
    if lowered.startswith("sh"):
        return f"{lowered[2:]}.SH"
    if lowered.startswith("sz"):
        return f"{lowered[2:]}.SZ"
    if lowered.startswith("bj"):
        return f"{lowered[2:]}.BJ"
    raise PermanentRouteFailure(
        "AKShare index symbol has an unrecognized exchange",
        FailureClassification.SCHEMA,
    )


def _yyyymmdd(value: date) -> str:
    return value.strftime("%Y%m%d")


def _raise_provider_error(method: str, exc: Exception) -> None:
    text = str(exc).lower()
    if any(marker in text for marker in ("rate limit", "too many", "频率")):
        raise TransientRouteFailure(
            f"AKShare {method} failed: {exc}",
            FailureClassification.RATE_LIMIT,
        ) from exc
    if any(marker in text for marker in ("timeout", "network", "connection", "连接")):
        raise TransientRouteFailure(
            f"AKShare {method} failed: {exc}",
            FailureClassification.TRANSPORT,
        ) from exc
    raise PermanentRouteFailure(
        f"AKShare {method} failed: {exc}",
        FailureClassification.SCHEMA,
    ) from exc


__all__ = [
    "AkshareFormalEndpointClient",
    "CNINFO_DISCLOSURE_COLUMNS",
    "CNINFO_HARD_RISK_CATEGORIES",
    "SPOT_COLUMNS",
]
