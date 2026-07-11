# V3 Formal Warehouse Restoration Design

> **Status:** Approved for implementation on 2026-07-12. This document resolves the storage contradiction introduced after the original storage-governance design. Where later plans or code store wide formal acquisition payloads as JSON, this design supersedes that behavior while preserving the existing formal-v2 data and decision contracts.
>
> **Current-state authority:** Implementation and production status are authoritative only in `docs/operations/production-capability-matrix.md`; this specification defines required behavior but is not evidence that migration or activation is complete.

## 1. Purpose

Restore the originally approved local storage architecture end to end:

- Parquet is the compressed, immutable store for wide formal data.
- `warehouse.duckdb` is the only supported query and catalog entry point for formal acquisition data.
- Supabase remains a narrow decision ledger.
- JSON remains valid for published report assets and small human-maintained inputs, but not for wide formal market, universe, board, fundamental, or event payload storage.

The correction covers documentation, implementation plans, production code, migration, verification, cutover, and removal of the superseded wide JSON payloads.

## 2. Authority and Conflict Resolution

This design restores and makes executable the storage rules in:

- `2026-07-08-storage-governance-design.md`
- `2026-07-10-v3-phase-3-strategy-v2-design.md`
- `2026-07-10-v3-formal-report-data-readiness-design.md`

The following later behavior is invalid and must be removed:

- serializing an entire `AcquisitionPayload.records` collection into `formal_evidence/group_versions/*.json`;
- treating a report target-date directory as the physical partition for all historical rows;
- allowing the formal production pipeline to bypass `warehouse.duckdb` and Parquet;
- accepting a formal production run without proving that every frozen input version resolves through the warehouse catalog.

Historical plans remain audit records. Their lifecycle banners must state when this design supersedes a storage step; historical text must not be silently rewritten to pretend the contradiction never occurred.

## 3. Storage Ownership

### 3.1 Parquet wide data

Wide records are stored below `local_warehouse/parquet/formal/` in record-family datasets. Required families are:

- `calendar`
- `stock_universe`
- `market_daily`
- `daily_basic`
- `index_daily`
- `board_daily`
- `company_profile`
- `fundamental_snapshot`
- `industry_membership`
- `concept_membership`
- `event_catalyst`
- `official_risk`
- `manual_holding`

Every Parquet row carries `version_id`, `group_id`, `record_type`, the applicable business date, and the normalized record fields. Market, valuation, index, and board rows are partitioned by their actual `trade_date`, never only by the report target date. Low-frequency facts use their actual `as_of_date`, `published_at` date, or acquisition target date according to the formal record contract.

Parquet version files are immutable after catalog commit. A new source acquisition creates a new version. Canonical recovery changes a pointer; it never edits an already committed version.

### 3.2 DuckDB catalog and query entry

`local_warehouse/warehouse.duckdb` owns:

- `formal_versions`: immutable group-version manifests and payload metadata;
- `formal_version_files`: the exact Parquet files, record families, row counts, hashes, and covered dates for each version;
- `formal_canonical_versions`: one transactional canonical pointer per group and target date;
- `formal_run_receipts`: append-only formal run receipt revisions;
- `formal_candidate_sets`: immutable candidate sets;
- `formal_checkpoints`: same-run resumability checkpoints;
- `formal_reconciliation_tasks`: backup-to-primary reconciliation state;
- `formal_frozen_reports`: frozen report-to-input references;
- `formal_report_candidates`: pre-activation report candidates;
- `formal_migrations`: migration inventory, validation results, cutover state, and deletion eligibility.

DuckDB views expose the current canonical record families and version-scoped record reads. Production consumers use repository methods backed by these catalog tables and views; they do not open Parquet or wide JSON directly.

### 3.3 JSON boundaries

JSON is permitted only when it is not acting as the wide calculation warehouse:

- published static report contracts such as `reports/data/latest.json` and `formal-run.json`;
- small operator status and notification files;
- the manually maintained holdings input until a separate approved design changes it;
- an export generated for diagnostics, provided production never reads it as a data source.

