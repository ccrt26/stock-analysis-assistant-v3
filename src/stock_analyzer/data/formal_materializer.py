from __future__ import annotations

from datetime import date
from typing import Any

from pydantic import BaseModel, ConfigDict

from stock_analyzer.analysis.pool import clean_stock_pool
from stock_analyzer.analysis.scoring import score_feature
from stock_analyzer.data.feature_builder import build_market_bundle
from stock_analyzer.data.formal_routes import derive_expected_tradable_codes
from stock_analyzer.data.models import (
    BoardContextRow,
    CompanyProfileRow,
    ConceptTagRow,
    DailyBar,
    DailyBasicRow,
    DataStatus,
    EventCatalystRow,
    FundamentalSummaryRow,
    MarketDataBundle,
    SourceGrade,
    SourceRunRecord,
    SourceStatus,
    StockBasicRow,
)
from stock_analyzer.data.readiness import (
    AcquisitionGroupId,
    AcquisitionPayload,
    FormalRunState,
    RouteKind,
)
from stock_analyzer.domain.models import FeatureSnapshot, ManualHolding
from stock_analyzer.ops.formal_run import FormalScreeningOutput, RunReceipt


class FormalMaterializationError(RuntimeError):
    pass


class FormalMarketInputs(BaseModel):
    model_config = ConfigDict(frozen=True)

    bundle: MarketDataBundle
    included_codes: tuple[str, ...]
    feature_profiles: dict[str, FeatureSnapshot]


class FormalTargetContext(BaseModel):
    model_config = ConfigDict(frozen=True)

    trade_date: date
    target_codes: tuple[str, ...]
    company_profiles: dict[str, CompanyProfileRow]
    fundamental_summaries: dict[str, FundamentalSummaryRow]
    board_contexts: dict[str, BoardContextRow]
    official_events: dict[str, tuple[EventCatalystRow, ...]]
    concept_tags: dict[str, tuple[ConceptTagRow, ...]]
    manual_holdings: dict[str, ManualHolding]


