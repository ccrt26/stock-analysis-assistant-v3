from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from stock_analyzer.evaluation.v3_forward.inputs import FormationInputs
from stock_analyzer.evaluation.v3_forward.ledger import ForwardLedger, sha256_file
from stock_analyzer.evaluation.v3_forward.reports import render_formation_report
from stock_analyzer.evaluation.v3_forward.__main__ import build_parser
from stock_analyzer.evaluation.v3_forward.service import (
    form_observation,
    update_observations,
)


FORMATION_DATE = date(2026, 7, 17)
ENTRY_DATE = date(2026, 7, 20)
NOW = datetime(2026, 7, 19, 16, 0, tzinfo=ZoneInfo("Asia/Shanghai"))


def _candidates() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "formation_date": [FORMATION_DATE, FORMATION_DATE],
            "formation_item_id": [
                "v3-forward-baseline-01|2026-07-17|A",
                "v3-forward-baseline-01|2026-07-17|B",
            ],
            "ts_code": ["A", "B"],
            "stock_name": ["甲公司", "乙公司"],
            "user_layer": ["关注", "关注"],
            "hard_invalid": [False, False],
            "routes": ["hotspot|price", "price"],
            "hotspot_group_name": ["测试热点", None],
            "return_5d": [0.02, -0.01],
            "relative_return_20d": [0.03, 0.02],
            "current_amount_ratio_20d": [1.2, 1.1],
            "confirm_return_5d_positive": [True, False],
            "confirm_relative_return_20d_positive": [True, True],
            "confirm_amount_ratio_20d": [True, True],
            "action_confirmed": [True, False],
            "market_breadth_20d": [0.55, 0.55],
            "tr_yoy": [10.0, None],
            "netprofit_yoy": [12.0, None],
            "dt_netprofit_yoy": [11.0, None],
            "n_cashflow_act": [100.0, None],
            "price_location_60d": [0.8, 0.7],
            "risk_notes": ["市场仍有不确定性", "价格尚未启动"],
            "entry_state": ["waiting", "waiting"],
        }
    )


def _inputs() -> FormationInputs:
    return FormationInputs(
        formation_date=FORMATION_DATE,
        cutoff=datetime(2026, 7, 17, 23, 59, 59, tzinfo=ZoneInfo("Asia/Shanghai")),
        market=pd.DataFrame({"analysis_date": [FORMATION_DATE]}),
        stocks=pd.DataFrame(),
        hotspots=pd.DataFrame(),
        memberships=pd.DataFrame(),
        company_facts=pd.DataFrame(),
        names={"A": "甲公司", "B": "乙公司"},
        health_report={"data_date": "2026-07-17", "complete_core_date": True},
        input_manifest={"health_report": {"sha256": "h"}, "facts": {"input_manifest_hash": "f"}},
        sector_catalogs=pd.DataFrame(),
        company_profiles=pd.DataFrame(),
        announcements=pd.DataFrame(),
    )


def _write_partition(root: Path, table: str, trading_date: date, frame: pd.DataFrame):
    path = root / "facts" / table / f"trade_date={trading_date.isoformat()}" / "data.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(path, index=False)


def _market_partition(trading_date: date, *, include_a: bool = True):
    codes = ["A"] if include_a else []
    return pd.DataFrame(
        {
            "trade_date": [trading_date] * len(codes),
            "ts_code": codes,
            "open": [10.0] * len(codes),
            "high": [10.5] * len(codes),
            "low": [9.8] * len(codes),
            "close": [10.2] * len(codes),
        }
    )


