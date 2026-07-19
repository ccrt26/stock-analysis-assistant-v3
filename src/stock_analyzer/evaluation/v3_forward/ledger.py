from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import tempfile
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd


FROZEN_OUTPUT_ROOT = Path(
    "/Volumes/ZHUTONG/股票分析助手-V3回测/2026-07-19-v3-forward-observation"
)


class ImmutableEvidenceConflict(RuntimeError):
    """Raised when an immutable identity is reused with different evidence."""


@dataclass(frozen=True)
class BundleWriteResult:
    path: Path
    bundle_content_hash: str
    idempotent: bool


@dataclass(frozen=True)
class FormationBundle:
    path: Path
    payload: dict[str, Any]
    candidates: pd.DataFrame
    manifest: dict[str, Any]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json_safe(value: Any) -> Any:
    if value is None or value is pd.NA:
        return None
    if isinstance(value, (date, datetime, pd.Timestamp)):
        return value.isoformat()
    if isinstance(value, np.generic):
        return _json_safe(value.item())
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


def _canonical_json(value: Any) -> str:
    return json.dumps(
        _json_safe(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _frame_payload(frame: pd.DataFrame) -> dict[str, Any]:
    return {
        "columns": list(frame.columns),
        "rows": [_json_safe(row) for row in frame.to_dict(orient="records")],
    }


def _fsync_file(path: Path) -> None:
    with path.open("rb") as handle:
        os.fsync(handle.fileno())


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


class ForwardLedger:
    def __init__(self, root: Path, *, enforce_real_root: bool = True) -> None:
        self.root = Path(root)
        if enforce_real_root and self.root.resolve(strict=False) != FROZEN_OUTPUT_ROOT.resolve(
            strict=False
        ):
            raise ValueError("输出路径必须是冻结的U盘专用目录")
        for child in (
            "formations",
            "entries",
            "snapshots",
            "tables",
            "manifests",
            "reports",
            "logs",
        ):
            (self.root / child).mkdir(parents=True, exist_ok=True)

    def write_formation_bundle(
        self,
        payload: Mapping[str, Any],
        candidates: pd.DataFrame,
        report: str,
    ) -> BundleWriteResult:
        formation_date = date.fromisoformat(str(payload["formation_date"]))
        required = {"formation_date", "ts_code"}
        missing = sorted(required - set(candidates.columns))
        if missing:
            raise ValueError(f"formation candidates lack fields: {', '.join(missing)}")
        if candidates.duplicated(["formation_date", "ts_code"]).any():
            raise ValueError("formation contains duplicate stock-date rows")
        final = self.root / "formations" / f"formation_date={formation_date.isoformat()}"
        return self._write_bundle(
            final,
            json_name="formation.json",
            payload=payload,
            table_name="candidates.parquet",
            frame=candidates,
            report=report,
        )

    def write_entry_bundle(
        self,
        formation_date: date,
        entry_date: date,
        entries: pd.DataFrame,
        report: str,
    ) -> BundleWriteResult:
        payload = {
            "schema_version": "v3-forward-entry-01",
            "formation_date": formation_date.isoformat(),
            "entry_date": entry_date.isoformat(),
            "row_count": len(entries),
        }
        final = (
            self.root
            / "entries"
            / f"entry_date={entry_date.isoformat()}"
            / f"formation_date={formation_date.isoformat()}"
        )
        return self._write_bundle(
            final,
            json_name="entry.json",
            payload=payload,
            table_name="entries.parquet",
            frame=entries,
            report=report,
        )

    def write_snapshot_bundle(
        self,
        formation_date: date,
        as_of_date: date,
        horizon: int,
        snapshots: pd.DataFrame,
        report: str,
    ) -> BundleWriteResult:
        payload = {
            "schema_version": "v3-forward-snapshot-01",
            "formation_date": formation_date.isoformat(),
            "as_of_date": as_of_date.isoformat(),
            "horizon": int(horizon),
            "row_count": len(snapshots),
        }
        final = (
            self.root
            / "snapshots"
            / f"as_of_date={as_of_date.isoformat()}"
            / f"formation_date={formation_date.isoformat()}"
            / f"horizon={int(horizon)}"
        )
        return self._write_bundle(
            final,
            json_name="snapshot.json",
            payload=payload,
            table_name="snapshots.parquet",
            frame=snapshots,
            report=report,
        )

    def load_formations(self) -> tuple[FormationBundle, ...]:
        bundles: list[FormationBundle] = []
        for path in sorted((self.root / "formations").glob("formation_date=*")):
            manifest = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
            self._verify_manifest(path, manifest)
            payload = json.loads((path / "formation.json").read_text(encoding="utf-8"))
            candidates = pd.read_parquet(path / "candidates.parquet")
            bundles.append(FormationBundle(path, payload, candidates, manifest))
        return tuple(bundles)

    def _write_bundle(
        self,
        final: Path,
        *,
        json_name: str,
        payload: Mapping[str, Any],
        table_name: str,
        frame: pd.DataFrame,
        report: str,
    ) -> BundleWriteResult:
        canonical = {
            "payload": _json_safe(payload),
            "frame": _frame_payload(frame),
            "report": str(report),
        }
        bundle_hash = hashlib.sha256(_canonical_json(canonical).encode("utf-8")).hexdigest()
        if final.exists():
            return self._existing_result(final, bundle_hash)
        final.parent.mkdir(parents=True, exist_ok=True)
        stage = Path(tempfile.mkdtemp(prefix=".tmp-v3-forward-", dir=final.parent))
        try:
            json_path = stage / json_name
            json_path.write_text(
                json.dumps(_json_safe(payload), ensure_ascii=False, indent=2, sort_keys=True),
                encoding="utf-8",
            )
            table_path = stage / table_name
            frame.to_parquet(table_path, index=False)
            report_path = stage / "report.md"
            report_path.write_text(str(report), encoding="utf-8")
            for path in (json_path, table_path, report_path):
                _fsync_file(path)
            manifest = {
                "schema_version": "v3-forward-bundle-manifest-01",
                "bundle_content_hash": bundle_hash,
                "files": {
                    path.name: {"sha256": sha256_file(path), "bytes": path.stat().st_size}
                    for path in (json_path, table_path, report_path)
                },
            }
            manifest_path = stage / "manifest.json"
            manifest_path.write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True),
                encoding="utf-8",
            )
            _fsync_file(manifest_path)
            _fsync_directory(stage)
            try:
                os.rename(stage, final)
            except FileExistsError:
                return self._existing_result(final, bundle_hash)
            _fsync_directory(final.parent)
            return BundleWriteResult(final, bundle_hash, False)
        finally:
            if stage.exists():
                shutil.rmtree(stage)

    def _existing_result(self, final: Path, expected_hash: str) -> BundleWriteResult:
        manifest_path = final / "manifest.json"
        if not manifest_path.exists():
            raise ImmutableEvidenceConflict(f"incomplete immutable bundle: {final}")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self._verify_manifest(final, manifest)
        actual = str(manifest.get("bundle_content_hash", ""))
        if actual != expected_hash:
            raise ImmutableEvidenceConflict(
                f"immutable evidence conflict for {final}: {actual} != {expected_hash}"
            )
        return BundleWriteResult(final, actual, True)

    @staticmethod
    def _verify_manifest(path: Path, manifest: Mapping[str, Any]) -> None:
        files = manifest.get("files")
        if not isinstance(files, Mapping):
            raise ImmutableEvidenceConflict(f"invalid immutable manifest: {path}")
        for name, metadata in files.items():
            file_path = path / str(name)
            if not file_path.is_file() or sha256_file(file_path) != str(metadata["sha256"]):
                raise ImmutableEvidenceConflict(f"immutable file hash mismatch: {file_path}")


__all__ = [
    "FROZEN_OUTPUT_ROOT",
    "BundleWriteResult",
    "FormationBundle",
    "ForwardLedger",
    "ImmutableEvidenceConflict",
    "sha256_file",
]
