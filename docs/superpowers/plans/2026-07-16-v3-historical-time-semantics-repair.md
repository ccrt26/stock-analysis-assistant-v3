# V3 Historical Time Semantics Repair Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` for inline execution, `superpowers:test-driven-development` for every behavior change, and `superpowers:verification-before-completion` before commits and completion. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Correct historical availability semantics in the unified research warehouse so strict historical `as_of` reads deterministic facts at their conservative business availability times while continuing to fail closed for future disclosures, revisions, relationships, and facts with no defensible historical publication time.

**Architecture:** Make the dataset contract authoritative for availability provenance, initial availability, revision timing, validity masking, and strict replay support. Fix ingestion to produce row-level times, enforce initial-versus-revision behavior in the warehouse, migrate only affected governance fields with dataset-level atomic swaps and conservation checks, then recompute derived partitions whose exact fact manifests changed.

**Tech Stack:** Python 3.11+, pandas, DuckDB, PyArrow/Parquet, Pydantic v2, Typer, pytest.

## Global Constraints

- Work directly on the current local `main`; do not create a branch or worktree.
- Preserve all user changes and the existing five local commits; never reset or overwrite unrelated content.
- Do not add a data source.
- Do not change V3 stock selection, scoring, report structure, publication, activation, deployment, or the knowledge base.
- Preserve `ingested_at`; it means local receipt time and must remain distinct from historical analytical availability.
- Never change business fields, business keys, `payload_hash`, fact partition paths, or existing revision business content during temporal migration.
- Never add a query option that bypasses `available_at` with `trade_date`.
- A deterministic fact may be reconstructed only for its initial version. A later changed version uses trustworthy source update time or, if absent, the new ingestion time.
- Announcement, financial, forecast, express, and other revisable disclosure facts require row-level publication evidence; absent evidence uses an auditable ingestion cutoff or fails closed.
- All real warehouse mutations use staging, conservation validation, atomic directory replacement, DuckDB transactions, rollback, and an idempotent migration receipt.

---

### Task 1: Encode the authoritative temporal contract

**Files:**
- Modify: `src/stock_analyzer/data/research_contracts.py`
- Create: `src/stock_analyzer/data/research_time.py`
- Test: `tests/test_research_contracts.py`
- Create: `tests/test_research_time.py`

**Interfaces:**
- Produces `AvailabilityPolicy`, `RevisionAvailabilityPolicy`, and `StrictReplayLevel` enums.
- Extends `DatasetContract` with `business_time_field`, `availability_policy`, `revision_availability_policy`, `strict_replay_level`, `source_published_fields`, and `mask_future_valid_to`.
- Produces `resolve_initial_availability(dataset_id, record, batch_ingested_at, explicit_available_at) -> ResolvedAvailability`.
- Produces `resolve_revision_availability(contract, normalized_row, *, batch_ingested_at, old_available_at) -> ResolvedAvailability`.
- `ResolvedAvailability` contains `available_at: datetime` and `precision: AvailabilityPrecision`.

- [x] **Step 1: Write failing registry coverage tests**

Add assertions to `tests/test_research_contracts.py` that all 29 datasets declare one policy and one strict replay level, and freeze the critical assignments:

```python
def test_every_research_dataset_has_an_explicit_temporal_contract():
    registry = research_contract_registry()
    assert set(registry) == set(ResearchDatasetId)
    for dataset, contract in registry.items():
        assert contract.availability_policy is not None, dataset.value
        assert contract.revision_availability_policy is not None, dataset.value
        assert contract.strict_replay_level is not None, dataset.value


def test_temporal_contract_separates_reconstructible_and_disclosure_facts():
    assert research_contract(ResearchDatasetId.TRADE_CALENDAR).availability_policy == (
        AvailabilityPolicy.BUSINESS_CLOSE
    )
    assert research_contract(ResearchDatasetId.INDUSTRY_DAILY).business_time_field == "trade_date"
    assert research_contract(ResearchDatasetId.THEME_DAILY).business_time_field == "trade_date"
    assert research_contract(ResearchDatasetId.ANNOUNCEMENT).availability_policy == (
        AvailabilityPolicy.SOURCE_PUBLISHED
    )
    assert research_contract(ResearchDatasetId.COMPANY_PROFILE).availability_policy == (
        AvailabilityPolicy.INGESTION_CUTOFF
    )
    assert research_contract(ResearchDatasetId.PLEDGE).strict_replay_level == (
        StrictReplayLevel.INGESTION_ONLY
    )
```

- [x] **Step 2: Run the registry tests and verify RED**

Run:

