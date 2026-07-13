from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path

from stock_analyzer.data.research_contracts import ResearchDatasetId, research_contract
from stock_analyzer.storage.research_query import ResearchQuery


def export_research_snapshot(
    query: ResearchQuery,
    *,
    datasets: tuple[ResearchDatasetId, ...],
    as_of: datetime,
    output_dir: Path,
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "as_of": as_of.isoformat(),
        "datasets": {},
        "quality": "passed_current_and_revisions_as_of",
    }
    for dataset in datasets:
        frame = query.dataset_as_of(dataset, as_of)
        path = output_dir / f"{dataset.value}.parquet"
        frame.to_parquet(path, index=False)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        contract = research_contract(dataset)
        manifest["datasets"][dataset.value] = {
            "path": path.name,
            "rows": len(frame),
            "business_key": list(contract.business_key),
            "sha256": digest,
        }
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2),
        encoding="utf-8",
    )
    return manifest_path


__all__ = ["export_research_snapshot"]
