"""Minimal, auditable historical validation for the temporary V3 framework.

This module is an experiment runner, not a production recommendation service.
Runtime artifacts are restricted to the dedicated USB experiment directory.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import yaml


EXPECTED_SUPPORTED_ROUTES = ("hotspot", "earnings", "price")
EXPECTED_NOT_TESTABLE_ROUTES = (
    "company_event",
    "industry_cycle",
    "distress_repair",
)
DEFAULT_ALLOWED_VOLUME_ROOT = Path("/Volumes/ZHUTONG")


@dataclass(frozen=True)
class Block:
    id: str
    start: date
    end: date


@dataclass(frozen=True)
class ValidationConfig:
    experiment_id: str
    warehouse_root: Path
    output_root: Path
    blocks: tuple[Block, ...]
    horizons: tuple[int, ...]
    target_return: float
    candidate_cap: int
    focus_cap: int
    route_recall_cap: int
    supported_routes: tuple[str, ...]
    not_testable_routes: tuple[str, ...]
    runtime_soft_hours: float
    runtime_stop_hours: float
    usb_soft_bytes: int


def load_config(path: str | Path) -> ValidationConfig:
    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("validation config must be a mapping")
    blocks = tuple(
        Block(
            id=str(item["id"]),
            start=date.fromisoformat(str(item["start"])),
            end=date.fromisoformat(str(item["end"])),
        )
        for item in payload["blocks"]
    )
    config = ValidationConfig(
        experiment_id=str(payload["experiment_id"]),
        warehouse_root=Path(payload["warehouse_root"]),
        output_root=Path(payload["output_root"]),
        blocks=blocks,
        horizons=tuple(int(value) for value in payload["horizons"]),
        target_return=float(payload["target_return"]),
        candidate_cap=int(payload["candidate_cap"]),
        focus_cap=int(payload["focus_cap"]),
        route_recall_cap=int(payload["route_recall_cap"]),
        supported_routes=tuple(str(value) for value in payload["supported_routes"]),
        not_testable_routes=tuple(
            str(value) for value in payload["not_testable_routes"]
        ),
        runtime_soft_hours=float(payload["runtime_soft_hours"]),
        runtime_stop_hours=float(payload["runtime_stop_hours"]),
        usb_soft_bytes=int(payload["usb_soft_bytes"]),
    )
    _validate_config(config)
    return config


def _validate_config(config: ValidationConfig) -> None:
    if config.supported_routes != EXPECTED_SUPPORTED_ROUTES:
        raise ValueError("supported routes differ from the frozen protocol")
    if config.not_testable_routes != EXPECTED_NOT_TESTABLE_ROUTES:
        raise ValueError("not-testable routes differ from the frozen protocol")
    if tuple(block.id for block in config.blocks) != ("A", "B", "C"):
        raise ValueError("blocks must be A, B and C")
    if config.horizons != (10, 20, 30):
        raise ValueError("horizons differ from the frozen protocol")
    if config.target_return != 0.20:
        raise ValueError("target return differs from the frozen protocol")
    if config.candidate_cap != 10 or config.focus_cap != 5:
        raise ValueError("candidate capacities differ from the frozen protocol")


def prepare_output_root(
    config: ValidationConfig,
    *,
    output_override: str | Path | None = None,
    allowed_volume_root: str | Path = DEFAULT_ALLOWED_VOLUME_ROOT,
) -> Path:
    output = Path(output_override) if output_override is not None else config.output_root
    volume_root = Path(allowed_volume_root)
    expected_parent = volume_root / "股票分析助手-V3回测"
    try:
        relative = output.resolve(strict=False).relative_to(expected_parent.resolve(strict=False))
    except ValueError as exc:
        raise ValueError("输出路径必须位于U盘专用目录") from exc
    if relative.parts != (config.experiment_id,):
        raise ValueError("输出路径必须是冻结的U盘专用实验目录")
    for child in ("manifests", "tables", "reports"):
        (output / child).mkdir(parents=True, exist_ok=True)
    return output


def _as_jsonable_config(config: ValidationConfig) -> dict[str, Any]:
    return {
        "experiment_id": config.experiment_id,
        "warehouse_root": str(config.warehouse_root),
        "output_root": str(config.output_root),
        "blocks": [
            {"id": item.id, "start": item.start.isoformat(), "end": item.end.isoformat()}
            for item in config.blocks
        ],
        "horizons": list(config.horizons),
        "target_return": config.target_return,
    }
