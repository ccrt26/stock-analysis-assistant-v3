import json
import os
import threading
from datetime import date

import pandas as pd
import pytest

from stock_analyzer.storage import research_derived as research_derived_module
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
            {"ts_code": "000002.SZ", "score": score - 0.1, "signal": "watch"},
            {"ts_code": "000001.SZ", "score": score, "signal": "buy"},
        ]
    )


def _commit(
    store: DerivedFeatureStore,
    frame: pd.DataFrame,
    *,
    input_manifest: dict | None = None,
    quality_status: str = "complete",
    limitations: tuple[str, ...] = (),
    run_id: str = "derived-run-1",
):
    return store.commit(
        FEATURE_SET,
        ANALYSIS_DATE,
        FORMULA_VERSION,
        frame,
        input_manifest=(
            {"equity_daily": {"2026-07-10": "sha-1"}}
            if input_manifest is None
            else input_manifest
        ),
        entity_key=("ts_code",),
        quality_status=quality_status,
        limitations=limitations,
        run_id=run_id,
    )


def _final_path(root):
    return (
        root
        / "derived"
        / FEATURE_SET
        / "analysis_date=2026-07-10"
        / f"formula_version={FORMULA_VERSION}"
        / "data.parquet"
    )


def test_valid_frame_is_atomically_promoted_readable_and_governed(tmp_path):
    store = DerivedFeatureStore(tmp_path)

    result = _commit(store, _frame())

    expected_path = _final_path(tmp_path)
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


@pytest.mark.parametrize(
    ("changed_frame", "quality_status", "limitations"),
    [
        (_frame(score=0.95), "complete", ()),
        (_frame(), "limited", ()),
        (_frame(), "complete", ("new limitation",)),
    ],
    ids=["content", "quality_status", "limitations"],
)
def test_same_input_manifest_rejects_nondeterministic_partition_change(
    tmp_path, changed_frame, quality_status, limitations
):
    store = DerivedFeatureStore(tmp_path)
    original = _commit(store, _frame())

    with pytest.raises(ValueError, match="deterministic conflict"):
        _commit(
            store,
            changed_frame,
            quality_status=quality_status,
            limitations=limitations,
            run_id="derived-run-conflict",
        )

    current = store.read(FEATURE_SET, ANALYSIS_DATE, FORMULA_VERSION)
    assert current.loc[current["ts_code"] == "000001.SZ", "score"].iloc[0] \
        == pytest.approx(0.75)
    assert store.partition_manifest(FEATURE_SET)["content_hash"].tolist() == [
        original.content_hash
    ]


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


def test_second_promotion_step_failure_never_hides_previous_file(
    tmp_path, monkeypatch
):
    store = DerivedFeatureStore(tmp_path)
    _commit(store, _frame())
    final_path = _final_path(tmp_path)
    backup_path = final_path.with_suffix(".parquet.previous")
    real_replace = os.replace
    observed_old_file_during_replace = False

    def fail_staged_replace(source, destination):
        nonlocal observed_old_file_during_replace
        if destination == final_path and source != backup_path:
            assert final_path.is_file(), "previous partition disappeared"
            current = pd.read_parquet(final_path)
            assert current.loc[
                current["ts_code"] == "000001.SZ", "score"
            ].iloc[0] == pytest.approx(0.75)
            observed_old_file_during_replace = True
            raise RuntimeError("simulated staged replace failure")
        return real_replace(source, destination)

    monkeypatch.setattr(os, "replace", fail_staged_replace)
    with pytest.raises(RuntimeError, match="simulated staged replace failure"):
        _commit(
            store,
            _frame(score=0.95),
            input_manifest={"equity_daily": {"2026-07-10": "sha-new"}},
            run_id="derived-run-replace-failure",
        )

    assert observed_old_file_during_replace is True
    assert not backup_path.exists()
    current = store.read(FEATURE_SET, ANALYSIS_DATE, FORMULA_VERSION)
    assert current.loc[current["ts_code"] == "000001.SZ", "score"].iloc[0] \
        == pytest.approx(0.75)


def test_initialization_recovers_crash_after_file_replace_before_metadata(
    tmp_path
):
    store = DerivedFeatureStore(tmp_path)
    original = _commit(store, _frame())
    final_path = _final_path(tmp_path)
    staged_path = tmp_path / ".staging" / "crashed-run" / "data.parquet"
    new_sha256 = research_derived_module.write_staged_parquet(
        staged_path,
        _frame(score=0.95).sort_values("ts_code").reset_index(drop=True),
    )

    promotion = store._promote_staged_partition(
        staged_path,
        final_path,
        old_metadata_sha256=original.file_sha256,
        new_file_sha256=new_sha256,
    )
    backup_path = promotion.backup_path
    assert backup_path is not None and backup_path.is_file()

    recovered = DerivedFeatureStore(tmp_path)

    assert not backup_path.exists()
    current = recovered.read(FEATURE_SET, ANALYSIS_DATE, FORMULA_VERSION)
    assert current.loc[current["ts_code"] == "000001.SZ", "score"].iloc[0] \
        == pytest.approx(0.75)
    assert recovered.partition_manifest(FEATURE_SET)["file_sha256"].tolist() \
        == [original.file_sha256]


