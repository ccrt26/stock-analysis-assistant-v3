import json

import pandas as pd
import pytest

from stock_analyzer.selection_lab.feature_builder import (
    build_model_frame,
    load_feature_dictionary,
)


def _dictionary(tmp_path):
    payload = {
        "feature_groups": {
            "numeric": {
                "columns": ["price_relative_return_5d", "company_event_age_days"],
                "type": "numeric",
            },
            "categorical": {
                "columns": ["company_event_type"],
                "type": "categorical",
            },
            "opportunity_type": {
                "columns": ["opportunity_type"],
                "type": "categorical_typed_model_only",
            },
        },
        "forbidden_columns": [
            "ts_code",
            "current_ai_fate",
            "executable_on_action_date",
            "hit_20pct_close_within_20d",
        ],
    }
    path = tmp_path / "features.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return load_feature_dictionary(path)


def test_forbidden_feature_request_is_rejected(tmp_path):
    dictionary = _dictionary(tmp_path)
    frame = pd.DataFrame({"ts_code": ["000001.SZ"]})

    with pytest.raises(ValueError, match="forbidden"):
        build_model_frame(frame, dictionary, requested_columns=["ts_code"])


def test_unknown_feature_request_is_rejected(tmp_path):
    dictionary = _dictionary(tmp_path)
    frame = pd.DataFrame({"unknown": [1.0]})

    with pytest.raises(ValueError, match="not preregistered"):
        build_model_frame(frame, dictionary, requested_columns=["unknown"])


def test_model_frame_preserves_dictionary_order(tmp_path):
    dictionary = _dictionary(tmp_path)
    frame = pd.DataFrame(
        {
            "company_event_age_days": [3],
            "price_relative_return_5d": [0.1],
            "company_event_type": ["forecast"],
            "opportunity_type": ["company_catalyst"],
        }
    )

    result = build_model_frame(frame, dictionary, include_opportunity_type=False)

    assert result.numeric_columns == [
        "price_relative_return_5d",
        "company_event_age_days",
    ]
    assert result.categorical_columns == ["company_event_type"]
    assert "opportunity_type" not in result.frame


def test_typed_model_adds_only_opportunity_type(tmp_path):
    dictionary = _dictionary(tmp_path)
    frame = pd.DataFrame(
        {
            "price_relative_return_5d": [0.1],
            "company_event_age_days": [3],
            "company_event_type": ["forecast"],
            "opportunity_type": ["company_catalyst"],
        }
    )

    plain = build_model_frame(frame, dictionary, include_opportunity_type=False)
    typed = build_model_frame(frame, dictionary, include_opportunity_type=True)

    assert typed.numeric_columns == plain.numeric_columns
    assert typed.categorical_columns == plain.categorical_columns + [
        "opportunity_type"
    ]
