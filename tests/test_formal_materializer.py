from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from stock_analyzer.analysis.scoring import score_feature
from stock_analyzer.data.formal_contracts import FORMAL_CONTRACT_VERSION
from stock_analyzer.data.formal_materializer import (
    FormalMaterializationError,
    materialize_market_inputs,
    materialize_target_context,
    screen_formal_market,
)
from stock_analyzer.data.readiness import (
    JULY_10_OFFICIAL_SESSIONS,
    AcquisitionGroupId,
    AcquisitionPayload,
    FormalRunState,
    RouteKind,
)
from stock_analyzer.domain.models import ActionLabel, FocusState
from stock_analyzer.ops.formal_run import RunReceipt
from stock_analyzer.storage.repositories import InMemoryAnalysisRepository


TARGET = date(2026, 7, 10)
CUTOFF = datetime(2026, 7, 10, 16, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
CODES = tuple(f"6000{index:02d}.SH" for index in range(11))


def receipt() -> RunReceipt:
    return RunReceipt(
        run_id="formal-2026-07-10",
        target_date=TARGET,
        report_cutoff=CUTOFF,
        acquisition_contract_version=FORMAL_CONTRACT_VERSION,
        screening_version="strategy-v2-screen-v1",
        state=FormalRunState.READY_TO_SCREEN,
        group_version_ids={"calendar_universe": "calendar-v1", "market_decision": "market-v1"},
        input_set_id="input-set-1",
    )


def payload(group_id, records, *, coverage_codes=CODES, coverage_proven=True):
    return AcquisitionPayload(
        group_id=group_id,
        route_id=f"recorded.{group_id.value}.v1",
        route_kind=RouteKind.PRIMARY,
        trade_date=TARGET,
        fetched_at=CUTOFF,
        source_names=(f"recorded.{group_id.value}",),
        records=tuple(records),
        covered_dates=JULY_10_OFFICIAL_SESSIONS,
        coverage_codes=tuple(coverage_codes),
        coverage_proven=coverage_proven,
        field_coverage={},
        unit_metadata={"volume": "shares", "amount": "CNY"},
        adjustment_basis="unadjusted",
        contract_version=FORMAL_CONTRACT_VERSION,
    )


def screening_payloads():
    calendar_records = [
        {
            "record_type": "calendar",
            "trade_date": session,
            "is_open": True,
            "source_name": "recorded.calendar",
        }
        for session in JULY_10_OFFICIAL_SESSIONS
    ]
    calendar_records.extend(
        {
            "record_type": "security",
            "trade_date": TARGET,
            "ts_code": code,
            "name": f"股票{index}",
            "exchange": "SSE",
            "list_date": date(2020, 1, 1),
            "status_verified": True,
            "is_suspended": False,
            "hard_excluded": False,
            "source_name": "recorded.security",
        }
        for index, code in enumerate(CODES)
    )
    market_records = []
    for index, code in enumerate(CODES):
        growth = 1.0 + index * 0.001
        for offset, session in enumerate(JULY_10_OFFICIAL_SESSIONS):
            close = 10.0 * (growth**offset)
            market_records.append(
                {
                    "record_type": "equity_bar",
                    "trade_date": session,
                    "ts_code": code,
                    "open": close,
                    "high": close * 1.01,
                    "low": close * 0.99,
                    "close": close,
                    "volume": 1_000_000.0,
                    "amount": 100_000_000.0 + index * 1_000_000.0,
                    "source_name": "recorded.daily",
                }
            )
        market_records.append(
            {
                "record_type": "daily_basic",
                "trade_date": TARGET,
                "ts_code": code,
                "turnover_rate": 1.0 + index / 10,
                "total_mv": 10_000_000_000.0,
                "circ_mv": 8_000_000_000.0,
                "pe_ttm": 10.0,
                "pb": 1.0,
                "source_name": "recorded.daily_basic",
            }
        )
    return {
        AcquisitionGroupId.CALENDAR_UNIVERSE: payload(
            AcquisitionGroupId.CALENDAR_UNIVERSE,
            calendar_records,
        ),
        AcquisitionGroupId.MARKET_DECISION: payload(
            AcquisitionGroupId.MARKET_DECISION,
            market_records,
        ),
    }


def target_payloads(codes=(CODES[0], CODES[-1])):
    fundamentals = []
    board = []
    for code in codes:
        fundamentals.extend(
            [
                {
                    "record_type": "company_profile",
                    "trade_date": TARGET,
                    "ts_code": code,
                    "business_summary": "主营业务",
                    "source_name": "recorded.profile",
                },
                {
                    "record_type": "financial_summary",
                    "trade_date": TARGET,
                    "ts_code": code,
                    "period_end": date(2026, 3, 31),
                    "announcement_time": datetime(
                        2026, 4, 30, tzinfo=ZoneInfo("Asia/Shanghai")
                    ),
                    "revenue_yoy": 5.0,
                    "profit_yoy": 4.0,
                    "gross_margin": 30.0,
                    "operating_cashflow": 100.0,
                    "source_name": "recorded.financial",
                },
            ]
        )
        board.append(
            {
                "record_type": "industry_mapping",
                "trade_date": TARGET,
                "ts_code": code,
                "industry_code": "BK1",
                "industry_name": "银行",
                "source_name": "recorded.board",
            }
        )
    board.append(
        {
            "record_type": "board_bar",
            "trade_date": TARGET,
            "board_code": "BK1",
            "board_name": "银行",
            "open": 100.0,
            "high": 102.0,
            "low": 99.0,
            "close": 101.0,
            "volume": 1_000.0,
            "amount": 10_000.0,
            "source_name": "recorded.board_bar",
        }
    )
    return {
        AcquisitionGroupId.CANDIDATE_FUNDAMENTAL: payload(
            AcquisitionGroupId.CANDIDATE_FUNDAMENTAL,
            fundamentals,
            coverage_codes=codes,
        ),
        AcquisitionGroupId.BOARD_INDUSTRY: payload(
            AcquisitionGroupId.BOARD_INDUSTRY,
            board,
            coverage_codes=codes,
        ),
        AcquisitionGroupId.OFFICIAL_EVENTS_RISK: payload(
            AcquisitionGroupId.OFFICIAL_EVENTS_RISK,
            (),
            coverage_codes=codes,
        ),
        AcquisitionGroupId.MANUAL_HOLDINGS: payload(
            AcquisitionGroupId.MANUAL_HOLDINGS,
            (),
            coverage_codes=(),
        ),
    }


def test_materializer_builds_features_only_for_verified_universe_with_61_bars_and_current_basic():
    inputs = materialize_market_inputs(TARGET, screening_payloads())

    assert inputs.included_codes == CODES
    assert set(inputs.feature_profiles) == set(CODES)
    assert len(inputs.bundle.daily_bars) == len(CODES) * 82
    assert len(inputs.bundle.daily_basic) == len(CODES)
    assert all(item.data_quality == "ok" for item in inputs.feature_profiles.values())


def test_materializer_rejects_payload_code_or_date_outside_frozen_contract():
    payloads = screening_payloads()
    market = payloads[AcquisitionGroupId.MARKET_DECISION]
    foreign = dict(market.records[0], ts_code="000001.SZ")
    payloads[AcquisitionGroupId.MARKET_DECISION] = market.model_copy(
        update={"records": (foreign, *market.records[1:])}
    )

    with pytest.raises(FormalMaterializationError, match="outside verified universe"):
        materialize_market_inputs(TARGET, payloads)

    targets = target_payloads()
    fundamental = targets[AcquisitionGroupId.CANDIDATE_FUNDAMENTAL]
    future = dict(fundamental.records[0], trade_date=date(2026, 7, 11))
    targets[AcquisitionGroupId.CANDIDATE_FUNDAMENTAL] = fundamental.model_copy(
        update={"records": (future, *fundamental.records[1:])}
    )
    with pytest.raises(FormalMaterializationError, match="outside frozen target"):
        materialize_target_context(TARGET, (CODES[0], CODES[-1]), targets)


def test_target_context_requires_every_frozen_candidate_and_active_focus_code():
    complete = materialize_target_context(
        TARGET,
        (CODES[0], CODES[-1]),
        target_payloads(),
    )
    assert set(complete.company_profiles) == {CODES[0], CODES[-1]}
    assert set(complete.fundamental_summaries) == {CODES[0], CODES[-1]}

    incomplete = target_payloads()
    fundamental = incomplete[AcquisitionGroupId.CANDIDATE_FUNDAMENTAL]
    incomplete[AcquisitionGroupId.CANDIDATE_FUNDAMENTAL] = fundamental.model_copy(
        update={
            "records": tuple(
                row
                for row in fundamental.records
                if not (row["record_type"] == "financial_summary" and row["ts_code"] == CODES[-1])
            )
        }
    )
    with pytest.raises(FormalMaterializationError, match=CODES[-1].replace(".", "\\.")):
        materialize_target_context(TARGET, (CODES[0], CODES[-1]), incomplete)


def test_screening_uses_score_feature_only_and_never_calls_final_strategy_builder(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("final strategy builder is unreachable during screening")

    monkeypatch.setattr(
        "stock_analyzer.analysis.strategy_v2.generate_strategy_v2_recommendations",
        forbidden,
    )
    result = screen_formal_market(
        receipt(),
        screening_payloads(),
        InMemoryAnalysisRepository(),
    )
    inputs = materialize_market_inputs(TARGET, screening_payloads())
    expected = tuple(
        feature.ts_code
        for feature in sorted(
            inputs.feature_profiles.values(),
            key=lambda item: (-score_feature(item), item.ts_code),
        )[:10]
    )

    assert result.ordered_codes == expected


def test_screening_freezes_top_ten_plus_active_focus_without_replacement():
    lowest_ranked = CODES[0]
    repository = InMemoryAnalysisRepository(
        focus_states=[
            FocusState(
                trade_date=date(2026, 7, 9),
                ts_code=lowest_ranked,
                state=ActionLabel.CONTINUE_OBSERVATION,
            )
        ]
    )

    result = screen_formal_market(receipt(), screening_payloads(), repository)

    assert len(result.ordered_codes) == 10
    assert lowest_ranked not in result.ordered_codes
    assert result.active_focus_codes == (lowest_ranked,)
