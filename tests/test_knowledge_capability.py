from datetime import date, datetime, timezone
import hashlib
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from stock_analyzer.analysis.market_context_features import (
    MARKET_CONTEXT_FORMULA_VERSION,
)
from stock_analyzer.knowledge import capability as capability_module
from stock_analyzer.knowledge.capability import (
    CapabilityItem,
    CapabilitySnapshot,
    assess_entry_capability,
    inspect_warehouse_capabilities,
)
from stock_analyzer.knowledge.governance_audit import audit_knowledge_governance
from stock_analyzer.knowledge.governance_models import (
    AnalysisModule,
    DataRequirement,
    KnowledgeEffect,
    KnowledgeEntry,
    KnowledgeRegistry,
    KnowledgeTopic,
    LegacyMigrationRegistry,
    LocalValidation,
    OpportunityType,
    SourceGrade,
    SourceKind,
    SourceRecord,
)
from stock_analyzer.storage.research_schema import connect_research_warehouse
from stock_analyzer.storage.research_warehouse import ResearchWarehouse


ANALYSIS_DATE = date(2026, 7, 10)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def initialize_root(tmp_path: Path, name: str = "warehouse") -> Path:
    root = tmp_path / name
    root.mkdir()
    with connect_research_warehouse(root / "research.duckdb"):
        pass
    return root


def write_table(root: Path, relative_path: str, rows: list[dict]) -> tuple[Path, str]:
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(rows), path)
    return path, sha256_file(path)


def insert_fact(
    root: Path,
    *,
    dataset_id: str = "equity_daily",
    include_available_at: bool = True,
    file_sha256: str | None = None,
) -> Path:
    row = {
        "trade_date": ANALYSIS_DATE,
        "ts_code": "000001.SZ",
        "close": 10.2,
    }
    if include_available_at:
        row["available_at"] = datetime(2026, 7, 10, 7, 1, tzinfo=timezone.utc)
    relative_path = f"facts/{dataset_id}/date=2026-07-10/data.parquet"
    path, actual_sha = write_table(root, relative_path, [row])
    with connect_research_warehouse(root / "research.duckdb") as connection:
        connection.execute(
            """
            insert into research_fact_partitions values
            (?, '2026-07-10', ?, 1, 'content', ?, null, null,
             '["test"]', now(), 'test-run', 'passed')
            """,
            [dataset_id, relative_path, file_sha256 or actual_sha],
        )
    return path


def insert_derived(
    root: Path,
    *,
    feature_set: str = "market_context",
    analysis_date: date = ANALYSIS_DATE,
    formula_version: str = MARKET_CONTEXT_FORMULA_VERSION,
    quality_status: str = "complete",
    limitations: str = "[]",
    file_sha256: str | None = None,
) -> Path:
    relative_path = (
        f"derived/{feature_set}/analysis_date={analysis_date.isoformat()}/"
        f"formula_version={formula_version}/data.parquet"
    )
    path, actual_sha = write_table(
        root,
        relative_path,
        [{"analysis_date": analysis_date, "coverage_status": "complete"}],
    )
    with connect_research_warehouse(root / "research.duckdb") as connection:
        connection.execute(
            """
            insert into research_derived_partitions values
            (?, ?, ?, ?, 1, 'content', ?, 'input-hash', '{}', ?, ?,
             now(), 'derived-run')
            """,
            [
                feature_set,
                analysis_date,
                formula_version,
                relative_path,
                file_sha256 or actual_sha,
                quality_status,
                limitations,
            ],
        )
    return path


def fail_row_loading(*args, **kwargs):
    raise AssertionError("capability inspection must not load parquet rows")


def test_inspector_reads_manifests_and_parquet_schema_without_loading_rows(
    tmp_path, monkeypatch
):
    root = initialize_root(tmp_path)
    insert_fact(root)
    insert_derived(root)
    monkeypatch.setattr(pd, "read_parquet", fail_row_loading)
    monkeypatch.setattr(ResearchWarehouse, "read_current", fail_row_loading)

    snapshot = inspect_warehouse_capabilities(root, ANALYSIS_DATE)

    fact = snapshot.lookup("fact", "equity_daily")
    derived = snapshot.lookup("derived", "market_context")
    assert fact is not None
    assert fact.fields == ("available_at", "close", "trade_date", "ts_code")
    assert fact.row_count == 1
    assert fact.structurally_ready is True
    assert derived is not None
    assert derived.fields == ("analysis_date", "coverage_status")
    assert derived.structurally_ready is True


def test_inspector_opens_duckdb_read_only(tmp_path, monkeypatch):
    root = initialize_root(tmp_path)
    insert_fact(root)
    captured: list[bool] = []
    original = connect_research_warehouse

    def capture(path, *, read_only=False):
        captured.append(read_only)
        return original(path, read_only=read_only)

    monkeypatch.setattr(capability_module, "connect_research_warehouse", capture)
    inspect_warehouse_capabilities(root, ANALYSIS_DATE)

    assert captured
    assert all(value is True for value in captured)


