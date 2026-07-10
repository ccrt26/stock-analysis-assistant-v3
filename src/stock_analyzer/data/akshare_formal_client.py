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
from stock_analyzer.data.formal_routes import EndpointResponse
from stock_analyzer.data.readiness import (
    JULY_10_OFFICIAL_SESSIONS,
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
        required_index_symbols: tuple[str, ...] = (
            "sh000001",
            "sz399001",
            "bj899050",
        ),
    ) -> None:
        self.ak = ak
        self.required_index_symbols = required_index_symbols

    def fetch_calendar_universe(self, request: AcquisitionRequest) -> EndpointResponse:
        sessions = _required_sessions(request.trade_date)
        calendar = self._call("tool_trade_date_hist_sina")
        _require_columns(calendar, ("trade_date",), "tool_trade_date_hist_sina")
        sh = self._call("stock_info_sh_name_code")
        _require_columns(sh, ("证券代码", "证券简称", "上市日期"), "stock_info_sh_name_code")
        sz = self._call("stock_info_sz_name_code")
        _require_columns(sz, ("A股代码", "A股简称", "A股上市日期"), "stock_info_sz_name_code")
        bj = self._call("stock_info_bj_name_code")
        _require_columns(bj, ("证券代码", "证券简称", "上市日期"), "stock_info_bj_name_code")
        sh_delist = self._call("stock_info_sh_delist")
        _require_columns(
            sh_delist,
            ("公司代码", "公司简称", "终止上市日期"),
            "stock_info_sh_delist",
        )
        sz_delist = self._call("stock_info_sz_delist")
        _require_columns(
            sz_delist,
            ("证券代码", "证券简称", "终止上市日期"),
            "stock_info_sz_delist",
        )
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
        delisted = {
            _to_ts_code(row.公司代码, exchange="SH")
            for row in sh_delist.itertuples(index=False)
        } | {
            _to_ts_code(row.证券代码, exchange="SZ")
            for row in sz_delist.itertuples(index=False)
        }
        spot_by_code = {
            _to_ts_code(getattr(row, "代码")): row
            for row in spot.itertuples(index=False)
        }
        covered_dates = tuple(
            sorted(
                value
                for value in (_parse_date(item) for item in calendar["trade_date"])
                if value in sessions
            )
        )
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
                    "hard_excluded": code in delisted,
                    "source_name": "akshare.exchange_lists+eastmoney_spot",
                }
            )
        return EndpointResponse(
            records=tuple(records),
            covered_dates=covered_dates,
            coverage_codes=tuple(sorted(code for code, _, _, _ in listed)),
            coverage_proven=True,
            field_coverage=_field_coverage(request, AcquisitionGroupId.CALENDAR_UNIVERSE),
            source_names=(
                "akshare.tool_trade_date_hist_sina",
                "akshare.stock_info_sh_name_code",
                "akshare.stock_info_sz_name_code",
                "akshare.stock_info_bj_name_code",
                "akshare.stock_info_sh_delist",
                "akshare.stock_info_sz_delist",
                "akshare.stock_zh_a_spot_em",
            ),
        )

    def fetch_market_decision(self, request: AcquisitionRequest) -> EndpointResponse:
        sessions = _required_sessions(request.trade_date)
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

        spot = self._call("stock_zh_a_spot_em")
        _require_column_map(spot, SPOT_COLUMNS, "stock_zh_a_spot_em")
        for row in spot.to_dict(orient="records"):
            code = _to_ts_code(row["代码"])
            if code not in requested:
                continue
            records.append(
                {
                    "record_type": "daily_basic",
                    "trade_date": request.trade_date,
                    "ts_code": code,
                    "turnover_rate": _safe_float(row["换手率"]),
                    "total_mv": _safe_float(row["总市值"]),
                    "circ_mv": _safe_float(row["流通市值"]),
                    "pe_ttm": _safe_float(row["市盈率-动态"]),
                    "pb": _safe_float(row["市净率"]),
                    "source_name": "akshare.stock_zh_a_spot_em",
                }
            )

        found_indexes: set[str] = set()
        for symbol in self.required_index_symbols:
            frame = self._call("stock_zh_index_daily_em", symbol=symbol)
            _require_column_map(frame, INDEX_COLUMNS, "stock_zh_index_daily_em")
            index_code = _index_ts_code(symbol)
            for row in frame.itertuples(index=False):
                found_indexes.add(index_code)
                records.append(
                    {
                        "record_type": "index_bar",
                        "trade_date": _parse_date(row.date),
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
        covered_dates = tuple(
            session
            for session in sessions
            if all(session in dates_by_code.get(code, set()) for code in requested)
        )
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
                start_date=_yyyymmdd(JULY_10_OFFICIAL_SESSIONS[0]),
                end_date=_yyyymmdd(request.trade_date),
                period="日k",
                adjust="",
            )
            _require_column_map(history, BOARD_HISTORY_COLUMNS, "stock_board_industry_hist_em")
            for row in history.itertuples(index=False):
                trade_date = _parse_date(getattr(row, "日期"))
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
                records.append(
                    {
                        "record_type": "financial_summary",
                        "trade_date": request.trade_date,
                        "ts_code": code,
                        "period_end": period_end,
                        "announcement_time": announcement,
                        "revenue_yoy": _safe_float(getattr(row, "营业总收入同比增长率")),
                        "profit_yoy": _safe_float(getattr(row, "净利润同比增长率")),
                        "gross_margin": _safe_float(getattr(row, "销售毛利率")),
                        "operating_cashflow": _safe_float(
                            getattr(row, "经营活动产生的现金流量净额")
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
        notices = self._call(
            "stock_notice_report",
            symbol="全部",
            date=_yyyymmdd(request.trade_date),
        )
        _require_columns(
            notices,
            ("代码", "名称", "公告标题", "公告类型", "公告日期", "网址"),
            "stock_notice_report",
        )
        requested = set(request.target_codes)
        hard_risk_types = {"风险提示", "停牌", "退市", "处罚"}
        records: list[dict[str, Any]] = []
        publication_times: dict[str, datetime] = {}
        for row in notices.itertuples(index=False):
            code = _to_ts_code(getattr(row, "代码"))
            publication = _publication_time(getattr(row, "公告日期"), request)
            if code not in requested or publication > request.report_cutoff:
                continue
            event_id = str(getattr(row, "网址"))
            event_type = str(getattr(row, "公告类型"))
            publication_times[event_id] = publication
            records.append(
                {
                    "record_type": "official_event",
                    "trade_date": request.trade_date,
                    "ts_code": code,
                    "event_id": event_id,
                    "event_type": event_type,
                    "title": str(getattr(row, "公告标题")),
                    "publication_time": publication,
                    "source_reliability": "exchange_disclosure",
                    "is_new_information": True,
                    "hard_risk": event_type in hard_risk_types,
                    "source_name": "akshare.stock_notice_report",
                }
            )
        return EndpointResponse(
            records=tuple(records),
            covered_dates=(request.trade_date,),
            coverage_codes=tuple(sorted(requested)),
            coverage_proven=True,
            field_coverage=_field_coverage(request, AcquisitionGroupId.OFFICIAL_EVENTS_RISK),
            source_names=("akshare.stock_notice_report",),
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

    def _call(self, method: str, **kwargs: Any) -> pd.DataFrame:
        try:
            frame = getattr(self.ak, method)(**kwargs)
        except RouteFailure:
            raise
        except Exception as exc:
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


def _required_sessions(trade_date: date) -> tuple[date, ...]:
    if trade_date != JULY_10_OFFICIAL_SESSIONS[-1]:
        raise PermanentRouteFailure(
            "verified 82-session window is unavailable for requested trade date",
            FailureClassification.STALE_DATA,
        )
    return JULY_10_OFFICIAL_SESSIONS


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
    return datetime.combine(
        _parse_date(value),
        time.min,
        tzinfo=request.report_cutoff.tzinfo,
    )


def _safe_float(value: Any) -> float | None:
    if pd.isna(value):
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


__all__ = ["AkshareFormalEndpointClient", "SPOT_COLUMNS"]
