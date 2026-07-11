# V3 Formal Warehouse Restoration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan inline task-by-task. Do not use subagents unless the user later explicitly authorizes an exception. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Current-state authority:** Completion claims remain governed by `docs/operations/production-capability-matrix.md`; checked plan steps alone are not production evidence.

**Goal:** Restore the approved DuckDB + Parquet formal warehouse, migrate every active and historical formal JSON object without semantic change, cut production over to the warehouse, verify real 2026-07-10 evidence and reports, and delete the superseded wide JSON store only after all gates pass.

**Architecture:** `FormalWarehouse` stores wide normalized acquisition records in immutable, actual-date-partitioned Parquet files and stores version manifests, file inventories, canonical pointers, receipt revisions, candidates, checkpoints, reconciliation state, frozen reports, capabilities, report candidates, and migration audits in `warehouse.duckdb`. Existing formal-v2 domain models and pipeline boundaries remain stable. Migration is copy-validate-cutover-delete and idempotent; the JSON reader exists only in the migration module and is never a production fallback.

**Tech Stack:** Python 3.11+, Pydantic 2.7+, DuckDB 1.0+, PyArrow 16+, pandas 2.2+, Typer 0.12+, pytest 8.2+.

## Global Constraints

- Parquet is the immutable store for wide formal records; `warehouse.duckdb` is the only supported query/catalog entry point.
- Market, valuation, index, and board records are partitioned by actual `trade_date`, not report target date.
- Existing formal-v2 content hashes, version IDs, input-set IDs, receipts, candidate IDs, report references, and artifacts remain reproducible.
- The 82/61/21/5 session constants and Strategy V2 rules do not change.
- Historical `daily_basic` is not added; the current contract remains target-date only.
- No full-market Supabase write and no provider refetch occurs during migration.
- Production has no wide-JSON fallback after cutover.
- JSON remains until all migration, replay, integrity, and cutover gates pass. Deletion is separately authorized.
- Published report JSON and `local_warehouse/manual/holdings.json` are not deletion targets.
- Execute inline in the current worktree. Do not spawn subagents.
- Every task follows RED → GREEN → focused regression → commit.

## File Responsibility Map

- `storage/formal_schema.py`: DuckDB DDL, schema version, catalog initialization.
- `storage/formal_parquet.py`: record-family mapping, actual-date partitioning, staged writes, promotion, hashes, reconstruction.
- `storage/formal_warehouse.py`: production formal storage API and DuckDB state operations.
- `storage/formal_migration.py`: the only legacy JSON importer, inventory and semantic comparison.
- `ops/formal_warehouse_ops.py`: audit, migrate, cutover validation and deletion-manifest orchestration.
- `data/capability_store.py`: capability models plus DuckDB adapter.
- `ops/production_dependencies.py` and `ops/formal_live.py`: warehouse-backed production construction and live writes.
- `cli.py`: explicit inventory, migrate, audit and deletion-manifest commands; no deletion command.
- `tests/test_formal_schema.py`, `test_formal_parquet.py`, `test_formal_warehouse.py`, `test_formal_migration.py`: unit and migration gates.
- `tests/test_formal_warehouse_real_data.py`: opt-in real 2026-07-10 acceptance.
- active specs, capability matrix and runbook: authority and evidence.

---

### Task 1: Establish the DuckDB Formal Catalog

**Files:**
- Create: `src/stock_analyzer/storage/formal_schema.py`
- Create: `tests/test_formal_schema.py`
- Modify: `src/stock_analyzer/storage/local_warehouse.py:23-87`
- Modify: `tests/test_local_warehouse.py:68-92`

**Interfaces:**
- `FORMAL_WAREHOUSE_SCHEMA_VERSION = 1`
- `connect_formal_warehouse(path: Path, *, read_only: bool = False) -> duckdb.DuckDBPyConnection`
- `initialize_formal_schema(connection: duckdb.DuckDBPyConnection) -> None`
- `formal_schema_version(connection) -> int`
- `LocalWarehouse.save_bundle()` and `query_count()` remain compatible.

