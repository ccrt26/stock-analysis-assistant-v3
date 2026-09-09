"""CurrentOpportunityV1 合同与联动测试（V3 执行单 E1）。

T08（第21日触达不改固定20日）与 T09（盘中触达不等于收盘触达）由
tests/test_export_skill_optimization_dataset.py 的 T04/T05 覆盖，此处不重复。
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest
from pydantic import ValidationError

from stock_analyzer.ops.forward_monitor import (
    CurrentOpportunityV1,
    DailyFormalReviewLedgerV1,
    DailyFormalReviewV1,
    current_opportunity_changed,
)

BASE = dict(
    reference_close=10.0,
    reference_date=date(2026, 9, 9),
    outlook_5_10d="up",
    outlook_reason="测试：中期支持仍在，近期可能先整理。",
    participation="wait",
    participation_reason="测试：方向偏上但当前价格不支持追入。",
    change_condition="测试：原支持消失时重新判断。",
)


def _review(**overrides) -> DailyFormalReviewV1:
    payload = dict(
        episode_id="formal:2026-09-01:002602.SZ:selected",
        day_number=5,
        review_kind="regular_detail",
        current_assessment="partly_supported",
        current_path="up",
        best_supported_explanation="stock_specific_move",
        current_weak_or_failed_link="none",
        view_change="unchanged",
        view_change_reason="测试：判断没有实质变化。",
        outlook_1_3d="continuation_possible",
        outlook_reason_plain_language="测试：短期仍有支撑。",
        tracking_decision="keep_active_tracking",
        tracking_decision_reason="测试：继续按原周期观察。",
        review_origin="live",
    )
    payload.update(overrides)
    return DailyFormalReviewV1(**payload)


def test_upward_outlook_does_not_force_buy():
    row = CurrentOpportunityV1(**BASE)
    assert row.outlook_5_10d == "up"
    assert row.participation == "wait"


def test_consider_requires_current_reference():
    data = {**BASE, "reference_close": None, "reference_date": None,
            "participation": "consider"}
    with pytest.raises(ValidationError):
        CurrentOpportunityV1(**data)


def test_unclear_is_not_sideways():
    row = CurrentOpportunityV1(**{**BASE, "outlook_5_10d": "unclear",
                                "participation": "insufficient"})
    assert row.outlook_5_10d == "unclear"


def test_reference_fields_must_pair():
    with pytest.raises(ValidationError):
        CurrentOpportunityV1(**{**BASE, "reference_date": None})
    with pytest.raises(ValidationError):
        CurrentOpportunityV1(**{**BASE, "reference_close": None})


def test_T01_old_ledger_without_current_opportunity_reads_as_is(tmp_path: Path) -> None:
    review = _review().model_dump(mode="json")
    review.pop("current_opportunity")
    ledger = {
        "ledger_version": "daily-formal-reviews-v1",
        "analysis_date": "2026-09-08",
        "as_of": "2026-09-08T18:30:00+08:00",
        "reviews": [review],
    }
    path = tmp_path / "ledger.json"
    path.write_text(json.dumps(ledger, ensure_ascii=False), encoding="utf-8")
    parsed = DailyFormalReviewLedgerV1.model_validate_json(path.read_text(encoding="utf-8"))
    assert parsed.reviews[0].current_opportunity is None
    # 不回写：文件保持原样，没有 null 键被补进旧 JSON
    assert "current_opportunity" not in json.loads(path.read_text(encoding="utf-8"))["reviews"][0]


def test_T04_windows_can_differ_and_participation_stays_wait():
    row = CurrentOpportunityV1(**BASE)
    review = _review(current_opportunity=row)
    assert review.outlook_1_3d == "continuation_possible"
    assert review.current_opportunity.outlook_5_10d == "up"
    assert review.current_opportunity.participation == "wait"


def test_T06_avoid_with_supported_assessment_is_legal():
    row = CurrentOpportunityV1(**{**BASE, "participation": "avoid",
                                  "participation_reason": "测试：当前价格不利，暂不参与。"})
    review = _review(current_assessment="supported", current_opportunity=row)
    assert review.current_assessment == "supported"
    assert review.current_opportunity.participation == "avoid"


def test_T07_d20_miss_with_current_up_keeps_them_independent(tmp_path: Path) -> None:
    frozen = {
        "weak_or_failed_link": "remaining_room",
        "decision_review": "direction_right_stock_wrong",
        "overall_review": "测试：前20日未触达20%的固定结案。",
    }
    row = CurrentOpportunityV1(**BASE)
    review = _review(
        day_number=20,
        checkpoint="D20",
        tracking_decision="complete_observation",
        tracking_decision_reason="测试：观察期结束。",
        final_twenty_day_review=frozen,
        current_opportunity=row,
    )
    assert review.final_twenty_day_review.overall_review.startswith("测试：")
    assert review.current_opportunity.outlook_5_10d == "up"


def _previous_with_opportunity(row: dict | None) -> dict:
    return {"episode_id": "formal:2026-09-01:002602.SZ:selected",
            "current_opportunity": row}


def test_T11_participation_change_enters_priority_group():
    before = CurrentOpportunityV1(**BASE).model_dump(mode="json")
    after = CurrentOpportunityV1(
        **{**BASE, "participation": "avoid",
           "participation_reason": "测试：转为暂不参与。"}
    ).model_dump(mode="json")
    previous = _previous_with_opportunity(before)
    current = _review(
        view_change="unchanged",
        current_opportunity=CurrentOpportunityV1(**after),
    ).model_dump(mode="json")
    assert current_opportunity_changed(previous, current) is True


def test_T12_first_introduction_is_not_a_priority_change():
    current = _review(
        current_opportunity=CurrentOpportunityV1(**BASE)
    ).model_dump(mode="json")
    assert current_opportunity_changed(None, current) is False
    assert current_opportunity_changed(_previous_with_opportunity(None), current) is False


def test_current_opportunity_changed_on_window_shift():
    before = CurrentOpportunityV1(**BASE).model_dump(mode="json")
    after = CurrentOpportunityV1(**{**BASE, "outlook_5_10d": "down"}).model_dump(mode="json")
    assert current_opportunity_changed(
        _previous_with_opportunity(before), {**_review().model_dump(mode="json"),
                                             "current_opportunity": after}
    ) is True
    same = current_opportunity_changed(
        _previous_with_opportunity(before), _review(
            current_opportunity=CurrentOpportunityV1(**before)
        ).model_dump(mode="json")
    )
    assert same is False


# ---------------------------------------------------------------------------
# record 合同（T02/T03/T10）与展示/Prompt 合同（T14/T15/T23/T24/T25）
# ---------------------------------------------------------------------------


def _snapshot_payload(
    *, required: bool = True, current_close: float | None = None,
    previous: dict | None = None, episodes_extra: list[dict] | None = None,
) -> dict:
    episode = {
        "episode_id": "formal:2026-09-01:002602.SZ:selected",
        "ts_code": "002602.SZ",
        "action_date": "2026-09-02",
        "day_number": 5,
        "checkpoint": None,
        "role": "selected",
        "selection_output_class": "confirmed_active",
        "tracking_status": "active",
        "previous_daily_formal_review": previous,
    }
    if current_close is not None:
        episode["review_context"] = {"price_levels": {"current_close": current_close}}
    payload = {
        "snapshot_version": "forward-monitor-snapshot-v1",
        "analysis_date": "2026-09-08",
        "as_of": "2026-09-08T18:30:00+08:00",
        "current_opportunity_required": required,
        "daily_review_episode_ids": [episode["episode_id"]],
        "evaluation_only_episode_ids": [],
        "episodes": [episode] + (episodes_extra or []),
    }
    return payload


def _opportunity(**overrides) -> dict:
    row = CurrentOpportunityV1(**BASE).model_dump(mode="json")
    row.update(overrides)
    return row


def _write_and_record(tmp_path: Path, snapshot: dict, reviews: list[dict]):
    from stock_analyzer.ops.forward_monitor import record_daily_formal_reviews

    work = tmp_path / "work"
    work.mkdir(parents=True, exist_ok=True)
    snapshot_path = work / "snapshot.json"
    snapshot_path.write_text(json.dumps(snapshot), encoding="utf-8")
    ledger = {
        "ledger_version": "daily-formal-reviews-v1",
        "analysis_date": "2026-09-08",
        "as_of": "2026-09-08T18:30:00+08:00",
        "reviews": reviews,
    }
    pending = work / "pending.json"
    pending.write_text(json.dumps(ledger, ensure_ascii=False), encoding="utf-8")
    return record_daily_formal_reviews(
        snapshot_file=snapshot_path, review_file=pending,
        project_root=tmp_path,
    )


def _live_row(opportunity: dict | None, episode_id: str | None = None) -> dict:
    row = _review(
        current_opportunity=CurrentOpportunityV1(**opportunity) if opportunity else None,
    ).model_dump(mode="json")
    row["review_kind"] = "regular_detail"
    row.pop("current_review", None)
    if episode_id:
        row["episode_id"] = episode_id
    return row


def test_T02_required_snapshot_rejects_live_row_without_object(tmp_path: Path) -> None:
    snapshot = _snapshot_payload(required=True)
    with pytest.raises(ValueError, match="requires a current opportunity"):
        _write_and_record(tmp_path, snapshot, [_live_row(None)])
    # 空 reviews 只在快照本日无需复盘记录时合法
    empty_snapshot = _snapshot_payload(required=True)
    empty_snapshot["episodes"] = []
    empty_snapshot["daily_review_episode_ids"] = []
    summary = _write_and_record(tmp_path / "empty", empty_snapshot, [])
    assert summary.status == "recorded"
    # 非 required（旧快照）不强制
    snapshot_old = _snapshot_payload(required=False)
    summary = _write_and_record(tmp_path / "legacy", snapshot_old, [_live_row(None)])
    assert summary.status == "recorded"


def test_T03_reference_close_must_match_analysis_day_close(tmp_path: Path) -> None:
    snapshot = _snapshot_payload(required=True, current_close=16.13)
    bad_entry = _opportunity(reference_close=15.0, reference_date="2026-09-08")
    with pytest.raises(ValueError, match="analysis-day close"):
        _write_and_record(tmp_path, snapshot, [_live_row(bad_entry)])
    good = _opportunity(reference_close=16.13, reference_date="2026-09-08")
    summary = _write_and_record(tmp_path, snapshot, [_live_row(good)])
    assert summary.status == "recorded"


def test_T10_same_stock_same_day_must_share_one_opportunity(tmp_path: Path) -> None:
    second = {
        **_snapshot_payload()["episodes"][0],
        "episode_id": "formal:2026-08-26:002602.SZ:selected",
        "review_context": {"price_levels": {"current_close": 16.13}},
    }
    snapshot = _snapshot_payload(
        required=True, current_close=16.13, episodes_extra=[second],
    )
    snapshot["daily_review_episode_ids"] = [
        episode["episode_id"] for episode in snapshot["episodes"]
    ]
    first_row = _live_row(_opportunity(reference_close=16.13, reference_date="2026-09-08"))
    second_row = _live_row(
        _opportunity(reference_close=16.13, reference_date="2026-09-08",
                     participation="avoid", participation_reason="测试：转为暂不参与。"),
        episode_id="formal:2026-08-26:002602.SZ:selected",
    )
    with pytest.raises(ValueError, match="share one current opportunity"):
        _write_and_record(tmp_path, snapshot, [first_row, second_row])
    second_row_ok = _live_row(
        _opportunity(reference_close=16.13, reference_date="2026-09-08"),
        episode_id="formal:2026-08-26:002602.SZ:selected",
    )
    summary = _write_and_record(tmp_path, snapshot, [first_row, second_row_ok])
    assert summary.status == "recorded"


def test_T14_markdown_and_display_contract_read_the_same_object() -> None:
    from tools.web_display_contract import current_opportunity_for_display

    review = _review(current_opportunity=CurrentOpportunityV1(**BASE))
    payload = current_opportunity_for_display(review.model_dump(mode="json"))
    assert payload["directionText"] == "更可能向上"
    assert payload["participationText"] == "等待所述条件"
    assert payload["referenceDate"] == "2026-09-09"
    # 缺失/未识别不猜测（旧 JSON 中出现未识别枚举时原样拒绝渲染）
    assert current_opportunity_for_display({"current_opportunity": None}) is None
    bad = dict(BASE)
    bad["outlook_5_10d"] = "unknown_direction"
    assert current_opportunity_for_display({"current_opportunity": bad}) is None


def test_T15_prompt_paths_share_the_current_opportunity_contract() -> None:
    selection = Path("ops/forward-selection-prompt.md").read_text(encoding="utf-8")
    assert "current_opportunity" in selection


def test_T23_batch_entry_declares_diagnose_default_and_sample_honesty() -> None:
    text = Path("ops/selection-method-review-prompt.md").read_text(encoding="utf-8")
    assert "默认模式为`diagnose`" in text
    assert "推荐次数、不同股票数" in text
    assert "不能把这类辅助去重当作严格独立样本证明" in text


def test_T24_prompt_requires_explicit_degradation_on_kb_failure() -> None:
    monitor = Path("ops/forward-monitor-prompt.md").read_text(encoding="utf-8")
    assert "自定义知识库未读取成功" in monitor


def test_T25_current_window_does_not_extend_scheduled_tracking() -> None:
    monitor = Path("ops/forward-monitor-prompt.md").read_text(encoding="utf-8")
    assert "新5—10日判断超出旧生命周期不授权新日常任务" in monitor
