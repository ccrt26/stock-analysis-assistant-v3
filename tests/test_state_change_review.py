"""V2 state-change review: exact offline fake-output acceptance nodes T01-T18."""
from __future__ import annotations

import json
from argparse import Namespace
from copy import deepcopy
from datetime import date, datetime
from pathlib import Path

import pytest

import test_forward_monitor as legacy
from stock_analyzer.ops import forward_monitor as fm
from tools import nightly_report, render_monitor_web, stock_ai

POLICY = "state-change-v1"
SOURCE = Path(__file__).resolve().parents[1]


def case(count=1, *, previous="follow", current="follow", day=2):
    snapshot, reviews = legacy._multi_daily_formal_snapshot(count)
    snapshot["monitor_review_policy"] = POLICY
    snapshot["checkpoint_review_episode_ids"] = []
    snapshot["summary"]["regular_detail_stock_limit"] = 0
    for episode, review in zip(snapshot["episodes"], reviews):
        episode.update(day_number=day, checkpoint=legacy.CHECKPOINTS_FOR_TESTS.get(day),
                       previous_daily_formal_review=(
                           {"tracking_state": previous, "_analysis_date": "2026-08-28"}
                           if previous is not None else None))
        review.update(day_number=day, checkpoint=episode["checkpoint"],
                      monitor_review_policy=POLICY, tracking_state=current,
                      tracking_end_reason=None, review_kind="brief",
                      current_review=f"{episode['name']}｜今日检查\n\n原判断仍有依据，继续看原条件。")
    snapshot["checkpoint_review_episode_ids"] = [
        e["episode_id"] for e in snapshot["episodes"] if e["checkpoint"]
    ]
    return snapshot, reviews


def save_ledger(root, snapshot, reviews):
    root.mkdir(parents=True, exist_ok=True)
    p = root / "snapshot.json"
    p.write_text(json.dumps(snapshot, ensure_ascii=False))
    archive = root / "local_archive/forward_monitor"
    archive.mkdir(parents=True, exist_ok=True)
    (archive / f"snapshot-{snapshot['analysis_date']}.json").write_text(
        json.dumps(snapshot, ensure_ascii=False))
    q = root / "pending-ledger.json"
    q.write_text(json.dumps({"ledger_version": fm.DAILY_FORMAL_REVIEWS_VERSION,
                             "monitor_review_policy": POLICY,
                             "analysis_date": snapshot["analysis_date"],
                             "as_of": snapshot["as_of"],
                             "reviews": reviews}, ensure_ascii=False))
    return p, fm.record_daily_formal_reviews(snapshot_file=p, review_file=q, project_root=root)


def report_payload(snapshot, alerts=None):
    payload = legacy._report_payload(snapshot, alerts=alerts or [])
    payload["monitor_review_policy"] = POLICY
    return payload


def save_report(root, snapshot_path, snapshot, alerts=None):
    p = root / "pending-report.json"
    p.write_text(json.dumps(report_payload(snapshot, alerts), ensure_ascii=False))
    return fm.record_forward_monitor(snapshot_file=snapshot_path, report_file=p, project_root=root)


def change_alert(episode, review, body="这次推荐由继续关注改为等待变化：原相对优势减弱，等同行比较恢复。"):
    alert = legacy._daily_detail_alert(episode, review)
    alert["stock_review"] = f"{episode['name']}｜状态改变\n\n{body}"
    for item in alert["episode_reviews"]:
        item["current_review"] = None
    return alert


def install_knowledge(root):
    target = root / ".agents/skills/reviewing-stock-recommendations/references/state-change"
    target.mkdir(parents=True)
    for p in (SOURCE / ".agents/skills/reviewing-stock-recommendations/references/state-change").glob("*.md"):
        (target / p.name).write_bytes(p.read_bytes())


def test_T01_all_active_episodes_one_stock_facts_compact_input(tmp_path):
    snapshot, _ = case(50)
    duplicate = dict(snapshot["episodes"][0], episode_id="older:000001.SZ", action_date="2026-08-01",
                     original_selection_reason="旧推荐独立理由", original_strongest_counterevidence="旧风险完整保留")
    duplicate["review_context"] = {"post_entry_sessions": [{"date": str(i)} for i in range(60)]}
    snapshot["episodes"].append(duplicate)
    snapshot["daily_review_episode_ids"].append(duplicate["episode_id"])
    install_knowledge(tmp_path)
    bundle = fm.build_state_change_input(snapshot, tmp_path)
    assert len(bundle["stocks"]) == 50
    assert len(bundle["episodes"]) == 51
    assert bundle["episodes"][duplicate["episode_id"]]["original_selection_reason"] == "旧推荐独立理由"
    assert bundle["episodes"][duplicate["episode_id"]]["original_strongest_counterevidence"] == "旧风险完整保留"
    assert "post_entry_sessions" not in json.dumps(bundle["episodes"][duplicate["episode_id"]])