- [ ] **Step 1: Write schema RED tests**

Assert exact tables and transaction behavior:

```python
EXPECTED_TABLES = {
    "formal_versions", "formal_version_files", "formal_canonical_versions",
    "formal_run_receipts", "formal_run_latest", "formal_candidate_sets",
    "formal_checkpoints", "formal_reconciliation_tasks",
    "formal_frozen_reports", "formal_report_candidates",
    "formal_capability_bundles", "formal_migrations", "warehouse_metadata",
}

def test_initialize_formal_schema_creates_exact_catalog(tmp_path):
    with connect_formal_warehouse(tmp_path / "warehouse.duckdb") as connection:
        assert formal_schema_version(connection) == 1
        tables = {row[0] for row in connection.execute(
            "select table_name from information_schema.tables where table_schema='main'"
        ).fetchall()}
    assert EXPECTED_TABLES <= tables
```

Add a transaction test that inserts a version and file, raises, rolls back, and observes neither row. Add a read-only test that never initializes or mutates schema.

- [ ] **Step 2: Run RED**

```bash
.venv/bin/python -m pytest tests/test_formal_schema.py tests/test_local_warehouse.py -q
```

Expected: collection fails because `formal_schema` does not exist.

- [ ] **Step 3: Implement the exact catalog**

Use scalar columns for identities, dates, timestamps, state, counts, and hashes. Small structured metadata may use DuckDB `JSON`; acquisition `records` may not.

```sql
create table formal_versions (
  version_id varchar primary key, group_id varchar not null,
  target_date date not null, route_id varchar not null,
  route_kind varchar not null, content_hash varchar not null,
  complete boolean not null, fetched_at timestamptz not null,
  contract_version varchar not null, covered_dates json not null,
  coverage_codes json not null, coverage_proven boolean not null,
  field_coverage json not null, source_names json not null,
  unit_metadata json not null, adjustment_basis varchar,
  publication_times json not null,
  unique(group_id, target_date, content_hash)
);
create table formal_version_files (
  version_id varchar not null, record_type varchar not null,
  partition_date date not null, relative_path varchar not null unique,
  row_count bigint not null, file_sha256 varchar not null,
  schema_json json not null,
  primary key(version_id, record_type, partition_date, relative_path)
);
create table formal_canonical_versions (
  group_id varchar not null, target_date date not null,
  version_id varchar not null, updated_at timestamptz not null,
  primary key(group_id, target_date)
);
```

Receipt/object tables use `(run_id, revision)`, `candidate_set_id`, `(run_id, stage)`, `task_id`, and `run_id` keys. Update `LocalWarehouse._refresh_duckdb_marker()` to call schema initialization and record `format=duckdb-parquet-v2`.

- [ ] **Step 4: Run GREEN**

```bash
.venv/bin/python -m pytest tests/test_formal_schema.py tests/test_local_warehouse.py -q
```

Expected: all pass and the exact catalog exists.

- [ ] **Step 5: Commit**

```bash
git add src/stock_analyzer/storage/formal_schema.py src/stock_analyzer/storage/local_warehouse.py tests/test_formal_schema.py tests/test_local_warehouse.py
git commit -m "feat: establish formal DuckDB catalog"
```

---

### Task 2: Implement Immutable Actual-Date Parquet Versions

**Files:**
- Create: `src/stock_analyzer/storage/formal_parquet.py`
- Create: `tests/test_formal_parquet.py`

**Interfaces:**
- `prepare_version_files(root: Path, payload: AcquisitionPayload) -> PreparedVersionFiles`
- `verify_prepared_version(prepared, payload) -> None`
- `promote_prepared_version(root, prepared) -> tuple[FormalVersionFile, ...]`
- `read_version_records(root, files) -> tuple[dict[str, Any], ...]`
- `verify_version_files(root, files, *, strict_hashes: bool) -> None`

- [ ] **Step 1: Write partition and round-trip RED tests**

Create two equity dates, target-date `daily_basic`, index rows, an `as_of_date` financial fact and a published event. Assert actual-date paths:

