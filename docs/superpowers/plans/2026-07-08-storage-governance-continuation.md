# Storage Governance Continuation Implementation Plan

> **Lifecycle:** Historical execution record. Current production status is tracked only in [`docs/operations/production-capability-matrix.md`](../../operations/production-capability-matrix.md).

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Implementer and reviewer must use GPT-5.5 xhigh for every task in this plan; if unavailable, stop and ask the user before continuing.

**Goal:** Continue the paused Tushare Ingestion V1 work by moving full-market raw/coarse-analysis data into a managed local DuckDB + Parquet warehouse, limiting Supabase to the decision ledger and selected market windows, and preserving complete reports in local archive.

**Architecture:** This plan amends and continues `docs/superpowers/plans/2026-07-08-tushare-ingestion-v1.md`; it does not replace the Tushare provider, recommendation engine, focus logic, evidence logic, or report generator. Production `run-daily` must persist the full `MarketDataBundle` to `local_warehouse`, then write only final recommendations, focus stocks, structured evidence, evaluation tasks, data-source records, report indexes, and selected 120-trading-day windows to Supabase. `local_archive` stores full HTML reports and manifest files after report generation.

**Tech Stack:** Python 3.12 in `.venv`, Typer, Pydantic, Pandas, DuckDB, PyArrow/Parquet, Supabase Python client, pytest.

## Global Constraints

- Project root is `/Users/ccrt/股票分析助手`; current Codex workspace path is `/Users/ccrt/Documents/股票分析助手`.
- Use `.venv/bin/python`; do not use system Python.
- Do not print, copy, or commit `SUPABASE_SERVICE_ROLE_KEY`, Tushare token, or `.env.local`.
- Do not run production `run-daily` against real Supabase until all unit tests and reviewer gates in this plan pass and the user explicitly confirms a real write.
- Do not write full-market `daily_bars`, `daily_basic`, full stock statuses, full feature snapshots, or full candidate pools to Supabase.
- Supabase selected market windows are limited to recommendation, active focus, and internal control codes; until internal controls are implemented, use recommendation and active focus codes only.
- Low-level Supabase market-window writes must reject more than 40 unique stock codes or more than 5,000 rows per call.
- Supabase capacity guard thresholds are 350 MB warning and 400 MB stop-large-writes.
- `local_warehouse/`, `local_archive/`, and generated Parquet/HTML/archive artifacts must remain Git ignored.
- Keep the existing Tushare fixes as mainline requirements: `daily.amount` is converted from thousand yuan to yuan, current-bar coverage has a hard threshold, historical rows outside `stock_basic` are filtered, and `stock_master` is updated from Tushare `stock_basic`.

---

## File Structure

- Modify: `/Users/ccrt/股票分析助手/pyproject.toml`
  Add `duckdb` and `pyarrow` runtime dependencies because local warehouse tests read/write Parquet.
- Modify: `/Users/ccrt/股票分析助手/.gitignore`
  Ignore `local_warehouse/` and `local_archive/`.
- Modify: `/Users/ccrt/股票分析助手/src/stock_analyzer/config.py`
  Add `local_warehouse_dir`, `local_archive_dir`, `supabase_warn_mb`, and `supabase_stop_mb`.
- Create: `/Users/ccrt/股票分析助手/src/stock_analyzer/storage/local_warehouse.py`
  Own local DuckDB + Parquet writes for full-market raw/coarse-analysis data.
- Create: `/Users/ccrt/股票分析助手/src/stock_analyzer/storage/capacity_guard.py`
  Own Supabase capacity checks and selected-window write scope checks.
- Create: `/Users/ccrt/股票分析助手/src/stock_analyzer/storage/local_archive.py`
  Own report archive copying and manifest generation.
- Modify: `/Users/ccrt/股票分析助手/src/stock_analyzer/storage/repositories.py`
  Add capacity/scope guard to Supabase market-window writes.
- Modify: `/Users/ccrt/股票分析助手/src/stock_analyzer/pipeline.py`
  Require local warehouse for production persistence and filter Supabase writes to selected decision codes.
- Modify: `/Users/ccrt/股票分析助手/src/stock_analyzer/cli.py`
  Construct `LocalWarehouse`, `LocalArchive`, and capacity-guarded `SupabaseAnalysisRepository` for production runs. `LocalWarehouse` is wired in Task 4; `LocalArchive` is wired after Task 5 creates it.
- Modify: `/Users/ccrt/股票分析助手/supabase/migrations/202607080002_ingestion_v1.sql`
  Add a service-role callable database-size function used by capacity guard.
- Test: `/Users/ccrt/股票分析助手/tests/test_local_warehouse.py`
- Test: `/Users/ccrt/股票分析助手/tests/test_capacity_guard.py`
- Test: `/Users/ccrt/股票分析助手/tests/test_local_archive.py`
- Modify: `/Users/ccrt/股票分析助手/tests/test_pipeline_smoke.py`
- Modify: `/Users/ccrt/股票分析助手/tests/test_repositories.py`
- Modify: `/Users/ccrt/股票分析助手/tests/test_config_health.py`
- Modify: `/Users/ccrt/股票分析助手/tests/test_supabase_schema.py`

---

### Task 1: Storage Configuration, Dependencies, and Ignore Rules

