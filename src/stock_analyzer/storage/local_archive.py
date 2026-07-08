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

        copied_files = []
        for source in self._report_files(reports_dir, trade_date):
            relative = source.relative_to(reports_dir)
            destination = target / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
            copied_files.append(destination)

        return self.write_manifest(trade_date, copied_files, base_dir=target)

    def write_manifest(
        self,
        trade_date: date,
        files: list[Path],
        *,
        base_dir: Path | None = None,
    ) -> Path:
        manifest_dir = self.root / "manifests"
        manifest_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = manifest_dir / f"{trade_date.isoformat()}.json"
        manifest_base = base_dir or self.root
        payload = {
            "trade_date": trade_date.isoformat(),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "file_count": len(files),
            "files": [
                {
                    "path": _manifest_relative_path(path, manifest_base),
                    "size": path.stat().st_size,
                    "sha256": _sha256(path),
                }
                for path in sorted(
                    files,
                    key=lambda item: _manifest_relative_path(item, manifest_base),
                )
            ],
        }
        manifest_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return manifest_path

    def _report_files(self, reports_dir: Path, trade_date: date) -> list[Path]:
        files_to_copy = []
        root_index = reports_dir / "index.html"
        if root_index.exists() and _is_archive_report_file(root_index, reports_dir):
            files_to_copy.append(root_index)

        daily_dir = reports_dir / "daily" / trade_date.isoformat()
        if daily_dir.exists():
            files_to_copy.extend(
                path
                for path in daily_dir.rglob("*")
                if path.is_file() and _is_archive_report_file(path, reports_dir)
            )

        data_dir = reports_dir / "data"
        if data_dir.exists():
            files_to_copy.extend(
                path
                for path in data_dir.rglob("*")
                if path.is_file() and _is_archive_report_file(path, reports_dir)
            )

        return files_to_copy


_SYSTEM_ARCHIVE_NAMES = {"thumbs.db", "desktop.ini"}


def _is_archive_report_file(path: Path, reports_dir: Path) -> bool:
    relative = path.relative_to(reports_dir)
    return not any(_is_hidden_or_system_part(part) for part in relative.parts)


def _is_hidden_or_system_part(part: str) -> bool:
    return (
        part.startswith(".")
        or part.lower() in _SYSTEM_ARCHIVE_NAMES
        or part.endswith("~")
    )


def _manifest_relative_path(path: Path, base_dir: Path) -> str:
    try:
        return path.relative_to(base_dir).as_posix()
    except ValueError:
        return path.name


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