```python
def test_prepare_market_version_partitions_by_actual_trade_date(tmp_path):
    prepared = prepare_version_files(tmp_path, market_payload())
    paths = {item.relative_path.as_posix() for item in prepared.files}
    assert any("market_daily/trade_date=2026-07-09" in p for p in paths)
    assert any("market_daily/trade_date=2026-07-10" in p for p in paths)
    assert any("daily_basic/trade_date=2026-07-10" in p for p in paths)
    assert not any("daily_basic/trade_date=2026-07-09" in p for p in paths)
```

Assert round-trip equality with `payload.model_dump(mode="json")["records"]`: omitted fields stay omitted, explicit null stays null, nested values preserve types and ordinal order preserves the canonical hash. Add immutable collision and one-byte corruption rejection tests.

- [ ] **Step 2: Run RED**

```bash
.venv/bin/python -m pytest tests/test_formal_parquet.py -q
```

Expected: missing module collection failure.

- [ ] **Step 3: Implement explicit record-family mapping**

```python
RECORD_FAMILIES = {
    "calendar": "calendar", "security": "stock_universe",
    "equity_bar": "market_daily", "daily_basic": "daily_basic",
    "index_bar": "index_daily", "board_bar": "board_daily",
    "company_profile": "company_profile",
    "financial": "fundamental_snapshot",
    "financial_summary": "fundamental_snapshot",
    "forecast": "fundamental_snapshot", "express": "fundamental_snapshot",
    "main_business": "fundamental_snapshot",
    "industry_mapping": "industry_membership",
    "concept_mapping": "concept_membership", "event": "event_catalyst",
    "official_event": "official_risk", "official_risk": "official_risk",
    "manual_holding": "manual_holding",
}
```

Convert values with `to_jsonable_python`; add `__version_id`, `__group_id`, `__record_type`, `__ordinal`, `__present_fields`, and `__json_fields`. Serialize only nested fields Arrow cannot represent consistently, never the whole record. Stage under `.staging/<uuid>` and promote to:

```text
parquet/formal/<family>/<date_key>=YYYY-MM-DD/version_id=<version_id>/part-00000.parquet
```

- [ ] **Step 4: Run GREEN**

```bash
.venv/bin/python -m pytest tests/test_formal_parquet.py -q
```