**Files:**
- Modify: `/Users/ccrt/股票分析助手/pyproject.toml`
- Modify: `/Users/ccrt/股票分析助手/.gitignore`
- Modify: `/Users/ccrt/股票分析助手/src/stock_analyzer/config.py`
- Modify: `/Users/ccrt/股票分析助手/tests/test_config_health.py`

**Interfaces:**
- Produces: `AppConfig.local_warehouse_dir: Path`
- Produces: `AppConfig.local_archive_dir: Path`
- Produces: `AppConfig.supabase_warn_mb: float`
- Produces: `AppConfig.supabase_stop_mb: float`

- [ ] **Step 1: Write failing config test**

Add this test to `/Users/ccrt/股票分析助手/tests/test_config_health.py`:

```python
def test_storage_governance_paths_and_thresholds_default_to_project_root(tmp_path):
    config = AppConfig.load({"PROJECT_ROOT": str(tmp_path)})

    assert config.local_warehouse_dir == tmp_path / "local_warehouse"
    assert config.local_archive_dir == tmp_path / "local_archive"
    assert config.supabase_warn_mb == 350
    assert config.supabase_stop_mb == 400


def test_storage_governance_paths_can_be_overridden(tmp_path):
    config = AppConfig.load(
        {
            "PROJECT_ROOT": str(tmp_path),
            "LOCAL_WAREHOUSE_DIR": str(tmp_path / "warehouse-custom"),
            "LOCAL_ARCHIVE_DIR": str(tmp_path / "archive-custom"),
            "SUPABASE_WARN_MB": "321",
            "SUPABASE_STOP_MB": "399",
        }
    )

    assert config.local_warehouse_dir == tmp_path / "warehouse-custom"
    assert config.local_archive_dir == tmp_path / "archive-custom"
    assert config.supabase_warn_mb == 321
    assert config.supabase_stop_mb == 399
```

- [ ] **Step 2: Run test to verify failure**

Run: `.venv/bin/python -m pytest tests/test_config_health.py -v`
Expected: FAIL because `AppConfig` does not yet expose the four storage-governance fields.

- [ ] **Step 3: Add config fields**

In `/Users/ccrt/股票分析助手/src/stock_analyzer/config.py`, add fields to `AppConfig`:

```python
local_warehouse_dir: Path = _default_project_root() / "local_warehouse"
local_archive_dir: Path = _default_project_root() / "local_archive"
supabase_warn_mb: float = 350
supabase_stop_mb: float = 400
```

Inside `AppConfig.load()`, after `reports_dir` is defined, add:

```python
local_warehouse_dir = Path(
    values.get("LOCAL_WAREHOUSE_DIR", project_root / "local_warehouse")
).expanduser()
local_archive_dir = Path(
    values.get("LOCAL_ARCHIVE_DIR", project_root / "local_archive")
).expanduser()
```

Pass these fields into `cls(...)`:

```python
local_warehouse_dir=local_warehouse_dir,
local_archive_dir=local_archive_dir,
supabase_warn_mb=float(values.get("SUPABASE_WARN_MB", 350)),
supabase_stop_mb=float(values.get("SUPABASE_STOP_MB", 400)),
```

- [ ] **Step 4: Add dependencies and ignore rules**

In `/Users/ccrt/股票分析助手/pyproject.toml`, add runtime dependencies:

```toml
  "duckdb>=1.0",
  "pyarrow>=16",
```

In `/Users/ccrt/股票分析助手/.gitignore`, ensure these lines exist:

```gitignore
local_warehouse/
local_archive/
```

- [ ] **Step 5: Run tests**

Run: `.venv/bin/python -m pytest tests/test_config_health.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml .gitignore src/stock_analyzer/config.py tests/test_config_health.py
git commit -m "feat: add storage governance configuration"
```

---

### Task 2: Local Warehouse for Full-Market Data

**Files:**
- Create: `/Users/ccrt/股票分析助手/src/stock_analyzer/storage/local_warehouse.py`
- Create: `/Users/ccrt/股票分析助手/tests/test_local_warehouse.py`

**Interfaces:**
- Produces: `WarehouseWriteResult`
- Produces: `LocalWarehouse.save_bundle(bundle: MarketDataBundle) -> WarehouseWriteResult`
- Produces: `LocalWarehouse.query_count(dataset: str, trade_date: date) -> int`

- [ ] **Step 1: Write failing tests**

Create `/Users/ccrt/股票分析助手/tests/test_local_warehouse.py`:

