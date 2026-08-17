from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping
from zoneinfo import ZoneInfo

from pydantic import BaseModel

from stock_analyzer.selection_lab.schemas import CapabilityResult
from stock_analyzer.selection_lab.temporal_split import REGISTERED_FORMATION_DATES


class DatasetCapabilities(BaseModel):
    tracks: dict[str, CapabilityResult]
    main_conclusion: str


@dataclass(frozen=True)
class ArtifactPaths:
    features: Path
    labels: Path
    model: Path


class SelectionDatasetBuilder:
    def __init__(
        self,
        *,
        warehouse_root: Path,
        archive_root: Path,
        models_root: Path,
        candidate_chain_root: Path,
        security_master_earliest_available_at: datetime | None,
    ) -> None:
        self.warehouse_root = Path(warehouse_root)
        self.archive_root = Path(archive_root)
        self.models_root = Path(models_root)
        self.candidate_chain_root = Path(candidate_chain_root)
        self.security_master_earliest_available_at = (
            security_master_earliest_available_at
        )

    def preflight(self) -> DatasetCapabilities:
        candidate_available = self._has_frozen_candidate_chain()
        candidate = (
            CapabilityResult(status="available")
            if candidate_available
            else CapabilityResult(
                status="unavailable",
                reason_code="no_frozen_candidate_chain",
                details=[
                    "No machine-readable candidate chain proves a pre-future freeze."
                ],
            )
        )
        all_formation_dates = [
            value
            for values in REGISTERED_FORMATION_DATES.values()
            for value in values
        ]
        earliest_cutoff = datetime.fromisoformat(
            min(all_formation_dates) + "T23:59:59+08:00"
        )
        identity_available = (
            self.security_master_earliest_available_at is not None
            and self.security_master_earliest_available_at <= earliest_cutoff
        )
        universe = (
            CapabilityResult(status="available")
            if identity_available
            else CapabilityResult(
                status="blocked",
                reason_code="point_in_time_security_master_unavailable",
                details=[
                    "Historical identity and ST status are unavailable at the registered cutoffs."
                ],
            )
        )
        surface = CapabilityResult(
            status="available",
            details=["Identity remains unknown_identity_history."],
        )
        return DatasetCapabilities(
            tracks={
                "frozen_candidate_chain": candidate,
                "deterministic_research_surface": surface,
                "full_universe": universe,
            },
            main_conclusion=("not_evaluated" if candidate_available else "实验阻塞"),
        )

    def artifact_paths(self, split: str) -> ArtifactPaths:
        if split not in REGISTERED_FORMATION_DATES:
            raise ValueError(f"unknown selection-lab split: {split}")
        return ArtifactPaths(
            features=self.warehouse_root / "selection_lab" / f"{split}-features.parquet",
            labels=self.archive_root / "selection_lab" / f"{split}-labels.parquet",
            model=self.models_root / "selection_lab" / f"{split}-ranker.json",
        )

    def _has_frozen_candidate_chain(self) -> bool:
        if not self.candidate_chain_root.is_dir():
            return False
        for path in sorted(self.candidate_chain_root.glob("*.json")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            required = {
                "formation_date",
                "formation_as_of",
                "candidate_chain",
                "frozen_before_future",
            }
            if required.issubset(payload) and payload["frozen_before_future"] is True:
                return True
        return False


def validate_final_test_reveal(
    freeze_manifest: Mapping[str, Any],
    *,
    expected_hashes: Mapping[str, str],
) -> None:
    required = (
        "features_frozen",
        "split_hash",
        "feature_dictionary_hash",
        "model_variant",
        "C",
        "threshold",
    )
    missing = [key for key in required if freeze_manifest.get(key) is None]
    if missing:
        raise ValueError("final-test reveal is missing: " + ", ".join(missing))
    if freeze_manifest["features_frozen"] is not True:
        raise ValueError("features_frozen must be true before final-test reveal")
    for key, expected in expected_hashes.items():
        if freeze_manifest.get(key) != expected:
            raise ValueError(f"final-test reveal hash mismatch: {key}")
