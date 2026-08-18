from datetime import date

import pandas as pd
import pytest

from stock_analyzer.storage.research_derived import (
    DerivedFeatureStore,
    stable_dataframe_content_hash,
)


FEATURE_SET = "market_technical"
ANALYSIS_DATE = date(2026, 7, 10)
FORMULA_VERSION = "technical-v1"


def _frame(*, score: float = 0.75) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"ts_code": "000002.SZ", "score": score - 0.1},
            {"ts_code": "000001.SZ", "score": score},
        ]
    )


def _commit(
    store: DerivedFeatureStore,
    frame: pd.DataFrame,
    *,
    input_hash: str = "sha-1",
    run_id: str = "derived-run-1",
):
    return store.commit(
        FEATURE_SET,
        ANALYSIS_DATE,
        FORMULA_VERSION,
        frame,
        input_manifest={"equity_daily": {"2026-07-10": input_hash}},
        entity_key="ts_code",
        quality_status="complete",
        run_id=run_id,
    )


def test_commit_keeps_formula_input_and_content_auditable(tmp_path):
    store = DerivedFeatureStore(tmp_path)

    result = _commit(store, _frame())

    pd.testing.assert_frame_equal(
        store.read(FEATURE_SET, ANALYSIS_DATE, FORMULA_VERSION),
        _frame().sort_values("ts_code").reset_index(drop=True),
    )
    manifest = store.partition_manifest(FEATURE_SET).iloc[0]
    assert manifest["formula_version"] == FORMULA_VERSION
    assert manifest["input_manifest_hash"] == result.input_manifest_hash
    assert manifest["content_hash"] == result.content_hash
    assert manifest["file_sha256"] == result.file_sha256


def test_same_visible_facts_skip_the_same_deterministic_result(tmp_path):
    store = DerivedFeatureStore(tmp_path)
    first = _commit(store, _frame())

    second = _commit(
        store,
        _frame().iloc[::-1],
        run_id="derived-run-retry",
    )

    assert second.skipped is True
    assert second.content_hash == first.content_hash
    assert second.file_sha256 == first.file_sha256


def test_same_visible_facts_reject_changed_output(tmp_path):
    store = DerivedFeatureStore(tmp_path)
    _commit(store, _frame())

    with pytest.raises(ValueError, match="deterministic conflict"):
        _commit(store, _frame(score=0.95), run_id="derived-run-conflict")


def test_new_visible_facts_replace_the_partition(tmp_path):
    store = DerivedFeatureStore(tmp_path)
    first = _commit(store, _frame())

    changed = _commit(
        store,
        _frame(score=0.95),
        input_hash="sha-2",
        run_id="derived-run-2",
    )

    assert changed.input_manifest_hash != first.input_manifest_hash
    current = store.read(FEATURE_SET, ANALYSIS_DATE, FORMULA_VERSION)
    assert current.loc[current["ts_code"] == "000001.SZ", "score"].iloc[0] \
        == pytest.approx(0.95)


def test_duplicate_entity_is_rejected(tmp_path):
    store = DerivedFeatureStore(tmp_path)
    duplicate = pd.concat([_frame(), _frame().iloc[[0]]], ignore_index=True)

    with pytest.raises(ValueError, match="duplicate entity key"):
        _commit(store, duplicate)


def test_content_hash_distinguishes_missing_and_non_finite_values():
    hashes = {
        stable_dataframe_content_hash(
            pd.DataFrame([{"ts_code": "000001.SZ", "value": value}])
        )
        for value in [None, float("nan"), float("inf"), float("-inf")]
    }

    assert len(hashes) == 4