def test_form_records_honest_times_hashes_waiting_and_is_idempotent(
    tmp_path: Path, monkeypatch
):
    monkeypatch.setattr(
        "stock_analyzer.evaluation.v3_forward.service.load_formation_inputs",
        lambda *_args, **_kwargs: _inputs(),
    )
    monkeypatch.setattr(
        "stock_analyzer.evaluation.v3_forward.service.form_attention_list",
        lambda _inputs: _candidates(),
    )
    output = tmp_path / "forward"

    first = form_observation(
        warehouse_root=tmp_path / "warehouse",
        archive_root=tmp_path / "archive",
        output_root=output,
        formation_date=FORMATION_DATE,
        now=NOW,
        enforce_real_root=False,
    )
    before = {
        path.name: sha256_file(path) for path in first.bundle.path.iterdir() if path.is_file()
    }
    second = form_observation(
        warehouse_root=tmp_path / "warehouse",
        archive_root=tmp_path / "archive",
        output_root=output,
        formation_date=FORMATION_DATE,
        now=NOW.replace(hour=17),
        enforce_real_root=False,
    )

    payload = json.loads((first.bundle.path / "formation.json").read_text(encoding="utf-8"))
    assert payload["formation_date"] == "2026-07-17"
    assert payload["data_cutoff_at"] == "2026-07-17T23:59:59+08:00"
    assert payload["generated_at"] == "2026-07-19T16:00:00+08:00"
    assert payload["attention_count"] == 2
    assert payload["action_count"] == 1
    assert len(payload["rule_manifest_hash"]) == 64
    assert len(payload["input_manifest_hash"]) == 64
    assert second.bundle.idempotent is True
    assert {
        path.name: sha256_file(path) for path in first.bundle.path.iterdir() if path.is_file()
    } == before
    projected = output / "reports" / "formation_date=2026-07-17" / "formation.md"
    assert projected.read_bytes() == (first.bundle.path / "report.md").read_bytes()
    audit_path = output / "manifests" / "formation_date=2026-07-17" / "audit.json"
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    assert audit["status"] == "passed"
    assert audit["candidate_rows"] == 2
    assert audit["duplicate_stock_dates"] == 0
    assert audit["future_fields"] == []
    assert (
        output / "logs" / "formation_date=2026-07-17" / "formation-run.json"
    ).is_file()


def test_update_without_later_market_session_keeps_waiting(tmp_path: Path):
    ledger = ForwardLedger(tmp_path / "forward", enforce_real_root=False)
    payload = {
        "formation_date": FORMATION_DATE.isoformat(),
        "rule_version": "v3-forward-baseline-01",
        "generated_at": NOW.isoformat(),
    }
    ledger.write_formation_bundle(payload, _candidates(), "形成报告")
    _write_partition(tmp_path / "warehouse", "equity_daily", FORMATION_DATE, _market_partition(FORMATION_DATE))

    result = update_observations(
        warehouse_root=tmp_path / "warehouse",
        output_root=tmp_path / "forward",
        as_of_date=date(2026, 7, 19),
        now=NOW,
        enforce_real_root=False,
    )

    assert result.waiting_formations == (FORMATION_DATE,)
    assert not list((tmp_path / "forward" / "entries").rglob("entries.parquet"))


def test_update_uses_first_market_session_and_only_confirmed_items(tmp_path: Path):
    ledger = ForwardLedger(tmp_path / "forward", enforce_real_root=False)
    payload = {
        "formation_date": FORMATION_DATE.isoformat(),
        "rule_version": "v3-forward-baseline-01",
        "generated_at": NOW.isoformat(),
    }
    ledger.write_formation_bundle(payload, _candidates(), "形成报告")
    warehouse = tmp_path / "warehouse"
    _write_partition(warehouse, "equity_daily", FORMATION_DATE, _market_partition(FORMATION_DATE))
    _write_partition(warehouse, "adj_factor", FORMATION_DATE, pd.DataFrame({"trade_date": [FORMATION_DATE], "ts_code": ["A"], "adj_factor": [1.0]}))
    _write_partition(warehouse, "equity_daily", ENTRY_DATE, _market_partition(ENTRY_DATE))
    _write_partition(warehouse, "adj_factor", ENTRY_DATE, pd.DataFrame({"trade_date": [ENTRY_DATE], "ts_code": ["A"], "adj_factor": [1.0]}))
    _write_partition(warehouse, "stock_limit", ENTRY_DATE, pd.DataFrame({"trade_date": [ENTRY_DATE], "ts_code": ["A"], "up_limit": [11.0]}))

    result = update_observations(
        warehouse_root=warehouse,
        output_root=tmp_path / "forward",
        as_of_date=ENTRY_DATE,
        now=NOW,
        enforce_real_root=False,
    )

    entries = pd.read_parquet(result.entry_bundles[0].path / "entries.parquet")
    assert entries["ts_code"].tolist() == ["A"]
    assert pd.to_datetime(entries.iloc[0]["entry_date"]).date() == ENTRY_DATE
    assert entries.iloc[0]["entry_status"] == "executable_entry"
    assert bool(entries.iloc[0]["executable_entry"]) is True
    assert entries.iloc[0]["action_price"] == 10.0

    rerun = update_observations(
        warehouse_root=warehouse,
        output_root=tmp_path / "forward",
        as_of_date=ENTRY_DATE,
        now=NOW.replace(hour=18),
        enforce_real_root=False,
    )
    assert rerun.entry_bundles[0].idempotent is True


