import json
from types import SimpleNamespace

from stock_analyzer.selection_lab.audit import scan_public_payload
from stock_analyzer.selection_lab.reporting import (
    REVIEW_FILENAMES,
    build_review_bundle,
    run_local_workflow,
)


def _blocked_state():
    return {
        "main_conclusion": "实验阻塞",
        "main_track_status": "unavailable",
        "main_track_reason_code": "no_frozen_candidate_chain",
        "gate_conclusion": "not_evaluable",
        "data_through": "2026-08-14",
    }


def test_blocked_bundle_writes_all_public_files(tmp_path):
    paths = build_review_bundle(_blocked_state(), tmp_path)

    assert {path.name for path in paths} == set(REVIEW_FILENAMES)
    assert all(path.exists() for path in paths)
    baseline = json.loads((tmp_path / "baseline_metrics.json").read_text())
    assert baseline["policy_precision_at_5"] is None
    assert baseline["reason_code"] == "no_frozen_candidate_chain"
    rank_examples = json.loads((tmp_path / "rank_examples.json").read_text())
    assert rank_examples["examples"] == []
    assert rank_examples["reason_code"] == "no_frozen_candidate_chain"


def test_bundle_is_byte_identical_across_runs(tmp_path):
    first = tmp_path / "first"
    second = tmp_path / "second"
    build_review_bundle(_blocked_state(), first)
    build_review_bundle(_blocked_state(), second)

    for filename in REVIEW_FILENAMES:
        assert (first / filename).read_bytes() == (second / filename).read_bytes()


def test_bundle_payloads_pass_public_audit(tmp_path):
    paths = build_review_bundle(_blocked_state(), tmp_path)

    for path in paths:
        if path.suffix == ".json":
            assert scan_public_payload(json.loads(path.read_text())) == []


def test_review_workflow_preserves_frozen_preregistration(tmp_path):
    review = tmp_path / "docs" / "selection_lab" / "review"
    review.mkdir(parents=True)
    marker = {"status": "frozen", "formation_dates": ["2026-01-05"]}
    (review / "split_manifest.json").write_text(json.dumps(marker))
    config = SimpleNamespace(
        project_root=tmp_path,
        local_archive_dir=tmp_path / "archive",
    )

    run_local_workflow("build-review-bundle", config)

    assert json.loads((review / "split_manifest.json").read_text()) == marker