```python
from datetime import date

from stock_analyzer.data.models import (
    DailyBar,
    DailyBasicRow,
    DataStatus,
    MarketDataBundle,
    SourceGrade,
    SourceRunRecord,
    SourceStatus,
    StockBasicRow,
)
from stock_analyzer.storage.local_warehouse import LocalWarehouse


def _bundle(trade_date: date) -> MarketDataBundle:
    return MarketDataBundle(
        trade_date=trade_date,
        data_status=DataStatus.COMPLETE_PRIMARY,
        source_grade=SourceGrade.PRIMARY,
        source_versions={"tushare": f"daily:{trade_date.isoformat()}"},
        stock_basic=[
            StockBasicRow(ts_code="600000.SH", name="浦发银行", exchange="SSE"),
            StockBasicRow(ts_code="000004.SZ", name="国华网安", exchange="SZSE"),
        ],
        daily_bars=[
            DailyBar(
                trade_date=trade_date,
                ts_code="600000.SH",
                close=10.2,
                amount=100000000,
                source_name="tushare",
                source_grade=SourceGrade.PRIMARY,
            ),
            DailyBar(
                trade_date=trade_date,
                ts_code="000004.SZ",
                close=12.3,
                amount=80000000,
                source_name="tushare",
                source_grade=SourceGrade.PRIMARY,
            ),
        ],
        daily_basic=[
            DailyBasicRow(
                trade_date=trade_date,
                ts_code="600000.SH",
                turnover_rate=1.2,
                source_name="tushare",
                source_grade=SourceGrade.PRIMARY,
            )
        ],
        source_runs=[
            SourceRunRecord(
                trade_date=trade_date,
                source_name="tushare",
                stage="daily",
                status=SourceStatus.SUCCESS,
                message="ok",
                source_grade=SourceGrade.PRIMARY,
                data_status=DataStatus.COMPLETE_PRIMARY,
                record_count=2,
            )
        ],
    )


def test_local_warehouse_writes_partitioned_parquet_and_duckdb_index(tmp_path):
    trade_date = date(2026, 7, 8)
    warehouse = LocalWarehouse(tmp_path / "local_warehouse")

    result = warehouse.save_bundle(_bundle(trade_date))

    assert result.market_daily_rows == 2
    assert result.daily_basic_rows == 1
    assert result.stock_basic_rows == 2
    assert result.source_run_rows == 1
    assert (tmp_path / "local_warehouse" / "warehouse.duckdb").exists()
    assert warehouse.query_count("market_daily", trade_date) == 2
    assert warehouse.query_count("daily_basic", trade_date) == 1


def test_local_warehouse_rerun_replaces_same_partition(tmp_path):
    trade_date = date(2026, 7, 8)
    warehouse = LocalWarehouse(tmp_path / "local_warehouse")

    warehouse.save_bundle(_bundle(trade_date))
    warehouse.save_bundle(_bundle(trade_date))

    assert warehouse.query_count("market_daily", trade_date) == 2
```

- [ ] **Step 2: Run test to verify failure**

Run: `.venv/bin/python -m pytest tests/test_local_warehouse.py -v`
Expected: FAIL because `stock_analyzer.storage.local_warehouse` does not exist.

- [ ] **Step 3: Implement local warehouse**

Create `/Users/ccrt/股票分析助手/src/stock_analyzer/storage/local_warehouse.py`:

```python
from __future__ import annotations

import shutil
from datetime import date
from pathlib import Path

import duckdb
import pandas as pd
from pydantic import BaseModel

from stock_analyzer.data.models import MarketDataBundle


class WarehouseWriteResult(BaseModel):
    market_daily_rows: int
    daily_basic_rows: int
    stock_basic_rows: int
    source_run_rows: int


class LocalWarehouse:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.parquet_root = root / "parquet"
        self.duckdb_path = root / "warehouse.duckdb"

    def save_bundle(self, bundle: MarketDataBundle) -> WarehouseWriteResult:
        self.root.mkdir(parents=True, exist_ok=True)
        self.parquet_root.mkdir(parents=True, exist_ok=True)
        market_rows = [item.model_dump(mode="json") for item in bundle.daily_bars]
        basic_rows = [item.model_dump(mode="json") for item in bundle.daily_basic]
        stock_rows = [item.model_dump(mode="json") for item in bundle.stock_basic]
        source_rows = [item.model_dump(mode="json") for item in bundle.source_runs]

        self._write_trade_date_partition("market_daily", bundle.trade_date, market_rows)
        self._write_trade_date_partition("daily_basic", bundle.trade_date, basic_rows)
        self._write_trade_date_partition("source_runs", bundle.trade_date, source_rows)
        self._write_snapshot_partition("stock_basic", bundle.trade_date, stock_rows)
        self._refresh_duckdb_marker()
        return WarehouseWriteResult(
            market_daily_rows=len(market_rows),
            daily_basic_rows=len(basic_rows),
            stock_basic_rows=len(stock_rows),
            source_run_rows=len(source_rows),
        )

    def query_count(self, dataset: str, trade_date: date) -> int:
        partition = self.parquet_root / dataset / f"trade_date={trade_date.isoformat()}" / "data.parquet"
        if not partition.exists():
            return 0
        with duckdb.connect(str(self.duckdb_path)) as connection:
            return int(
                connection.execute(
                    "select count(*) from read_parquet(?)",
                    [str(partition)],
                ).fetchone()[0]
            )

    def _write_trade_date_partition(self, dataset: str, trade_date: date, rows: list[dict]) -> None:
        partition_dir = self.parquet_root / dataset / f"trade_date={trade_date.isoformat()}"
        self._replace_partition(partition_dir, rows)

    def _write_snapshot_partition(self, dataset: str, snapshot_date: date, rows: list[dict]) -> None:
        partition_dir = self.parquet_root / dataset / f"snapshot_date={snapshot_date.isoformat()}"
        self._replace_partition(partition_dir, rows)

    def _replace_partition(self, partition_dir: Path, rows: list[dict]) -> None:
        if partition_dir.exists():
            shutil.rmtree(partition_dir)
        partition_dir.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(rows).to_parquet(partition_dir / "data.parquet", index=False)

    def _refresh_duckdb_marker(self) -> None:
        with duckdb.connect(str(self.duckdb_path)) as connection:
            connection.execute("create table if not exists warehouse_metadata (key text primary key, value text)")
            connection.execute(
                "insert or replace into warehouse_metadata values ('format', 'duckdb-parquet-v1')"
            )
```