```bash
.venv/bin/pytest tests/test_research_contracts.py -q
```

Expected: FAIL because the enums and contract fields do not exist.

- [x] **Step 3: Write failing availability resolution tests**

Create `tests/test_research_time.py` with direct, timezone-aware expectations:

```python
def test_calendar_initial_fact_uses_its_own_calendar_date_not_batch_through():
    resolved = resolve_initial_availability(
        ResearchDatasetId.TRADE_CALENDAR,
        {"cal_date": date(2025, 8, 15)},
        batch_ingested_at=datetime(2026, 7, 13, 16, tzinfo=timezone.utc),
        explicit_available_at=None,
    )
    assert resolved.available_at.astimezone(ZoneInfo("Asia/Shanghai")) == datetime(
        2025, 8, 15, 15, 1, tzinfo=ZoneInfo("Asia/Shanghai")
    )


def test_ingestion_only_fact_cannot_backdate_to_snapshot_date():
    ingested = datetime(2026, 7, 14, 1, 15, tzinfo=timezone.utc)
    resolved = resolve_initial_availability(
        ResearchDatasetId.COMPANY_PROFILE,
        {"valid_from": date(2026, 7, 13)},
        batch_ingested_at=ingested,
        explicit_available_at=datetime(2026, 7, 13, 16, tzinfo=timezone.utc),
    )
    assert resolved.available_at == ingested
    assert resolved.precision is AvailabilityPrecision.INGESTION_CUTOFF


def test_source_published_fact_requires_row_level_evidence():
    with pytest.raises(ValueError, match="row-level publication time"):
        resolve_initial_availability(
            ResearchDatasetId.ANNOUNCEMENT,
            {"announcement_id": "A1"},
            batch_ingested_at=datetime(2026, 7, 14, tzinfo=timezone.utc),
            explicit_available_at=None,
        )
```

- [x] **Step 4: Run the new tests and verify RED**

Run:

```bash
.venv/bin/pytest tests/test_research_time.py -q
```

Expected: collection or assertion FAIL because `research_time.py` is absent.

- [x] **Step 5: Implement the minimal temporal model**

In `research_contracts.py`, add:

```python
class AvailabilityPolicy(str, Enum):
    BUSINESS_CLOSE = "business_close"
    VALID_FROM_CLOSE = "valid_from_close"
    NEXT_MORNING = "next_morning"
    SOURCE_PUBLISHED = "source_published"
    INGESTION_CUTOFF = "ingestion_cutoff"


class RevisionAvailabilityPolicy(str, Enum):
    OBSERVED_CHANGE = "observed_change"
    SOURCE_PUBLISHED = "source_published"


class StrictReplayLevel(str, Enum):
    STRICT = "strict"
    RECONSTRUCTED_CONSERVATIVE = "reconstructed_conservative"
    INGESTION_ONLY = "ingestion_only"
```

Add `INGESTION_CUTOFF = "ingestion_cutoff"` to `AvailabilityPrecision` and the contract fields listed in **Interfaces**. Populate every registry entry explicitly through `_contract()` defaults plus per-dataset overrides. Critical mappings:

```python
TRADE_CALENDAR -> BUSINESS_CLOSE/cal_date/OBSERVED_CHANGE/RECONSTRUCTED_CONSERVATIVE
EQUITY_DAILY, ADJ_FACTOR, DAILY_BASIC, STOCK_LIMIT, INDEX_DAILY,
INDUSTRY_DAILY, THEME_DAILY, SUSPENSION, MINUTE_BAR
    -> BUSINESS_CLOSE/trade_date/OBSERVED_CHANGE/RECONSTRUCTED_CONSERVATIVE
INDUSTRY_CATALOG, INDUSTRY_MEMBER, THEME_CATALOG, THEME_MEMBER
    -> VALID_FROM_CLOSE/valid_from/OBSERVED_CHANGE/RECONSTRUCTED_CONSERVATIVE
MARGIN_DETAIL -> NEXT_MORNING/trade_date/OBSERVED_CHANGE/RECONSTRUCTED_CONSERVATIVE
SECURITY_MASTER, COMPANY_PROFILE, PLEDGE
    -> INGESTION_CUTOFF/no business derivation/OBSERVED_CHANGE/INGESTION_ONLY
financials, forecasts, express, main business, announcements, holder trade,
share float, repurchase
    -> SOURCE_PUBLISHED/source fields/SOURCE_PUBLISHED/STRICT or conservative
```

Implement `research_time.py` with Asia/Shanghai helpers, aware-datetime normalization, and these rules:

