from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

from stock_analyzer.data.readiness import (
    AcquisitionGroupId,
    AcquisitionPayload,
    GroupValidation,
    RouteKind,
)
from stock_analyzer.storage.evidence_store import (
    FrozenReportReference,
    LocalEvidenceStore,
)


SHANGHAI = ZoneInfo("Asia/Shanghai")
TARGET = date(2026, 7, 10)
CUTOFF = datetime(2026, 7, 10, 16, 0, tzinfo=SHANGHAI)
VALID = GroupValidation(complete=True)


def _payload(
    trade_date: date = TARGET,
    *,
    kind: RouteKind = RouteKind.PRIMARY,
    route_id: str = "primary.market.v1",
    close: float = 10.5,
    publication_time: datetime | None = None,
) -> AcquisitionPayload:
    return AcquisitionPayload(
        group_id=AcquisitionGroupId.MARKET_DECISION,
        route_id=route_id,
        route_kind=kind,
        trade_date=trade_date,
        fetched_at=CUTOFF,
        source_names=(route_id,),
        records=(
            {
                "trade_date": trade_date,
                "ts_code": "600000.SH",
                "close": close,
            },
        ),
        covered_dates=(trade_date,),
        coverage_codes=("600000.SH",),
        field_coverage={"trade_date": True, "ts_code": True, "close": True},
        publication_times=(
            {"600000.SH:event": publication_time}
            if publication_time is not None
            else {}
        ),
    )


def test_versions_are_immutable_and_canonical_pointer_is_atomic(tmp_path):
    store = LocalEvidenceStore(tmp_path)
    first = store.save_group_version(_payload(close=10.5), VALID)
    store.set_canonical(first.group_id, TARGET, first.version_id)
    first_bytes = store.version_path(first.version_id).read_bytes()

    second = store.save_group_version(_payload(close=11.5), VALID)
    store.set_canonical(second.group_id, TARGET, second.version_id)

    assert first.version_id != second.version_id
    assert store.version_path(first.version_id).read_bytes() == first_bytes
    assert store.version_path(second.version_id).is_file()
    assert store.canonical_manifest(first.group_id, TARGET).version_id == second.version_id
    assert not list(tmp_path.rglob("*.tmp"))


def test_prior_session_cache_excludes_target_date_current_facts(tmp_path):
    store = LocalEvidenceStore(tmp_path)
    prior_date = date(2026, 7, 9)
    prior = store.save_group_version(_payload(prior_date), VALID)
    current = store.save_group_version(_payload(TARGET, close=12.0), VALID)
    store.set_canonical(prior.group_id, prior_date, prior.version_id)
    store.set_canonical(current.group_id, TARGET, current.version_id)

    history = store.load_prior_sessions(AcquisitionGroupId.MARKET_DECISION, TARGET, 82)

    assert [payload.trade_date for payload in history] == [prior_date]
    assert all(payload.trade_date < TARGET for payload in history)


def test_checkpoint_resume_requires_same_run_date_and_contract_version(tmp_path):
    store = LocalEvidenceStore(tmp_path)
    store.save_checkpoint("run-1", TARGET, "formal-v1", "screening", "version-1")

    assert store.load_checkpoint("run-1", TARGET, "formal-v1", "screening") == "version-1"
    assert store.load_checkpoint("run-1", date(2026, 7, 9), "formal-v1", "screening") is None
    assert store.load_checkpoint("run-1", TARGET, "formal-v2", "screening") is None
    assert store.load_checkpoint("run-2", TARGET, "formal-v1", "screening") is None


def test_backup_version_creates_pending_reconciliation_task(tmp_path):
    store = LocalEvidenceStore(tmp_path)
    backup = store.save_group_version(
        _payload(kind=RouteKind.BACKUP, route_id="backup.market.v1"),
        VALID,
    )
    store.set_canonical(backup.group_id, TARGET, backup.version_id)

    task = store.create_reconciliation_task(backup)

    assert task.status == "pending"
    assert task.backup_version_id == backup.version_id
    assert store.reconciliation_task(task.task_id) == task


def test_recovered_primary_becomes_canonical_without_deleting_backup(tmp_path):
    store = LocalEvidenceStore(tmp_path)
    backup = store.save_group_version(
        _payload(kind=RouteKind.BACKUP, route_id="backup.market.v1"),
        VALID,
    )
    store.set_canonical(backup.group_id, TARGET, backup.version_id)
    task = store.create_reconciliation_task(backup)

    primary = store.reconcile_primary(
        task.task_id,
        _payload(kind=RouteKind.PRIMARY, route_id="primary.market.v1", close=12.5),
        VALID,
    )

    assert store.canonical_manifest(backup.group_id, TARGET).version_id == primary.version_id
    assert store.version_path(backup.version_id).is_file()
    assert store.version_path(primary.version_id).is_file()
    assert store.reconciliation_task(task.task_id).status == "completed"


def test_reconciliation_preserves_frozen_receipt_input_set_and_artifact_hashes(tmp_path):
    store = LocalEvidenceStore(tmp_path)
    backup = store.save_group_version(
        _payload(kind=RouteKind.BACKUP, route_id="backup.market.v1"),
        VALID,
    )
    store.set_canonical(backup.group_id, TARGET, backup.version_id)
    frozen = FrozenReportReference(
        run_id="run-backup",
        input_set_id="input-backup-001",
        group_version_ids=(backup.version_id,),
        artifact_hashes={"index.html": "sha256-old"},
    )
    path = store.save_frozen_report_reference(frozen)
    frozen_bytes = path.read_bytes()
    task = store.create_reconciliation_task(backup)

    store.reconcile_primary(
        task.task_id,
        _payload(kind=RouteKind.PRIMARY, route_id="primary.market.v1", close=13.0),
        VALID,
    )

    assert path.read_bytes() == frozen_bytes
    assert store.frozen_report_reference("run-backup") == frozen


def test_look_ahead_financial_or_event_version_is_not_read(tmp_path):
    store = LocalEvidenceStore(tmp_path)
    future = datetime(2026, 7, 10, 16, 1, tzinfo=SHANGHAI)
    manifest = store.save_group_version(
        _payload(publication_time=future),
        VALID,
    )

    assert store.read_group_version(manifest.version_id, report_cutoff=CUTOFF) is None
    assert store.read_group_version(
        manifest.version_id,
        report_cutoff=datetime(2026, 7, 10, 16, 2, tzinfo=SHANGHAI),
    ) is not None