- [ ] **Step 4: Install storage dependencies if missing**

Run: `.venv/bin/python -m pip install 'duckdb>=1.0' 'pyarrow>=16'`
Expected: PASS. Record this dependency install in the subagent report.

- [ ] **Step 5: Run tests**

Run: `.venv/bin/python -m pytest tests/test_local_warehouse.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/stock_analyzer/storage/local_warehouse.py tests/test_local_warehouse.py
git commit -m "feat: add local market warehouse"
```

---

### Task 3: Supabase Capacity Guard and Selected-Window Scope Guard

**Files:**
- Create: `/Users/ccrt/股票分析助手/src/stock_analyzer/storage/capacity_guard.py`
- Modify: `/Users/ccrt/股票分析助手/src/stock_analyzer/storage/repositories.py`
- Modify: `/Users/ccrt/股票分析助手/supabase/migrations/202607080002_ingestion_v1.sql`
- Create: `/Users/ccrt/股票分析助手/tests/test_capacity_guard.py`
- Modify: `/Users/ccrt/股票分析助手/tests/test_repositories.py`
- Modify: `/Users/ccrt/股票分析助手/tests/test_supabase_schema.py`

**Interfaces:**
- Produces: `SupabaseCapacityGuard.check() -> CapacityStatus`
- Produces: `SupabaseCapacityGuard.ensure_large_writes_allowed() -> None`
- Produces: `ensure_selected_market_window_scope(rows: Sequence[DailyBar | DailyBasicRow]) -> None`

- [ ] **Step 1: Write failing capacity tests**

Create `/Users/ccrt/股票分析助手/tests/test_capacity_guard.py`:

```python
from datetime import date

import pytest

from stock_analyzer.data.models import DailyBar, SourceGrade
from stock_analyzer.storage.capacity_guard import (
    SupabaseCapacityGuard,
    SupabaseCapacityLimitExceeded,
    SupabaseWriteScopeError,
    ensure_selected_market_window_scope,
)


class FakeRpcResult:
    def __init__(self, data):
        self.data = data


class FakeCapacityClient:
    def __init__(self, size_mb):
        self.size_mb = size_mb

    def rpc(self, name):
        assert name == "database_size_mb"
        return self

    def execute(self):
        return FakeRpcResult(self.size_mb)


def _bar(ts_code):
    return DailyBar(
        trade_date=date(2026, 7, 8),
        ts_code=ts_code,
        close=10.0,
        source_name="tushare",
        source_grade=SourceGrade.PRIMARY,
    )


def test_capacity_guard_allows_normal_size_and_flags_warning():
    normal = SupabaseCapacityGuard(FakeCapacityClient(349), warn_mb=350, stop_mb=400).check()
    warning = SupabaseCapacityGuard(FakeCapacityClient(350), warn_mb=350, stop_mb=400).check()

    assert normal.warn is False
    assert normal.stop_large_writes is False
    assert warning.warn is True
    assert warning.stop_large_writes is False


def test_capacity_guard_stops_large_writes_at_stop_threshold():
    guard = SupabaseCapacityGuard(FakeCapacityClient(400), warn_mb=350, stop_mb=400)

    with pytest.raises(SupabaseCapacityLimitExceeded):
        guard.ensure_large_writes_allowed()


def test_selected_market_window_scope_rejects_full_market_shape():
    rows = [_bar(f"600{i:03d}.SH") for i in range(41)]

    with pytest.raises(SupabaseWriteScopeError):
        ensure_selected_market_window_scope(rows)
```

- [ ] **Step 2: Add repository tests**

Add this test to `/Users/ccrt/股票分析助手/tests/test_repositories.py`:

```python
def test_supabase_repository_rejects_full_market_window_without_network():
    client = FakeSupabaseClient()
    repo = SupabaseAnalysisRepository(client)
    trade_date = date(2026, 7, 8)

    with pytest.raises(ValueError) as excinfo:
        repo.save_market_bars(
            [
                DailyBar(
                    trade_date=trade_date,
                    ts_code=f"600{i:03d}.SH",
                    close=10.0,
                    amount=100000000,
                    source_name="tushare",
                    source_grade=SourceGrade.PRIMARY,
                )
                for i in range(41)
            ]
        )

    assert "selected market window" in str(excinfo.value)
    assert client.write_calls == []
```

- [ ] **Step 3: Run tests to verify failure**

Run: `.venv/bin/python -m pytest tests/test_capacity_guard.py tests/test_repositories.py -v`
Expected: FAIL because capacity guard does not exist and repository does not enforce selected-window scope.

- [ ] **Step 4: Implement capacity guard**

