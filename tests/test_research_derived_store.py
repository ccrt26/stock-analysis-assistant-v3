from datetime import date

import pandas as pd
import pytest

from stock_analyzer.storage import research_derived as research_derived_module
from stock_analyzer.storage.research_derived import DerivedFeatureStore


FEATURE_SET = "market_technical"
ANALYSIS_DATE = date(2026, 7, 10)
FORMULA_VERSION = "technical-v1"


def _frame(*, score: float = 0.75) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"ts_code": "000002.SZ", "score": score - 0.1, "signal": "watch"},
            {"ts_code": "000001.SZ", "score": score, "signal": "buy"},
        ]
    )


def _commit(
    store: DerivedFeatureStore,
    frame: pd.DataFrame,
    *,
    input_manifest: dict | None = None,
    run_id: str = "derived-run-1",
):
    return store.commit(
        FEATURE_SET,
        ANALYSIS_DATE,
        FORMULA_VERSION,
        frame,
        input_manifest=input_manifest
        or {"equity_daily": {"2026-07-10": "sha-1"}},
        entity_key=("ts_code",),
        quality_status="complete",
        limitations=(),
        run_id=run_id,
    )


def test_valid_frame_is_atomically_promoted_readable_and_governed(tmp_path):
    store = DerivedFeatureStore(tmp_path)

    result = _commit(store, _frame())

    expected_path = (
        tmp_path
        / "derived"
        / FEATURE_SET
        / "analysis_date=2026-07-10"
        / f"formula_version={FORMULA_VERSION}"
        / "data.parquet"
    )
    assert expected_path.is_file()
    assert not list((tmp_path / ".staging").rglob("*.parquet"))
    pd.testing.assert_frame_equal(
        store.read(FEATURE_SET, ANALYSIS_DATE, FORMULA_VERSION),
        _frame().sort_values("ts_code").reset_index(drop=True),
    )

    manifest = store.partition_manifest(FEATURE_SET)
    assert manifest["row_count"].tolist() == [2]
    assert manifest["file_sha256"].tolist() == [result.file_sha256]
    assert manifest["content_hash"].tolist() == [result.content_hash]
    assert manifest["input_manifest_hash"].tolist() == [
        result.input_manifest_hash
    ]
    assert result.idempotent is False
    assert result.skipped is False


def test_same_input_and_output_retry_is_idempotent_without_rewrite(
    tmp_path, monkeypatch
):
    store = DerivedFeatureStore(tmp_path)
    first = _commit(
        store,
        _frame(),
        input_manifest={"b": {"partition": "sha-b"}, "a": ["sha-a"]},
    )

    def fail_if_rewritten(*args, **kwargs):
        raise AssertionError("idempotent retry must not stage parquet")

    monkeypatch.setattr(
        research_derived_module, "write_staged_parquet", fail_if_rewritten
    )
    reordered = _frame().iloc[::-1][["signal", "score", "ts_code"]]
    second = _commit(
        store,
        reordered,
        input_manifest={"a": ["sha-a"], "b": {"partition": "sha-b"}},
    )

    assert second.content_hash == first.content_hash
    assert second.file_sha256 == first.file_sha256
    assert second.input_manifest_hash == first.input_manifest_hash
    assert second.idempotent is True
    assert second.skipped is True


def test_changed_input_replaces_only_its_formula_date_partition(tmp_path):
    store = DerivedFeatureStore(tmp_path)
    original = _commit(store, _frame())
    other = store.commit(
        FEATURE_SET,
        ANALYSIS_DATE,
        "technical-v2",
        _frame(score=0.5),
        input_manifest={"equity_daily": {"2026-07-10": "sha-1"}},
        entity_key="ts_code",
        quality_status="limited",
        limitations=("minute bars unavailable",),
        run_id="derived-run-other",
    )

    changed = _commit(
        store,
        _frame(score=0.9),
        input_manifest={"equity_daily": {"2026-07-10": "sha-2"}},
        run_id="derived-run-2",
    )

    assert changed.input_manifest_hash != original.input_manifest_hash
    assert store.read(FEATURE_SET, ANALYSIS_DATE, FORMULA_VERSION).loc[
        lambda frame: frame["ts_code"] == "000001.SZ", "score"
    ].iloc[0] == pytest.approx(0.9)
    assert store.read(FEATURE_SET, ANALYSIS_DATE, "technical-v2").loc[
        lambda frame: frame["ts_code"] == "000001.SZ", "score"
    ].iloc[0] == pytest.approx(0.5)
    manifest = store.partition_manifest(FEATURE_SET)
    other_manifest = manifest.loc[manifest["formula_version"] == "technical-v2"]
    assert other_manifest["file_sha256"].tolist() == [other.file_sha256]


def test_duplicate_output_entity_key_is_rejected_before_writing(tmp_path):
    store = DerivedFeatureStore(tmp_path)
    duplicate = pd.concat([_frame(), _frame().iloc[[0]]], ignore_index=True)

    with pytest.raises(ValueError, match="duplicate entity key"):
        _commit(store, duplicate)

    assert not list((tmp_path / "derived").rglob("*.parquet"))


@pytest.mark.parametrize("failure_point", ["promotion", "metadata"])
def test_failed_commit_leaves_previous_partition_readable(
    tmp_path, monkeypatch, failure_point
):
    store = DerivedFeatureStore(tmp_path)
    first = _commit(store, _frame())

    if failure_point == "promotion":
        def fail(*args, **kwargs):
            raise RuntimeError("simulated promotion failure")

        monkeypatch.setattr(store, "_promote_staged_partition", fail)
    else:
        def fail(*args, **kwargs):
            raise RuntimeError("simulated metadata failure")

        monkeypatch.setattr(store, "_commit_metadata", fail)

    with pytest.raises(RuntimeError, match="simulated"):
        _commit(
            store,
            _frame(score=0.95),
            input_manifest={"equity_daily": {"2026-07-10": "sha-new"}},
            run_id=f"derived-run-failed-{failure_point}",
        )

    current = store.read(FEATURE_SET, ANALYSIS_DATE, FORMULA_VERSION)
    assert current.loc[current["ts_code"] == "000001.SZ", "score"].iloc[0] \
        == pytest.approx(0.75)
    manifest = store.partition_manifest(FEATURE_SET)
    assert manifest["content_hash"].tolist() == [first.content_hash]


def test_failed_quality_status_is_rejected_before_staging(tmp_path, monkeypatch):
    store = DerivedFeatureStore(tmp_path)

    def fail_if_staged(*args, **kwargs):
        raise AssertionError("failed output must not stage parquet")

    monkeypatch.setattr(
        research_derived_module, "write_staged_parquet", fail_if_staged
    )
    with pytest.raises(ValueError, match="failed quality status"):
        store.commit(
            FEATURE_SET,
            ANALYSIS_DATE,
            FORMULA_VERSION,
            _frame(),
            input_manifest={},
            entity_key=("ts_code",),
            quality_status="failed",
            limitations=("input gap",),
            run_id="derived-run-failed",
        )