def test_fact_capability_requires_available_at_for_as_of(tmp_path):
    root = initialize_root(tmp_path)
    insert_fact(root, include_available_at=False)

    item = inspect_warehouse_capabilities(root, ANALYSIS_DATE).lookup(
        "fact", "equity_daily"
    )

    assert item is not None
    assert item.as_of_supported is False
    assert item.structurally_ready is False
    assert any("available_at" in reason for reason in item.limitations)


@pytest.mark.parametrize(
    ("date_offset", "formula_version", "quality_status", "expected_present"),
    [
        (date(2026, 7, 9), MARKET_CONTEXT_FORMULA_VERSION, "complete", False),
        (ANALYSIS_DATE, "market-context-v0", "complete", True),
        (ANALYSIS_DATE, MARKET_CONTEXT_FORMULA_VERSION, "limited", True),
    ],
    ids=["wrong-date", "wrong-formula", "limited-quality"],
)
def test_derived_capability_requires_exact_date_formula_and_ready_quality(
    tmp_path, date_offset, formula_version, quality_status, expected_present
):
    root = initialize_root(tmp_path)
    insert_derived(
        root,
        analysis_date=date_offset,
        formula_version=formula_version,
        quality_status=quality_status,
    )

    item = inspect_warehouse_capabilities(root, ANALYSIS_DATE).lookup(
        "derived", "market_context"
    )

    if not expected_present:
        assert item is None
    else:
        assert item is not None
        assert item.structurally_ready is False


@pytest.mark.parametrize("damage", ["missing", "hash"], ids=["missing", "hash"])
def test_missing_file_or_hash_mismatch_is_not_complete(tmp_path, damage):
    root = initialize_root(tmp_path)
    path = insert_fact(root)
    if damage == "missing":
        path.unlink()
        expected = "missing file"
    else:
        path.write_bytes(path.read_bytes() + b"changed")
        expected = "sha256 mismatch"

    item = inspect_warehouse_capabilities(root, ANALYSIS_DATE).lookup(
        "fact", "equity_daily"
    )

    assert item is not None
    assert item.structurally_ready is False
    assert any(expected in reason for reason in item.limitations)


def test_complete_with_declared_gaps_is_ready_but_preserves_limitations(tmp_path):
    root = initialize_root(tmp_path)
    insert_derived(
        root,
        quality_status="complete_with_declared_gaps",
        limitations='["minute history unavailable"]',
    )

    item = inspect_warehouse_capabilities(root, ANALYSIS_DATE).lookup(
        "derived", "market_context"
    )

    assert item is not None
    assert item.structurally_ready is True
    assert item.limitations == ("minute history unavailable",)


def test_inspection_does_not_change_duckdb_sha256(tmp_path):
    root = initialize_root(tmp_path)
    insert_fact(root)
    insert_derived(root)
    database = root / "research.duckdb"
    before = sha256_file(database)

    inspect_warehouse_capabilities(root, ANALYSIS_DATE)

    assert sha256_file(database) == before


def capability_item(
    *,
    kind: str = "fact",
    name: str = "equity_daily",
    fields: tuple[str, ...] = ("available_at", "close", "trade_date", "ts_code"),
    limitations: tuple[str, ...] = (),
    structurally_ready: bool = True,
) -> CapabilityItem:
    return CapabilityItem(
        kind=kind,
        name=name,
        fields=fields,
        partition_count=1,
        row_count=100,
        formula_versions=("test-v1",) if kind == "derived" else (),
        quality_statuses=(
            "complete_with_declared_gaps" if limitations else "complete",
        ),
        limitations=limitations,
        as_of_supported=True,
        structurally_ready=structurally_ready,
    )


def capability_snapshot(*items: CapabilityItem) -> CapabilitySnapshot:
    return CapabilitySnapshot(
        analysis_date=ANALYSIS_DATE,
        items=items,
        snapshot_hash="snapshot-hash",
    )


def governance_source(source_id: str = "official-source") -> SourceRecord:
    return SourceRecord(
        source_id=source_id,
        grade=SourceGrade.S,
        kind=SourceKind.OFFICIAL_RULE,
        title="Official rule",
        publisher="中国证券监督管理委员会",
        url="https://www.csrc.gov.cn/csrc/c100028/c7480577/content.shtml",
        publication_date=date(2024, 5, 15),
        effective_from=date(2024, 10, 8),
        last_verified_on=date(2026, 7, 15),
        jurisdiction="中国大陆",
        market_scope=("A股",),
        method_summary="Sets a binding market-analysis boundary.",
        limitations=("Does not replace company-specific evidence.",),
    )