def materialize_market_inputs(
    trade_date: date,
    payloads: dict[AcquisitionGroupId, AcquisitionPayload],
) -> FormalMarketInputs:
    calendar = _required_payload(
        payloads,
        AcquisitionGroupId.CALENDAR_UNIVERSE,
        trade_date,
    )
    market = _required_payload(
        payloads,
        AcquisitionGroupId.MARKET_DECISION,
        trade_date,
    )
    security_records = [
        record for record in calendar.records if record.get("record_type") == "security"
    ]
    try:
        tradable_codes = derive_expected_tradable_codes(tuple(security_records))
    except ValueError as exc:
        raise FormalMaterializationError(str(exc)) from exc
    security_by_code: dict[str, dict[str, Any]] = {}
    for record in security_records:
        code = _record_code(record)
        if code in security_by_code:
            raise FormalMaterializationError(f"duplicate verified security: {code}")
        security_by_code[code] = record
    tradable = set(tradable_codes)

    stock_basic = [
        StockBasicRow(
            ts_code=code,
            name=str(security_by_code[code]["name"]),
            exchange=str(security_by_code[code]["exchange"]),
            list_date=_as_date(security_by_code[code].get("list_date")),
        )
        for code in tradable_codes
    ]
    daily_bars: list[DailyBar] = []
    daily_basic: list[DailyBasicRow] = []
    source_grade = _source_grade(market.route_kind)
    for record in market.records:
        record_type = record.get("record_type")
        if record_type not in {"equity_bar", "daily_basic"}:
            continue
        code = _record_code(record)
        record_date = _as_date(record.get("trade_date"))
        if code not in tradable:
            raise FormalMaterializationError(
                f"market code outside verified universe: {code}"
            )
        if record_date is None or record_date > trade_date:
            raise FormalMaterializationError(
                f"market date outside verified window: {record.get('trade_date')}"
            )
        if record_type == "equity_bar":
            daily_bars.append(
                DailyBar(
                    trade_date=record_date,
                    ts_code=code,
                    open=_optional_float(record.get("open")),
                    high=_optional_float(record.get("high")),
                    low=_optional_float(record.get("low")),
                    close=_required_float(record.get("close"), "close"),
                    vol=_optional_float(record.get("volume")),
                    amount=_optional_float(record.get("amount")),
                    source_name=str(record.get("source_name", market.route_id)),
                    source_grade=source_grade,
                    fetched_at=market.fetched_at,
                )
            )
        else:
            daily_basic.append(
                DailyBasicRow(
                    trade_date=record_date,
                    ts_code=code,
                    turnover_rate=_optional_float(record.get("turnover_rate")),
                    total_mv=_optional_float(record.get("total_mv")),
                    circ_mv=_optional_float(record.get("circ_mv")),
                    pe_ttm=_optional_float(record.get("pe_ttm")),
                    pb=_optional_float(record.get("pb")),
                    source_name=str(record.get("source_name", market.route_id)),
                    source_grade=source_grade,
                    fetched_at=market.fetched_at,
                )
            )

    data_status = (
        DataStatus.COMPLETE_LIVE_BACKUP
        if market.route_kind is RouteKind.BACKUP
        else DataStatus.COMPLETE_PRIMARY
    )
    bundle = build_market_bundle(
        trade_date=trade_date,
        stock_basic=stock_basic,
        daily_bars=daily_bars,
        daily_basic=daily_basic,
        data_status=data_status,
        source_grade=source_grade,
        source_versions={
            calendar.route_id: calendar.content_hash,
            market.route_id: market.content_hash,
        },
        source_runs=[
            SourceRunRecord(
                trade_date=trade_date,
                source_name=market.route_id,
                stage="formal_market_materialization",
                status=SourceStatus.SUCCESS,
                message="complete formal market group materialized",
                source_grade=source_grade,
                data_status=data_status,
                record_count=len(market.records),
                field_coverage=dict(market.field_coverage),
            )
        ],
        stock_status_by_code={
            code: {
                "is_st": bool(security_by_code[code].get("hard_excluded")),
                "is_suspended": bool(security_by_code[code].get("is_suspended")),
                "has_delisting_risk": bool(security_by_code[code].get("hard_excluded")),
            }
            for code in tradable_codes
        },
    )
    included_stocks, _ = clean_stock_pool(bundle.stocks)
    included_codes = tuple(sorted(stock.ts_code for stock in included_stocks))
    features = {
        code: bundle.feature_profiles[code]
        for code in included_codes
        if code in bundle.feature_profiles
    }
    included_codes = tuple(code for code in included_codes if code in features)
    return FormalMarketInputs(
        bundle=bundle,
        included_codes=included_codes,
        feature_profiles=features,
    )


