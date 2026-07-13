from __future__ import annotations

import hashlib
import os
import shutil
from pathlib import Path

import pandas as pd


def write_staged_parquet(path: Path, frame: pd.DataFrame) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(path, index=False)
    return sha256_file(path)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_promote(staged_path: Path, final_path: Path) -> Path | None:
    final_path.parent.mkdir(parents=True, exist_ok=True)
    backup_path: Path | None = None
    if final_path.exists():
        backup_path = final_path.with_suffix(".parquet.previous")
        if backup_path.exists():
            backup_path.unlink()
        os.replace(final_path, backup_path)
    try:
        os.replace(staged_path, final_path)
    except Exception:
        if backup_path is not None and backup_path.exists():
            os.replace(backup_path, final_path)
        raise
    return backup_path


def restore_previous(final_path: Path, backup_path: Path | None) -> None:
    if final_path.exists():
        final_path.unlink()
    if backup_path is not None and backup_path.exists():
        os.replace(backup_path, final_path)


def discard_backup(backup_path: Path | None) -> None:
    if backup_path is not None and backup_path.exists():
        backup_path.unlink()


def remove_tree_if_empty(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path, ignore_errors=True)


__all__ = [
    "atomic_promote",
    "discard_backup",
    "remove_tree_if_empty",
    "restore_previous",
    "sha256_file",
    "write_staged_parquet",
]
