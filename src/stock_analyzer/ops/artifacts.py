from __future__ import annotations

import os
import shutil
from pathlib import Path


class DeployArtifactError(RuntimeError):
    pass


_FORBIDDEN_DIR_NAMES = {
    ".git",
    ".venv",
    "local_warehouse",
    "local_archive",
    "logs",
    ".superpowers",
}
_FORBIDDEN_FILE_PREFIXES = (".env",)
_FORBIDDEN_RELATIVE_PREFIXES = (
    Path("data/cache"),
    Path("data/raw"),
)


def prepare_pages_artifact(project_root: Path, output_dir: Path) -> Path:
    root = Path(project_root).expanduser().resolve()
    target = _resolve_output_dir(root, output_dir)
    reports_dir = root / "reports"
    middleware_path = root / "functions" / "_middleware.ts"

    _validate_required_inputs(reports_dir, middleware_path)
    _validate_output_dir(root, reports_dir, middleware_path.parent, target)

    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True, exist_ok=True)

    _copy_report_tree(reports_dir, target)
    middleware_target = target / "functions" / "_middleware.ts"
    middleware_target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(middleware_path, middleware_target)
    _assert_forbidden_paths_absent(target)
    return target


def _resolve_output_dir(project_root: Path, output_dir: Path) -> Path:
    target = Path(output_dir).expanduser()
    if not target.is_absolute():
        target = project_root / target
    return target.resolve()


def _validate_required_inputs(reports_dir: Path, middleware_path: Path) -> None:
    if not reports_dir.is_dir():
        raise DeployArtifactError("reports directory is missing.")
    if not (reports_dir / "index.html").is_file():
        raise DeployArtifactError("reports/index.html is missing.")
    if not middleware_path.is_file():
        raise DeployArtifactError("functions/_middleware.ts is missing.")


def _validate_output_dir(
    project_root: Path,
    reports_dir: Path,
    functions_dir: Path,
    target: Path,
) -> None:
    if target == project_root:
        raise DeployArtifactError("Output directory cannot be the project root.")
    if target == reports_dir or _is_relative_to(target, reports_dir):
        raise DeployArtifactError("Output directory cannot be inside reports.")
    if target == functions_dir or _is_relative_to(target, functions_dir):
        raise DeployArtifactError("Output directory cannot be inside functions.")


def _copy_report_tree(reports_dir: Path, target: Path) -> None:
    for current_dir, dirnames, filenames in os.walk(reports_dir):
        current_path = Path(current_dir)
        relative_dir = current_path.relative_to(reports_dir)
        dirnames[:] = [
            dirname
            for dirname in dirnames
            if not _is_forbidden_relative_path(relative_dir / dirname)
        ]
        for filename in filenames:
            relative_file = relative_dir / filename
            if _is_forbidden_relative_path(relative_file):
                continue
            source = current_path / filename
            if source.is_symlink():
                continue
            destination = target / relative_file
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)


def _assert_forbidden_paths_absent(target: Path) -> None:
    for path in target.rglob("*"):
        if _is_forbidden_relative_path(path.relative_to(target)):
            raise DeployArtifactError("Forbidden path detected in deploy artifact.")


def _is_forbidden_relative_path(relative_path: Path) -> bool:
    parts = relative_path.parts
    if any(part in _FORBIDDEN_DIR_NAMES for part in parts):
        return True
    if any(part.startswith(_FORBIDDEN_FILE_PREFIXES) for part in parts):
        return True
    return any(
        relative_path == prefix or _is_relative_to(relative_path, prefix)
        for prefix in _FORBIDDEN_RELATIVE_PREFIXES
    )


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


__all__ = ["DeployArtifactError", "prepare_pages_artifact"]
