from __future__ import annotations

from datetime import date
from typing import Iterable, Mapping


REGISTERED_FORMATION_DATES: dict[str, tuple[str, ...]] = {
    "development": (
        "2025-12-30",
        "2026-01-05", "2026-01-06", "2026-01-07", "2026-01-08",
        "2026-01-09", "2026-01-12", "2026-01-13", "2026-01-14",
        "2026-01-15", "2026-01-16", "2026-01-19", "2026-01-22",
        "2026-01-23", "2026-01-27", "2026-01-28", "2026-01-29",
        "2026-01-30", "2026-02-02", "2026-02-03", "2026-02-04",
        "2026-02-05", "2026-02-06", "2026-02-10", "2026-02-11",
        "2026-02-12", "2026-02-13", "2026-02-26", "2026-03-02",
        "2026-03-04",
    ),
    "validation": (
        "2026-04-02", "2026-04-03", "2026-04-09", "2026-04-10",
        "2026-04-13", "2026-04-14", "2026-04-15", "2026-04-16",
        "2026-04-17", "2026-04-20",
    ),
    "final_test": (
        "2026-05-26", "2026-06-02", "2026-06-04", "2026-06-05",
        "2026-06-12", "2026-06-16", "2026-06-22", "2026-06-29",
        "2026-07-01", "2026-07-02",
    ),
}


_REGISTERED_BOUNDARIES = {
    "development": {
        "first_formation_date": "2025-12-30",
        "last_formation_date": "2026-03-04",
        "last_action_date": "2026-03-05",
        "last_label_date": "2026-04-01",
    },
    "validation": {
        "first_formation_date": "2026-04-02",
        "last_formation_date": "2026-04-20",
        "last_action_date": "2026-04-21",
        "last_label_date": "2026-05-21",
    },
    "final_test": {
        "first_formation_date": "2026-05-26",
        "last_formation_date": "2026-07-02",
        "last_action_date": "2026-07-03",
        "last_label_date": "2026-07-30",
    },
}


def label_window(
    formation_date: date,
    trading_sessions: Iterable[date],
) -> tuple[date, date]:
    sessions = sorted(set(trading_sessions))
    if formation_date not in sessions:
        raise ValueError("formation date is not an open trading session")
    position = sessions.index(formation_date)
    if position + 20 >= len(sessions):
        raise ValueError("trade calendar does not cover the 20-day label window")
    return sessions[position + 1], sessions[position + 20]


def build_registered_split_manifest() -> dict[str, object]:
    manifest: dict[str, object] = {
        name: {
            **values,
            "formation_dates": list(REGISTERED_FORMATION_DATES[name]),
        }
        for name, values in _REGISTERED_BOUNDARIES.items()
    }
    manifest["embargo_open_days"] = {
        "development_to_validation": 20,
        "validation_to_final_test": 22,
    }
    manifest["label_reveal_state"] = {
        "features_frozen": False,
        "development_labels_opened": False,
        "validation_labels_opened": False,
        "final_test_labels_opened": False,
    }
    return manifest


def assert_non_overlapping_label_windows(
    manifest: Mapping[str, object],
) -> None:
    development = manifest["development"]
    validation = manifest["validation"]
    final_test = manifest["final_test"]
    if not isinstance(development, Mapping) or not isinstance(validation, Mapping):
        raise TypeError("split manifest entries must be mappings")
    if not isinstance(final_test, Mapping):
        raise TypeError("split manifest entries must be mappings")
    if str(development["last_label_date"]) >= str(
        validation["first_formation_date"]
    ):
        raise ValueError("development and validation label windows overlap")
    if str(validation["last_label_date"]) >= str(
        final_test["first_formation_date"]
    ):
        raise ValueError("validation and final-test label windows overlap")