After successful cutover, `local_warehouse/formal_evidence` must contain no active wide group payload, receipt, candidate, checkpoint, reconciliation, or frozen-report JSON store. The migrated JSON tree is deleted after the deletion gate passes.

## 4. Warehouse Interfaces

The formal pipeline depends on a `FormalWarehouse` interface rather than `LocalEvidenceStore`:

- save and read immutable group versions;
- set and resolve canonical versions;
- load prior canonical sessions;
- save and load receipt revisions;
- save and load candidate sets, checkpoints, reconciliation tasks, frozen reports, and report candidates;
- list version files and validate their hashes;
- reconstruct an `AcquisitionPayload` exactly enough to reproduce its original canonical content hash.

The existing `AcquisitionPayload`, `GroupValidation`, `RunReceipt`, `CandidateSet`, and formal-v2 contracts remain unchanged at pipeline boundaries. Storage conversion is internal to the warehouse adapter.

`LocalWarehouse` becomes the owner of the shared DuckDB connection and schema initialization. Formal storage is implemented in focused modules rather than expanding the legacy marker-only class into one monolithic file.

## 5. Atomic Write Protocol

Saving a formal group version follows this order:

1. Reject an incomplete validation.
2. Normalize records by record contract and determine the actual partition date.
3. Write all Parquet files to a staging directory on the same filesystem.
4. Read the staged files through DuckDB and verify schema, row counts, unique keys, date coverage, and reconstructed payload hash.
5. Atomically rename staged files into immutable version paths.
6. Insert the manifest and file inventory in one DuckDB transaction.
7. Commit only when every file exists and every hash matches.
8. Change the canonical pointer in a separate DuckDB transaction after version commit.

A failure before catalog commit leaves no visible version. A failure after immutable files are renamed but before catalog commit is detected as an orphan and must be safe to clean or adopt only after revalidation. No partial version may support screening, analysis, or a report.

## 6. Read and Replay Semantics

Reading a version performs these checks:

- the version manifest exists and is complete;
- every cataloged Parquet file exists;
- stored file hashes match when strict verification is requested;
- the requested report cutoff excludes facts published after the cutoff;
- reconstructed covered dates, source metadata, units, adjustment basis, and records reproduce the stored content hash.

Formal runs freeze version IDs, not mutable query results. Replay resolves those exact version IDs even when the canonical pointer later advances.

The 82-session screening contract remains unchanged. For the 2026-07-10 production evidence this means 82 equity-bar sessions and 82 index sessions from 2026-03-12 through 2026-07-10. Current formal-v2 intentionally requires target-date `daily_basic`; expanding historical valuation or turnover features requires a separate strategy design.

## 7. Migration

Migration is copy-validate-cutover-delete. It must be idempotent and resumable.

### 7.1 Inventory

Inventory every active and historical object in `local_warehouse/formal_evidence`, including:

- all group versions and canonical pointers;
- capability references needed to construct production routes;
- receipt revisions and latest pointers;
- candidate sets, checkpoints, reconciliation tasks;
- frozen reports and report candidates.

The inventory records source path, size, source hash, semantic object ID, and all inbound references. Unknown or malformed objects block deletion.

### 7.2 Copy and validate

For every group version, migrate records to Parquet and metadata to DuckDB without changing or deleting the source JSON. For every object type, read it back through `FormalWarehouse` and compare it with the original object.

Required group-version comparisons are:

- total and per-record-type row counts;
- actual date range and distinct covered dates;
- code sets and unique keys;
- every normalized field and null classification;
- route, source, unit, adjustment, publication-time, and coverage metadata;
- original formal content hash.

Required graph comparisons prove that canonical pointers, receipt revisions, frozen input sets, candidate sets, reconciliation tasks, report candidates, and frozen reports resolve to the same IDs as before migration.

### 7.3 Replay and cutover

Before cutover:

- reconstruct every input set referenced by an existing formal receipt;
- reproduce the stored input-set hash;
- run the formal read/replay and report verification paths without network or production mutation;
- prove no formal production module imports or constructs `LocalEvidenceStore`.