def test_T02_unchanged_follow_and_wait_use_brief_even_with_price_opinion_change(tmp_path):
    for state in ("follow", "wait"):
        snapshot, reviews = case(previous=state, current=state)
        reviews[0]["current_opportunity"]["participation"] = "avoid"
        reviews[0]["outlook_1_3d"] = "weakening"
        p, _ = save_ledger(tmp_path / state, snapshot, reviews)
        assert save_report(tmp_path / state, p, snapshot).alert_count == 0
        assert fm.state_change_kind(state, state) == "brief"


def test_T03_both_directions_require_single_change_body(tmp_path):
    for before, after in (("follow", "wait"), ("wait", "follow")):
        root = tmp_path / f"{before}-{after}"
        root.mkdir()
        snapshot, reviews = case(previous=before, current=after)
        reviews[0].update(review_kind="regular_detail", current_review=None)
        p, _ = save_ledger(root, snapshot, reviews)
        result = save_report(root, p, snapshot, [change_alert(snapshot["episodes"][0], reviews[0])])
        md = Path(result.markdown_file).read_text()
        assert md.count("状态改变") == 1
        assert "状态变化复盘" in md and "简单复盘" in md


def test_T04_ended_requires_real_reason_not_price_or_quota(tmp_path):
    snapshot, reviews = case(previous="follow", current="ended")
    reviews[0].update(review_kind="regular_detail", current_review=None,
                      tracking_decision="stop_active_tracking", current_assessment="weakening",
                      tracking_decision_reason="只是没有达到目标")
    with pytest.raises(ValueError):
        save_ledger(tmp_path, snapshot, reviews)
    reviews[0].update(tracking_end_reason="thesis_invalidated", current_assessment="contradicted",
                      tracking_decision_reason="原撤回条件已按原口径确认")
    save_ledger(tmp_path, snapshot, reviews)


def test_T05_more_than_eight_true_changes_all_delivered(tmp_path):
    snapshot, reviews = case(12, previous="follow", current="wait")
    for review in reviews:
        review.update(review_kind="regular_detail", current_review=None)
    p, _ = save_ledger(tmp_path, snapshot, reviews)
    alerts = [change_alert(e, r) for e, r in zip(snapshot["episodes"], reviews)]
    result = save_report(tmp_path, p, snapshot, alerts)
    assert result.alert_count == 12
    assert Path(result.markdown_file).read_text().count("### 股票") == 12


def test_T06_checkpoint_without_transition_stays_short_and_keeps_facts(tmp_path):
    for day in (1, 3, 5, 10):
        root = tmp_path / f"D{day}"
        snapshot, reviews = case(previous="follow", current="follow", day=day)
        snapshot["episodes"][0]["current_close_return_since_entry"] = 0.07
        p, _ = save_ledger(root, snapshot, reviews)
        result = save_report(root, p, snapshot)
        md = Path(result.markdown_file).read_text()
        assert "简单复盘" in md and "关键节点复盘" not in md
        assert reviews[0]["checkpoint"] == f"D{day}"


def test_T07_d20_normal_completion_is_short_public_change_with_internal_final(tmp_path):
    snapshot, reviews = case(previous="follow", current="ended", day=20)
    snapshot["episodes"][0].update(final_review_pending=True, d20_close_return_since_entry=0.12)
    snapshot["required_final_review_episode_ids"] = [reviews[0]["episode_id"]]
    reviews[0].update(review_kind="regular_detail", current_review=None,
                      tracking_end_reason="observation_complete", tracking_decision="complete_observation",
                      final_twenty_day_review=legacy._final_review())
    p, _ = save_ledger(tmp_path, snapshot, reviews)
    result = save_report(tmp_path, p, snapshot, [change_alert(snapshot["episodes"][0], reviews[0], "观察期正常结束，结果已归档。")])
    md = Path(result.markdown_file).read_text()
    assert "观察期正常结束" in md and "20个交易日最终复盘" not in md
    assert fm.final_review_history(tmp_path / "local_archive/forward_monitor", date.fromisoformat(snapshot["analysis_date"]))[reviews[0]["episode_id"]]["report_delivered"]


