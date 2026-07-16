from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pyarrow.parquet as pq

from stock_analyzer.data.research_contracts import DatasetContract


@dataclass(frozen=True)
class PartitionContractAudit:
    missing_required_columns: tuple[str, ...]
    required_field_coverage: dict[str, float]
    coverage_failures: tuple[str, ...]

    @property
    def valid(self) -> bool:
        return not self.missing_required_columns and not self.coverage_failures


def audit_fact_partition_contract(
    path: Path,
    contract: DatasetContract,
) -> PartitionContractAudit:
    parquet = pq.ParquetFile(path)
    names = set(parquet.schema_arrow.names)
    missing = tuple(sorted(set(contract.required_columns) - names))
    coverage: dict[str, float] = {}
    present_coverage = [
        column for column in contract.coverage_columns if column in names
    ]
    if present_coverage:
        table = parquet.read(columns=present_coverage)
        for column in present_coverage:
            coverage[column] = (
                0.0
                if table.num_rows == 0
                else float((table.num_rows - table[column].null_count) / table.num_rows)
            )
    for column in contract.coverage_columns:
        coverage.setdefault(column, 0.0)
    failures = tuple(
        sorted(
            column
            for column, ratio in coverage.items()
            if ratio < contract.minimum_required_field_coverage
        )
    )
    return PartitionContractAudit(
        missing_required_columns=missing,
        required_field_coverage=coverage,
        coverage_failures=failures,
    )


__all__ = ["PartitionContractAudit", "audit_fact_partition_contract"]
