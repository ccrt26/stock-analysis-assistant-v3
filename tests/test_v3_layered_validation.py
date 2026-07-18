from __future__ import annotations

from pathlib import Path

import pytest

from stock_analyzer.evaluation.v3_layered_validation import (
    EXPECTED_NOT_TESTABLE_ROUTES,
    EXPECTED_SUPPORTED_ROUTES,
    load_config,
    prepare_output_root,
)


CONFIG_PATH = Path(
    "docs/superpowers/specs/2026-07-18-v3-layered-validation-config.yaml"
)


def test_frozen_config_preserves_three_thirty_session_blocks_and_targets():
    config = load_config(CONFIG_PATH)

    assert [(block.id, block.start.isoformat(), block.end.isoformat()) for block in config.blocks] == [
        ("A", "2025-10-30", "2025-12-10"),
        ("B", "2026-01-26", "2026-03-16"),
        ("C", "2026-04-20", "2026-06-03"),
    ]
    assert config.horizons == (10, 20, 30)
    assert config.target_return == pytest.approx(0.20)
    assert config.candidate_cap == 10
    assert config.focus_cap == 5


def test_frozen_config_declares_only_supported_and_not_testable_routes():
    config = load_config(CONFIG_PATH)

    assert config.supported_routes == EXPECTED_SUPPORTED_ROUTES
    assert config.not_testable_routes == EXPECTED_NOT_TESTABLE_ROUTES


def test_prepare_output_root_rejects_non_usb_path(tmp_path: Path):
    config = load_config(CONFIG_PATH)

    with pytest.raises(ValueError, match="U盘专用目录"):
        prepare_output_root(config, output_override=tmp_path / "experiment")


def test_prepare_output_root_creates_only_experiment_children(tmp_path: Path):
    config = load_config(CONFIG_PATH)
    volume = tmp_path / "ZHUTONG"
    unrelated = volume / "其他文件.txt"
    unrelated.parent.mkdir(parents=True)
    unrelated.write_text("keep", encoding="utf-8")
    experiment = volume / "股票分析助手-V3回测" / config.experiment_id

    prepared = prepare_output_root(
        config,
        output_override=experiment,
        allowed_volume_root=volume,
    )

    assert prepared == experiment
    assert unrelated.read_text(encoding="utf-8") == "keep"
    assert {path.name for path in experiment.iterdir()} == {
        "manifests",
        "tables",
        "reports",
    }