Cutover changes the production dependency factory to `FormalWarehouse`, runs the production health/read verification, and leaves the JSON source untouched for the observation gate.

### 7.4 Deletion gate

Deletion is allowed only when all of the following are true:

- migration inventory has no unknown or failed object;
- every migrated object passed semantic and hash comparison;
- all existing receipt and report references resolve through DuckDB;
- the complete automated test suite passes;
- a fresh warehouse integrity audit passes;
- repository search and runtime instrumentation show zero active reads from the wide JSON store;
- the formal production health check and offline replay pass after cutover;
- a deletion manifest lists exactly what will be removed.

Deletion removes the superseded `local_warehouse/formal_evidence` JSON data only after explicit destructive-action authorization. It must not remove report publication JSON or manual holdings input. After deletion, the integrity audit and replay run again. Failure after deletion restores from the still-available migration staging snapshot before the operation is declared complete.

## 8. Failure Behavior

- Any missing or corrupt Parquet file fails closed before analysis.
- Any incomplete catalog transaction is invisible to readers.
- Any mismatch between a DuckDB manifest and Parquet data blocks the version.
- Migration never changes canonical pointers until all referenced data is valid.
- A failed migration leaves production on the existing reader and preserves all JSON.
- A failed cutover restores the prior runtime selection without deleting JSON.
- A failed post-deletion audit is an incident and requires restoration before normal scheduling resumes.

No migration or repair may silently fetch replacement market data. Existing formal evidence is migrated exactly; provider acquisition remains a separate operation.

## 9. Tests and Acceptance Gates

Tests are required at four levels:

1. **Storage unit tests:** schemas, immutable writes, actual-date partitions, canonical transactions, receipt revisions, point-in-time reads, corruption rejection, and hash reconstruction.
2. **Formal integration tests:** production dependency construction, screening, frozen target acquisition, replay, report generation, and restart/resume use `FormalWarehouse` only.
3. **Migration tests:** realistic multi-version JSON fixtures migrate idempotently, preserve reference graphs, block on mismatch, and become deletion-eligible only after every gate.
4. **Real-data read-only acceptance:** inventory and migrate the existing 2026-07-10 evidence, prove exact 82-session coverage and stored counts, verify every frozen report reference, and record a machine-readable audit result.

Acceptance is not satisfied by test doubles alone. The final production data must show:

- 82 distinct equity and index trading dates for the canonical 2026-07-10 market version;
- 431,310 equity bars, 246 index bars, and 5,270 target-date daily-basic rows for the known canonical payload, unless the source inventory proves a different canonical version was selected before migration;
- no wide JSON group-version payload remains after authorized deletion;
- `warehouse.duckdb` can enumerate all migrated versions and resolve every active receipt;
- formal code has no active wide-JSON fallback.

## 10. Documentation and Operational Consistency

The implementation must update:

- storage-governance design status and concrete schema;
- formal data-readiness design storage section;
- production capability matrix with a warehouse restoration gate;
- runbook commands for integrity audit, migration, cutover, deletion eligibility, and rollback;
- active implementation plan and migration evidence report.

Documentation may not claim completion until the corresponding code and real-data evidence exist. The capability matrix is the authority for current state; historical specs and plans retain visible supersession notes.

## 11. Non-goals

- No change to Strategy V2 decision rules or the 82/61/21/5 session constants.
- No expansion of historical `daily_basic` requirements.
- No full-market write to Supabase.
- No provider refetch merely to make migration easier.
- No broker connection, order execution, or unrelated report redesign.

## 12. Execution Discipline

The implementation plan must be detailed enough that a later executor cannot reinterpret the storage target, narrow the migration silently, or declare success from unit tests alone. Every task names exact files, interfaces, red/green tests, verification commands, expected failure or success evidence, real-data gates, rollback conditions, and commit boundaries.

Implementation is executed inline in the current session. Subagents are not used unless a later blocking condition makes an independent specialist review necessary and the user explicitly authorizes that expansion. Token or time convenience alone is not a reason to delegate.