def materialize_target_context(
    trade_date: date,
    target_codes: tuple[str, ...],
    payloads: dict[AcquisitionGroupId, AcquisitionPayload],
) -> FormalTargetContext:
    target_codes = tuple(dict.fromkeys(target_codes))
    target_set = set(target_codes)
    fundamentals = _required_payload(
        payloads,
        AcquisitionGroupId.CANDIDATE_FUNDAMENTAL,
        trade_date,
    )
    boards = _required_payload(
        payloads,
        AcquisitionGroupId.BOARD_INDUSTRY,
        trade_date,
    )
    events = _required_payload(
        payloads,
        AcquisitionGroupId.OFFICIAL_EVENTS_RISK,
        trade_date,
    )
    holdings_payload = _required_payload(
        payloads,
        AcquisitionGroupId.MANUAL_HOLDINGS,
        trade_date,
    )
    for payload in (fundamentals, boards, events, holdings_payload):
        _reject_outside_target_records(payload, trade_date, target_set)

    company_profiles: dict[str, CompanyProfileRow] = {}
    fundamental_summaries: dict[str, FundamentalSummaryRow] = {}
    for record in fundamentals.records:
        code = _record_code(record)
        if record.get("record_type") == "company_profile":
            company_profiles[code] = CompanyProfileRow(
                trade_date=trade_date,
                ts_code=code,
                business_summary=_optional_text(record.get("business_summary")),
                main_business_lines=[],
                source_name=str(record.get("source_name", fundamentals.route_id)),
                source_grade=_source_grade(fundamentals.route_kind),
            )
        elif record.get("record_type") == "financial_summary":
            fundamental_summaries[code] = FundamentalSummaryRow(
                trade_date=trade_date,
                ts_code=code,
                period_end=_as_date(record.get("period_end")),
                announcement_time=record.get("announcement_time"),
                revenue_yoy=_optional_float(record.get("revenue_yoy")),
                profit_yoy=_optional_float(record.get("profit_yoy")),
                gross_margin=_optional_float(record.get("gross_margin")),
                operating_cashflow=_optional_float(record.get("operating_cashflow")),
                source_name=str(record.get("source_name", fundamentals.route_id)),
                source_grade=_source_grade(fundamentals.route_kind),
            )

    board_bars: dict[str, list[dict[str, Any]]] = {}
    mappings: dict[str, tuple[str, str]] = {}
    for record in boards.records:
        if record.get("record_type") == "industry_mapping":
            mappings[_record_code(record)] = (
                str(record["industry_code"]),
                str(record["industry_name"]),
            )
        elif record.get("record_type") == "board_bar":
            board_bars.setdefault(str(record["board_code"]), []).append(record)
    board_contexts: dict[str, BoardContextRow] = {}
    for code, (board_code, board_name) in mappings.items():
        history = sorted(
            board_bars.get(board_code, []),
            key=lambda row: _as_date(row.get("trade_date")) or date.min,
        )
        strength = None
        if len(history) >= 2:
            first = _required_float(history[max(0, len(history) - 21)].get("close"), "close")
            last = _required_float(history[-1].get("close"), "close")
            strength = 0.0 if first == 0 else (last - first) / first
        board_contexts[code] = BoardContextRow(
            trade_date=trade_date,
            board_name=board_name,
            board_type="industry",
            relative_strength_20d=strength,
            breadth=None,
            turnover_change=None,
            source_name=str(boards.source_names[0]),
            source_grade=_source_grade(boards.route_kind),
        )

    official_events: dict[str, list[EventCatalystRow]] = {
        code: [] for code in target_codes
    }
    for record in events.records:
        code = _record_code(record)
        official_events[code].append(
            EventCatalystRow(
                trade_date=trade_date,
                ts_code=code,
                event_type=str(record["event_type"]),
                title=str(record["title"]),
                source_reliability=str(record["source_reliability"]),
                is_new_information=bool(record["is_new_information"]),
                hard_risk=bool(record.get("hard_risk", False)),
                source_name=str(record.get("source_name", events.route_id)),
                source_grade=_source_grade(events.route_kind),
            )
        )

    concept_tags: dict[str, list[ConceptTagRow]] = {code: [] for code in target_codes}
    concept_payload = payloads.get(AcquisitionGroupId.CONCEPT_THEME)
    if concept_payload is not None:
        _reject_outside_target_records(concept_payload, trade_date, target_set)
        for record in concept_payload.records:
            code = _record_code(record)
            concept_tags[code].append(
                ConceptTagRow(
                    trade_date=trade_date,
                    ts_code=code,
                    concept_name=str(record["concept_name"]),
                    source_name=str(record.get("source_name", concept_payload.route_id)),
                    source_grade=_source_grade(concept_payload.route_kind),
                )
            )

    manual_holdings: dict[str, ManualHolding] = {}
    for record in holdings_payload.records:
        code = _record_code(record)
        manual_holdings[code] = ManualHolding(
            ts_code=code,
            name=str(record["name"]),
            position_pct=_required_float(record.get("position_pct"), "position_pct"),
            cost_price=_optional_float(record.get("cost_price")),
            quantity=_optional_float(record.get("quantity")),
            entry_date=_as_date(record.get("entry_date")),
            thesis_id=_optional_text(record.get("thesis_id")),
            notes=_optional_text(record.get("notes")),
        )

    missing_profiles = sorted(target_set - set(company_profiles))
    missing_fundamentals = sorted(target_set - set(fundamental_summaries))
    missing_boards = sorted(target_set - set(board_contexts))
    if missing_profiles or missing_fundamentals or missing_boards:
        reasons = []
        if missing_profiles:
            reasons.append("missing company profile: " + ", ".join(missing_profiles))
        if missing_fundamentals:
            reasons.append("missing financial summary: " + ", ".join(missing_fundamentals))
        if missing_boards:
            reasons.append("missing industry mapping: " + ", ".join(missing_boards))
        raise FormalMaterializationError("; ".join(reasons))
    if not events.coverage_proven or not target_set <= set(events.coverage_codes):
        raise FormalMaterializationError("official event coverage is incomplete")

    return FormalTargetContext(
        trade_date=trade_date,
        target_codes=target_codes,
        company_profiles=company_profiles,
        fundamental_summaries=fundamental_summaries,
        board_contexts=board_contexts,
        official_events={key: tuple(value) for key, value in official_events.items()},
        concept_tags={key: tuple(value) for key, value in concept_tags.items()},
        manual_holdings=manual_holdings,
    )