Create `/Users/ccrt/股票分析助手/src/stock_analyzer/storage/capacity_guard.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence


MAX_SELECTED_WINDOW_CODES = 40
MAX_SELECTED_WINDOW_ROWS = 5000


class SupabaseCapacityLimitExceeded(RuntimeError):
    pass


class SupabaseWriteScopeError(ValueError):
    pass


@dataclass(frozen=True)
class CapacityStatus:
    size_mb: float
    warn: bool
    stop_large_writes: bool


class SupabaseCapacityGuard:
    def __init__(self, client, *, warn_mb: float, stop_mb: float) -> None:
        self.client = client
        self.warn_mb = warn_mb
        self.stop_mb = stop_mb

    def check(self) -> CapacityStatus:
        result = self.client.rpc("database_size_mb").execute()
        size_mb = float(result.data)
        return CapacityStatus(
            size_mb=size_mb,
            warn=size_mb >= self.warn_mb,
            stop_large_writes=size_mb >= self.stop_mb,
        )

    def ensure_large_writes_allowed(self) -> None:
        status = self.check()
        if status.stop_large_writes:
            raise SupabaseCapacityLimitExceeded(
                f"Supabase database size is {status.size_mb:.1f} MB; large writes stop at {self.stop_mb:.1f} MB"
            )


def ensure_selected_market_window_scope(rows: Sequence[object]) -> None:
    ts_codes = {getattr(row, "ts_code") for row in rows}
    if len(ts_codes) > MAX_SELECTED_WINDOW_CODES or len(rows) > MAX_SELECTED_WINDOW_ROWS:
        raise SupabaseWriteScopeError(
            "Supabase selected market window write rejected: "
            f"{len(ts_codes)} codes and {len(rows)} rows exceeds "
            f"{MAX_SELECTED_WINDOW_CODES} codes or {MAX_SELECTED_WINDOW_ROWS} rows"
        )
```

- [ ] **Step 5: Guard repository writes**

In `/Users/ccrt/股票分析助手/src/stock_analyzer/storage/repositories.py`, import:

```python
from stock_analyzer.storage.capacity_guard import ensure_selected_market_window_scope
```

Change `SupabaseAnalysisRepository.__init__` to:

```python
def __init__(self, client, capacity_guard=None) -> None:
    self.client = client
    self.capacity_guard = capacity_guard
```

At the beginning of `save_market_bars()` and `save_daily_basic_indicators()`, add:

```python
if not bars:
    return
ensure_selected_market_window_scope(bars)
if self.capacity_guard is not None:
    self.capacity_guard.ensure_large_writes_allowed()
```

For `save_daily_basic_indicators()`, use `rows` in the guard block:

```python
if not rows:
    return
ensure_selected_market_window_scope(rows)
if self.capacity_guard is not None:
    self.capacity_guard.ensure_large_writes_allowed()
```

- [ ] **Step 6: Add database-size function to migration**

Append this to `/Users/ccrt/股票分析助手/supabase/migrations/202607080002_ingestion_v1.sql`:

```sql
create or replace function public.database_size_mb()
returns numeric
language sql
security definer
set search_path = public
as $$
  select pg_database_size(current_database()) / 1024.0 / 1024.0;
$$;

grant execute on function public.database_size_mb() to service_role;
```

Add this assertion to `/Users/ccrt/股票分析助手/tests/test_supabase_schema.py`:

```python
def test_ingestion_schema_adds_capacity_guard_function():
    sql = INGESTION_SCHEMA_PATH.read_text().lower()

    assert "create or replace function public.database_size_mb()" in sql
    assert "pg_database_size(current_database())" in sql
    assert "grant execute on function public.database_size_mb() to service_role" in sql
```

- [ ] **Step 7: Run tests**

Run: `.venv/bin/python -m pytest tests/test_capacity_guard.py tests/test_repositories.py tests/test_supabase_schema.py -v`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add src/stock_analyzer/storage/capacity_guard.py src/stock_analyzer/storage/repositories.py supabase/migrations/202607080002_ingestion_v1.sql tests/test_capacity_guard.py tests/test_repositories.py tests/test_supabase_schema.py
git commit -m "feat: guard supabase selected window writes"
```

---

### Task 4: Production Pipeline Persistence Boundary

**Files:**
- Modify: `/Users/ccrt/股票分析助手/src/stock_analyzer/pipeline.py`
- Modify: `/Users/ccrt/股票分析助手/src/stock_analyzer/cli.py`
- Modify: `/Users/ccrt/股票分析助手/tests/test_pipeline_smoke.py`
- Modify: `/Users/ccrt/股票分析助手/tests/test_repositories.py`

**Interfaces:**
- Modifies: `run_daily_pipeline(..., local_warehouse: Optional[LocalWarehouse] = None, local_archive: Optional[LocalArchive] = None)`
- Produces: `_selected_decision_codes(recommendations: list[Recommendation], focus_states: list[FocusState]) -> set[str]`
- Produces: `_filter_market_window(bundle: MarketDataBundle, selected_codes: set[str]) -> tuple[list[DailyBar], list[DailyBasicRow]]`

- [ ] **Step 1: Add failing pipeline test**

Add this test to `/Users/ccrt/股票分析助手/tests/test_pipeline_smoke.py`:

```python
class RecordingWarehouse:
    def __init__(self):
        self.saved_bundles = []

    def save_bundle(self, bundle):
        self.saved_bundles.append(bundle)


class ProviderWithExtraRawCode:
    def load(self, trade_date):
        stocks, stock_names, feature_profiles = _sample_market(trade_date)
        stock_names["000004.SZ"] = "国华网安"
        return MarketDataBundle(
            trade_date=trade_date,
            data_status=DataStatus.COMPLETE_PRIMARY,
            source_grade=SourceGrade.PRIMARY,
            source_versions={"fake-live": trade_date.isoformat()},
            stock_basic=_raw_stock_basic()
            + [StockBasicRow(ts_code="000004.SZ", name="国华网安", exchange="SZSE")],
            daily_bars=_raw_daily_bars(trade_date, "600000.SH")
            + _raw_daily_bars(trade_date, "600519.SH")
            + _raw_daily_bars(trade_date, "000004.SZ"),
            daily_basic=_raw_daily_basic(trade_date, "600000.SH")
            + _raw_daily_basic(trade_date, "600519.SH")
            + _raw_daily_basic(trade_date, "000004.SZ"),
            stocks=stocks,
            stock_names=stock_names,
            feature_profiles=feature_profiles,
            source_runs=_raw_source_runs(trade_date, 3),
        )


