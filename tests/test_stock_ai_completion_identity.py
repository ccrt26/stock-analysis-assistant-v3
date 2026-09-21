"""Final status and saved-result recovery; no real models or external services."""
import copy
import datetime as dt
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import stock_ai as s

PROFILE = "astra-files-v1"
FORMATION = "2026-09-21"
ACTION = "2026-09-22"
CUTOFF = "2026-09-21T18:30:00+08:00"
STATE_NAME = "nightly-rerun-2026-09-22.json"


def evidence(effort, session):
    provider, model, request = s.EXPECTED_MODEL_EVIDENCE["astra"]
    return dict(verified=True, consistent=True, provider=provider, model=model,
                request_model=request, effort=effort, auth_method="chatgpt",
                session_id=session,
                context_evidence=dict(verified=True, isolated=True,
                                      input_present=True, tool_calls=0))


def saved_state(profile=PROFILE):
    primary_effort = "xhigh" if profile == PROFILE else "high"
    primary = evidence(primary_effort, "synthetic-research")
    stages = []
    for name, effort in [("research", primary_effort), ("monitor", "high"),
                         ("author-000991-SZ", primary_effort),
                         ("review-000991-SZ", primary_effort),
                         ("company-introductions", "high")]:
        stages.append(dict(stage=name, provider="astra", status="completed",
                           configured_model=primary["model"], configured_effort=effort,
                           profile=PROFILE if effort == "xhigh" else None,
                           file_stage=name.startswith(("author-", "review-")),
                           fallback=False, evidence=evidence(effort, "synthetic-" + name)))
    return dict(task="nightly", slot_date=FORMATION, rerun_date=ACTION,
                formation_date=FORMATION, action_date=ACTION, selection_as_of=CUTOFF,
                status="failed", attempts=[dict(provider="astra", outcome="success")],
                model_provider="astra", last_model=primary["model"], model_evidence=primary,
                model_expectation=dict(provider="astra", configured_model=primary["model"],
                                       configured_effort=primary_effort, profile=profile),
                run_policy=dict(provider="astra", no_fallback=True,
                                recommendation_authoring_profile=profile),
                recommendation_stages=stages, company_introduction_pending=False,
                company_introductions=dict(status="finished", missing=[]),
                prepare=dict(status="ready_for_research", formation_date=FORMATION,
                             action_date=ACTION, selection_as_of=CUTOFF),
                result=dict(status="完成但模型身份待核对", detail="Synthetic prior false alarm"))


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    archive = tmp_path / "local_archive/ai_tasks"
    monkeypatch.setattr(s, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(s, "AI_ARCHIVE_DIR", archive)
    monkeypatch.setattr(s, "STATE_DIR", archive / "state")
    monkeypatch.setattr(s, "LOG_DIR", tmp_path / "logs/ai_tasks")
    monkeypatch.setattr(s, "INDEX_PATH", archive / "index.jsonl")
    monkeypatch.setattr(s, "_LAST_STATE_PATH", None)
    entries = []
    monkeypatch.setattr(s, "append_index", lambda row: entries.append(copy.deepcopy(row)))
    monkeypatch.setattr(s, "refresh_terminal_display", lambda *a, **k: None)
    monkeypatch.setattr(s, "mac_notify_result", lambda *a, **k: {"notified": False})
    # This test targets completion classification, not the independently-tested
    # financial validators or browser renderer. Do not mock the classifier,
    # finish_nightly_success, finish_task, run_nightly, or state persistence.
    monkeypatch.setattr(s, "assemble_saved_reply", lambda *a, **k: None)
    monkeypatch.setattr(s, "verify_assembled_reply", lambda *a, **k: (True, [], {}))
    monkeypatch.setattr(s, "sync_accepted_report", lambda *a, **k: (True, "unchanged"))

    def forbidden(*a, **k):
        pytest.fail("Completed results must not launch any model or repeat prepare")

    for name in ("run_agent", "run_task_agent", "run_prepare", "run_pre_research_stage",
                 "run_managed_company_introductions"):
        monkeypatch.setattr(s, name, forbidden)
    return tmp_path, entries


def finish(root, state):
    source = root / "retained-reviewed-reply.md"
    source.write_text("Synthetic retained report.\n", encoding="utf-8")
    directory = s.AI_ARCHIVE_DIR / "nightly" / ("rerun-" + ACTION)
    target = directory / "final-reply.md"
    result = s.finish_nightly_success(state, STATE_NAME, "astra", source,
                                      FORMATION, ACTION, CUTOFF, directory, target)
    assert target.read_bytes() == source.read_bytes()
    return result


def test_new_profile_mixed_efforts_complete_at_outer_entry(isolated):
    root, entries = isolated
    state = saved_state()
    assert s.state_route_evidence_matches(state) is True
    assert finish(root, state) == s.EXIT_OK
    assert state["status"] == "completed"
    assert state["result"]["status"] == "完整完成"
    assert entries[-1]["result_status"] == "完整完成"


def test_legacy_high_profile_still_completes(isolated):
    root, _ = isolated
    state = saved_state(profile=None)
    assert finish(root, state) == s.EXIT_OK
    assert state["result"]["status"] == "完整完成"


def test_wrong_research_effort_is_not_accepted(isolated):
    root, _ = isolated
    state = saved_state()
    state["model_evidence"]["effort"] = "high"
    state["recommendation_stages"][0]["evidence"]["effort"] = "high"
    assert finish(root, state) == s.EXIT_FAIL
    assert state["result"]["status"] == "完成但模型身份待核对"


def test_wrong_actual_model_in_one_stage_is_not_accepted(isolated):
    root, _ = isolated
    state = saved_state()
    state["recommendation_stages"][2]["evidence"]["request_model"] = "wrong-model"
    assert finish(root, state) == s.EXIT_FAIL
    assert state["result"]["status"] == "完成但模型身份待核对"


def test_unverified_evidence_is_not_promoted_to_success(isolated):
    root, _ = isolated
    state = saved_state()
    state["model_evidence"]["verified"] = False
    assert finish(root, state) == s.EXIT_FAIL
    assert state["result"]["status"] == "完成但模型身份待核对"


def test_saved_false_alarm_recovers_without_models_or_content_changes(isolated, monkeypatch):
    root, entries = isolated
    state = saved_state()
    directory = s.AI_ARCHIVE_DIR / "nightly" / ("rerun-" + ACTION)
    directory.mkdir(parents=True)
    target = directory / "final-reply.md"
    target.write_text("Previously completed report, do not regenerate.\n", encoding="utf-8")
    state["final_reply"] = str(target.relative_to(root))
    state["archive"] = str(directory.relative_to(root))
    path = s.STATE_DIR / STATE_NAME
    s.save_state(path, state)
    before = copy.deepcopy(state)
    report_before = target.read_bytes()
    # Stored prepare/financial artifacts stand in for local data. The actual
    # existing task routing, policy binding, status classifier and save run here.
    monkeypatch.setattr(s, "valid_prepare_summary", lambda *a, **k: True)
    monkeypatch.setattr(s, "prepare_arguments_ok", lambda *a, **k: True)
    monkeypatch.setattr(s, "assess_artifacts", lambda *a, **k: dict(
        trace_ok=True, csv_ok=True, ledger_ok=True, report_ok=True, reply_ok=True))
    args = s.build_parser().parse_args(["run", "nightly", "--rerun-date", ACTION])
    now = dt.datetime(2026, 9, 23, 0, 5, tzinfo=s.SHANGHAI)
    assert s.run_nightly(args, {}, None, now=now) == s.EXIT_OK
    after = json.loads(path.read_text(encoding="utf-8"))
    assert after["status"] == "completed"
    assert after["result"]["status"] == "完整完成"
    for key in ("attempts", "recommendation_stages", "model_evidence", "model_expectation", "run_policy"):
        assert after[key] == before[key]
    assert target.read_bytes() == report_before
    assert entries[-1]["result_status"] == "完整完成"
    # An additional invocation is idempotent and is not another business run.
    assert s.run_nightly(args, {}, None, now=now) == s.EXIT_OK
    again = json.loads(path.read_text(encoding="utf-8"))
    assert again["recommendation_stages"] == before["recommendation_stages"]
    assert target.read_bytes() == report_before