def governance_entry(
    *,
    knowledge_id: str = "governed-entry",
    primary_source_id: str = "official-source",
    requirements: tuple[DataRequirement, ...] | None = None,
) -> KnowledgeEntry:
    if requirements is None:
        requirements = (
            DataRequirement(
                kind="fact",
                name="equity_daily",
                required_fields=("available_at", "close"),
            ),
        )
    return KnowledgeEntry(
        knowledge_id=knowledge_id,
        title="Governed entry",
        primary_source_id=primary_source_id,
        source_grade=SourceGrade.S,
        version_status="current",
        effective_from=date(2024, 10, 8),
        effect=KnowledgeEffect.HARD_BOUNDARY,
        modules=(AnalysisModule.RISK,),
        opportunity_types=(OpportunityType.GENERAL,),
        topics=(KnowledgeTopic.EXCHANGE_CONSTRAINTS,),
        claim_summary="Use time-valid official rules.",
        allowed_uses=("Apply the official boundary.",),
        forbidden_uses=("Invent unavailable evidence.",),
        prerequisites=("Check the rule version.",),
        counter_evidence=("A later official rule.",),
        data_requirements=requirements,
        local_validation=LocalValidation(
            status="not_required",
            reason="Official boundary, not an empirical threshold.",
        ),
    )


def test_entry_is_complete_only_when_every_required_field_is_available():
    entry = governance_entry(
        requirements=(
            DataRequirement(
                kind="fact",
                name="equity_daily",
                required_fields=("available_at", "close", "amount"),
            ),
        )
    )
    complete = capability_snapshot(
        capability_item(fields=("amount", "available_at", "close"))
    )
    missing = capability_snapshot(
        capability_item(fields=("available_at", "close"))
    )

    assert assess_entry_capability(entry, complete).status.value == "complete"
    blocked = assess_entry_capability(entry, missing)
    assert blocked.status.value == "blocked"
    assert blocked.missing_requirements == ("fact:equity_daily.amount",)


@pytest.mark.parametrize("name", ["product_price", "inventory", "industry_sales"])
def test_globally_missing_core_dataset_is_blocked_not_limited(name):
    entry = governance_entry(
        requirements=(
            DataRequirement(
                kind="derived",
                name=name,
                required_fields=("analysis_date", "value"),
            ),
        )
    )

    assessment = assess_entry_capability(entry, capability_snapshot())

    assert assessment.status.value == "blocked"
    assert assessment.status.value != "limited"
    assert assessment.missing_requirements == (f"derived:{name}",)


def test_declared_derived_gap_is_complete_only_when_required_fields_exist():
    entry = governance_entry(
        requirements=(
            DataRequirement(
                kind="derived",
                name="sector_hotspot",
                required_fields=("analysis_date", "relative_return_20d"),
            ),
        )
    )
    limitation = "minute history unavailable"
    usable = capability_snapshot(
        capability_item(
            kind="derived",
            name="sector_hotspot",
            fields=("analysis_date", "relative_return_20d"),
            limitations=(limitation,),
        )
    )
    missing_field = capability_snapshot(
        capability_item(
            kind="derived",
            name="sector_hotspot",
            fields=("analysis_date",),
            limitations=(limitation,),
        )
    )

    complete = assess_entry_capability(entry, usable)
    blocked = assess_entry_capability(entry, missing_field)
    assert complete.status.value == "complete"
    assert complete.limitations == (limitation,)
    assert blocked.status.value == "blocked"


def test_active_registry_audit_rejects_any_blocked_entry():
    registry = KnowledgeRegistry(
        schema_version="v3-knowledge-governance-v1",
        generated_on=date(2026, 7, 15),
        sources=(governance_source(),),
        entries=(governance_entry(),),
        registry_hash="registry-hash",
    )
    migration = LegacyMigrationRegistry(
        schema_version="v3-legacy-migration-v1",
        entries=(),
    )

    report = audit_knowledge_governance(
        registry,
        migration,
        legacy_ids=set(),
        capabilities=capability_snapshot(),
    )

    assert report.passed is False
    assert report.blocked_active_entry_count == 1


def test_audit_report_order_and_hash_are_deterministic():
    source_a = governance_source("official-a")
    source_b = governance_source("official-b")
    entry_a = governance_entry(
        knowledge_id="entry-a", primary_source_id="official-a"
    )
    entry_b = governance_entry(
        knowledge_id="entry-b", primary_source_id="official-b"
    )
    registry = KnowledgeRegistry(
        schema_version="v3-knowledge-governance-v1",
        generated_on=date(2026, 7, 15),
        sources=(source_a, source_b),
        entries=(entry_a, entry_b),
        registry_hash="registry-hash",
    )
    reversed_registry = registry.model_copy(
        update={
            "sources": tuple(reversed(registry.sources)),
            "entries": tuple(reversed(registry.entries)),
        }
    )
    snapshot = capability_snapshot(capability_item())
    reversed_snapshot = snapshot.model_copy(
        update={"items": tuple(reversed(snapshot.items))}
    )
    migration = LegacyMigrationRegistry(
        schema_version="v3-legacy-migration-v1",
        entries=(),
    )

    first = audit_knowledge_governance(
        registry, migration, legacy_ids=set(), capabilities=snapshot
    )
    second = audit_knowledge_governance(
        reversed_registry,
        migration,
        legacy_ids=set(),
        capabilities=reversed_snapshot,
    )

    assert first.model_dump_json() == second.model_dump_json()
    assert first.audit_hash == second.audit_hash
