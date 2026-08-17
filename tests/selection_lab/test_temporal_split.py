from datetime import date, timedelta

import pytest

from stock_analyzer.selection_lab.temporal_split import (
    REGISTERED_FORMATION_DATES,
    assert_non_overlapping_label_windows,
    build_registered_split_manifest,
    label_window,
)


def test_action_date_and_twentieth_day_count_action_as_day_one():
    sessions = [date(2026, 1, 1) + timedelta(days=offset) for offset in range(30)]

    action_date, label_end = label_window(date(2026, 1, 1), sessions)

    assert action_date == date(2026, 1, 2)
    assert label_end == date(2026, 1, 21)


def test_label_window_rejects_non_session_formation_date():
    sessions = [date(2026, 1, day) for day in range(2, 25)]

    with pytest.raises(ValueError, match="formation date"):
        label_window(date(2026, 1, 1), sessions)


def test_registered_split_has_exact_date_counts_and_boundaries():
    manifest = build_registered_split_manifest()

    assert {key: len(values) for key, values in REGISTERED_FORMATION_DATES.items()} == {
        "development": 30,
        "validation": 10,
        "final_test": 10,
    }
    assert manifest["development"]["last_label_date"] == "2026-04-01"
    assert manifest["validation"]["first_formation_date"] == "2026-04-02"
    assert manifest["validation"]["last_label_date"] == "2026-05-21"
    assert manifest["final_test"]["first_formation_date"] == "2026-05-26"
    assert manifest["final_test"]["last_label_date"] == "2026-07-30"
    assert manifest["embargo_open_days"] == {
        "development_to_validation": 20,
        "validation_to_final_test": 22,
    }


def test_registered_split_windows_do_not_overlap():
    manifest = build_registered_split_manifest()

    assert_non_overlapping_label_windows(manifest)


def test_overlap_guard_rejects_equal_boundary():
    manifest = build_registered_split_manifest()
    manifest["validation"]["first_formation_date"] = manifest["development"][
        "last_label_date"
    ]

    with pytest.raises(ValueError, match="overlap"):
        assert_non_overlapping_label_windows(manifest)


def test_all_reveal_flags_start_closed():
    manifest = build_registered_split_manifest()

    assert manifest["label_reveal_state"] == {
        "features_frozen": False,
        "development_labels_opened": False,
        "validation_labels_opened": False,
        "final_test_labels_opened": False,
    }