def screen_formal_market(
    receipt: RunReceipt,
    payloads: dict[AcquisitionGroupId, AcquisitionPayload],
    repository: Any,
) -> FormalScreeningOutput:
    if receipt.state is not FormalRunState.READY_TO_SCREEN:
        raise FormalMaterializationError("screening requires READY_TO_SCREEN")
    inputs = materialize_market_inputs(receipt.target_date, payloads)
    ranked = sorted(
        inputs.feature_profiles.values(),
        key=lambda item: (-score_feature(item), item.ts_code),
    )
    ordered_codes = tuple(item.ts_code for item in ranked[:10])
    active_focus_codes = tuple(
        sorted({state.ts_code for state in repository.load_focus_states()})
    )
    return FormalScreeningOutput(
        ordered_codes=ordered_codes,
        active_focus_codes=active_focus_codes,
    )


def _required_payload(
    payloads: dict[AcquisitionGroupId, AcquisitionPayload],
    group_id: AcquisitionGroupId,
    trade_date: date,
) -> AcquisitionPayload:
    payload = payloads.get(group_id)
    if payload is None:
        raise FormalMaterializationError(f"missing formal payload: {group_id.value}")
    if payload.group_id is not group_id or payload.trade_date != trade_date:
        raise FormalMaterializationError(f"payload identity mismatch: {group_id.value}")
    return payload


def _reject_outside_target_records(
    payload: AcquisitionPayload,
    trade_date: date,
    target_codes: set[str],
) -> None:
    for record in payload.records:
        record_date = _as_date(record.get("trade_date"))
        if record_date is not None and record_date > trade_date:
            raise FormalMaterializationError(
                f"record date outside frozen target: {record_date.isoformat()}"
            )
        code = record.get("ts_code")
        if isinstance(code, str) and code and code not in target_codes:
            raise FormalMaterializationError(f"code outside frozen target: {code}")


def _record_code(record: dict[str, Any]) -> str:
    code = record.get("ts_code")
    if not isinstance(code, str) or not code:
        raise FormalMaterializationError("formal record is missing ts_code")
    return code


def _source_grade(kind: RouteKind) -> SourceGrade:
    return SourceGrade.LIVE_BACKUP if kind is RouteKind.BACKUP else SourceGrade.PRIMARY


def _as_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError as exc:
        raise FormalMaterializationError(f"invalid date: {value}") from exc


def _required_float(value: Any, field: str) -> float:
    result = _optional_float(value)
    if result is None:
        raise FormalMaterializationError(f"missing numeric field: {field}")
    return result


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise FormalMaterializationError(f"invalid numeric value: {value}") from exc


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


__all__ = [
    "FormalMarketInputs",
    "FormalMaterializationError",
    "FormalTargetContext",
    "materialize_market_inputs",
    "materialize_target_context",
    "screen_formal_market",
]
