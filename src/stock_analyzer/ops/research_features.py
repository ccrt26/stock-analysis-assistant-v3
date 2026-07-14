"""Build governed, decision-free research features from the fact warehouse.

This job has no data-source client.  It reads verified fact partitions through
``ResearchQuery`` at one explicit cutoff, normalizes the stored fact contracts
for the three deterministic formula modules, and gives every feature set its
own atomic commit boundary.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from stock_analyzer.analysis.hotspot_features import (
    HOTSPOT_FORMULA_VERSION,
    compute_hotspot_features,
)
from stock_analyzer.analysis.market_context_features import (
    MARKET_CONTEXT_FORMULA_VERSION,
    compute_market_context_features,
)
from stock_analyzer.analysis.stock_context_features import (
    STOCK_CONTEXT_FORMULA_VERSION,
    compute_stock_context_features,
)
from stock_analyzer.data.research_contracts import ResearchDatasetId
from stock_analyzer.storage.research_derived import DerivedFeatureStore
from stock_analyzer.storage.research_query import ResearchQuery
from stock_analyzer.storage.research_warehouse import ResearchWarehouse


_SHANGHAI = ZoneInfo("Asia/Shanghai")
_BENCHMARK_CODE = "000300.SH"
_PRICE_WINDOW = 82
_CONTEXT_WINDOW = 250


@dataclass(frozen=True)
class DerivedFeatureSummary:
    analysis_date: date
    as_of: datetime
    market_rows: int
    sector_rows: int
    stock_rows: int
    committed_feature_sets: tuple[str, ...]
    skipped_feature_sets: tuple[str, ...]
    failed_feature_sets: tuple[str, ...]
    limitations: tuple[str, ...]
    errors: tuple[str, ...]
    plain_language_summary: str


def run_research_features(
    warehouse: ResearchWarehouse,
    analysis_date: date | str,
    as_of: datetime | None = None,
) -> DerivedFeatureSummary:
    """Compute and independently commit the three daily derived products."""

    analysis_day = _as_date(analysis_date)
    cutoff = _cutoff(analysis_day, as_of)
    query = ResearchQuery(warehouse)
    store = DerivedFeatureStore(Path(warehouse.root))

    calendar_partitions = _calendar_partitions(warehouse, analysis_day)
    calendar = query.dataset_partitions_as_of(
        ResearchDatasetId.TRADE_CALENDAR,
        calendar_partitions,
        cutoff,
    )
    sessions = _open_sessions(calendar, analysis_day)
    if analysis_day not in sessions:
        raise ValueError(
            f"analysis date is not an open session in the fact calendar: "
            f"{analysis_day.isoformat()}"
        )
    price_dates = tuple(value.isoformat() for value in sessions[-_PRICE_WINDOW:])
    context_dates = tuple(value.isoformat() for value in sessions[-_CONTEXT_WINDOW:])
    recent_limit_dates = tuple(value.isoformat() for value in sessions[-5:])
    five_year_start = (pd.Timestamp(analysis_day) - pd.DateOffset(years=5)).date()
    valuation_dates = tuple(
        value.isoformat() for value in sessions if value >= five_year_start
    )

    cache: dict[tuple[ResearchDatasetId, tuple[str, ...]], pd.DataFrame] = {}

    def read(
        dataset: ResearchDatasetId,
        partitions: Iterable[str],
    ) -> pd.DataFrame:
        key = (dataset, tuple(str(value) for value in partitions))
        if key not in cache:
            cache[key] = query.dataset_partitions_as_of(
                dataset,
                key[1],
                cutoff,
            )
        return cache[key].copy()

    partition_cache: dict[ResearchDatasetId, tuple[str, ...]] = {}

    def partitions(dataset: ResearchDatasetId) -> tuple[str, ...]:
        if dataset not in partition_cache:
            partition_cache[dataset] = _required_partitions(warehouse, dataset)
        return partition_cache[dataset]
    minute_partitions = _optional_date_partitions(
        warehouse,
        ResearchDatasetId.MINUTE_BAR,
        (analysis_day.isoformat(),),
    )

    committed: list[str] = []
    skipped: list[str] = []
    failed: list[str] = []
    errors: list[str] = []
    limitations: list[str] = []
    row_counts = {
        "market_context": 0,
        "sector_hotspot": 0,
        "stock_trading_context": 0,
    }

    def execute(
        *,
        feature_set: str,
        formula_version: str,
        entity_key: str | tuple[str, ...],
        input_partitions: Callable[
            [], Mapping[ResearchDatasetId, Iterable[str]]
        ],
        calculate: Callable[[], pd.DataFrame],
    ) -> None:
        try:
            fact_snapshot = query.input_manifest(
                input_partitions(),
                as_of=cutoff,
            )
            previous = _unchanged_partition(
                store,
                feature_set=feature_set,
                analysis_date=analysis_day,
                formula_version=formula_version,
                fact_manifest_hash=str(fact_snapshot["input_manifest_hash"]),
            )
            if previous is not None:
                row_counts[feature_set] = previous[0]
                skipped.append(feature_set)
                limitations.extend(previous[1])
                return
            frame = calculate()
            row_counts[feature_set] = len(frame)
            quality_status, feature_limitations = _partition_quality(
                feature_set, frame, minute_available=bool(minute_partitions)
            )
            feature_summary = _feature_summary(
                feature_set,
                analysis_day,
                len(frame),
                quality_status,
                feature_limitations,
            )
            governed_manifest = {
                "fact_snapshot": fact_snapshot,
                "plain_language_summary": feature_summary,
            }
            result = store.commit(
                feature_set,
                analysis_day,
                formula_version,
                frame,
                input_manifest=governed_manifest,
                entity_key=entity_key,
                quality_status=quality_status,
                limitations=feature_limitations,
                run_id=_run_id(
                    feature_set,
                    analysis_day,
                    formula_version,
                    str(fact_snapshot["input_manifest_hash"]),
                ),
            )
            if result.skipped:
                skipped.append(feature_set)
            else:
                committed.append(feature_set)
            limitations.extend(feature_limitations)
        except Exception as exc:  # each feature set has an independent boundary
            failed.append(feature_set)
            errors.append(f"{feature_set}: {exc}")

    calendar_input = {ResearchDatasetId.TRADE_CALENDAR: calendar_partitions}

    def market_inputs() -> dict[ResearchDatasetId, Iterable[str]]:
        return {
            **calendar_input,
            ResearchDatasetId.SECURITY_MASTER: partitions(
                ResearchDatasetId.SECURITY_MASTER
            ),
            ResearchDatasetId.EQUITY_DAILY: price_dates,
            ResearchDatasetId.INDEX_DAILY: context_dates,
            ResearchDatasetId.STOCK_LIMIT: (analysis_day.isoformat(),),
        }

    def calculate_market() -> pd.DataFrame:
        equity = read(ResearchDatasetId.EQUITY_DAILY, price_dates)
        indexes = read(ResearchDatasetId.INDEX_DAILY, context_dates)
        limits = read(
            ResearchDatasetId.STOCK_LIMIT, (analysis_day.isoformat(),)
        )
        securities = read(
            ResearchDatasetId.SECURITY_MASTER,
            partitions(ResearchDatasetId.SECURITY_MASTER),
        )
        return compute_market_context_features(
            equity,
            indexes,
            limits,
            analysis_date=analysis_day,
            expected_current_rows=_expected_current_rows(securities, analysis_day),
        )

    execute(
        feature_set="market_context",
        formula_version=MARKET_CONTEXT_FORMULA_VERSION,
        entity_key="analysis_date",
        input_partitions=market_inputs,
        calculate=calculate_market,
    )

    def sector_inputs() -> dict[ResearchDatasetId, Iterable[str]]:
        inputs: dict[ResearchDatasetId, Iterable[str]] = {
            **calendar_input,
            ResearchDatasetId.EQUITY_DAILY: price_dates,
            ResearchDatasetId.INDEX_DAILY: price_dates,
            ResearchDatasetId.STOCK_LIMIT: (analysis_day.isoformat(),),
            ResearchDatasetId.INDUSTRY_CATALOG: partitions(
                ResearchDatasetId.INDUSTRY_CATALOG
            ),
            ResearchDatasetId.INDUSTRY_MEMBER: partitions(
                ResearchDatasetId.INDUSTRY_MEMBER
            ),
            ResearchDatasetId.INDUSTRY_DAILY: price_dates,
            ResearchDatasetId.THEME_CATALOG: partitions(
                ResearchDatasetId.THEME_CATALOG
            ),
            ResearchDatasetId.THEME_MEMBER: partitions(
                ResearchDatasetId.THEME_MEMBER
            ),
            ResearchDatasetId.THEME_DAILY: price_dates,
        }
        if minute_partitions:
            inputs[ResearchDatasetId.MINUTE_BAR] = minute_partitions
        return inputs

    def calculate_sector() -> pd.DataFrame:
        equity = read(ResearchDatasetId.EQUITY_DAILY, price_dates)
        indexes = read(ResearchDatasetId.INDEX_DAILY, price_dates)
        benchmark = _benchmark(indexes)
        limits = read(
            ResearchDatasetId.STOCK_LIMIT, (analysis_day.isoformat(),)
        )
        industry_catalog = read(
            ResearchDatasetId.INDUSTRY_CATALOG,
            partitions(ResearchDatasetId.INDUSTRY_CATALOG),
        )
        theme_catalog = read(
            ResearchDatasetId.THEME_CATALOG,
            partitions(ResearchDatasetId.THEME_CATALOG),
        )
        industry_members = read(
            ResearchDatasetId.INDUSTRY_MEMBER,
            partitions(ResearchDatasetId.INDUSTRY_MEMBER),
        )
        theme_members = read(
            ResearchDatasetId.THEME_MEMBER,
            partitions(ResearchDatasetId.THEME_MEMBER),
        )
        industry_daily = read(ResearchDatasetId.INDUSTRY_DAILY, price_dates)
        theme_daily = read(ResearchDatasetId.THEME_DAILY, price_dates)
        minutes = (
            read(ResearchDatasetId.MINUTE_BAR, minute_partitions)
            if minute_partitions
            else _empty_minutes()
        )
        return compute_hotspot_features(
            equity,
            _sector_catalog(industry_catalog, theme_catalog, analysis_day),
            _sector_memberships(industry_members, theme_members, analysis_day),
            benchmark,
            limits,
            _official_sector_daily(industry_daily, theme_daily),
            _minute_bars(minutes),
            analysis_date=analysis_day,
        )

    execute(
        feature_set="sector_hotspot",
        formula_version=HOTSPOT_FORMULA_VERSION,
        entity_key=("analysis_date", "group_type", "group_code"),
        input_partitions=sector_inputs,
        calculate=calculate_sector,
    )

    def stock_inputs() -> dict[ResearchDatasetId, Iterable[str]]:
        return {
            **calendar_input,
            ResearchDatasetId.EQUITY_DAILY: price_dates,
            ResearchDatasetId.INDEX_DAILY: context_dates,
            ResearchDatasetId.STOCK_LIMIT: recent_limit_dates,
            ResearchDatasetId.DAILY_BASIC: valuation_dates,
        }

    def calculate_stock() -> pd.DataFrame:
        equity = read(ResearchDatasetId.EQUITY_DAILY, price_dates)
        indexes = read(ResearchDatasetId.INDEX_DAILY, context_dates)
        limits = read(ResearchDatasetId.STOCK_LIMIT, recent_limit_dates)
        valuations = read(ResearchDatasetId.DAILY_BASIC, valuation_dates)
        return compute_stock_context_features(
            equity,
            _benchmark(indexes),
            limits,
            valuations,
            analysis_date=analysis_day,
        )

    execute(
        feature_set="stock_trading_context",
        formula_version=STOCK_CONTEXT_FORMULA_VERSION,
        entity_key=("analysis_date", "ts_code"),
        input_partitions=stock_inputs,
        calculate=calculate_stock,
    )

    unique_limitations = tuple(dict.fromkeys(limitations))
    plain = _job_summary(
        analysis_day,
        row_counts,
        committed,
        skipped,
        failed,
        errors,
        unique_limitations,
    )
    return DerivedFeatureSummary(
        analysis_date=analysis_day,
        as_of=cutoff,
        market_rows=row_counts["market_context"],
        sector_rows=row_counts["sector_hotspot"],
        stock_rows=row_counts["stock_trading_context"],
        committed_feature_sets=tuple(committed),
        skipped_feature_sets=tuple(skipped),
        failed_feature_sets=tuple(failed),
        limitations=unique_limitations,
        errors=tuple(errors),
        plain_language_summary=plain,
    )


def _unchanged_partition(
    store: DerivedFeatureStore,
    *,
    feature_set: str,
    analysis_date: date,
    formula_version: str,
    fact_manifest_hash: str,
) -> tuple[int, tuple[str, ...]] | None:
    manifest = store.partition_manifest(
        feature_set,
        analysis_date=analysis_date,
        formula_version=formula_version,
    )
    if manifest.empty:
        return None
    if len(manifest) != 1:
        raise ValueError(
            f"derived partition metadata is not unique for {feature_set}"
        )
    row = manifest.iloc[0]
    raw_input = row["input_manifest_json"]
    stored_input = json.loads(raw_input) if isinstance(raw_input, str) else raw_input
    if not isinstance(stored_input, Mapping):
        raise ValueError(f"invalid stored input manifest for {feature_set}")
    fact_snapshot = stored_input.get("fact_snapshot")
    if not isinstance(fact_snapshot, Mapping):
        return None
    if str(fact_snapshot.get("input_manifest_hash")) != fact_manifest_hash:
        return None
    raw_limitations = row["limitations_json"]
    stored_limitations = (
        json.loads(raw_limitations)
        if isinstance(raw_limitations, str)
        else raw_limitations
    )
    return int(row["row_count"]), tuple(
        str(value) for value in (stored_limitations or ())
    )


def _calendar_partitions(
    warehouse: ResearchWarehouse,
    analysis_date: date,
) -> tuple[str, ...]:
    available = _required_partitions(warehouse, ResearchDatasetId.TRADE_CALENDAR)
    selected = tuple(
        value
        for value in available
        if value.isdigit() and int(value) <= analysis_date.year
    )
    if not selected:
        raise ValueError("fact trading calendar has no usable partition")
    return selected


def _required_partitions(
    warehouse: ResearchWarehouse,
    dataset: ResearchDatasetId,
) -> tuple[str, ...]:
    manifest = warehouse.partition_manifest(dataset)
    if manifest.empty or "partition_value" not in manifest:
        raise ValueError(f"required fact dataset has no partition: {dataset.value}")
    values = tuple(sorted(manifest["partition_value"].astype(str).unique()))
    if not values:
        raise ValueError(f"required fact dataset has no partition: {dataset.value}")
    return values


def _optional_date_partitions(
    warehouse: ResearchWarehouse,
    dataset: ResearchDatasetId,
    requested: Iterable[str],
) -> tuple[str, ...]:
    manifest = warehouse.partition_manifest(dataset)
    if manifest.empty or "partition_value" not in manifest:
        return ()
    available = set(manifest["partition_value"].astype(str))
    return tuple(value for value in requested if value in available)


def _open_sessions(calendar: pd.DataFrame, through: date) -> list[date]:
    required = {"cal_date", "is_open"}
    missing = sorted(required - set(calendar.columns))
    if missing:
        raise ValueError(f"trade calendar lacks required fields: {', '.join(missing)}")
    prepared = calendar.copy()
    prepared["cal_date"] = pd.to_datetime(
        prepared["cal_date"], errors="raise"
    ).dt.date
    is_open = prepared["is_open"].map(_truthy)
    return sorted(
        set(prepared.loc[is_open & (prepared["cal_date"] <= through), "cal_date"])
    )


def _expected_current_rows(securities: pd.DataFrame, analysis_date: date) -> int:
    required = {"ts_code", "valid_from", "valid_to"}
    missing = sorted(required - set(securities.columns))
    if missing:
        raise ValueError(f"security master lacks required fields: {', '.join(missing)}")
    frame = securities.copy()
    boundary = pd.Timestamp(analysis_date)
    valid_from = pd.to_datetime(frame["valid_from"], errors="raise")
    valid_to = pd.to_datetime(frame["valid_to"], errors="coerce")
    active = (valid_from <= boundary) & (
        valid_to.isna() | (valid_to >= boundary)
    )
    if "list_status" in frame:
        active &= frame["list_status"].astype(str).isin(("L", "P"))
    count = int(frame.loc[active, "ts_code"].astype(str).nunique())
    if count <= 0:
        raise ValueError("security master has no active securities for analysis date")
    return count


def _benchmark(indexes: pd.DataFrame) -> pd.DataFrame:
    required = {"trade_date", "index_code", "close"}
    missing = sorted(required - set(indexes.columns))
    if missing:
        raise ValueError(f"index daily lacks required fields: {', '.join(missing)}")
    return (
        indexes[indexes["index_code"].astype(str) == _BENCHMARK_CODE][
            ["trade_date", "close"]
        ]
        .sort_values("trade_date")
        .reset_index(drop=True)
    )


def _sector_catalog(
    industries: pd.DataFrame,
    themes: pd.DataFrame,
    analysis_date: date,
) -> pd.DataFrame:
    industry_required = {
        "industry_code",
        "industry_name",
        "level",
        "is_published",
        "valid_from",
        "valid_to",
    }
    theme_required = {
        "theme_code",
        "theme_name",
        "valid_from",
        "valid_to",
    }
    _require_columns(industries, industry_required, "industry catalog")
    _require_columns(themes, theme_required, "theme catalog")
    current_industries = _effective_rows(industries, analysis_date)
    current_industries = current_industries[
        current_industries["is_published"].map(_truthy)
    ]
    industry_rows = pd.DataFrame(
        {
            "group_type": "industry",
            "group_code": current_industries["industry_code"].astype(str),
            "group_name": current_industries["industry_name"].astype(str),
            "level": current_industries["level"].astype(str),
            "official_index_code": current_industries.apply(
                lambda row: (
                    str(row["industry_code"])
                    if str(row["level"]) == "L1"
                    else None
                ),
                axis=1,
            ),
        }
    )
    current_themes = _effective_rows(themes, analysis_date)
    theme_rows = pd.DataFrame(
        {
            "group_type": "theme",
            "group_code": current_themes["theme_code"].astype(str),
            "group_name": current_themes["theme_name"].astype(str),
            "level": "theme",
            "official_index_code": current_themes["theme_code"].astype(str),
        }
    )
    result = pd.concat((industry_rows, theme_rows), ignore_index=True)
    if result.duplicated(["group_type", "group_code"]).any():
        raise ValueError("duplicate active sector catalog entity")
    return result.sort_values(["group_type", "level", "group_code"]).reset_index(
        drop=True
    )


def _sector_memberships(
    industries: pd.DataFrame,
    themes: pd.DataFrame,
    analysis_date: date,
) -> pd.DataFrame:
    _require_columns(
        industries,
        {"industry_code", "ts_code", "valid_from", "valid_to"},
        "industry membership",
    )
    _require_columns(
        themes,
        {"theme_code", "ts_code", "valid_from", "valid_to"},
        "theme membership",
    )
    industry = industries.copy()
    industry = industry[
        pd.to_datetime(industry["valid_from"], errors="raise")
        <= pd.Timestamp(analysis_date)
    ]
    industry_rows = pd.DataFrame(
        {
            "group_type": "industry",
            "group_code": industry["industry_code"].astype(str),
            "ts_code": industry["ts_code"].astype(str),
            "valid_from": industry["valid_from"],
            "valid_to": industry["valid_to"],
        }
    )
    theme = themes.copy()
    theme = theme[
        pd.to_datetime(theme["valid_from"], errors="raise")
        <= pd.Timestamp(analysis_date)
    ]
    theme_rows = pd.DataFrame(
        {
            "group_type": "theme",
            "group_code": theme["theme_code"].astype(str),
            "ts_code": theme["ts_code"].astype(str),
            "valid_from": theme["valid_from"],
            "valid_to": theme["valid_to"],
        }
    )
    return pd.concat((industry_rows, theme_rows), ignore_index=True)


def _official_sector_daily(
    industries: pd.DataFrame,
    themes: pd.DataFrame,
) -> pd.DataFrame:
    _require_columns(industries, {"trade_date", "industry_code", "close"}, "industry daily")
    _require_columns(themes, {"trade_date", "theme_code", "close"}, "theme daily")
    industry = industries.rename(columns={"industry_code": "index_code"})[
        ["trade_date", "index_code", "close"]
    ]
    theme = themes.rename(columns={"theme_code": "index_code"})[
        ["trade_date", "index_code", "close"]
    ]
    result = pd.concat((industry, theme), ignore_index=True)
    if result.duplicated(["trade_date", "index_code"]).any():
        raise ValueError("duplicate official sector daily entity")
    return result


def _minute_bars(minutes: pd.DataFrame) -> pd.DataFrame:
    if minutes.empty:
        return _empty_minutes()
    code_field = "instrument_code" if "instrument_code" in minutes else "ts_code"
    _require_columns(
        minutes,
        {"trade_date", code_field, "minute", "close", "amount"},
        "minute bar",
    )
    frame = minutes.copy()
    if "frequency" in frame:
        frame = frame[frame["frequency"].astype(str) == "1min"]
    return frame.rename(columns={code_field: "ts_code"})[
        ["trade_date", "ts_code", "minute", "close", "amount"]
    ].reset_index(drop=True)


def _empty_minutes() -> pd.DataFrame:
    return pd.DataFrame(
        columns=["trade_date", "ts_code", "minute", "close", "amount"]
    )


def _effective_rows(frame: pd.DataFrame, analysis_date: date) -> pd.DataFrame:
    boundary = pd.Timestamp(analysis_date)
    valid_from = pd.to_datetime(frame["valid_from"], errors="raise")
    valid_to = pd.to_datetime(frame["valid_to"], errors="coerce")
    return frame[
        (valid_from <= boundary)
        & (valid_to.isna() | (valid_to >= boundary))
    ].copy()


def _partition_quality(
    feature_set: str,
    frame: pd.DataFrame,
    *,
    minute_available: bool,
) -> tuple[str, tuple[str, ...]]:
    if frame.empty or "coverage_status" not in frame:
        return "limited", ("no derived observations were produced",)
    statuses = set(frame["coverage_status"].dropna().astype(str))
    limitations: list[str] = []
    if feature_set == "sector_hotspot" and not minute_available:
        limitations.append(
            "历史分钟事实当前不可用，盘中路径指标留空，日线热点证据仍正常复算"
        )
    if feature_set == "stock_trading_context":
        limitations.append(
            "日线事实不能识别交易者身份，成交现象不解释为机构买入或出货"
        )
    limited_count = int((frame["coverage_status"].astype(str) == "limited").sum())
    if limited_count:
        limitations.append(f"{limited_count} 行因核心输入不足仅保留可用观察")
    if statuses == {"complete"} and not limitations:
        return "complete", ()
    if statuses and statuses != {"limited"}:
        return "complete_with_declared_gaps", tuple(limitations)
    return "limited", tuple(limitations or ["all observations are limited"])


def _feature_summary(
    feature_set: str,
    analysis_date: date,
    rows: int,
    quality_status: str,
    limitations: tuple[str, ...],
) -> str:
    labels = {
        "market_context": "市场环境",
        "sector_hotspot": "行业和主题热点证据",
        "stock_trading_context": "个股交易背景",
    }
    status_text = {
        "complete": "核心观察完整",
        "complete_with_declared_gaps": "日线核心观察可用，缺少的能力已单独说明",
        "limited": "关键输入不足，只保留可用观察",
    }[quality_status]
    suffix = "" if not limitations else f"；已声明 {len(limitations)} 项数据边界"
    return (
        f"{analysis_date.isoformat()} {labels[feature_set]}已复算 {rows} 行，"
        f"{status_text}{suffix}。"
    )


def _job_summary(
    analysis_date: date,
    row_counts: Mapping[str, int],
    committed: list[str],
    skipped: list[str],
    failed: list[str],
    errors: list[str],
    limitations: tuple[str, ...],
) -> str:
    text = (
        f"{analysis_date.isoformat()} 已处理市场环境 {row_counts['market_context']} 行、"
        f"行业/主题 {row_counts['sector_hotspot']} 行、个股背景 "
        f"{row_counts['stock_trading_context']} 行；新落地 {len(committed)} 类，"
        f"输入未变跳过 {len(skipped)} 类。"
    )
    if limitations:
        text += f" 已明确声明 {len(limitations)} 项数据边界。"
    if failed:
        text += f" 失败 {len(failed)} 类：" + "；".join(errors) + "。"
    return text


def _run_id(
    feature_set: str,
    analysis_date: date,
    formula_version: str,
    input_manifest_hash: str,
) -> str:
    digest = hashlib.sha256(
        "|".join(
            (
                feature_set,
                analysis_date.isoformat(),
                formula_version,
                input_manifest_hash,
            )
        ).encode("utf-8")
    ).hexdigest()
    return f"derived:{feature_set}:{digest[:24]}"


def _cutoff(analysis_date: date, as_of: datetime | None) -> datetime:
    if as_of is None:
        return datetime.combine(
            analysis_date,
            time(23, 59, 59),
            tzinfo=_SHANGHAI,
        )
    if as_of.tzinfo is None:
        raise ValueError("as_of must include a timezone")
    return as_of.astimezone(_SHANGHAI)


def _as_date(value: date | str) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def _truthy(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "t", "y", "yes"}


def _require_columns(frame: pd.DataFrame, required: set[str], label: str) -> None:
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"{label} lacks required fields: {', '.join(missing)}")


__all__ = ["DerivedFeatureSummary", "run_research_features"]
