import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from stock_analyzer.selection_lab.dataset_builder import (
    SelectionDatasetBuilder,
    validate_final_test_reveal,
)


def test_preflight_reports_current_main_track_and_universe_blockers(tmp_path):
    builder = SelectionDatasetBuilder(
        warehouse_root=tmp_path / "warehouse",
        archive_root=tmp_path / "archive",
        models_root=tmp_path / "models",
        candidate_chain_root=tmp_path / "candidate-chains",
        security_master_earliest_available_at=datetime(
            2026, 7, 13, 23, 38, tzinfo=ZoneInfo("Asia/Shanghai")
        ),
    )

    capabilities = builder.preflight()

    assert capabilities.tracks["frozen_candidate_chain"].reason_code == (
        "no_frozen_candidate_chain"
    )
    assert capabilities.tracks["full_universe"].reason_code == (
        "point_in_time_security_master_unavailable"
    )
    assert capabilities.main_conclusion == "实验阻塞"


def test_security_master_must_cover_earliest_registered_formation_date(tmp_path):
    builder = SelectionDatasetBuilder(
        warehouse_root=tmp_path / "warehouse",
        archive_root=tmp_path / "archive",
        models_root=tmp_path / "models",
        candidate_chain_root=tmp_path / "candidate-chains",
        security_master_earliest_available_at=datetime(
            2026, 6, 1, 0, 0, tzinfo=ZoneInfo("Asia/Shanghai")
        ),
    )

    capabilities = builder.preflight()

    assert capabilities.tracks["full_universe"].status == "blocked"


def test_candidate_chain_requires_machine_freeze_marker(tmp_path):
    root = tmp_path / "candidate-chains"
    root.mkdir()
    (root / "bad.json").write_text(
        json.dumps({"formation_date": "2026-01-05", "candidate_chain": {}}),
        encoding="utf-8",
    )
    builder = SelectionDatasetBuilder(
        warehouse_root=tmp_path / "warehouse",
        archive_root=tmp_path / "archive",
        models_root=tmp_path / "models",
        candidate_chain_root=root,
        security_master_earliest_available_at=None,
    )

    capabilities = builder.preflight()

    assert capabilities.tracks["frozen_candidate_chain"].status == "unavailable"


def test_final_test_labels_require_all_matching_freeze_hashes():
    freeze = {
        "features_frozen": True,
        "split_hash": "split",
        "feature_dictionary_hash": "features",
        "model_variant": "without_opportunity_type",
        "C": 1.0,
        "threshold": 0.5,
    }

    validate_final_test_reveal(freeze, expected_hashes={
        "split_hash": "split",
        "feature_dictionary_hash": "features",
    })


def test_final_test_labels_reject_missing_threshold():
    freeze = {
        "features_frozen": True,
        "split_hash": "split",
        "feature_dictionary_hash": "features",
        "model_variant": "without_opportunity_type",
        "C": 1.0,
        "threshold": None,
    }

    with pytest.raises(ValueError, match="threshold"):
        validate_final_test_reveal(freeze, expected_hashes={
            "split_hash": "split",
            "feature_dictionary_hash": "features",
        })


def test_local_artifact_paths_stay_below_configured_roots(tmp_path):
    builder = SelectionDatasetBuilder(
        warehouse_root=tmp_path / "warehouse",
        archive_root=tmp_path / "archive",
        models_root=tmp_path / "models",
        candidate_chain_root=tmp_path / "candidate-chains",
        security_master_earliest_available_at=None,
    )

    paths = builder.artifact_paths("development")

    assert paths.features.parent == tmp_path / "warehouse" / "selection_lab"
    assert paths.labels.parent == tmp_path / "archive" / "selection_lab"
    assert paths.model.parent == tmp_path / "models" / "selection_lab"