def test_production_pipeline_writes_full_bundle_to_warehouse_and_selected_windows_to_repo(tmp_path):
    repo = InMemoryAnalysisRepository()
    warehouse = RecordingWarehouse()

    run_daily_pipeline(
        date(2026, 7, 7),
        tmp_path,
        repository=repo,
        fixture_mode=False,
        market_data_provider=ProviderWithExtraRawCode(),
        local_warehouse=warehouse,
    )

    assert len(warehouse.saved_bundles) == 1
    assert {bar.ts_code for bar in warehouse.saved_bundles[0].daily_bars} == {
        "600000.SH",
        "600519.SH",
        "000004.SZ",
    }
    selected_codes = {item.ts_code for item in repo.recommendations} | {
        item.ts_code for item in repo.focus_states
    }
    assert {bar.ts_code for bar in repo.market_bars} <= selected_codes
    assert "000004.SZ" not in {bar.ts_code for bar in repo.market_bars}


def test_production_pipeline_requires_local_warehouse_before_persisting(tmp_path):
    repo = InMemoryAnalysisRepository()

    with pytest.raises(RuntimeError) as excinfo:
        run_daily_pipeline(
            date(2026, 7, 7),
            tmp_path,
            repository=repo,
            fixture_mode=False,
            market_data_provider=ProviderWithExtraRawCode(),
        )

    assert "local warehouse" in str(excinfo.value).lower()
    assert repo.recommendations == []
    assert repo.market_bars == []
```

- [ ] **Step 2: Run test to verify failure**

Run: `.venv/bin/python -m pytest tests/test_pipeline_smoke.py::test_production_pipeline_writes_full_bundle_to_warehouse_and_selected_windows_to_repo tests/test_pipeline_smoke.py::test_production_pipeline_requires_local_warehouse_before_persisting -v`
Expected: FAIL because `run_daily_pipeline` has no `local_warehouse` parameter and currently writes all raw bars to repository.

- [ ] **Step 3: Modify pipeline signature and production raw persistence**

In `/Users/ccrt/股票分析助手/src/stock_analyzer/pipeline.py`, import the data row types:

```python
from stock_analyzer.data.models import DailyBar, DailyBasicRow, MarketDataBundle
```

Change `run_daily_pipeline` signature:

```python
def run_daily_pipeline(
    trade_date: date,
    output_dir: Path,
    dry_run: bool = False,
    repository: Optional[AnalysisRepository] = None,
    existing_focus_states: Optional[list[FocusState]] = None,
    persist: bool = True,
    fixture_mode: bool = False,
    market_data_provider: Optional[MarketDataProvider] = None,
    local_warehouse=None,
    local_archive=None,
) -> DailyRunResult:
```

Replace the current production pre-save block:

```python
if persist and production_bundle is not None:
    repository.save_stock_master(production_bundle.stock_basic)
    repository.save_market_bars(production_bundle.daily_bars)
    repository.save_daily_basic_indicators(production_bundle.daily_basic)
    repository.save_data_source_runs(production_bundle.source_runs)
```

with:

```python
if persist and production_bundle is not None:
    if local_warehouse is None:
        raise ProductionDataSourceUnavailable(
            "Production persistence requires local warehouse before Supabase writes."
        )
    local_warehouse.save_bundle(production_bundle)
    repository.save_stock_master(production_bundle.stock_basic)
    repository.save_data_source_runs(production_bundle.source_runs)
```

- [ ] **Step 4: Filter Supabase daily state and feature writes to selected decision codes**

In `/Users/ccrt/股票分析助手/src/stock_analyzer/pipeline.py`, replace the final `if persist:` block with:

```python
if persist:
    selected_codes = _selected_decision_codes(recommendations, focus_states)
    if production_bundle is not None:
        selected_market_bars, selected_daily_basic = _filter_market_window(
            production_bundle,
            selected_codes,
        )
        repository.save_market_bars(selected_market_bars)
        repository.save_daily_basic_indicators(selected_daily_basic)
        stock_statuses_to_save = [
            stock for stock in stocks if stock.ts_code in selected_codes
        ]
        features_to_save = [
            feature for feature in features if feature.ts_code in selected_codes
        ]
    else:
        stock_statuses_to_save = stocks
        features_to_save = features
    repository.save_stock_master(stock_statuses_to_save)
    repository.save_stock_statuses(stock_statuses_to_save)
    repository.save_feature_snapshots(features_to_save)
    repository.save_recommendations(recommendations)
    repository.save_focus_states(focus_states)
    repository.save_evidence_packages(evidence_packages)
    repository.save_evaluation_tasks(evaluation_tasks)
```

Add helpers near `_has_recommendation_eligible_features`:

```python
def _selected_decision_codes(
    recommendations: list[Recommendation],
    focus_states: list[FocusState],
) -> set[str]:
    excluded_states = {ActionLabel.EXIT_OBSERVATION, ActionLabel.INSUFFICIENT_DATA}
    return {item.ts_code for item in recommendations} | {
        item.ts_code for item in focus_states if item.state not in excluded_states
    }


