"""公司介绍 prepare/record 与展示绑定的行为测试。

全部使用临时事实仓与临时归档目录，不触碰用户事实仓与正式归档；
文章正文语义由真实写作验收覆盖，这里只测会造成错误公司、未来数据、
身份错配或 Web 不更新的程序合同。
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd
import pytest
from zoneinfo import ZoneInfo

from stock_analyzer.data.research_contracts import FactBatch, ResearchDatasetId
from stock_analyzer.ops import company_introduction as ci
from stock_analyzer.storage.research_warehouse import ResearchWarehouse


SH = ZoneInfo("Asia/Shanghai")
AS_OF = "2026-08-23T09:05:02+08:00"
AS_OF_DT = datetime(2026, 8, 23, 9, 5, 2, tzinfo=SH)
FORMATION = "2026-08-21"
ACTION = "2026-08-24"
CODE = "600583.SH"
OTHER = "600980.SH"


# ---------------------------------------------------------------------------
# 临时事实仓
# ---------------------------------------------------------------------------


def _at(year, month, day, hour=10, minute=0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)


def _batch(dataset, partition, records, available_at, run="run-1") -> FactBatch:
    rows = [
        {**record, "available_at": record.get("available_at", available_at)}
        for record in records
    ]
    return FactBatch(
        dataset_id=dataset,
        partition_value=partition,
        source_name="tushare",
        source_endpoint="test",
        ingestion_run_id=run,
        ingested_at=available_at,
        default_available_at=available_at,
        records=rows,
    )


def _build_warehouse(root: Path) -> None:
    warehouse = ResearchWarehouse(root)
    warehouse.commit_batch(_batch(
        ResearchDatasetId.SECURITY_MASTER, "sec-master-v1",
        [{
            "ts_code": CODE, "symbol": "600583", "name": "海油工程",
            "industry": "油服工程", "market": "主板", "exchange": "SSE",
            "list_date": "2004-04-15", "list_status": "L", "valid_from": "2020-01-01",
        }],
        _at(2026, 8, 1),
    ))
    warehouse.commit_batch(_batch(
        ResearchDatasetId.COMPANY_PROFILE, "company-profile",
        [{
            "ts_code": CODE, "com_name": "海洋石油工程股份有限公司",
            "introduction": "公司是中国海洋石油集团下属的油田工程服务公司。",
            "main_business": "海洋油气田工程设计、建造与安装",
            "profile_snapshot_date": "2026-06-30", "valid_from": "2026-06-30",
        }],
        _at(2026, 8, 1),
    ))
    warehouse.commit_batch(_batch(
        ResearchDatasetId.INCOME_STATEMENT, "2026-06-30",
        [{
            "ts_code": CODE, "report_period": "2026-06-30", "report_type": "2",
            "statement_type": "1", "end_type": "2", "comp_type": "4",
            "ann_date": "20260820", "f_ann_date": "20260820", "update_flag": 0,
            "revenue": 1.2e9, "total_revenue": 1.2e9, "total_cogs": 1.1e9,
            "total_profit": 1.1e8, "n_income": 1.05e8, "n_income_attr_p": 1.0e8,
        }],
        _at(2026, 8, 20, 16, 0),
    ))
    warehouse.commit_batch(_batch(
        ResearchDatasetId.INCOME_STATEMENT, "2025-06-30",
        [{
            "ts_code": CODE, "report_period": "2025-06-30", "report_type": "2",
            "statement_type": "1", "end_type": "2", "comp_type": "4",
            "ann_date": "20250820", "f_ann_date": "20250820", "update_flag": 0,
            "revenue": 1.0e9, "total_revenue": 1.0e9, "total_cogs": 9.2e8,
            "total_profit": 1.0e8, "n_income": 9.5e7, "n_income_attr_p": 9.0e7,
        }],
        _at(2025, 8, 20, 16, 0),
    ))
    warehouse.commit_batch(_batch(
        ResearchDatasetId.CASH_FLOW, "2026-06-30",
        [{
            "ts_code": CODE, "report_period": "2026-06-30", "report_type": "2",
            "statement_type": "1", "end_type": "2", "comp_type": "4",
            "ann_date": "20260820", "f_ann_date": "20260820", "update_flag": 0,
            "n_cashflow_act": 1.4e8, "c_inf_fr_operate_a": 1.3e9,
            "c_paid_goods_s": 9.0e8,
        }],
        _at(2026, 8, 20, 16, 0),
    ))
    warehouse.commit_batch(_batch(
        ResearchDatasetId.FINANCIAL_INDICATOR, "2026-06-30",
        [{
            "ts_code": CODE, "report_period": "2026-06-30", "report_type": "2",
            "ann_date": "20260820", "eps": 0.23, "dt_eps": 0.2,
            "gross_margin": 8.3, "netprofit_margin": 8.8, "roe": 3.9,
            "roe_dt": 3.2, "debt_to_assets": 40.1, "profit_dedt": 8.8e7,
        }],
        _at(2026, 8, 20, 16, 0),
    ))
    warehouse.commit_batch(_batch(
        ResearchDatasetId.MAIN_BUSINESS, "2026-06-30",
        [
            {"ts_code": CODE, "report_period": "2026-06-30", "classification": "product",
             "item_name": "工程设计", "bz_item": "工程设计", "bz_sales": 6.0e8,
             "bz_cost": 4.0e8, "bz_profit": 2.0e8, "curr_type": "CNY"},
            {"ts_code": CODE, "report_period": "2026-06-30", "classification": "product",
             "item_name": "工程建造", "bz_item": "工程建造", "bz_sales": 5.0e8,
             "bz_cost": 4.7e8, "bz_profit": 3.0e7, "curr_type": "CNY"},
            {"ts_code": CODE, "report_period": "2026-06-30", "classification": "region",
             "item_name": "境内", "bz_item": "境内", "bz_sales": 1.1e9,
             "bz_cost": 8.7e8, "bz_profit": 2.3e8, "curr_type": "CNY"},
        ],
        _at(2026, 8, 20, 16, 0),
    ))
    warehouse.commit_batch(_batch(
        ResearchDatasetId.DAILY_BASIC, "2026-08-21",
        [{
            "ts_code": CODE, "trade_date": "2026-08-21", "close": 6.12,
            "pe": 13.5, "pe_ttm": 13.0, "pb": 0.9, "total_mv": 2.7e10,
            "circ_mv": 2.2e10, "turnover_rate_f": 1.2,
        }],
        _at(2026, 8, 21, 9, 0),
    ))
    warehouse.commit_batch(_batch(
        ResearchDatasetId.ANNOUNCEMENT, "2026-08",
        [
            {"ts_code": CODE, "announcement_id": "ann-1",
             "announcement_time": "2026-08-20T16:00:00+08:00",
             "title": "2026年半年度报告", "url": "https://example.invalid/a.pdf",
             "available_at": _at(2026, 8, 20, 8, 0)},
            {"ts_code": CODE, "announcement_id": "ann-2",
             "announcement_time": "2026-08-23T10:30:00+08:00",
             "title": "行动日之后才可见的公告", "url": "https://example.invalid/b.pdf",
             "available_at": _at(2026, 8, 23, 2, 30)},
        ],
        _at(2026, 8, 20, 8, 0),
    ))


def _write_v4_trace(selection_dir: Path, *, extra=None, completed=True) -> None:
    trace = {
        "trace_version": "daily-research-trace-v4",
        "formation_date": FORMATION,
        "action_date": ACTION,
        "as_of": AS_OF,
        "market_search_context": "测试",
        "market_propagation_mode": "unclear",
        "market_risk_overlays": [],
        "candidate_ledger": [
            {
                "ts_code": CODE, "name": "海油工程", "final_fate": "selected",
                "primary_reason": "r",
                "research_thesis": {
                    "engine_type": "sector_leader_cluster",
                    "engine_status": "active",
                    "market_recognition": {"status": "confirmed"},
                },
            },
            {
                "ts_code": "600150.SH", "name": "中国船舶", "final_fate": "selected",
                "primary_reason": "r",
                "research_thesis": {
                    "engine_type": "fresh_event_pending",
                    "engine_status": "conditional",
                    "market_recognition": {"status": "pending"},
                },
            },
            *(
                extra
                or [
                    {
                        "ts_code": OTHER, "name": "北矿科技", "final_fate": "comparator",
                        "primary_reason": "r",
                        "research_thesis": {"engine_type": "anchor_only",
                                            "engine_status": "active",
                                            "market_recognition": {"status": "confirmed"}},
                    }
                ]
            ),
        ],
        "decision_trace": [],
        "research_result": {
            "research_completed": completed,
            "point_in_time_evidence_verified": completed,
            "failure_reason": "",
            "skills_used": ["orchestrating-stock-research", "interpreting-market-macro",
                            "researching-sectors-industries", "researching-company-events",
                            "analyzing-price-trading"],
            "selected_stocks": [{"ts_code": CODE, "name": "海油工程",
                                 "opportunity_type": "sector_diffusion",
                                 "selection_reason": "r", "strongest_counterevidence": "c",
                                 "nearest_comparison": "n", "priority": 1}],
            "nearest_nonselections": [],
            "empty_reason": "",
        },
    }
    selection_dir.mkdir(parents=True, exist_ok=True)
    (selection_dir / f"research-trace-{FORMATION}.json").write_text(
        json.dumps(trace, ensure_ascii=False), encoding="utf-8"
    )


@pytest.fixture
def project(tmp_path):
    """临时项目：事实仓 + selection 目录 + monitor 目录。"""

    warehouse_root = tmp_path / "local_warehouse"
    _build_warehouse(warehouse_root)
    selection = tmp_path / "local_archive" / "forward_selection"
    monitor = tmp_path / "local_archive" / "forward_monitor"
    monitor.mkdir(parents=True)
    _write_v4_trace(selection)
    return {
        "root": tmp_path,
        "warehouse_root": warehouse_root,
        "selection_dir": selection,
        "monitor_dir": monitor,
        "intro_root": tmp_path / "local_archive" / "company_introductions",
    }


def _prepare(project, **kwargs):
    return ci.prepare_formal_context(
        formation_date=FORMATION,
        action_date=kwargs.pop("action_date", ACTION),
        as_of=kwargs.pop("as_of", AS_OF),
        project_root=project["root"],
        warehouse_root=project["warehouse_root"],
        intro_root=project["intro_root"],
        **kwargs,
    )


# ---------------------------------------------------------------------------
# 正式范围与身份
# ---------------------------------------------------------------------------


def test_prepare_scope_keeps_only_confirmed_active(project):
    result = _prepare(project)
    scope = {item["ts_code"]: item["intro_status"] for item in result["scope"]}
    assert scope == {CODE: "missing"}
    classes = {item["ts_code"]: item["output_class"] for item in result["scope"]}
    assert classes == {CODE: "confirmed_active"}


def test_legacy_scope_requires_explicit_request(project, tmp_path):
    # 同一 trace 换成 V1：默认范围不含 legacy，明确要求时才纳入
    legacy_trace = {
        "trace_version": "daily-research-trace-v1",
        "formation_date": FORMATION, "action_date": ACTION, "as_of": AS_OF,
        "candidate_ledger": [{"ts_code": CODE, "name": "海油工程",
                              "final_fate": "selected"}],
        "research_result": {"research_completed": True,
                            "point_in_time_evidence_verified": True},
    }
    (project["selection_dir"] / f"research-trace-{FORMATION}.json").write_text(
        json.dumps(legacy_trace, ensure_ascii=False), encoding="utf-8")
    result = _prepare(project)
    assert result["scope"] == []
    result = ci.prepare_formal_context(
        formation_date=FORMATION, action_date=ACTION, as_of=AS_OF,
        include_legacy=True,
        project_root=project["root"], warehouse_root=project["warehouse_root"],
        intro_root=project["intro_root"],
    )
    assert [item["output_class"] for item in result["scope"]] == [
        "legacy_v1_not_rewritten"
    ]


def test_prepare_empty_formal_list_stays_empty(project, tmp_path):
    (project["selection_dir"] / f"research-trace-{FORMATION}.json").unlink()
    trace = {
        "trace_version": "daily-research-trace-v4", "formation_date": FORMATION,
        "action_date": ACTION, "as_of": AS_OF, "candidate_ledger": [],
        "decision_trace": [],
        "research_result": {"research_completed": True,
                            "point_in_time_evidence_verified": True,
                            "failure_reason": "", "skills_used": [], "selected_stocks": [],
                            "nearest_nonselections": [], "empty_reason": "无"},
    }
    (project["selection_dir"] / f"research-trace-{FORMATION}.json").write_text(
        json.dumps(trace, ensure_ascii=False), encoding="utf-8"
    )
    result = _prepare(project)
    assert result["scope"] == [] and result["stocks"] == {}


def test_prepare_verifies_time_arguments_against_trace(project):
    with pytest.raises(ValueError, match="action_date"):
        _prepare(project, action_date="2026-08-25")
    with pytest.raises(ValueError, match="as_of"):
        _prepare(project, as_of="2026-08-23T18:30:00+08:00")
    # UTC 等价时刻可用，context 仍逐字保留归档原值
    result = _prepare(project, as_of="2026-08-23T01:05:02+00:00")
    assert result["context"]["as_of"] == AS_OF


def test_prepare_rejects_naive_and_missing_inputs(project):
    with pytest.raises(ValueError, match="timezone"):
        ci.prepare_formal_context(
            formation_date=FORMATION, action_date=ACTION,
            as_of="2026-08-23T09:05:02",
            project_root=project["root"], warehouse_root=project["warehouse_root"],
        )
    with pytest.raises(ValueError, match="missing"):
        ci.prepare_formal_context(
            formation_date="2026-08-20", action_date="2026-08-21",
            as_of="2026-08-21T09:00:00+08:00",
            project_root=project["root"], warehouse_root=project["warehouse_root"],
        )


def test_prepare_rejects_incomplete_research(project):
    _write_v4_trace(project["selection_dir"], completed=False)
    with pytest.raises(ValueError, match="not complete"):
        _prepare(project)


# ---------------------------------------------------------------------------
# 备料事实与确定性计算
# ---------------------------------------------------------------------------


def _stock_facts(project):
    result = _prepare(project)
    assert list(result["stocks"]) == [CODE]
    return result["stocks"][CODE]


def test_prepare_honors_as_of_visibility_and_partitions(project):
    facts = _stock_facts(project)
    blocks = {block["block_id"]: block for block in facts["blocks"]}
    # as_of 之后 available_at 的公告不可见
    announcements = blocks["announcements"]["rows"]
    assert [row["announcement_id"] for row in announcements] == ["ann-1"]
    assert "ann-2" not in {
        row["announcement_id"] for row in announcements
    }
    # 未来修订不可用：同业务键提交 available_at 更晚的修订版
    warehouse = ResearchWarehouse(project["warehouse_root"])
    warehouse.commit_batch(_batch(
        ResearchDatasetId.INCOME_STATEMENT, "2026-06-30",
        [{
            "ts_code": CODE, "report_period": "2026-06-30", "report_type": "2",
            "statement_type": "1", "end_type": "2", "comp_type": "4",
            "ann_date": "20260820", "f_ann_date": "20260820", "update_flag": 1,
            "revenue": 9.9e8, "total_revenue": 9.9e8, "total_cogs": 9.0e8,
            "total_profit": 9.0e7, "n_income": 8.8e7, "n_income_attr_p": 8.6e7,
        }],
        _at(2026, 8, 23, 12, 0), run="run-2",
    ))
    facts = _stock_facts(project)
    blocks = {block["block_id"]: block for block in facts["blocks"]}
    assert blocks["income-2026-06-30"]["row"]["revenue"] == 1.2e9
    assert blocks["income-2026-06-30"]["available_at"] == "2026-08-20T16:00:00+00:00"


def test_computed_values_units_ratios_and_yoy(project):
    warehouse = ResearchWarehouse(project["warehouse_root"])
    warehouse.commit_batch(_batch(
        ResearchDatasetId.CASH_FLOW, "2025-06-30",
        [{
            "ts_code": CODE, "report_period": "2025-06-30", "report_type": "2",
            "statement_type": "1", "end_type": "2", "comp_type": "4",
            "ann_date": "20250820", "f_ann_date": "20250820", "update_flag": 0,
            "n_cashflow_act": 7.0e7, "c_inf_fr_operate_a": 9.0e8,
            "c_paid_goods_s": 8.0e8,
        }],
        _at(2025, 8, 20, 16, 0), run="run-cash-year-ago",
    ))
    facts = _stock_facts(project)
    computed = next(b for b in facts["blocks"] if b["block_id"] == "computed")
    entries = {entry["key"]: entry for entry in computed["entries"]}
    assert entries["营业收入"]["formatted"] == "12.00亿元"
    assert entries["归母净利润"]["formatted"] == "1.00亿元"
    assert entries["毛利率（由收入与营业成本计算）"]["formatted"] == "8.3%"
    assert entries["营业收入同比"]["formatted"] == "20.0%"
    assert entries["归母净利润同比"]["formatted"] == "11.1%"
    assert entries["经营活动现金流净额（上年同期）"]["formatted"] == "0.70亿元"
    assert entries["经营活动现金流净额同比"]["formatted"] == "100.0%"
    # 来源字段为百分数数值口径，不再二次放大
    assert entries["净资产收益率（来源原值）"]["formatted"] == "3.90%"
    # 估值在形成日当te用且 as_of 可见
    valuation = next(b for b in facts["blocks"] if b["block_id"].startswith("valuation-"))
    assert valuation["row"]["trade_date"] == "2026-08-21"
    assert valuation["row"]["pe_ttm"] == 13.0


def test_business_shares_are_within_classification_only(project):
    facts = _stock_facts(project)
    business = next(b for b in facts["blocks"] if b["block_id"].startswith("main-business"))
    shares = business["computed_shares"]
    # product 分类内 6/11 与 5/11；region 不并入 product 合计
    assert shares["product|工程设计"]["share"] == pytest.approx(6.0 / 11.0)
    assert shares["product|工程建造"]["share"] == pytest.approx(5.0 / 11.0)
    assert "region|境内" in shares
    assert shares["region|境内"]["share"] == pytest.approx(1.0)


def test_yoy_guard_is_reported_when_shapes_differ():
    """上年同期行形状（report_type/end_type）与本期不同时，不生成同比。"""

    blocks = [{
        "block_id": "income-2026-06-30", "kind": "warehouse",
        "dataset": "income_statement", "row": {
            "report_period": "2026-06-30", "report_type": "1", "end_type": "2",
            "revenue": 1.2e9, "n_income_attr_p": 1.0e8,
        },
    }]
    year_ago = {"report_period": "2025-06-30", "report_type": "3",
                "end_type": "2", "revenue": 9.0e8, "n_income_attr_p": 8.0e7}
    entries = {
        entry["key"]: entry
        for entry in ci._financial_computed(blocks, year_ago)
    }
    assert entries["同比"]["error"] == "report_type_or_end_type_differs"
    assert "营业收入同比" not in entries and "归母净利润同比" not in entries
    # 形状一致时正常生成同比
    year_ago["report_type"] = "1"
    entries = {
        entry["key"]: entry
        for entry in ci._financial_computed(blocks, year_ago)
    }
    assert entries["营业收入同比"]["formatted"] == "33.3%"


def test_query_failure_is_isolated_as_gap_not_zero(project, monkeypatch):
    def broken(dataset, partitions, as_of):
        raise OSError("simulated warehouse read failure")

    monkeypatch.setattr(
        ci.ResearchQuery, "dataset_partitions_as_of",
        lambda self, dataset, partitions, as_of: broken(dataset, partitions, as_of),
    )
    facts = _stock_facts(project)
    # 全部时点查询失败：资料块缺失，但不冒充"真实无记录"
    assert facts["blocks"] == []
    gaps = facts["gaps"]
    assert any(gap["gap"] == "query_failed" for gap in gaps)
    assert not any(
        gap["gap"].endswith("_rows_missing") or gap["gap"] == "identity_row_missing"
        for gap in gaps
    )


# ---------------------------------------------------------------------------
# record：来源核对、保存、复用与拒绝
# ---------------------------------------------------------------------------


def _sample_intro(**overrides) -> dict:
    intro = {
        "schema_version": "company-introduction-v1",
        "ts_code": CODE,
        "name": "海油工程",
        "formation_date": FORMATION,
        "action_date": ACTION,
        "as_of": AS_OF,
        "generated_at": "2026-08-23T20:05:00+08:00",
        "sections": [
            {
                "title": "公司定位与主要业务",
                "paragraphs": ["公司是海洋油气工程服务商，客户是油气公司。"],
                "source_ids": ["S1"],
            },
            {
                "title": "收入与利润来源",
                "paragraphs": ["工程设计贡献了主要毛利。"],
                "table": {
                    "columns": ["业务", "收入", "收入占比"],
                    "rows": [["工程设计", "6.00亿元", "54.5%"]],
                    "note": "2026-06-30 product 分类内占比",
                },
                "source_ids": ["S2"],
            },
        ],
        "sources": [
            {
                "id": "S1", "kind": "warehouse", "title": "本地利润表",
                "dataset": "income_statement", "block_id": "income-2026-06-30",
                "available_at": "2026-08-20T16:00:00+00:00",
                "locator": "income_statement ts_code=600583.SH report_period=2026-06-30",
                "report_period": "2026-06-30",
                "values": {"revenue": 1.2e9},
            },
            {
                "id": "S2", "kind": "official_document", "title": "2026年半年度报告",
                "available_at": "2026-08-20T16:00:00+08:00",
                "url": "https://example.invalid/a.pdf",
                "availability_basis": "巨潮公告条目 announcement_id=ann-1 的公告时间",
                "retrieved_at": "2026-08-23T19:40:00+08:00",
                "locator": "业务说明所在页",
                "report_period": "2026-06-30",
            },
        ],
        "limitations": ["未核对全部历史公告。"],
    }
    intro.update(overrides)
    return intro


def _write_facts_file(project, result) -> Path:
    path = project["root"] / "tmp-facts.json"
    path.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    return path


def _record(project, intro: dict, facts_path: Path, expect_error: str | None = None):
    intro_path = project["root"] / "tmp-intro.json"
    intro_path.write_text(json.dumps(intro, ensure_ascii=False), encoding="utf-8")
    if expect_error is None:
        return ci.record_introduction(
            intro_file=intro_path, facts_file=facts_path,
            intro_root=project["intro_root"], project_root=project["root"],
        )
    with pytest.raises(ValueError, match=expect_error):
        ci.record_introduction(
            intro_file=intro_path, facts_file=facts_path,
            intro_root=project["intro_root"], project_root=project["root"],
        )
    return None


def test_record_saves_then_reuses_without_rewrite(project):
    facts_path = _write_facts_file(project, _prepare(project))
    summary = _record(project, _sample_intro(), facts_path)
    assert summary["status"] == "recorded"
    target = project["intro_root"] / ACTION / f"{CODE}.json"
    saved = json.loads(target.read_text(encoding="utf-8"))
    assert saved["sections"][0]["paragraphs"]
    first_hash = hashlib.sha256(target.read_bytes()).hexdigest()
    first_mtime = target.stat().st_mtime_ns
    again = _record(project, _sample_intro(), facts_path)
    assert again["status"] == "already_exists"
    assert hashlib.sha256(target.read_bytes()).hexdigest() == first_hash
    assert target.stat().st_mtime_ns == first_mtime


def test_record_rejects_fabricated_or_mismatched_local_sources(project):
    facts_path = _write_facts_file(project, _prepare(project))
    bad_value = _sample_intro()
    bad_value["sources"][0]["values"] = {"revenue": 3.3e9}
    _record(project, bad_value, facts_path, expect_error="cites values")

    bad_block = _sample_intro()
    bad_block["sources"][0]["block_id"] = "income-2099-12-31"
    _record(project, bad_block, facts_path, expect_error="does not match")

    bad_time = _sample_intro()
    bad_time["sources"][0]["available_at"] = "2026-08-21T16:00:00+00:00"
    _record(project, bad_time, facts_path, expect_error="available_at contradicts")

    unknown_ref = _sample_intro()
    unknown_ref["sections"][0]["source_ids"] = ["S9"]
    _record(project, unknown_ref, facts_path, expect_error="unknown source ids")

    future_source = _sample_intro()
    future_source["sources"][1]["available_at"] = "2026-08-23T20:00:00+08:00"
    _record(project, future_source, facts_path, expect_error="after as_of")

    official_missing_basis = _sample_intro()
    official_missing_basis["sources"][1]["availability_basis"] = None
    _record(project, official_missing_basis, facts_path, expect_error="availability_basis")

    # 全部被拒后未产生任何文件
    assert not (project["intro_root"] / ACTION / f"{CODE}.json").exists()


def test_record_rejects_conditional_pending_and_single_stock(project):
    facts_path = _write_facts_file(project, _prepare(project))
    conditional = _sample_intro(ts_code="600150.SH", name="中国船舶")
    _record(project, conditional, facts_path,
            expect_error="cannot pass production record")

    # 未完成研究的 trace 连 prepare 都不能通过
    _write_v4_trace(project["selection_dir"], completed=False)
    with pytest.raises(ValueError, match="not complete"):
        _prepare(project)

    # 单股备料不能过生产 record
    single = ci.prepare_single_stock(
        code=CODE, as_of=AS_OF,
        project_root=project["root"], warehouse_root=project["warehouse_root"],
    )
    single_path = _write_facts_file(project, single)
    _record(project, _sample_intro(), single_path, expect_error="production record")

    _write_v4_trace(project["selection_dir"])  # 恢复完整 trace


def test_record_separate_action_dates_are_separate_files(project):
    facts_path = _write_facts_file(project, _prepare(project))
    _record(project, _sample_intro(), facts_path)
    second = _sample_intro()
    second["action_date"] = "2026-08-25"
    with pytest.raises(ValueError, match="identity does not match"):
        _record(project, second, facts_path)


def test_record_never_overwrites_conflicting_or_corrupt_files(project):
    facts_path = _write_facts_file(project, _prepare(project))
    _record(project, _sample_intro(), facts_path)
    target = project["intro_root"] / ACTION / f"{CODE}.json"
    original = target.read_bytes()

    conflicting = _sample_intro(
        formation_date="2026-08-20",
        action_date="2026-08-21",
        as_of="2026-08-21T00:30:00+08:00",
    )
    with pytest.raises(ValueError, match="identity does not match"):
        _record(project, conflicting, facts_path)
    assert target.read_bytes() == original

    target.write_text("{not json", encoding="utf-8")
    with pytest.raises(ValueError, match="not valid JSON"):
        _record(project, _sample_intro(), facts_path)
    assert target.read_text(encoding="utf-8") == "{not json"
    target.write_bytes(original)


def test_record_does_not_touch_trace_or_warehouse(project):
    before_selection = {
        p: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(project["selection_dir"].rglob("*")) if p.is_file()
    }
    before_warehouse = {
        p: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(project["warehouse_root"].rglob("*")) if p.is_file()
    }
    facts_path = _write_facts_file(project, _prepare(project))
    _record(project, _sample_intro(), facts_path)
    after_selection = {
        p: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(project["selection_dir"].rglob("*")) if p.is_file()
    }
    after_warehouse = {
        p: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(project["warehouse_root"].rglob("*")) if p.is_file()
    }
    assert before_selection == after_selection
    assert before_warehouse == after_warehouse


def test_single_stock_prepare_is_read_only_and_flagged(project):
    before = {
        p: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(project["warehouse_root"].rglob("*")) if p.is_file()
    }
    result = ci.prepare_single_stock(
        code=CODE, as_of=AS_OF, price_date="2026-08-21",
        project_root=project["root"], warehouse_root=project["warehouse_root"],
    )
    assert result["context"]["mode"] == "single_stock"
    assert result["scope"][0]["intro_status"] == "single_stock"
    assert any(b["block_id"] == "income-2026-06-30"
               for b in result["stocks"][CODE]["blocks"])
    after = {
        p: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(project["warehouse_root"].rglob("*")) if p.is_file()
    }
    assert before == after
    with pytest.raises(ValueError, match="ts_code"):
        ci.prepare_single_stock(
            code="860583.XX", as_of=AS_OF,
            project_root=project["root"], warehouse_root=project["warehouse_root"],
        )


# ---------------------------------------------------------------------------
# 展示绑定：build_payload 的 companyIntroduction
# ---------------------------------------------------------------------------


def _payload_stock(payload, code, rec_date):
    return next(
        item for item in payload["stocks"]
        if item["code"] == code and item["recDate"] == rec_date
    )


def _calendar(tmp_path: Path) -> None:
    days = pd.date_range("2026-06-01", "2026-12-31", freq="D")
    frame = pd.DataFrame({
        "exchange": "SSE", "cal_date": days.strftime("%Y-%m-%d"),
        "is_open": days.dayofweek < 5,
    })
    directory = (
        tmp_path / "local_warehouse" / "facts" / "trade_calendar" / "cal_year=2026"
    )
    directory.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(directory / "data.parquet")


def _display_archive(project, *, episodes, daily_ids):
    """构造合法的空复盘归档（正式 V4），用于 build_payload 展示测试。"""

    _calendar(project["root"])
    counts = dict.fromkeys((
        "open_episode_count", "distinct_stock_count", "selected_count",
        "comparator_count", "primary_count", "passive_tail_count",
        "attention_stock_count", "routine_stock_count",
    ), 0)
    cutoff = AS_OF
    report_date = "2026-08-21"
    review = None
    if episodes and daily_ids:
        review = {
            "episode_id": episodes[0]["episode_id"], "day_number": 0,
            "review_kind": "brief", "current_assessment": "partly_supported",
            "current_path": "sideways", "best_supported_explanation": "unknown",
            "current_weak_or_failed_link": "none", "current_review": "暂无。",
            "view_change": "unchanged", "view_change_reason": "无。",
            "outlook_1_3d": "range_or_wait",
            "outlook_reason_plain_language": "等待首日。",
            "tracking_decision": "keep_active_tracking",
            "tracking_decision_reason": "原条件仍待检验。", "review_origin": "live",
        }
    (project["monitor_dir"] / f"snapshot-{report_date}.json").write_text(
        json.dumps({
            "snapshot_version": "forward-monitor-snapshot-v1",
            "analysis_date": report_date, "as_of": cutoff,
            "episodes": episodes, "daily_review_episode_ids": daily_ids,
            "checkpoint_review_episode_ids": [],
            "attention_stocks": [], "summary": counts,
        }, ensure_ascii=False), encoding="utf-8")
    (project["monitor_dir"] / f"daily-formal-reviews-{report_date}.json").write_text(
        json.dumps({"ledger_version": "daily-formal-reviews-v1",
                    "analysis_date": report_date, "as_of": cutoff,
                    "reviews": [review] if review else []}, ensure_ascii=False),
        encoding="utf-8")
    (project["monitor_dir"] / f"monitor-report-{report_date}.json").write_text(
        json.dumps({
            "report_version": "daily-forward-monitor-report-v2",
            "analysis_date": report_date, "as_of": cutoff,
            "market_overview": {"market_propagation_mode": "unclear",
                                "market_risk_overlays": [], "what_changed": "无。",
                                "implication_for_monitored_stocks": "无。"},
            "pool_summary": counts, "alerts": [], "unreported_attention_count": 0,
            "routine_summary": "无。",
        }, ensure_ascii=False), encoding="utf-8")
    (project["monitor_dir"] / f"monitor-report-{report_date}.md").write_text(
        "无复盘。", encoding="utf-8")


def _episode(code, name, *, action, formation, episode_id, priority=1, extra=None):
    episode = {
        "episode_id": episode_id, "ts_code": code, "name": name,
        "role": "selected", "selection_output_class": "confirmed_active",
        "day_number": 0, "formation_date": formation, "action_date": action,
        "original_priority": priority, "original_research_thesis": {},
        "previous_monitor_state": None, "previous_episode_review": None,
        "first_event_reaction": None, "original_engine_type": "sector_leader_cluster",
        "monitor_phase": "primary", "tracking_status": "active",
        "tracking_exit_date": None, "tracking_exit_reason": None,
    }
    episode.update(extra or {})
    return episode


def _write_introduction_file(intro_root: Path, action: str, code: str, marker: str,
                             *, as_of=AS_OF, formation=FORMATION, action_date=None):
    path = ci.intro_path(intro_root, action, code)
    path.parent.mkdir(parents=True, exist_ok=True)
    sources = None
    if as_of != AS_OF:
        # 与自定义截止兼容的最小来源，避免样例来源晚于该 as_of
        sources = [{
            "id": "S1", "kind": "official_document", "title": "兼容来源",
            "available_at": "2026-08-08T10:00:00+08:00",
            "availability_basis": "测试公开时间定位",
            "retrieved_at": "2026-08-09T20:00:00+08:00",
            "locator": "第1页",
        }]
    path.write_text(json.dumps(_sample_intro(
        ts_code=code, formation_date=formation,
        action_date=action_date or action, as_of=as_of,
        sections=[{"title": marker, "paragraphs": [f"{marker}正文。"],
                   "source_ids": ["S1"]}],
        **({"sources": sources} if sources else {}),
    ), ensure_ascii=False), encoding="utf-8")
    return path


def test_payload_binds_introductions_by_identity(project):
    from tools.render_monitor_web import build_payload

    episode = _episode(CODE, "海油工程", action=ACTION, formation=FORMATION,
                       episode_id=f"formal:{FORMATION}:{CODE}:selected")
    _display_archive(project, episodes=[episode], daily_ids=[episode["episode_id"]])
    report = json.loads(
        (project["monitor_dir"] / "monitor-report-2026-08-21.json").read_text(encoding="utf-8")
    )
    snapshot = json.loads(
        (project["monitor_dir"] / "snapshot-2026-08-21.json").read_text(encoding="utf-8")
    )
    # 无介绍文件时保持缺项
    payload = build_payload(project["root"], project["monitor_dir"],
                            date(2026, 8, 21), report, snapshot,
                            selection_dir=project["selection_dir"],
                            intro_root=project["intro_root"])
    stock = _payload_stock(payload, CODE, ACTION)
    assert "companyIntroduction" not in stock
    # 写入合法介绍后按身份绑定；D0 参考价仍为空
    _write_introduction_file(project["intro_root"], ACTION, CODE, "身份匹配篇")
    payload = build_payload(project["root"], project["monitor_dir"],
                            date(2026, 8, 21), report, snapshot,
                            selection_dir=project["selection_dir"],
                            intro_root=project["intro_root"])
    stock = _payload_stock(payload, CODE, ACTION)
    assert stock["companyIntroduction"]["sections"][0]["title"] == "身份匹配篇"
    if stock.get("d0"):
        assert stock["ref"] is None


def test_payload_rejects_identity_mismatched_introduction(project):
    from tools.render_monitor_web import build_payload

    episode = _episode(CODE, "海油工程", action=ACTION, formation=FORMATION,
                       episode_id=f"formal:{FORMATION}:{CODE}:selected")
    _display_archive(project, episodes=[episode], daily_ids=[episode["episode_id"]])
    report = json.loads(
        (project["monitor_dir"] / "monitor-report-2026-08-21.json").read_text(encoding="utf-8")
    )
    snapshot = json.loads(
        (project["monitor_dir"] / "snapshot-2026-08-21.json").read_text(encoding="utf-8")
    )
    # as_of 与原 trace 不同：不能证明是同一截止的文章，不绑定
    _write_introduction_file(project["intro_root"], ACTION, CODE, "截止不符篇",
                             as_of="2026-08-23T18:30:00+08:00")
    payload = build_payload(project["root"], project["monitor_dir"],
                            date(2026, 8, 21), report, snapshot,
                            selection_dir=project["selection_dir"],
                            intro_root=project["intro_root"])
    assert "companyIntroduction" not in _payload_stock(payload, CODE, ACTION)
    # 同代码不同行动日：行动日不符同样不绑定
    _write_introduction_file(project["intro_root"], "2026-08-25", CODE, "行动日不符篇")
    payload = build_payload(project["root"], project["monitor_dir"],
                            date(2026, 8, 21), report, snapshot,
                            selection_dir=project["selection_dir"],
                            intro_root=project["intro_root"])
    assert "companyIntroduction" not in _payload_stock(payload, CODE, ACTION)


def test_same_stock_two_recommendations_keep_own_introductions(project):
    from tools.render_monitor_web import build_payload

    ep_new = _episode(CODE, "海油工程", action=ACTION, formation=FORMATION,
                      episode_id=f"formal:{FORMATION}:{CODE}:selected")
    ep_old = _episode(CODE, "海油工程", action="2026-08-10", formation="2026-08-07",
                      episode_id="formal:2026-08-07:600583.SH:selected")
    _display_archive(project, episodes=[ep_old, ep_new],
                     daily_ids=[ep_new["episode_id"]])
    # 第二条身份来自更早的原 trace
    old_trace = {
        "trace_version": "daily-research-trace-v4", "formation_date": "2026-08-07",
        "action_date": "2026-08-10", "as_of": "2026-08-09T18:30:00+08:00",
        "candidate_ledger": [{
            "ts_code": CODE, "name": "海油工程", "final_fate": "selected",
            "research_thesis": {"engine_type": "sector_leader_cluster",
                                "engine_status": "active",
                                "market_recognition": {"status": "confirmed"}},
        }],
        "decision_trace": [],
        "research_result": {"research_completed": True,
                            "point_in_time_evidence_verified": True,
                            "failure_reason": "", "skills_used": [], "selected_stocks": [],
                            "nearest_nonselections": [], "empty_reason": ""},
    }
    (project["selection_dir"] / "research-trace-2026-08-07.json").write_text(
        json.dumps(old_trace, ensure_ascii=False), encoding="utf-8")
    _write_introduction_file(project["intro_root"], ACTION, CODE, "本次推荐篇")
    _write_introduction_file(project["intro_root"], "2026-08-10", CODE, "上次推荐篇",
                             as_of="2026-08-09T18:30:00+08:00", formation="2026-08-07")
    report = json.loads(
        (project["monitor_dir"] / "monitor-report-2026-08-21.json").read_text(encoding="utf-8")
    )
    snapshot = json.loads(
        (project["monitor_dir"] / "snapshot-2026-08-21.json").read_text(encoding="utf-8")
    )
    payload = build_payload(project["root"], project["monitor_dir"],
                            date(2026, 8, 21), report, snapshot,
                            selection_dir=project["selection_dir"],
                            intro_root=project["intro_root"])
    assert _payload_stock(payload, CODE, ACTION)[
        "companyIntroduction"]["sections"][0]["title"] == "本次推荐篇"
    assert _payload_stock(payload, CODE, "2026-08-10")[
        "companyIntroduction"]["sections"][0]["title"] == "上次推荐篇"


def test_payload_binds_introduction_for_trace_only_d0(project):
    """当晚 snapshot 尚无新推荐 episode 时，D0 从正式 trace 追加并绑定介绍。"""

    from tools.render_monitor_web import build_payload

    _display_archive(project, episodes=[], daily_ids=[])
    report = json.loads(
        (project["monitor_dir"] / "monitor-report-2026-08-21.json").read_text(encoding="utf-8")
    )
    snapshot = json.loads(
        (project["monitor_dir"] / "snapshot-2026-08-21.json").read_text(encoding="utf-8")
    )
    _write_introduction_file(project["intro_root"], ACTION, CODE, "D0当天篇")
    payload = build_payload(project["root"], project["monitor_dir"],
                            date(2026, 8, 21), report, snapshot,
                            selection_dir=project["selection_dir"],
                            intro_root=project["intro_root"])
    stock = _payload_stock(payload, CODE, ACTION)
    assert stock.get("d0") is True
    assert stock["ref"] is None  # D0 参考价仍依原合同为空
    assert stock["companyIntroduction"]["sections"][0]["title"] == "D0当天篇"
    assert stock["formedOn"] == "2026-08-21"


def test_legacy_displayed_episode_can_bind_v1_introduction(project):
    from tools.render_monitor_web import build_payload

    episode = _episode(CODE, "海油工程", action=ACTION, formation=FORMATION,
                       episode_id="legacy:2026-08-21:600583.SH:selected",
                       extra={"selection_output_class": "legacy_v1_not_rewritten"})
    _display_archive(project, episodes=[episode], daily_ids=[])
    legacy_trace = {
        "trace_version": "daily-research-trace-v1",
        "formation_date": FORMATION, "action_date": ACTION, "as_of": AS_OF,
        "candidate_ledger": [{"ts_code": CODE, "name": "海油工程",
                              "final_fate": "selected"}],
        "research_result": {"research_completed": True,
                            "point_in_time_evidence_verified": True},
    }
    (project["selection_dir"] / f"research-trace-{FORMATION}.json").write_text(
        json.dumps(legacy_trace, ensure_ascii=False), encoding="utf-8")
    _write_introduction_file(project["intro_root"], ACTION, CODE, "历史补写篇")
    report = json.loads(
        (project["monitor_dir"] / "monitor-report-2026-08-21.json").read_text(encoding="utf-8")
    )
    snapshot = json.loads(
        (project["monitor_dir"] / "snapshot-2026-08-21.json").read_text(encoding="utf-8")
    )
    payload = build_payload(project["root"], project["monitor_dir"],
                            date(2026, 8, 21), report, snapshot,
                            selection_dir=project["selection_dir"],
                            intro_root=project["intro_root"])
    stock = _payload_stock(payload, CODE, ACTION)
    assert stock["companyIntroduction"]["sections"][0]["title"] == "历史补写篇"
    # 旧 company 简要字段保持兼容
    assert stock.get("company") is not None


# ---------------------------------------------------------------------------
# 收尾第二次同步条件
# ---------------------------------------------------------------------------


def test_second_sync_condition_truth_table():
    assert ci.needs_second_sync(first_sync_ok=True, new_articles_saved=False) is False
    assert ci.needs_second_sync(first_sync_ok=True, new_articles_saved=True) is True
    assert ci.needs_second_sync(first_sync_ok=False, new_articles_saved=False) is True
    assert ci.needs_second_sync(first_sync_ok=False, new_articles_saved=True) is True


# ---------------------------------------------------------------------------
# 晚间 Prompt 的收尾合同
# ---------------------------------------------------------------------------


def test_forward_selection_prompt_declares_introduction_closing():
    text = Path("ops/forward-selection-prompt.md").read_text(encoding="utf-8")
    assert "### 公司介绍补齐（同一共同收尾，介绍失败不撤销推荐）" in text
    assert "ops/company-introduction-prompt.md" in text
    assert "writing-company-introductions/SKILL.md" in text
    assert "本轮新增保存了介绍，或首次同步失败" in text
    assert "介绍生成失败不撤销推荐、不阻断已完成的网页同步" in text
    # 不把介绍写进正式产物
    assert "不得把介绍写入正式推荐正文、V4 轨迹、Forward CSV 或复盘" in text


def test_introduction_prompt_declares_flow_and_boundaries():
    text = Path("ops/company-introduction-prompt.md").read_text(encoding="utf-8")
    assert "company_introduction prepare" in text
    assert "company_introduction record" in text
    assert "逐字传递，不得改写" in text
    assert "不循环重试" in text
    assert "不补位" in text
    assert "不读取未来数据" in text


def test_skill_declares_reader_contract_and_boundaries():
    text = Path(".agents/skills/writing-company-introductions/SKILL.md").read_text(
        encoding="utf-8"
    )
    assert "公司卖什么，谁使用、谁付钱" in text
    assert "不给出股票推荐、短期走势、买入条件、仓位或目标价" in text
    assert "不由程序模板拼接" in text
    assert "availability_basis" in text and "retrieved_at" in text
    assert "核电小额外加剂合同不能写成核电主营已经放量" in text


# 本地无法读取时仍可由 AI 取得官方证据；正式身份和来源合同保持不变。
@pytest.mark.parametrize("error_type", [
    FileNotFoundError, ci.FactRecoveryError, ci.duckdb.IOException,
    ci.duckdb.ConnectionException, ci.duckdb.PermissionException,
])
def test_formal_prepare_keeps_scope_when_warehouse_cannot_open(project, monkeypatch, error_type):
    def unavailable(*args, **kwargs):
        assert kwargs["read_only"] is True
        raise error_type("known local access failure")

    monkeypatch.setattr(ci, "ResearchWarehouse", unavailable)
    result = _prepare(project)
    assert result["context"]["mode"] == "formal"
    assert result["context"]["as_of"] == AS_OF
    assert result["context"]["action_date"] == ACTION
    assert [(x["ts_code"], x["intro_status"]) for x in result["scope"]] == [(CODE, "missing")]
    assert result["stocks"][CODE]["blocks"] == []
    assert result["stocks"][CODE]["gaps"][0]["gap"] == "warehouse_unavailable"
    assert result["warehouse_gaps"] == result["stocks"][CODE]["gaps"]
    assert result["used_partitions"] == {}

    # 合成官方来源用于合同测试，实际资料真实性仍由原文核查负责。
    intro = _sample_intro()
    intro["sources"] = [intro["sources"][1]]
    for section in intro["sections"]:
        section["source_ids"] = ["S2"]
    facts_path = _write_facts_file(project, result)
    assert _record(project, intro, facts_path)["status"] == "recorded"


def test_unavailable_warehouse_does_not_relax_identity_or_sources(project, monkeypatch):
    def unavailable(*args, **kwargs):
        raise FileNotFoundError("warehouse absent")

    monkeypatch.setattr(ci, "ResearchWarehouse", unavailable)
    facts_path = _write_facts_file(project, _prepare(project))
    _record(project, _sample_intro(), facts_path, expect_error="does not match this round")

    def official_intro(**overrides):
        intro = _sample_intro(**overrides)
        intro["sources"] = [intro["sources"][1]]
        for section in intro["sections"]:
            section["source_ids"] = ["S2"]
        return intro

    future = official_intro()
    future["sources"][0]["available_at"] = "2026-08-24T10:00:00+08:00"
    _record(project, future, facts_path, expect_error="after as_of")
    _record(project, official_intro(action_date="2026-08-25"), facts_path,
            expect_error="identity does not match")
    _record(project, official_intro(ts_code="600150.SH"), facts_path,
            expect_error="conditional_event")
    with pytest.raises(ValueError, match="does not match the archived trace"):
        _prepare(project, action_date="2026-08-25")
    _write_v4_trace(project["selection_dir"], completed=False)
    with pytest.raises(ValueError, match="formal research is not complete"):
        _prepare(project)
    _record(project, official_intro(), facts_path, expect_error="research is not complete")


@pytest.mark.parametrize("error_type", [RuntimeError, ci.duckdb.BinderException])
@pytest.mark.parametrize("stage", ["open", "query"])
def test_program_errors_are_not_presented_as_missing_data(project, monkeypatch, error_type, stage):
    def broken(*args, **kwargs):
        raise error_type("program bug must remain visible")

    if stage == "open":
        monkeypatch.setattr(ci, "ResearchWarehouse", broken)
    else:
        monkeypatch.setattr(ci.ResearchQuery, "dataset_partitions_as_of", broken)
    with pytest.raises(error_type, match="program bug must remain visible"):
        _prepare(project)


def test_read_failure_isolated_per_stock_and_metadata_includes_every_stock(project, monkeypatch):
    extra = [{
        "ts_code": OTHER, "name": "第二家公司", "final_fate": "selected",
        "research_thesis": {"engine_type": "sector_leader_cluster", "engine_status": "active",
                            "market_recognition": {"status": "confirmed"}},
    }]
    _write_v4_trace(project["selection_dir"], extra=extra)
    actual = ci._stock_facts

    def per_stock(gatherer, ts_code, name_hint, price_date_upper):
        if ts_code == CODE:
            gatherer.used_partitions["income_statement"] = ["2025-06-30"]
            raise OSError("first stock partition unavailable")
        result = actual(gatherer, ts_code, name_hint, price_date_upper)
        gatherer.used_partitions["income_statement"] = ["2026-06-30"]
        return result

    monkeypatch.setattr(ci, "_stock_facts", per_stock)
    result = _prepare(project)
    assert set(result["stocks"]) == {CODE, OTHER}
    assert result["stocks"][CODE]["blocks"] == []
    assert result["stocks"][CODE]["gaps"][0]["gap"] == "query_failed"
    assert result["stocks"][OTHER]["ts_code"] == OTHER
    for stock in result["stocks"].values():
        assert all(gap in result["warehouse_gaps"] for gap in stock["gaps"])
    assert result["used_partitions"]["income_statement"] == ["2025-06-30", "2026-06-30"]