Expected: partition, round-trip, immutability and corruption tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/stock_analyzer/storage/formal_parquet.py tests/test_formal_parquet.py
git commit -m "feat: store formal versions in immutable Parquet"
```

---

### Task 3: Replace JSON Group-Version Storage with FormalWarehouse

**Files:**
- Create: `src/stock_analyzer/storage/formal_warehouse.py`
- Create: `tests/test_formal_warehouse.py`
- Preserve temporarily: `src/stock_analyzer/storage/evidence_store.py`

**Interfaces:**
- `FormalWarehouse(root: Path)`, where `root` is `local_warehouse`.
- Preserve methods consumed from `LocalEvidenceStore`: group-version, canonical, history, reconciliation, checkpoint, receipt, candidate, frozen-report, and report-candidate operations.
- Add `verify_group_version(version_id: str, *, strict_hashes: bool = True) -> GroupVersionAudit`.
- Add `list_group_versions() -> tuple[GroupVersionManifest, ...]`.

- [ ] **Step 1: Port behavior into RED tests**

Copy behavior assertions, not implementation details, from `test_evidence_store.py`. Instantiate `FormalWarehouse(tmp_path / "local_warehouse")` and assert:

- no `formal_evidence/group_versions/*.json` is created;
- every saved version has cataloged Parquet files;
- incomplete validation creates neither files nor catalog rows;
- injected catalog failure leaves no visible version;
- canonical replacement preserves immutable versions;
- report-cutoff exclusion is unchanged;
- reconstructed `AcquisitionPayload.content_hash` equals manifest hash.

- [ ] **Step 2: Run RED**

```bash
.venv/bin/python -m pytest tests/test_formal_warehouse.py -q
```

Expected: collection fails because `FormalWarehouse` does not exist.

- [ ] **Step 3: Implement atomic group save/read**

`save_group_version()` performs this exact order:

```python
if not validation.complete:
    raise ValueError("cannot persist an incomplete acquisition group version")
version_id = (
    f"{payload.group_id.value}-{payload.trade_date.isoformat()}-"
    f"{payload.content_hash}"
)
prepared = prepare_version_files(self.root, payload)
verify_prepared_version(prepared, payload)
files = promote_prepared_version(self.root, prepared)
with self._connect() as connection:
    connection.begin()
    self._insert_version(connection, payload, validation, files)
    connection.commit()
return self.group_version_manifest(version_id)
```

Detect promoted-but-uncataloged orphans. Adopt only after exact file and payload revalidation. `read_group_version()` reads catalog metadata and files, reconstructs ordinal records, verifies the content hash, then applies report-cutoff semantics.

- [ ] **Step 4: Run GREEN and compatibility regression**

```bash
.venv/bin/python -m pytest tests/test_formal_warehouse.py tests/test_evidence_store.py tests/test_atomic_acquisition.py tests/test_formal_run_state.py -q
```

Expected: warehouse and legacy compatibility tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/stock_analyzer/storage/formal_warehouse.py tests/test_formal_warehouse.py
git commit -m "feat: persist formal group versions through warehouse"
```

---

### Task 4: Move Formal State and Capabilities into DuckDB

**Files:**
- Modify: `src/stock_analyzer/storage/formal_warehouse.py`
- Modify: `src/stock_analyzer/data/capability_store.py`
- Modify: `tests/test_formal_warehouse.py`
- Modify: `tests/test_capability_store.py`

**Interfaces:**
- `WarehouseCapabilityStore(warehouse: FormalWarehouse)` implements `load(require_live: bool)` and `save(bundle)` parity.
- All former evidence-store state methods return the same domain models.

- [ ] **Step 1: Write metadata parity RED tests**

For every object type, test exact Pydantic equality and immutability. Receipt revisions must be append-only and latest transactional:

```python
def test_receipt_revisions_are_append_only_and_latest_is_transactional(warehouse):
    warehouse.save_run_receipt(receipt(revision=0))
    warehouse.save_run_receipt(receipt(revision=1, state=RunState.READY_TO_SCREEN))
    assert warehouse.latest_run_receipt("run-1").revision == 1
    with pytest.raises(ValueError, match="already exists"):
        warehouse.save_run_receipt(receipt(revision=1, state=RunState.FAILED_RETRYABLE))
```

Test candidate sets, checkpoints, reconciliation, frozen reports, report candidates and live/recorded capability selection without filesystem JSON.

- [ ] **Step 2: Run RED**

```bash
.venv/bin/python -m pytest tests/test_formal_warehouse.py tests/test_capability_store.py -q
```

Expected: missing metadata methods and adapter failures.

- [ ] **Step 3: Implement transactional state adapters**

Store small Pydantic payloads as canonical JSON inside DuckDB rows with separately constrained identity/state columns. Immutable objects use `INSERT`; latest pointers and reconciliation transitions use transactions with expected-prior-state predicates. Capability rows include `bundle_hash`, `contract_version`, `generated_at`, `mode`, and canonical payload.

- [ ] **Step 4: Run GREEN and state-machine regression**

```bash
.venv/bin/python -m pytest tests/test_formal_warehouse.py tests/test_capability_store.py tests/test_formal_run_state.py tests/test_formal_activation.py -q
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/stock_analyzer/storage/formal_warehouse.py src/stock_analyzer/data/capability_store.py tests/test_formal_warehouse.py tests/test_capability_store.py
git commit -m "feat: catalog formal state in DuckDB"
```

---

### Task 5: Cut Production Over to FormalWarehouse

**Files:**
- Modify: `src/stock_analyzer/ops/production_dependencies.py:57-193`
- Modify: `src/stock_analyzer/ops/formal_live.py:345-364,500-530`
- Modify: `src/stock_analyzer/ops/formal_run.py`
- Modify: `src/stock_analyzer/ops/publish.py`
- Modify: `src/stock_analyzer/ops/artifacts.py`
- Modify: `tests/test_production_dependencies.py`
- Modify: `tests/test_formal_live.py`
- Modify: `tests/test_default_formal_production_entry.py`
- Modify: `tests/test_formal_pipeline.py`

**Interfaces:**
- `FormalPipelineDependencies.evidence_store` keeps its field name temporarily, but production value is `FormalWarehouse`.
- `ProductionExternalRuntime.capability_store` accepts a store protocol, not a path assumption.
- Production contains no import or construction of `LocalEvidenceStore`.

- [ ] **Step 1: Write no-JSON production RED tests**

```python
def test_default_formal_entry_uses_duckdb_parquet_and_creates_no_wide_json(tmp_path):
    dependencies = build_production_formal_dependencies(...)
    assert isinstance(dependencies.evidence_store, FormalWarehouse)
    result = run_formal_strategy_v2(...)
    assert result.receipt.group_version_ids
    assert (tmp_path / "local_warehouse/warehouse.duckdb").is_file()
    assert not list((tmp_path / "local_warehouse/formal_evidence").glob("**/*.json"))