```python
def resolve_initial_availability(...):
    if contract.availability_policy is AvailabilityPolicy.INGESTION_CUTOFF:
        return ResolvedAvailability(_utc(batch_ingested_at), INGESTION_CUTOFF)
    if contract.availability_policy is AvailabilityPolicy.SOURCE_PUBLISHED:
        if explicit_available_at is None:
            raise ValueError(f"{dataset.value} requires row-level publication time")
        return ResolvedAvailability(_utc(explicit_available_at), _record_precision(record))
    if explicit_available_at is not None:
        return ResolvedAvailability(_utc(explicit_available_at), _record_precision(record))
    if contract.availability_policy is AvailabilityPolicy.BUSINESS_CLOSE:
        return ResolvedAvailability(
            _post_close(record[contract.business_time_field]),
            INFERRED_FROM_ENDPOINT_POLICY,
        )
    if contract.availability_policy is AvailabilityPolicy.VALID_FROM_CLOSE:
        return ResolvedAvailability(
            _post_close(record[contract.business_time_field]),
            INFERRED_FROM_ENDPOINT_POLICY,
        )
    if contract.availability_policy is AvailabilityPolicy.NEXT_MORNING:
        return ResolvedAvailability(
            _next_morning(record[contract.business_time_field]),
            INFERRED_FROM_ENDPOINT_POLICY,
        )
    raise AssertionError(contract.availability_policy)
```

For source-published records, `_record_precision` respects explicit row precision; otherwise exact timestamps remain `EXACT`, while callers that use date-conservative rules must write `DATE_CONSERVATIVE` explicitly.

- [x] **Step 6: Run tests and verify GREEN**

Run:

```bash
.venv/bin/pytest tests/test_research_contracts.py tests/test_research_time.py -q
```

Expected: PASS.

- [x] **Step 7: Commit Task 1**

```bash
git add src/stock_analyzer/data/research_contracts.py src/stock_analyzer/data/research_time.py tests/test_research_contracts.py tests/test_research_time.py
git commit -m "feat: define research temporal contracts"
```

### Task 2: Enforce initial-versus-revision time semantics in the warehouse

**Files:**
- Modify: `src/stock_analyzer/storage/research_warehouse.py`
- Modify: `src/stock_analyzer/data/research_backfill.py`
- Modify: `src/stock_analyzer/data/classification_backfill.py`
- Modify: `src/stock_analyzer/data/fundamental_backfill.py`
- Modify: `src/stock_analyzer/data/event_backfill.py`
- Modify: `src/stock_analyzer/data/trading_structure_backfill.py`
- Test: `tests/test_research_warehouse.py`
- Test: `tests/test_research_market_backfill.py`
- Test: `tests/test_classification_backfill.py`
- Test: `tests/test_fundamental_backfill.py`
- Test: `tests/test_event_backfill.py`
- Test: `tests/test_trading_structure_backfill.py`

**Interfaces:**
- `ResearchWarehouse._normalize_batch()` calls `resolve_initial_availability()` per record instead of blindly applying one batch default.
- `ResearchWarehouse._merge()` applies `resolve_revision_availability()` only when payloads differ.
- Backfill services write row-level `available_at` and `availability_precision` when a source publication date exists.

- [x] **Step 1: Write failing warehouse tests for batch backfill and later corrections**

Add to `tests/test_research_warehouse.py`:

```python
def test_calendar_batch_uses_each_rows_business_date(tmp_path):
    warehouse = ResearchWarehouse(tmp_path)
    warehouse.commit_batch(FactBatch(
        dataset_id=ResearchDatasetId.TRADE_CALENDAR,
        partition_value="2025",
        source_name="tushare",
        source_endpoint="trade_cal",
        ingestion_run_id="calendar-backfill",
        ingested_at=datetime(2026, 7, 13, 16, tzinfo=timezone.utc),
        default_available_at=datetime(2026, 7, 13, 7, 1, tzinfo=timezone.utc),
        records=[
            {"exchange": "SSE", "cal_date": date(2025, 8, 15), "is_open": True},
            {"exchange": "SSE", "cal_date": date(2025, 8, 16), "is_open": False},
        ],
    ))
    rows = warehouse.read_current(ResearchDatasetId.TRADE_CALENDAR)
    assert pd.to_datetime(rows["available_at"], utc=True).dt.date.tolist() == [
        date(2025, 8, 15), date(2025, 8, 16)
    ]


def test_later_market_revision_uses_observed_ingestion_not_trade_date(tmp_path):
    warehouse = ResearchWarehouse(tmp_path)
    warehouse.commit_batch(_batch(close=10.2))
    changed = _batch(close=10.4).model_copy(update={
        "ingestion_run_id": "late-correction",
        "ingested_at": datetime(2026, 7, 12, 3, tzinfo=timezone.utc),
        "default_available_at": datetime(2026, 7, 10, 7, 1, tzinfo=timezone.utc),
    })
    warehouse.commit_batch(changed)
    current = warehouse.read_current(ResearchDatasetId.EQUITY_DAILY)
    assert pd.Timestamp(current.iloc[0]["available_at"]) == pd.Timestamp(
        datetime(2026, 7, 12, 3, tzinfo=timezone.utc)
    )
```