def test_T08_early_ended_d20_only_internal_no_opportunity_or_public_body(tmp_path):
    snapshot, reviews = case(previous="ended", current="ended", day=20)
    snapshot["episodes"][0].update(final_review_pending=True, tracking_status="evaluation_only")
    snapshot["required_final_review_episode_ids"] = [reviews[0]["episode_id"]]
    reviews[0].update(review_kind="internal_only", current_review=None, current_opportunity=None,
                      tracking_end_reason="thesis_invalidated", tracking_decision="complete_observation",
                      final_twenty_day_review=legacy._final_review())
    p, _ = save_ledger(tmp_path, snapshot, reviews)
    result = save_report(tmp_path, p, snapshot)
    assert "股票1｜" not in Path(result.markdown_file).read_text()
    assert fm.final_review_history(tmp_path / "local_archive/forward_monitor", date.fromisoformat(snapshot["analysis_date"]))[reviews[0]["episode_id"]]["report_delivered"]


def test_T09_target_hit_not_auto_ended_and_approved_tail_keeps_d20():
    episode = {"monitor_phase": "passive_tail", "frozen_twenty_day_review": legacy._final_review(),
               "final_review_pending": False, "current_hit_20pct_close": True}
    prior = {"tracking_decision": "keep_active_tracking", "day_number": 20}
    assert fm._tracking_status(episode, prior) == "active"
    assert fm.state_change_kind("follow", "follow") == "brief"
    assert episode["frozen_twenty_day_review"] == legacy._final_review()


def test_T10_first_registration_is_not_mass_transition():
    snapshot, reviews = case(50, previous=None, current="follow")
    assert sum(fm.state_change_kind(None, r["tracking_state"]) == "regular_detail" for r in reviews) == 0
    assert all(e["previous_daily_formal_review"] is None for e in snapshot["episodes"])


def test_T11_ended_cannot_revive_old_episode(tmp_path):
    snapshot, reviews = case(previous="ended", current="follow")
    with pytest.raises(ValueError, match="ended"):
        save_ledger(tmp_path, snapshot, reviews)


def test_T12_missing_facts_preserve_last_state_date_without_today_confirmation(tmp_path):
    snapshot, reviews = case(previous="wait", current=None)
    reviews[0].update(current_assessment="insufficient_evidence", current_path="not_evaluable",
                      current_review="股票1｜今日资料待核实\n\n上次等待变化的判断日期为8月28日；今日缺可靠行情。")
    p, _ = save_ledger(tmp_path, snapshot, reviews)
    result = save_report(tmp_path, p, snapshot)
    assert "8月28日" in Path(result.markdown_file).read_text()
    assert fm.state_change_kind("wait", None) == "brief"


def test_T13_participation_change_does_not_force_state_transition(tmp_path):
    snapshot, reviews = case(previous="follow", current="follow")
    reviews[0]["current_opportunity"]["participation"] = "avoid"
    p, _ = save_ledger(tmp_path, snapshot, reviews)
    assert save_report(tmp_path, p, snapshot).alert_count == 0


def test_T14_final_history_does_not_use_later_as_of(tmp_path):
    snapshot, reviews = case(previous="ended", current="ended", day=20)
    snapshot["episodes"][0].update(final_review_pending=True, tracking_status="evaluation_only")
    snapshot["required_final_review_episode_ids"] = [reviews[0]["episode_id"]]
    reviews[0].update(review_kind="internal_only", current_review=None, current_opportunity=None,
                      tracking_end_reason="thesis_invalidated", tracking_decision="complete_observation",
                      final_twenty_day_review=legacy._final_review())
    p, _ = save_ledger(tmp_path, snapshot, reviews)
    save_report(tmp_path, p, snapshot)
    cutoff = datetime.fromisoformat(snapshot["as_of"])
    assert fm.final_review_history(tmp_path / "local_archive/forward_monitor", date.fromisoformat(snapshot["analysis_date"]), as_of=cutoff)
    assert not fm.final_review_history(tmp_path / "local_archive/forward_monitor", date.fromisoformat(snapshot["analysis_date"]), as_of=cutoff.replace(day=cutoff.day - 1))