```

Add a governance test failing on production imports of `LocalEvidenceStore` or literals containing `formal_evidence/group_versions`. Verify live capability bootstrap stores primary screening versions in the warehouse.

- [ ] **Step 2: Run RED**

```bash
.venv/bin/python -m pytest tests/test_production_dependencies.py tests/test_formal_live.py tests/test_default_formal_production_entry.py tests/test_formal_pipeline.py -q
```

Expected: current JSON construction causes failures.

- [ ] **Step 3: Implement cutover without fallback**

Construct one warehouse per configured local root:

```python
warehouse = FormalWarehouse(runtime.config.local_warehouse_dir)
capability_store = WarehouseCapabilityStore(warehouse)
dependencies = FormalPipelineDependencies(..., evidence_store=warehouse, ...)
```

Update live verification, publish receipt resolution and artifact validation. Remove active `formal_evidence` path construction. Do not add fallback logic.

- [ ] **Step 4: Run GREEN and integration regression**

```bash
.venv/bin/python -m pytest tests/test_production_dependencies.py tests/test_formal_live.py tests/test_default_formal_production_entry.py tests/test_formal_pipeline.py tests/test_formal_runtime_render.py tests/test_formal_activation.py -q
```

Expected: all pass with no wide JSON creation.

- [ ] **Step 5: Commit**

```bash
git add src/stock_analyzer/ops/production_dependencies.py src/stock_analyzer/ops/formal_live.py src/stock_analyzer/ops/formal_run.py src/stock_analyzer/ops/publish.py src/stock_analyzer/ops/artifacts.py tests/test_production_dependencies.py tests/test_formal_live.py tests/test_default_formal_production_entry.py tests/test_formal_pipeline.py
git commit -m "fix: route formal production through warehouse"
```

---

### Task 6: Build Idempotent Legacy Migration and Integrity Audit

**Files:**
- Create: `src/stock_analyzer/storage/formal_migration.py`
- Create: `src/stock_analyzer/ops/formal_warehouse_ops.py`
- Create: `tests/test_formal_migration.py`
- Modify: `src/stock_analyzer/cli.py`
- Modify: `tests/test_cli.py`

**Interfaces:**
- `inventory_legacy_formal_store(source_root: Path) -> LegacyInventory`
- `migrate_legacy_formal_store(source_root: Path, warehouse: FormalWarehouse, *, migration_id: str) -> MigrationAudit`
- `audit_formal_warehouse(warehouse: FormalWarehouse, *, strict_hashes: bool = True) -> WarehouseAudit`
- `build_deletion_manifest(source_root: Path, audit: MigrationAudit) -> DeletionManifest`
- CLI: `formal-warehouse-inventory`, `formal-warehouse-migrate`, `formal-warehouse-audit`, `formal-warehouse-deletion-manifest`.

- [ ] **Step 1: Write realistic migration RED tests**

Build a JSON fixture with multiple group versions, canonical replacement, receipt revisions, candidate, checkpoint, reconciliation, frozen report, report candidate and capability. Assert:

- inventory discovers every file and inbound reference;
- unknown JSON blocks deletion eligibility;
- migration preserves exact objects and hashes;
- the same migration twice creates no duplicate rows/files;
- source change after inventory blocks migration;
- row/hash/date mismatch blocks cutover and deletion;
- deletion manifest excludes reports and manual holdings;
- only `formal_migration.py` may import the legacy JSON reader.

- [ ] **Step 2: Run RED**

```bash
.venv/bin/python -m pytest tests/test_formal_migration.py tests/test_cli.py -q
```

Expected: missing module and commands.

- [ ] **Step 3: Implement explicit inventory and semantic migration**

Define a parser for every known directory; never copy opaque JSON blobs into DuckDB. Inventory SHA-256 precedes semantic reads. Group payloads use `AcquisitionPayload.model_validate`, warehouse save/read and exact comparison. Metadata uses its domain model and warehouse method.

```python
class MigrationItem(BaseModel):
    source_path: str
    source_sha256: str
    object_kind: str
    object_id: str
    status: Literal["migrated", "already_present", "failed", "unknown"]
    target_ids: tuple[str, ...] = ()
    checks: dict[str, bool]
    error: str | None = None