- [x] **Step 2: Add failing service-level regression tests**

Add these behaviors:

- `test_market_backfill_calendar_uses_each_cal_date_when_through_is_later`
- `test_classification_daily_history_uses_each_trade_date_as_available_at`
- `test_company_profile_uses_ingested_at_not_snapshot_date`
- `test_pledge_without_publication_time_uses_ingested_at`
- `test_financial_date_publication_is_marked_date_conservative`
- `test_margin_detail_keeps_t_plus_one_morning_policy`

Each test must assert the stored `available_at`, `ingested_at`, and `availability_precision`, not only row counts.

- [x] **Step 3: Run tests and verify RED**

Run:

```bash
.venv/bin/pytest tests/test_research_warehouse.py tests/test_research_market_backfill.py tests/test_classification_backfill.py tests/test_fundamental_backfill.py tests/test_event_backfill.py tests/test_trading_structure_backfill.py -q
```

Expected: new assertions FAIL because batch defaults still win and later market changes remain backdated.

- [x] **Step 4: Implement warehouse enforcement**

In `_normalize_batch()`:

```python
explicit = raw.get("available_at")
resolved = resolve_initial_availability(
    batch.dataset_id,
    raw,
    batch_ingested_at=batch.ingested_at,
    explicit_available_at=explicit,
)
row["available_at"] = resolved.available_at
row["availability_precision"] = raw.get(
    "availability_precision", resolved.precision.value
)
```

In `_merge()`, immediately before recording a changed row:

```python
contract = research_contract(batch.dataset_id)
revision_availability = resolve_revision_availability(
    contract,
    new_row,
    batch_ingested_at=batch.ingested_at,
    old_available_at=old_row["available_at"],
)
new_row["available_at"] = revision_availability.available_at
new_row["availability_precision"] = revision_availability.precision.value
```

For `OBSERVED_CHANGE`, use `source_updated_at` only when it is present and not before the old version's `available_at`; otherwise use `batch.ingested_at`. For `SOURCE_PUBLISHED`, keep the row publication time and reject missing evidence.

- [x] **Step 5: Make collectors explicit and remove unsafe defaults from production paths**

Change calendar records before `FactBatch` creation:

```python
records = frame.drop(columns=["cal_year"]).to_dict(orient="records")
for record in records:
    record["available_at"] = _post_close_utc(record["cal_date"])
```

Change classification daily normalization to add `available_at = _post_close_utc(trade_date)` per row. Set `availability_precision=DATE_CONSERVATIVE` in `_normalize_financial_row()`, `_holder_row()`, `_float_row()`, and `_repurchase_row()` where the source only supplies a date. Remove the synthetic `_conservative_available(actual_snapshot)` assignment for pledge; allow the contract to use ingestion cutoff. Company profile likewise uses ingestion cutoff.

Keep `default_available_at` in `FactBatch` for compatibility with controlled tests and legacy callers, but no production historical batch may rely on it for multiple business dates.

Update announcement and financial test helpers in `tests/test_research_warehouse.py`, `tests/test_research_as_of.py`, and `tests/test_research_partition_query.py` so source-published fixtures put `available_at` on each record. Do not weaken `SOURCE_PUBLISHED` by silently accepting a batch default as publication evidence.

- [x] **Step 6: Run focused tests and verify GREEN**

Run the command from Step 3. Expected: PASS.

- [x] **Step 7: Run adjacent source tests**

```bash
.venv/bin/pytest tests/test_tushare_research_client.py tests/test_cninfo_research_client.py tests/test_research_as_of.py -q
```

Expected: PASS; official CNInfo millisecond timestamps remain unchanged.

- [x] **Step 8: Commit Task 2**

```bash
git add src/stock_analyzer/storage/research_warehouse.py src/stock_analyzer/data/research_backfill.py src/stock_analyzer/data/classification_backfill.py src/stock_analyzer/data/fundamental_backfill.py src/stock_analyzer/data/event_backfill.py src/stock_analyzer/data/trading_structure_backfill.py tests/test_research_warehouse.py tests/test_research_market_backfill.py tests/test_classification_backfill.py tests/test_fundamental_backfill.py tests/test_event_backfill.py tests/test_trading_structure_backfill.py
git commit -m "fix: enforce fact availability semantics"
```