def _filter_market_window(
    bundle: MarketDataBundle,
    selected_codes: set[str],
) -> tuple[list[DailyBar], list[DailyBasicRow]]:
    if not selected_codes:
        return [], []
    return (
        [bar for bar in bundle.daily_bars if bar.ts_code in selected_codes],
        [row for row in bundle.daily_basic if row.ts_code in selected_codes],
    )
```

Add `ActionLabel` to the existing domain imports.

- [ ] **Step 5: Wire CLI production warehouse and capacity guard**

In `/Users/ccrt/股票分析助手/src/stock_analyzer/cli.py`, import:

```python
from stock_analyzer.storage.capacity_guard import SupabaseCapacityGuard
from stock_analyzer.storage.local_warehouse import LocalWarehouse
```

When calling `run_daily_pipeline`, pass:

```python
local_warehouse=(
    LocalWarehouse(config.local_warehouse_dir)
    if not dry_run and not effective_fixture_mode
    else None
),
```

In `_analysis_repository`, construct capacity guard when creating Supabase repository:

```python
client = create_supabase_client(config)
return SupabaseAnalysisRepository(
    client,
    capacity_guard=SupabaseCapacityGuard(
        client,
        warn_mb=config.supabase_warn_mb,
        stop_mb=config.supabase_stop_mb,
    ),
)
```

- [ ] **Step 6: Run tests**

Run: `.venv/bin/python -m pytest tests/test_pipeline_smoke.py tests/test_repositories.py tests/test_cli.py -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/stock_analyzer/pipeline.py src/stock_analyzer/cli.py tests/test_pipeline_smoke.py tests/test_repositories.py tests/test_cli.py
git commit -m "feat: route production persistence through storage governance"
```

---

### Task 5: Local Archive and Report Manifest

**Files:**
- Create: `/Users/ccrt/股票分析助手/src/stock_analyzer/storage/local_archive.py`
- Create: `/Users/ccrt/股票分析助手/tests/test_local_archive.py`
- Modify: `/Users/ccrt/股票分析助手/src/stock_analyzer/pipeline.py`
- Modify: `/Users/ccrt/股票分析助手/src/stock_analyzer/cli.py`
- Modify: `/Users/ccrt/股票分析助手/tests/test_pipeline_smoke.py`

**Interfaces:**
- Produces: `LocalArchive.archive_report_tree(reports_dir: Path, trade_date: date) -> Path`
- Produces: `LocalArchive.write_manifest(trade_date: date, files: list[Path]) -> Path`

- [ ] **Step 1: Write failing archive tests**

Create `/Users/ccrt/股票分析助手/tests/test_local_archive.py`:

```python
import json
from datetime import date

from stock_analyzer.storage.local_archive import LocalArchive


def test_local_archive_copies_report_tree_and_writes_manifest(tmp_path):
    reports_dir = tmp_path / "reports"
    data_dir = reports_dir / "data"
    daily_dir = reports_dir / "daily" / "2026-07-08"
    data_dir.mkdir(parents=True)
    daily_dir.mkdir(parents=True)
    (reports_dir / "index.html").write_text("<html>latest</html>", encoding="utf-8")
    (data_dir / "latest.json").write_text("{}", encoding="utf-8")
    (daily_dir / "index.html").write_text("<html>daily</html>", encoding="utf-8")

    archive = LocalArchive(tmp_path / "local_archive")
    manifest_path = archive.archive_report_tree(reports_dir, date(2026, 7, 8))

    assert (tmp_path / "local_archive" / "reports" / "2026-07-08" / "index.html").exists()
    assert (tmp_path / "local_archive" / "reports" / "2026-07-08" / "data" / "latest.json").exists()
    assert manifest_path.exists()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["trade_date"] == "2026-07-08"
    assert manifest["file_count"] == 3
    assert all("sha256" in item for item in manifest["files"])
```

- [ ] **Step 2: Run test to verify failure**

Run: `.venv/bin/python -m pytest tests/test_local_archive.py -v`
Expected: FAIL because `stock_analyzer.storage.local_archive` does not exist.

- [ ] **Step 3: Implement local archive**

Create `/Users/ccrt/股票分析助手/src/stock_analyzer/storage/local_archive.py`:

```python
from __future__ import annotations

import hashlib
import json
import shutil
from datetime import date, datetime, timezone
from pathlib import Path


class LocalArchive:
    def __init__(self, root: Path) -> None:
        self.root = root

    def archive_report_tree(self, reports_dir: Path, trade_date: date) -> Path:
        target = self.root / "reports" / trade_date.isoformat()
        if target.exists():
            shutil.rmtree(target)
        target.mkdir(parents=True, exist_ok=True)
        files_to_copy = [reports_dir / "index.html"]
        daily_dir = reports_dir / "daily" / trade_date.isoformat()
        if daily_dir.exists():
            files_to_copy.extend(path for path in daily_dir.rglob("*") if path.is_file())
        data_dir = reports_dir / "data"
        if data_dir.exists():
            files_to_copy.extend(path for path in data_dir.rglob("*") if path.is_file())
        copied_files = []
        for source in files_to_copy:
            if not source.exists():
                continue
            relative = source.relative_to(reports_dir)
            destination = target / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
            copied_files.append(destination)
        return self.write_manifest(trade_date, copied_files)

    def write_manifest(self, trade_date: date, files: list[Path]) -> Path:
        manifest_dir = self.root / "manifests"
        manifest_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = manifest_dir / f"{trade_date.isoformat()}.json"
        payload = {
            "trade_date": trade_date.isoformat(),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "file_count": len(files),
            "files": [
                {
                    "path": str(path),
                    "size": path.stat().st_size,
                    "sha256": _sha256(path),
                }
                for path in sorted(files)
            ],
        }
        manifest_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return manifest_path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