def test_snapshot_is_written_only_when_exact_horizon_is_mature(tmp_path: Path):
    ledger = ForwardLedger(tmp_path / "forward", enforce_real_root=False)
    payload = {
        "formation_date": FORMATION_DATE.isoformat(),
        "rule_version": "v3-forward-baseline-01",
        "generated_at": NOW.isoformat(),
    }
    ledger.write_formation_bundle(payload, _candidates(), "形成报告")
    formation_hash = sha256_file(
        tmp_path
        / "forward"
        / "formations"
        / "formation_date=2026-07-17"
        / "formation.json"
    )
    warehouse = tmp_path / "warehouse"
    sessions = [date(2026, 7, 17), date(2026, 7, 20), date(2026, 7, 21), date(2026, 7, 22), date(2026, 7, 23), date(2026, 7, 24)]
    for position, session in enumerate(sessions):
        prices = _market_partition(session)
        prices.loc[:, "close"] = 10.0 + position * 0.6
        prices.loc[:, "high"] = 10.2 + position * 0.6
        prices.loc[:, "low"] = 9.8 + position * 0.5
        _write_partition(warehouse, "equity_daily", session, prices)
        _write_partition(
            warehouse,
            "adj_factor",
            session,
            pd.DataFrame({"trade_date": [session], "ts_code": ["A"], "adj_factor": [1.0]}),
        )
        _write_partition(
            warehouse,
            "stock_limit",
            session,
            pd.DataFrame({"trade_date": [session], "ts_code": ["A"], "up_limit": [20.0]}),
        )

    immature = update_observations(
        warehouse_root=warehouse,
        output_root=tmp_path / "forward",
        as_of_date=date(2026, 7, 23),
        now=NOW,
        enforce_real_root=False,
    )
    assert immature.snapshot_bundles == ()

    mature = update_observations(
        warehouse_root=warehouse,
        output_root=tmp_path / "forward",
        as_of_date=date(2026, 7, 24),
        now=NOW,
        enforce_real_root=False,
    )
    assert len(mature.snapshot_bundles) == 1
    snapshot = pd.read_parquet(mature.snapshot_bundles[0].path / "snapshots.parquet")
    assert snapshot.iloc[0]["horizon"] == 5
    assert snapshot.iloc[0]["observed_market_sessions"] == 5
    assert sha256_file(
        tmp_path
        / "forward"
        / "formations"
        / "formation_date=2026-07-17"
        / "formation.json"
    ) == formation_hash
    report = (mature.snapshot_bundles[0].path / "report.md").read_text(encoding="utf-8")
    assert "阶段快照" in report
    assert "不能作为 20/30 日最终验证" in report


def test_formation_report_distinguishes_attention_action_and_future():
    report = render_formation_report(
        {
            "formation_date": "2026-07-17",
            "data_cutoff_at": "2026-07-17T23:59:59+08:00",
            "generated_at": "2026-07-19T16:00:00+08:00",
            "rule_version": "v3-forward-baseline-01",
            "input_manifest_hash": "abc",
        },
        _candidates(),
    )

    assert "关注股票" in report
    assert "满足行动确认" in report
    assert "未来结果尚未到达" in report
    assert "不构成买卖建议" in report
    assert "市场仍有不确定性" in report


def test_manual_parser_exposes_only_forward_observation_commands():
    parser = build_parser()
    subparsers = next(
        action for action in parser._actions if getattr(action, "choices", None)
    )

    assert set(subparsers.choices) == {
        "form",
        "form-v2",
        "explain",
        "dossier",
        "update",
    }