def test_T15_knowledge_text_is_really_in_input_once_and_marked_fictional(tmp_path):
    snapshot, _ = case(50)
    install_knowledge(tmp_path)
    bundle = fm.build_state_change_input(snapshot, tmp_path)
    texts = [v["text"] for v in bundle["knowledge"].values()]
    assert len(texts) == 3
    assert sum("example_only: true" in x for x in texts) == 2
    assert "不是实际投资分析" in "".join(texts)
    assert json.dumps(bundle, ensure_ascii=False).count("状态变化复盘：范文与注意事项") == 1


def test_T16_new_policy_bound_old_saved_policy_preserved(tmp_path):
    snapshot, _ = case()
    snapshot["summary"]["checkpoint_review_stock_count"] = 0
    archive = tmp_path / "local_archive/forward_monitor"
    archive.mkdir(parents=True)
    saved = archive / f"snapshot-{snapshot['analysis_date']}.json"
    saved.write_text(json.dumps(snapshot, ensure_ascii=False))
    install_knowledge(tmp_path)
    result = fm.prepare_forward_monitor(analysis_date=date.fromisoformat(snapshot["analysis_date"]),
        as_of=datetime.fromisoformat(snapshot["as_of"]), project_root=tmp_path,
        monitor_review_policy=POLICY)
    assert result.status == "already_prepared" and Path(result.input_file).is_file()
    assert json.loads(saved.read_text()) == snapshot
    with pytest.raises(ValueError, match="same-date snapshot"):
        fm.prepare_forward_monitor(analysis_date=date.fromisoformat(snapshot["analysis_date"]),
            as_of=datetime.fromisoformat(snapshot["as_of"]), project_root=tmp_path)
    args = Namespace(recommendation_authoring_profile=None, no_fallback=None, provider=None)
    config = {"recommendation_authoring_profile": "astra-files-v1", "monitor_review_policy": POLICY}
    state = {}
    _, policy = stock_ai.nightly_run_policy(args, config, state, date(2026, 9, 26), new_task=True)
    assert policy["monitor_review_policy"] == POLICY
    old = {"run_policy": {"recommendation_authoring_profile": "astra-files-v1", "provider": "astra", "no_fallback": False}}
    _, saved = stock_ai.nightly_run_policy(args, config, old, date(2026, 9, 26), new_task=False)
    assert saved.get("monitor_review_policy") is None


def test_T17_fake_saved_body_reaches_markdown_and_web_once(tmp_path):
    snapshot, reviews = case(previous="follow", current="wait")
    reviews[0].update(review_kind="regular_detail", current_review=None)
    newer_episode = deepcopy(snapshot["episodes"][0])
    newer_episode.update(episode_id="formal:2026-08-25:000001.SZ:selected",
                         formation_date="2026-08-25", action_date="2026-08-26")
    newer_review = deepcopy(reviews[0])
    newer_review.update(episode_id=newer_episode["episode_id"], tracking_state="follow",
                        review_kind="brief", current_review=None)
    snapshot["episodes"].append(newer_episode)
    snapshot["daily_review_episode_ids"].append(newer_episode["episode_id"])
    reviews.append(newer_review)
    p, _ = save_ledger(tmp_path, snapshot, reviews)
    alert = change_alert(snapshot["episodes"][0], reviews[0])
    alert["episode_ids"].append(newer_episode["episode_id"])
    duplicate = deepcopy(alert["episode_reviews"][0])
    duplicate["episode_id"] = newer_episode["episode_id"]
    alert["episode_reviews"].append(duplicate)
    result = save_report(tmp_path, p, snapshot, [alert])
    md = Path(result.markdown_file).read_text()
    assert md.count("原相对优势减弱") == 1
    history = render_monitor_web.scan_history(tmp_path / "local_archive/forward_monitor", date.fromisoformat(snapshot["analysis_date"]))
    assert sum(row["copy"].count("原相对优势减弱") for rows in history.values() for row in rows) == 1
    assert history[reviews[0]["episode_id"]][-1]["trackingState"] == "wait"
    assert history[newer_episode["episode_id"]][-1]["trackingState"] == "follow"
    assert "状态变化复盘" in nightly_report.source_sections(tmp_path, snapshot["analysis_date"])[0]


def test_T18_normal_cli_policy_parses_without_model_or_profile_change():
    args = fm._parse_args(["prepare", "--analysis-date", "2026-09-21", "--as-of", "2026-09-21T18:30:00+08:00",
                           "--review-policy", POLICY])
    assert args.review_policy == POLICY
    assert "model" not in vars(args)
    assert "astra-files-v1" not in Path("tools/stock_ai.py").read_text().split("def write_monitor_prompt", 1)[1].split("def write_preopen_prompt", 1)[0]
