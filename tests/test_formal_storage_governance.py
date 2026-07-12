from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_original_storage_design_points_to_restoration_and_duckdb_catalog():
    text = _text("docs/superpowers/specs/2026-07-08-storage-governance-design.md")
    assert "2026-07-12-v3-formal-warehouse-restoration-design.md" in text
    assert "warehouse.duckdb" in text
    assert "formal_versions" in text
    assert "wide formal payload" in text


def test_formal_readiness_design_forbids_wide_json_and_requires_actual_dates():
    text = _text(
        "docs/superpowers/specs/2026-07-10-v3-formal-report-data-readiness-design.md"
    )
    assert "Wide formal records MUST NOT be stored as JSON" in text
    assert "actual covered trade date" in text
    assert "FormalWarehouse" in text


def test_historical_conflicting_plans_have_visible_supersession_banners():
    for path in (
        "docs/superpowers/plans/2026-07-10-v3-formal-report-data-readiness.md",
        "docs/superpowers/plans/2026-07-10-v3-production-capability-correction.md",
    ):
        text = _text(path)
        assert "Storage supersession (2026-07-12)" in text
        assert "2026-07-12-v3-formal-warehouse-restoration-design.md" in text


def test_capability_matrix_reports_production_write_verified_with_deletion_evidence():
    text = _text("docs/operations/production-capability-matrix.md")
    assert "STORE-004" in text
    assert "PRODUCTION_WRITE_VERIFIED" in _store_004_row(text)
    assert "formal_evidence` no longer exists" in _store_004_row(text)
    assert "620,398,257 bytes" in _store_004_row(text)


def test_runbook_contains_exact_non_destructive_migration_commands():
    text = _text("docs/operations/runbook.md")
    for command in (
        "stock-analyzer formal-warehouse-inventory",
        "stock-analyzer formal-warehouse-migrate",
        "stock-analyzer formal-warehouse-audit",
        "stock-analyzer formal-warehouse-deletion-manifest",
    ):
        assert command in text
    assert "does not delete" in text


def test_readme_reports_verified_json_deletion():
    text = _text("README.md")
    assert "STORE-004" in text
    assert "PRODUCTION_WRITE_VERIFIED" in text
    assert "formal_evidence` 已不存在" in text


def _store_004_row(text: str) -> str:
    return next(line for line in text.splitlines() if "STORE-004" in line)