### Task 3: Prevent future validity edges from leaking through strict queries

**Files:**
- Modify: `src/stock_analyzer/storage/research_query.py`
- Test: `tests/test_research_partition_query.py`
- Test: `tests/test_research_as_of.py`

**Interfaces:**
- Produces `_mask_future_validity_edges(dataset, frame, cutoff) -> pd.DataFrame`.
- `_resolve_as_of()` applies the mask after selecting the correct version and before returning public facts.

- [x] **Step 1: Write a failing relationship test**

```python
def test_historical_relationship_hides_future_end_boundary(tmp_path):
    warehouse = ResearchWarehouse(tmp_path)
    warehouse.commit_batch(FactBatch(
        dataset_id=ResearchDatasetId.THEME_MEMBER,
        partition_value="official-theme-v1",
        source_name="tushare",
        source_endpoint="index_weight",
        ingestion_run_id="theme-members",
        ingested_at=datetime(2026, 7, 14, tzinfo=timezone.utc),
        records=[{
            "theme_code": "000019.SH",
            "ts_code": "000001.SZ",
            "valid_from": date(2025, 7, 31),
            "valid_to": date(2025, 8, 28),
        }],
    ))
    query = ResearchQuery(warehouse)
    before_end = query.dataset_as_of(
        ResearchDatasetId.THEME_MEMBER,
        datetime(2025, 8, 15, 15, 59, tzinfo=timezone.utc),
    )
    after_end = query.dataset_as_of(
        ResearchDatasetId.THEME_MEMBER,
        datetime(2025, 8, 29, 15, 59, tzinfo=timezone.utc),
    )
    assert pd.isna(before_end.iloc[0]["valid_to"])
    assert pd.Timestamp(after_end.iloc[0]["valid_to"]).date() == date(2025, 8, 28)
```

Also assert a row with `valid_from=2025-09-01` is absent at the 2025-08-15 cutoff.

- [x] **Step 2: Run and verify RED**

```bash
.venv/bin/pytest tests/test_research_partition_query.py::test_historical_relationship_hides_future_end_boundary -q
```

Expected: FAIL because `valid_to` is exposed before it occurs.

- [x] **Step 3: Implement validity masking**

Use contract `mask_future_valid_to`. Convert cutoff to Asia/Shanghai date, copy the frame, and set `valid_to` to `None` only where parsed `valid_to > cutoff_date`. Do not mutate the warehouse frame and do not remove historical closed relationships needed for past window calculations.

- [x] **Step 4: Run strict-query tests and verify GREEN**

```bash
.venv/bin/pytest tests/test_research_partition_query.py tests/test_research_as_of.py tests/test_classification_backfill.py -q
```

Expected: PASS.

- [x] **Step 5: Commit Task 3**

```bash
git add src/stock_analyzer/storage/research_query.py tests/test_research_partition_query.py tests/test_research_as_of.py
git commit -m "fix: hide future classification validity edges"
```

### Task 4: Build an atomic, conservative temporal migration

**Files:**
- Create: `src/stock_analyzer/storage/research_time_migration.py`
- Modify: `src/stock_analyzer/cli.py`
- Create: `tests/test_research_time_migration.py`
- Modify: `tests/test_cli.py`

**Interfaces:**
- Produces Pydantic models `TemporalDatasetAudit`, `TemporalMigrationReport`.
- Produces `audit_research_time_semantics(warehouse) -> tuple[TemporalDatasetAudit, ...]`.
- Produces `migrate_research_time_semantics(warehouse, *, migration_id: str) -> TemporalMigrationReport`.
- Adds CLI `python -m stock_analyzer data audit-time-semantics --output ...`.
- Adds CLI `python -m stock_analyzer data migrate-time-semantics --migration-id ...`.

- [x] **Step 1: Write a failing migration conservation test**

Create a tiny warehouse with:

- two calendar rows whose current `available_at` equals a 2026 backfill cutoff;
- one industry daily and one theme daily row with the same defect;
- one company profile and one pledge row backdated before ingestion;
- one announcement with an official timestamp;
- one financial revision with date-conservative availability.

Assert after migration:

```python
assert set(report.changed_datasets) == {
    "company_profile", "income_statement", "industry_daily", "pledge",
    "security_master", "theme_daily", "trade_calendar",
}
assert before_business_hashes == after_business_hashes
assert before_partition_keys == after_partition_keys
assert before_revision_business_payloads == after_revision_business_payloads
assert official_announcement_time_before == official_announcement_time_after
assert calendar_2025_available.date() == date(2025, 8, 15)
assert company_profile_available == company_profile_ingested
assert pledge_available == pledge_ingested
```

