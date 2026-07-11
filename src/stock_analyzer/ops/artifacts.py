from __future__ import annotations

import hashlib
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
    ".staging",
    ".activation",
    ".formal-runs",
}
_FORBIDDEN_FILE_PREFIXES = (".env",)
_FORBIDDEN_RELATIVE_PREFIXES = (
    Path("data/cache"),
    Path("data/raw"),
)
_DEFAULT_SOURCE_ROOT = Path(__file__).resolve().parents[3]


def prepare_pages_artifact(
    project_root: Path,
    output_dir: Path,
    *,
    source_root: Path | None = None,
    receipt=None,
) -> Path:
    _validate_formal_receipt(receipt)
    root = Path(project_root).expanduser().resolve()
    source = Path(source_root or _DEFAULT_SOURCE_ROOT).expanduser().resolve()
    target = _resolve_output_dir(root, output_dir)
    reports_dir = root / "reports"
    middleware_path = _middleware_path(root, source)

    _validate_required_inputs(reports_dir, middleware_path)
    _validate_receipt_artifact_hashes(reports_dir, receipt)
    _validate_output_dir(root, reports_dir, middleware_path.parent, target)

    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True, exist_ok=True)

    _copy_receipt_artifacts(reports_dir, target, receipt)
    middleware_target = target / "functions" / "_middleware.ts"
    middleware_target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(middleware_path, middleware_target)
    _assert_forbidden_paths_absent(target)
    return target


def _validate_formal_receipt(receipt) -> None:
    from stock_analyzer.data.readiness import FormalRunState

    if (
        receipt is None
        or getattr(receipt, "state", None) != FormalRunState.REPORT_GENERATED
        or not getattr(receipt, "group_version_ids", None)
        or getattr(receipt, "input_set_id", None) is None
        or getattr(receipt, "candidate_set_id", None) is None
        or not getattr(receipt, "evidence_hashes", None)
        or not getattr(receipt, "artifact_hashes", None)
        or getattr(receipt, "local_activation_id", None) is None
        or getattr(receipt, "local_activation_id", None)
        != getattr(receipt, "ledger_activation_id", None)
    ):
        raise DeployArtifactError(
            "Deploy preparation requires an activated REPORT_GENERATED receipt."
        )


def _validate_receipt_artifact_hashes(reports_dir: Path, receipt) -> None:
    for relative_name, expected_hash in receipt.artifact_hashes.items():
        relative_path = Path(relative_name)
        if relative_path.is_absolute() or ".." in relative_path.parts:
            raise DeployArtifactError("Formal receipt contains an unsafe artifact path.")
        artifact_path = reports_dir / relative_path
        if (
            not artifact_path.is_file()
            or hashlib.sha256(artifact_path.read_bytes()).hexdigest() != expected_hash
        ):
            raise DeployArtifactError(
                f"Formal report artifact hash mismatch: {relative_name}."
            )


def _middleware_path(project_root: Path, source_root: Path) -> Path:
    project_middleware = project_root / "functions" / "_middleware.ts"
    if project_middleware.is_file():
        return project_middleware
    return source_root / "functions" / "_middleware.ts"


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
    if not _is_allowed_output_dir(project_root, target):
        raise DeployArtifactError(
            "Output directory must be under project dist/ or an approved temp "
            "stock-analysis artifact directory."
        )


def _copy_receipt_artifacts(reports_dir: Path, target: Path, receipt) -> None:
    for relative_name in sorted(receipt.artifact_hashes):
        relative_file = Path(relative_name)
        if _is_forbidden_relative_path(relative_file):
            raise DeployArtifactError(
                f"Formal receipt contains a forbidden artifact path: {relative_name}."
            )
        source = reports_dir / relative_file
        if source.is_symlink():
            raise DeployArtifactError(
                f"Formal receipt artifact cannot be a symlink: {relative_name}."
            )
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


def _is_allowed_output_dir(project_root: Path, target: Path) -> bool:
    dist_dir = (project_root / "dist").resolve()
    if target == dist_dir or _is_relative_to(target, dist_dir):
        return True
    return _is_approved_temp_artifact_dir(target)


def _is_approved_temp_artifact_dir(target: Path) -> bool:
    if not target.name.startswith("stock-analysis"):
        return False
    return any(
        target != temp_root and _is_relative_to(target, temp_root)
        for temp_root in _temp_roots()
    )


def _temp_roots() -> tuple[Path, ...]:
    candidates = [
        os.environ.get("TMPDIR"),
        "/tmp",
        "/private/tmp",
    ]
    roots: list[Path] = []
    for candidate in candidates:
        if not candidate:
            continue
        root = Path(candidate).expanduser().resolve()
        if root not in roots:
            roots.append(root)
    return tuple(roots)


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


__all__ = ["DeployArtifactError", "prepare_pages_artifact"]