```

Compute `deletion_eligible`; callers cannot supply it. It requires no failed/unknown item, all references resolved, all group hashes equal, a strict warehouse audit and a clean production reader scan.

- [ ] **Step 4: Implement non-destructive CLI**

Commands are offline and atomic-output. They return nonzero on any failed gate. No command deletes a file.

- [ ] **Step 5: Run GREEN**

```bash
.venv/bin/python -m pytest tests/test_formal_migration.py tests/test_cli.py tests/test_ops_artifacts.py -q
```

Expected: migration is idempotent and fail-closed.

- [ ] **Step 6: Commit**

```bash
git add src/stock_analyzer/storage/formal_migration.py src/stock_analyzer/ops/formal_warehouse_ops.py src/stock_analyzer/cli.py tests/test_formal_migration.py tests/test_cli.py
git commit -m "feat: migrate formal JSON evidence into warehouse"
```

---

### Task 7: Align Authority Documents and Operational Gates

**Files:**
- Modify: `docs/superpowers/specs/2026-07-08-storage-governance-design.md`
- Modify: `docs/superpowers/specs/2026-07-10-v3-formal-report-data-readiness-design.md`
- Modify: `docs/superpowers/plans/2026-07-10-v3-formal-report-data-readiness.md`
- Modify: `docs/superpowers/plans/2026-07-10-v3-production-capability-correction.md`
- Modify: `docs/operations/production-capability-matrix.md`
- Modify: `docs/operations/runbook.md`
- Modify: `README.md`
- Create: `tests/test_formal_storage_governance.py`

**Interfaces:**
- Capability gate: `STORE-004 Formal DuckDB + Parquet restoration`.
- The gate cannot be complete before migration, cutover, deletion and post-deletion evidence.

- [ ] **Step 1: Write documentation-governance RED tests**

Assert active docs contain ownership, commands, rollback and deletion gates; historical plans contain visible supersession banners; production source has no legacy store import outside migration.

- [ ] **Step 2: Run RED**

```bash
.venv/bin/python -m pytest tests/test_formal_storage_governance.py -q
```

Expected: current docs and source fail the new authority checks.

- [ ] **Step 3: Update lifecycle state honestly**

Before real migration, mark `STORE-004` as `IMPLEMENTED_NOT_MIGRATED`. Add exact operator commands and audit paths. Preserve historical text and add supersession banners dated 2026-07-12.

- [ ] **Step 4: Run GREEN and whitespace check**

```bash
.venv/bin/python -m pytest tests/test_formal_storage_governance.py -q
git diff --check
```

Expected: both exit zero.

- [ ] **Step 5: Commit**

```bash
git add README.md docs tests/test_formal_storage_governance.py
git commit -m "docs: align formal storage authority"
```

---

### Task 8: Verify Implementation Before Production Data

**Files:**
- Modify only files required by failures caused by Tasks 1–7.

- [ ] **Step 1: Run focused suite**

```bash
.venv/bin/python -m pytest tests/test_formal_schema.py tests/test_formal_parquet.py tests/test_formal_warehouse.py tests/test_formal_migration.py tests/test_formal_storage_governance.py -q
```

Expected: zero failures.

- [ ] **Step 2: Run formal production suite**

```bash
.venv/bin/python -m pytest tests/test_formal_readiness_contracts.py tests/test_atomic_acquisition.py tests/test_evidence_store.py tests/test_formal_run_state.py tests/test_formal_activation.py tests/test_formal_pipeline.py tests/test_default_formal_production_entry.py tests/test_formal_live.py tests/test_formal_runtime_render.py tests/test_production_dependencies.py -q
```

Expected: zero failures and no wide JSON creation.

- [ ] **Step 3: Run complete suite**

```bash
.venv/bin/python -m pytest -q
```

Expected: zero failures.

- [ ] **Step 4: Run governance checks**

```bash
rg -n "LocalEvidenceStore|formal_evidence/group_versions" src/stock_analyzer --glob '*.py'
git diff --check
git status --short
```

Expected: legacy mention only in migration compatibility code; clean diff; intentional status.

- [ ] **Step 5: Commit narrow regression fixes separately**

Use one commit for each independently explainable failure. Do not bundle cleanup.

---

### Task 9: Migrate and Validate Real 2026-07-10 Data

**Files/Data:**
- Read: `/Users/ccrt/股票分析助手/local_warehouse/formal_evidence`
- Write: `/Users/ccrt/股票分析助手/local_warehouse/warehouse.duckdb`
- Write: `/Users/ccrt/股票分析助手/local_warehouse/parquet/formal`
- Audit: `/Users/ccrt/股票分析助手/local_archive/manifests/formal-warehouse-migration-2026-07-12.json`
- Create: `tests/test_formal_warehouse_real_data.py`

**Safety:** Copy and validate only. Do not delete JSON, publish, write Supabase, call providers or alter broker state. Request exact command approval if the sandbox requires it.

- [x] **Step 1: Capture pre-migration inventory**

Record file count, bytes, object counts, version IDs, canonical pointers, receipt graph and source hashes. Known current canonical market evidence should contain 82 dates from 2026-03-12 through 2026-07-10, 431,310 equity bars, 246 index bars and 5,270 target-date daily-basic rows. If the pointer differs, stop and explain before writing.

- [x] **Step 2: Add opt-in real-data RED acceptance**

Skip unless `STOCK_ANALYZER_REAL_WAREHOUSE_ROOT` is set. Enumerate every source version/reference, not only canonical market data. Before migration it must fail because DuckDB lacks the graph.

```bash
STOCK_ANALYZER_REAL_WAREHOUSE_ROOT=/Users/ccrt/股票分析助手/local_warehouse .venv/bin/python -m pytest tests/test_formal_warehouse_real_data.py -q
```

Expected RED: missing migrated versions/references.

- [x] **Step 3: Run idempotent real migration**

```bash
.venv/bin/stock-analyzer-publish formal-warehouse-migrate \
  --source-root /Users/ccrt/股票分析助手/local_warehouse/formal_evidence \
  --warehouse-root /Users/ccrt/股票分析助手/local_warehouse \
  --migration-id formal-json-to-duckdb-parquet-20260712 \
  --output /Users/ccrt/股票分析助手/local_archive/manifests/formal-warehouse-migration-2026-07-12.json