def test_initialization_removes_first_commit_orphan_using_durable_journal(
    tmp_path
):
    store = DerivedFeatureStore(tmp_path)
    final_path = _final_path(tmp_path)
    staged_path = tmp_path / ".staging" / "first-crashed-run" / "data.parquet"
    new_sha256 = research_derived_module.write_staged_parquet(
        staged_path,
        _frame().sort_values("ts_code").reset_index(drop=True),
    )

    promotion = store._promote_staged_partition(
        staged_path,
        final_path,
        old_metadata_sha256=None,
        new_file_sha256=new_sha256,
    )
    journal = json.loads(promotion.journal_path.read_text(encoding="utf-8"))

    assert journal == {
        "backup_relative_path": None,
        "final_relative_path": final_path.relative_to(tmp_path).as_posix(),
        "new_file_sha256": new_sha256,
        "old_metadata_sha256": None,
        "version": 1,
    }
    assert store.read(FEATURE_SET, ANALYSIS_DATE, FORMULA_VERSION).empty

    recovered = DerivedFeatureStore(tmp_path)

    assert recovered.read(FEATURE_SET, ANALYSIS_DATE, FORMULA_VERSION).empty
    assert not final_path.exists()
    assert not promotion.journal_path.exists()


def test_initialization_finalizes_crash_after_metadata_before_backup_delete(
    tmp_path, monkeypatch
):
    store = DerivedFeatureStore(tmp_path)
    _commit(store, _frame())
    final_path = _final_path(tmp_path)
    backup_path = final_path.with_suffix(".parquet.previous")

    with monkeypatch.context() as context:
        def simulate_crash(*args, **kwargs):
            raise RuntimeError("simulated crash before backup delete")

        context.setattr(research_derived_module, "discard_backup", simulate_crash)
        with pytest.raises(RuntimeError, match="simulated crash"):
            _commit(
                store,
                _frame(score=0.95),
                input_manifest={"equity_daily": {"2026-07-10": "sha-new"}},
                run_id="derived-run-metadata-committed",
            )

    assert backup_path.is_file()
    recovered = DerivedFeatureStore(tmp_path)

    assert not backup_path.exists()
    current = recovered.read(FEATURE_SET, ANALYSIS_DATE, FORMULA_VERSION)
    assert current.loc[current["ts_code"] == "000001.SZ", "score"].iloc[0] \
        == pytest.approx(0.95)


def test_initialization_fails_closed_when_backup_cannot_be_reconciled(tmp_path):
    store = DerivedFeatureStore(tmp_path)
    _commit(store, _frame())
    final_path = _final_path(tmp_path)
    backup_path = final_path.with_suffix(".parquet.previous")
    final_path.write_bytes(b"unknown-current")
    backup_path.write_bytes(b"unknown-backup")

    with pytest.raises(RuntimeError, match="cannot reconcile"):
        DerivedFeatureStore(tmp_path)


def test_metadata_file_mismatch_fails_closed_for_read_and_initialization(
    tmp_path
):
    store = DerivedFeatureStore(tmp_path)
    _commit(store, _frame())
    final_path = _final_path(tmp_path)
    final_path.write_bytes(b"corrupt derived output")

    with pytest.raises(RuntimeError, match="metadata/file mismatch"):
        store.read(FEATURE_SET, ANALYSIS_DATE, FORMULA_VERSION)
    with pytest.raises(RuntimeError, match="metadata/file mismatch"):
        DerivedFeatureStore(tmp_path)


def test_second_store_initialization_waits_for_active_commit_lock(
    tmp_path, monkeypatch
):
    committing_store = DerivedFeatureStore(tmp_path)
    metadata_entered = threading.Event()
    allow_metadata = threading.Event()
    initialization_finished = threading.Event()
    errors = []
    real_commit_metadata = committing_store._commit_metadata

    def pause_metadata(**kwargs):
        metadata_entered.set()
        if not allow_metadata.wait(timeout=5):
            raise TimeoutError("test did not release metadata commit")
        real_commit_metadata(**kwargs)

    monkeypatch.setattr(committing_store, "_commit_metadata", pause_metadata)

    def run_commit():
        try:
            _commit(committing_store, _frame())
        except BaseException as exc:
            errors.append(exc)

    def initialize_second_store():
        try:
            DerivedFeatureStore(tmp_path)
        except BaseException as exc:
            errors.append(exc)
        finally:
            initialization_finished.set()

    commit_thread = threading.Thread(target=run_commit)
    initialization_thread = threading.Thread(target=initialize_second_store)
    commit_thread.start()
    assert metadata_entered.wait(timeout=2)
    initialization_thread.start()
    try:
        assert not initialization_finished.wait(timeout=0.2)
    finally:
        allow_metadata.set()
        commit_thread.join(timeout=5)
        initialization_thread.join(timeout=5)

    assert not commit_thread.is_alive()
    assert not initialization_thread.is_alive()
    assert initialization_finished.is_set()
    assert errors == []


def test_content_hash_distinguishes_missing_and_non_finite_values():
    values = [None, float("nan"), float("inf"), float("-inf")]

    hashes = {
        stable_dataframe_content_hash(
            pd.DataFrame([{"ts_code": "000001.SZ", "value": value}])
        )
        for value in values
    }

    assert len(hashes) == len(values)


def test_staging_is_cleaned_when_parquet_write_fails(tmp_path, monkeypatch):
    store = DerivedFeatureStore(tmp_path)

    def fail_write(path, frame):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"partial parquet")
        raise RuntimeError("simulated parquet write failure")

    monkeypatch.setattr(
        research_derived_module, "write_staged_parquet", fail_write
    )
    with pytest.raises(RuntimeError, match="simulated parquet write failure"):
        _commit(store, _frame())

    assert not list((tmp_path / ".staging").rglob("*"))
    assert not list((tmp_path / "derived").rglob("*.parquet"))


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