```

- [ ] **Step 4: Archive production reports from pipeline**

In `/Users/ccrt/股票分析助手/src/stock_analyzer/pipeline.py`, after `render_reports(...)`, add:

```python
if local_archive is not None and not fixture_mode:
    local_archive.archive_report_tree(output_dir, trade_date)
```

In `/Users/ccrt/股票分析助手/src/stock_analyzer/cli.py`, import:

```python
from stock_analyzer.storage.local_archive import LocalArchive
```

When calling `run_daily_pipeline`, add:

```python
local_archive=(
    LocalArchive(config.local_archive_dir)
    if not dry_run and not effective_fixture_mode
    else None
),
```

Add a test to `/Users/ccrt/股票分析助手/tests/test_pipeline_smoke.py`:

```python
class RecordingArchive:
    def __init__(self):
        self.calls = []

    def archive_report_tree(self, reports_dir, trade_date):
        self.calls.append((reports_dir, trade_date))


def test_production_pipeline_archives_report_after_render(tmp_path):
    repo = InMemoryAnalysisRepository()
    warehouse = RecordingWarehouse()
    archive = RecordingArchive()

    run_daily_pipeline(
        date(2026, 7, 7),
        tmp_path,
        repository=repo,
        fixture_mode=False,
        market_data_provider=ProviderWithExtraRawCode(),
        local_warehouse=warehouse,
        local_archive=archive,
    )

    assert archive.calls == [(tmp_path, date(2026, 7, 7))]
```

- [ ] **Step 5: Run tests**

Run: `.venv/bin/python -m pytest tests/test_local_archive.py tests/test_pipeline_smoke.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/stock_analyzer/storage/local_archive.py src/stock_analyzer/pipeline.py src/stock_analyzer/cli.py tests/test_local_archive.py tests/test_pipeline_smoke.py
git commit -m "feat: archive production reports locally"
```

---

### Task 6: Verification, No-Real-Write Gate, and Handoff Back to Tushare V1

**Files:**
- Modify only if tests reveal a defect in files touched by Tasks 1-5.
- Update docs only if commands or behavior changed during implementation.

**Interfaces:**
- Consumes: all interfaces from Tasks 1-5.
- Produces: a reviewed branch ready to resume Tushare V1 Task 9 with storage governance.

- [ ] **Step 1: Verify storage dependencies are installed**

Run: `.venv/bin/python -m pip install 'duckdb>=1.0' 'pyarrow>=16'`
Expected: PASS with packages already satisfied or installed. Record the result in the subagent report.

- [ ] **Step 2: Run focused storage and pipeline tests**

Run: `.venv/bin/python -m pytest tests/test_local_warehouse.py tests/test_capacity_guard.py tests/test_local_archive.py tests/test_pipeline_smoke.py tests/test_repositories.py tests/test_supabase_schema.py -v`
Expected: PASS.

- [ ] **Step 3: Run full unit test suite**

Run: `.venv/bin/python -m pytest`
Expected: PASS.

- [ ] **Step 4: Secret and artifact leakage check**

Run: `rg -n "SUPABASE_SERVICE_ROLE_KEY|TUSHARE_TOKEN|sb_secret_|Fixture/sample" reports src tests docs`
Expected: no secret values. `Fixture/sample` may appear only in fixture-warning code/tests, not in production report artifacts.

- [ ] **Step 5: Confirm no production full-market Supabase call remains**

Run: `rg -n "save_market_bars\\(production_bundle\\.daily_bars\\)|save_daily_basic_indicators\\(production_bundle\\.daily_basic\\)" src tests`
Expected: no matches.

- [ ] **Step 6: Handle verification fixes if needed**

If Step 2-5 required fixes, return to the task that owns the failing file and create a normal task-scoped commit using that task's commit command. Expected: no verification-only commit is created when no fixes were needed.

- [ ] **Step 7: Handoff back to Tushare Ingestion V1 Task 9**

Do not run real production `run-daily` yet. Report to the user:

```text
存储治理续跑已完成，Tushare V1 可以恢复到 Task 9。
下一次真实写入前需要你确认：是否允许执行一次受控生产 run-daily。
```

Expected: user confirms before any real Supabase write.

---

## Self-Review Checklist

- Spec coverage: local warehouse, selective Supabase writes, capacity guard, local archive, and continuation back to Tushare V1 Task 9 are all mapped to tasks.
- Storage boundary: full-market data is written only to local warehouse; Supabase market tables are guarded by code count, row count, and capacity threshold.
- Existing code continuity: Tushare provider, feature builder, recommendation logic, focus logic, evidence logic, and report generator remain in place and are integrated rather than replaced.
- Test coverage: config, local warehouse, capacity guard, repository scope, pipeline persistence, local archive, schema, and full suite are covered.
- Real-write safety: final task explicitly stops before production `run-daily` and asks the user for confirmation.