```

Expected: exit zero, source bytes unchanged, every item `migrated` or `already_present`, no unknown/failed item, exact content hashes.

- [x] **Step 4: Run strict audit and migrate again**

Hash every Parquet file and reconstruct every payload. Second migration creates zero new versions/files.

- [x] **Step 5: Run real-data GREEN acceptance**

```bash
STOCK_ANALYZER_REAL_WAREHOUSE_ROOT=/Users/ccrt/股票分析助手/local_warehouse .venv/bin/python -m pytest tests/test_formal_warehouse_real_data.py -q
```

Expected: pass with exact 82-session and reference-graph assertions.

- [x] **Step 6: Replay every existing receipt offline**

Compare input-set, candidate-set, evidence and artifact hashes. Do not regenerate or activate production output.

- [x] **Step 7: Record migration evidence**

Set `STORE-004` to `MIGRATED_NOT_DELETED`, with audit path, counts, dates, tests and cutover state. Commit code/test/doc evidence, not local data.

---

### Task 10: Cut Over, Authorize Deletion and Prove Final State

**Files/Data:**
- Delete only manifest-listed paths below `/Users/ccrt/股票分析助手/local_warehouse/formal_evidence`.
- Modify: `docs/operations/production-capability-matrix.md`
- Modify: `docs/operations/runbook.md`
- Modify: `README.md`

- [ ] **Step 1: Run post-migration production health and offline verification**

Use production paths without provider refetch or Supabase mutation. Confirm dependency construction, canonical reads, receipts, report verification and scheduler imports use `FormalWarehouse`.

- [ ] **Step 2: Prove zero legacy reads**

Run source scan and instrumented replay with the legacy source unreadable in a temporary clone. Replay must pass with no `formal_evidence` open attempt.

- [ ] **Step 3: Generate deletion manifest**

List exact path, current SHA-256, size, semantic ID, migration target IDs and safety audit. Re-hash immediately before deletion; any change invalidates authorization.

- [ ] **Step 4: Request explicit destructive authorization**

Present manifest totals and evidence. Request escalation for the exact deletion command without a reusable prefix.

- [ ] **Step 5: Delete only manifested legacy paths**

Do not delete published report JSON, manual holdings, Parquet, DuckDB, migration audit or local archive. Remove empty legacy directories only after files.

- [ ] **Step 6: Run immediate post-deletion gates**

```bash
.venv/bin/stock-analyzer-publish formal-warehouse-audit \
  --warehouse-root /Users/ccrt/股票分析助手/local_warehouse \
  --strict-hashes \
  --output /Users/ccrt/股票分析助手/local_archive/manifests/formal-warehouse-post-delete-2026-07-12.json