The fixture contains only the seven changed datasets above plus an unchanged
announcement control. The real populated warehouse is expected to report the
applicable subset of the 16 migration-policy datasets; empty or already correct
datasets must not be rewritten merely to satisfy a fixed count.

- [x] **Step 2: Write failing rollback and idempotence tests**

Monkeypatch the metadata transaction method to raise after the staged directory swap; assert the original file SHA-256 and manifest row remain visible. Run the migration twice and assert the second report has `already_completed=True` and changes no file hashes.

- [x] **Step 3: Run migration tests and verify RED**

```bash
.venv/bin/pytest tests/test_research_time_migration.py -q
```

Expected: collection FAIL because the migration module is absent.

- [x] **Step 4: Implement audit and row transforms**

The current-row transform may alter only governance fields:

```python
if dataset is TRADE_CALENDAR:
    row["available_at"] = post_close(row["cal_date"])
elif dataset in {INDUSTRY_DAILY, THEME_DAILY}:
    row["available_at"] = post_close(row["trade_date"])
elif dataset in {SECURITY_MASTER, COMPANY_PROFILE, PLEDGE}:
    row["available_at"] = row["ingested_at"]
    row["availability_precision"] = AvailabilityPrecision.INGESTION_CUTOFF.value
elif dataset in DATE_ONLY_DISCLOSURE_DATASETS:
    row["availability_precision"] = AvailabilityPrecision.DATE_CONSERVATIVE.value
```

For `MAIN_BUSINESS`, use ingestion cutoff only when `availability_limitation` says the provider has no announcement date. Never infer a new timestamp for `ANNOUNCEMENT`.

Transform revision `row_payload` with the same precision-only rules. Change `valid_from/valid_to` only if the corresponding row payload `available_at` actually changes; no affected real dataset currently combines bad backfilled time with revisions, but the implementation must remain correct for test fixtures.

- [x] **Step 5: Implement per-dataset staged atomic replacement**

For one dataset at a time:

1. Read manifest rows and revisions.
2. Write every transformed partition under `.staging/time-semantics/<migration-id>/<dataset>/...`.
3. Calculate before/after business-key hashes, payload hashes, revision payload business hashes, row counts, partition set, content hashes, and new file SHA-256.
4. Refuse promotion if any conservation item differs.
5. Move the existing dataset directory to `.staging/.../previous`, move staged data into the canonical location, and update all manifest/revision metadata in one DuckDB transaction.
6. On failure, restore the old directory and rollback the transaction.
7. On success, remove the short-lived previous directory.

Record one row in existing `research_migrations` with the fixed migration id, source root, pre-migration manifest hash, `completed` status, and the full JSON report.

- [x] **Step 6: Add the audit and migration CLI commands and test them**

Add:

```python
@data_app.command("audit-time-semantics")
def data_audit_time_semantics(
    output: Path = typer.Option(..., "--output"),
) -> None:
    config = AppConfig.load()
    audit = audit_research_time_semantics(
        ResearchWarehouse(config.local_warehouse_dir)
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps([item.model_dump(mode="json") for item in audit], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    typer.echo(f"time semantics audit: datasets={len(audit)} output={output}")
```

Add:

```python
@data_app.command("migrate-time-semantics")
def data_migrate_time_semantics(
    migration_id: str = typer.Option(..., "--migration-id"),
) -> None:
    config = AppConfig.load()
    report = migrate_research_time_semantics(
        ResearchWarehouse(config.local_warehouse_dir),
        migration_id=migration_id,
    )
    typer.echo(
        f"time semantics migration {report.migration_id}: "
        f"changed={len(report.changed_datasets)} "
        f"already_completed={str(report.already_completed).lower()}"
    )
```

- [x] **Step 7: Run tests and verify GREEN**

```bash
.venv/bin/pytest tests/test_research_time_migration.py tests/test_cli.py -q
```

Expected: PASS.

- [x] **Step 8: Run storage regression tests**

```bash
.venv/bin/pytest tests/test_research_schema.py tests/test_research_warehouse.py tests/test_research_migration.py tests/test_research_partition_query.py -q
```

Expected: PASS.

- [x] **Step 9: Commit Task 4**

```bash
git add src/stock_analyzer/storage/research_time_migration.py src/stock_analyzer/cli.py tests/test_research_time_migration.py tests/test_cli.py
git commit -m "feat: migrate historical fact availability safely"
```

