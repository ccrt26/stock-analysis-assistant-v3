from __future__ import annotations

import shutil
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from stock_analyzer.storage.repositories import SAME_DAY_CLEANUP_TABLES


APPROVED_SAME_DAY_CLEANUP_TABLES = SAME_DAY_CLEANUP_TABLES


@dataclass(frozen=True)
class CleanupSummary:
    trade_date: date
    repository_deleted_counts: dict[str, int]
    removed_paths: tuple[str, ...]

    @property
    def repository_tables(self) -> tuple[str, ...]:
        return tuple(self.repository_deleted_counts)


def cleanup_trade_date(
    project_root: Path,
    repository,
    trade_date: date,
) -> CleanupSummary:
    _ensure_trade_date(trade_date)
    root = Path(project_root)
    date_text = trade_date.isoformat()

    repository_deleted_counts = dict(repository.cleanup_trade_date(trade_date))
    removed_paths = _remove_same_day_local_outputs(root, date_text)

    return CleanupSummary(
        trade_date=trade_date,
        repository_deleted_counts=repository_deleted_counts,
        removed_paths=removed_paths,
    )


def _ensure_trade_date(value: date) -> None:
    if not isinstance(value, date) or isinstance(value, datetime):
        raise ValueError("trade_date must be a date instance")


def _remove_same_day_local_outputs(project_root: Path, date_text: str) -> tuple[str, ...]:
    targets = (
        (project_root / "reports" / "daily" / date_text, f"reports/daily/{date_text}"),
        (
            project_root / "local_archive" / "manifests" / f"{date_text}.json",
            f"local_archive/manifests/{date_text}.json",
        ),
        (
            project_root / "local_archive" / "reports" / date_text,
            f"local_archive/reports/{date_text}",
        ),
    )
    removed_paths: list[str] = []
    for path, relative_path in targets:
        if not path.exists() and not path.is_symlink():
            continue
        _remove_path(path)
        removed_paths.append(relative_path)
    return tuple(removed_paths)


def _remove_path(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink()