STOCK_ANALYZER_REAL_WAREHOUSE_ROOT=/Users/ccrt/股票分析助手/local_warehouse .venv/bin/python -m pytest tests/test_formal_warehouse_real_data.py -q
.venv/bin/python -m pytest -q
```

Expected: zero failures, no wide formal JSON, every version/receipt resolves through DuckDB, exact 82-session counts remain.

- [ ] **Step 7: Final documentation state**

Set `STORE-004` to `PRODUCTION_WRITE_VERIFIED` only now. Record pre/post counts and sizes, schema version, Parquet/version counts, exact coverage, migration/cutover/deletion audit IDs, tests and zero-fallback confirmation.

- [ ] **Step 8: Final repository verification and commit**

```bash
git diff --check
git status --short
git log --oneline -12
git add README.md docs/operations/production-capability-matrix.md docs/operations/runbook.md
git commit -m "docs: record formal warehouse production migration"
```

Do not claim completion without fresh full tests, strict audit, real-data acceptance and post-deletion replay in the same turn.

---

## Plan Self-Review Checklist

- [ ] Every restoration-design requirement maps to a task.
- [ ] No task introduces historical `daily_basic`, strategy change, refetch or full-market Supabase write.
- [ ] `FormalWarehouse`, `WarehouseCapabilityStore`, migration functions and CLI names are consistent.
- [ ] Every production change has a RED test first.
- [ ] Real migration is copy-only until separately authorized deletion.
- [ ] Inventory includes all formal objects, not only canonical market data.
- [ ] Documentation reports implemented, migrated, cutover and deleted states honestly.
- [ ] No subagent step exists; execution is inline with `executing-plans`.