### Task 5: Prove strict historical feature computation without a business-date bypass

**Files:**
- Modify: `src/stock_analyzer/ops/research_features.py`
- Modify: `tests/test_research_feature_job.py`
- Create: `tests/test_research_historical_availability.py`

**Interfaces:**
- The real `ResearchQuery` and `run_research_features()` must consume migrated facts with a historical cutoff.
- No fake query may select market facts solely by `trade_date`.
- When `security_master` is correctly hidden before its ingestion cutoff, the
  historical market coverage denominator uses only securities with visible
  same-day market facts and records that conservative universe limitation; it
  never backfills current descriptive security attributes.

- [x] **Step 1: Write a failing end-to-end historical test**

Build a minimal but real `ResearchWarehouse` containing enough open sessions and fact partitions for a historical analysis date. Seed calendar, equity, adjustment, valuation, limits, broad index, industry/theme catalog/member/daily facts with current defective backfill availability, run the migration, then run `run_research_features(..., analysis_date=date(2025, 8, 15), as_of=2025-08-15 23:59:59 Asia/Shanghai)`.

Assert:

```python
assert summary.failed_feature_sets == ()
assert summary.market_rows == 1
assert summary.stock_rows > 0
assert summary.as_of.year == 2025
```

Add future disclosure and future relationship rows and assert direct strict queries exclude them.

- [x] **Step 2: Run and verify RED before migration behavior is wired**

```bash
.venv/bin/pytest tests/test_research_historical_availability.py -q
```

Expected: FAIL at the calendar or strict cutoff assertion before the complete migration path exists.

- [x] **Step 3: Make only the minimal integration adjustments**

If the Task 1–4 code already satisfies the test, prove the regression test is meaningful by temporarily constructing the fixture without migration and observing the expected calendar failure, then restore the migration call and rerun. Do not add any `trade_date` query fallback.

- [x] **Step 4: Run feature and contract regressions**

```bash
.venv/bin/pytest tests/test_research_historical_availability.py tests/test_research_feature_job.py tests/test_research_contracts.py tests/test_research_as_of.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit Task 5**

```bash
git add tests/test_research_historical_availability.py tests/test_research_feature_job.py
git commit -m "test: prove strict historical research availability"
```

### Task 6: Execute the real migration and rebind derived dependencies

**Files/data:**
- Modify through normal application APIs: `local_warehouse/facts/**`, `local_warehouse/research.duckdb`, and affected `local_warehouse/derived/**` partitions.
- Create: `local_archive/audits/2026-07-16-v3-historical-time-semantics-migration.json`
- Create: `docs/operations/2026-07-16-v3-historical-time-semantics-repair.md`

**Interfaces:**
- Fixed migration id: `2026-07-16-historical-time-semantics-v1`.
- Formal audit records pre/post coverage, changed datasets, conservation results, migration receipt, derived recomputations, and strict replay limitations.

- [ ] **Step 1: Capture the real pre-migration audit**

Run:

```bash
.venv/bin/python -m stock_analyzer data audit-time-semantics --output local_archive/audits/2026-07-16-v3-historical-time-semantics-before.json
```

The JSON must record all 29 datasets, partition/row coverage, min/max business time, min/max `available_at`, min/max `ingested_at`, revision count, policy, and strict replay level.

- [ ] **Step 2: Run the real temporal migration**

```bash
.venv/bin/python -m stock_analyzer data migrate-time-semantics --migration-id 2026-07-16-historical-time-semantics-v1
```

Expected: exit 0 and a non-empty changed dataset count.

- [ ] **Step 3: Verify idempotence immediately**

Run the same command again. Expected: exit 0 and `already_completed=true`.

- [ ] **Step 4: Run post-migration read-only invariants**

Run:

```bash
.venv/bin/python -m stock_analyzer data audit-time-semantics --output local_archive/audits/2026-07-16-v3-historical-time-semantics-after.json
```

Verify:

- all 29 dataset partition/row totals are unchanged;
- business keys, payload hashes, content hashes, revision counts, and revision business payloads satisfy conservation;
- `trade_calendar` min availability now follows 2021-07-14;
- `industry_daily` and `theme_daily` min availability follow 2025-07-02;
- `security_master`, `company_profile`, and `pledge` are unavailable before their actual ingestion;
- future official announcements and financial revisions remain excluded at historical cutoffs.

- [ ] **Step 5: Recompute affected current derived partitions**

Read `research_derived_partitions.input_manifest_json`, select analysis dates whose fact snapshots reference changed file SHA-256 values, and invoke:

```bash
.venv/bin/python -m stock_analyzer data derive --data-date 2026-07-13
.venv/bin/python -m stock_analyzer data derive --data-date 2026-07-14
.venv/bin/python -m stock_analyzer data derive --data-date 2026-07-15
```

Only run dates that exist in the current derived manifest. Verify the stored fact snapshot hashes now match the migrated fact files and the three feature sets read back successfully.

- [ ] **Step 6: Execute one real strict historical recomputation**

Run `run_research_features()` for 2025-08-15 with an explicit 2025-08-15 23:59:59 Asia/Shanghai cutoff. It must complete without the historical validation module's trade-date reconstruction path. Preserve the resulting derived partition as migration verification evidence, not as a new selection result.

- [ ] **Step 7: Write the formal operations record**

`docs/operations/2026-07-16-v3-historical-time-semantics-repair.md` must contain:

- original symptom and root cause by layer;
- 29-dataset audit table;
- five-field time contract;
- migration id and commands;
- before/after counts and time ranges;
- business/revision/hash conservation evidence;
- derived recomputation list;
- historical and current verification results;
- unrecoverable history: company profile snapshots, pledge publication time, missing announcement dates, minute/Level 2/account identity;
- explicit statement that the prior frozen historical result remains pseudo-out-of-sample and is not retroactively renamed strict point-in-time.

### Task 7: Full verification, documentation consistency, and final main commit

**Files:**
- Update: `docs/operations/production-capability-matrix.md`
- Update: `docs/operations/runbook.md`
- Update: `docs/operations/2026-07-16-v3-historical-time-semantics-repair.md`
- Update plan checkboxes in this file.

- [ ] **Step 1: Run the focused temporal suite**

```bash
.venv/bin/pytest tests/test_research_time.py tests/test_research_time_migration.py tests/test_research_historical_availability.py tests/test_research_as_of.py tests/test_research_partition_query.py tests/test_research_warehouse.py tests/test_research_market_backfill.py tests/test_classification_backfill.py tests/test_fundamental_backfill.py tests/test_event_backfill.py tests/test_trading_structure_backfill.py tests/test_research_feature_job.py -q
```

Expected: all pass.

- [ ] **Step 2: Run all research data and feature contract tests**

```bash
.venv/bin/pytest tests/test_research_contracts.py tests/test_research_schema.py tests/test_research_migration.py tests/test_research_derived_store.py tests/test_research_health.py tests/test_research_data_job.py tests/test_research_gap_repair.py tests/test_market_context_features.py tests/test_hotspot_features.py tests/test_stock_context_features.py -q
```

Expected: all pass.

- [ ] **Step 3: Run the full suite**

```bash
.venv/bin/pytest -q
```

Expected: zero failures.

- [ ] **Step 4: Verify current real health and derived state**

```bash
.venv/bin/python -m stock_analyzer data health --data-date 2026-07-15 --full-history
```

Expected: command exits 0, current core facts remain complete, and affected derived partitions validate against their new input manifests.

- [ ] **Step 5: Run repository and scope checks**

```bash
git diff --check
rg -n "trade_date.*available_at|available_at.*trade_date" src/stock_analyzer/storage/research_query.py
rg -n "report|score|recommendation|publish|deploy" src/stock_analyzer/data/research_time.py src/stock_analyzer/storage/research_time_migration.py
git status --short
```

Expected: no whitespace errors, no query bypass, no out-of-scope feature logic, and only task files plus expected local data artifacts changed.

- [ ] **Step 6: Re-read the design and check every acceptance criterion**

Create a line-by-line checklist against `docs/superpowers/specs/2026-07-16-v3-historical-time-semantics-repair-design.md`. Add any missing evidence to the operations document before claiming completion.

- [ ] **Step 7: Stage and inspect the final code/document scope**

```bash
git add src tests docs/superpowers/plans/2026-07-16-v3-historical-time-semantics-repair.md docs/operations/2026-07-16-v3-historical-time-semantics-repair.md docs/operations/production-capability-matrix.md docs/operations/runbook.md
git diff --cached --check
git diff --cached --stat
```

- [ ] **Step 8: Commit the completed repair on current main**

```bash
git commit -m "fix: restore strict historical fact availability"
```

- [ ] **Step 9: Report in plain language**

Report:

- which datasets were physically corrected;
- which datasets were intentionally restricted instead of backdated;
- which historical gaps remain impossible to repair without real publication history;
- whether current daily processing and all tests passed;
- that future strict V3 validation may use only datasets with strict or conservative-reconstructed contracts;
- that the already frozen first historical batch remains pseudo-out-of-sample evidence.
