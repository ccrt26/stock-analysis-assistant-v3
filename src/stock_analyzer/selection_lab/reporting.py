from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from stock_analyzer.selection_lab.audit import deterministic_json, scan_public_payload


REVIEW_FILENAMES = (
    "README.md",
    "previously_used_formation_dates.json",
    "data_lineage_manifest.json",
    "feature_dictionary.json",
    "split_manifest.json",
    "baseline_metrics.json",
    "ranker_metrics.json",
    "opportunity_type_audit.json",
    "model_coefficients.json",
    "rank_examples.json",
    "verification.json",
)


def _blocked_metric(reason_code: str) -> dict[str, Any]:
    return {
        "status": "not_evaluable",
        "reason_code": reason_code,
        "policy_precision_at_1": None,
        "policy_precision_at_3": None,
        "policy_precision_at_5": None,
        "executable_precision_at_1": None,
        "executable_precision_at_3": None,
        "executable_precision_at_5": None,
    }


def _review_payloads(state: Mapping[str, Any]) -> dict[str, Any]:
    reason = str(state.get("main_track_reason_code") or "no_frozen_candidate_chain")
    conclusion = str(state.get("main_conclusion") or "实验阻塞")
    gate = str(state.get("gate_conclusion") or "not_evaluable")
    preregistration = state.get("preregistration", {})
    return {
        "previously_used_formation_dates.json": preregistration.get(
            "previously_used_formation_dates",
            {
                "status": "frozen_before_label_reveal",
                "dates": [],
                "reason_code": "base_commit_scan_recorded_separately",
            },
        ),
        "data_lineage_manifest.json": {
            "status": "blocked",
            "reason_code": reason,
            "main_conclusion": conclusion,
            "data_through": state.get("data_through"),
            "base_commit": state.get("base_commit"),
            "implementation_commit": state.get("implementation_commit"),
            "report_commit": state.get("report_commit"),
            "dataset_version": state.get("dataset_version", "selection-lab-v1"),
            "feature_version": state.get("feature_version", "selection-lab-v1"),
            "input_hashes": state.get("input_hashes", {}),
            "label_reveal_state": state.get(
                "label_reveal_state", "features_frozen"
            ),
            "limitations": [
                "No machine-readable frozen candidate chain was available.",
                "The deterministic research surface cannot upgrade the main conclusion.",
            ],
        },
        "feature_dictionary.json": preregistration.get(
            "feature_dictionary",
            {
                "status": "frozen_before_label_reveal",
                "features": [],
            },
        ),
        "split_manifest.json": preregistration.get(
            "split_manifest",
            {
                "status": "frozen_before_label_reveal",
                "splits": {},
            },
        ),
        "baseline_metrics.json": {
            **_blocked_metric(reason),
            "main_conclusion": conclusion,
            "secondary_track": state.get("secondary_baseline_metrics"),
        },
        "ranker_metrics.json": {
            **_blocked_metric(reason),
            "model_status": "not_trainable",
            "selected_model_variant": None,
            "selected_C": None,
            "probability_threshold": None,
            "zero_to_five_status": "not_supported",
            "main_conclusion": conclusion,
        },
        "opportunity_type_audit.json": {
            "status": "not_evaluable",
            "reason_code": reason,
            "counts": {
                "company_catalyst": None,
                "sector_diffusion": None,
                "independent_price_anomaly": None,
                "null": None,
            },
            "sole_gate_conclusion": gate,
            "main_conclusion": conclusion,
        },
        "model_coefficients.json": {
            "status": "not_available",
            "reason_code": reason,
            "model_type": None,
            "hyperparameters": None,
            "features": [],
            "coefficients": [],
            "intercept": None,
            "version": None,
        },
        "rank_examples.json": {
            "status": "not_available",
            "reason_code": reason,
            "examples": [],
        },
        "verification.json": state.get(
            "verification",
            {
                "status": "pending",
                "reason_code": "verification_not_yet_recorded",
                "commands": [],
            },
        ),
    }


def build_review_bundle(
    state: Mapping[str, Any], output_dir: Path
) -> tuple[Path, ...]:
    """Write the deterministic, aggregate-only public review bundle."""
    payloads = _review_payloads(state)
    findings = {
        filename: scan_public_payload(payload)
        for filename, payload in payloads.items()
        if scan_public_payload(payload)
    }
    if findings:
        raise ValueError(f"public review payload rejected: {findings}")

    output_dir.mkdir(parents=True, exist_ok=True)
    readme = output_dir / "README.md"
    readme.write_text(
        "# Selection Lab 审阅包\n\n"
        "本目录只包含可公开审阅的预注册清单、聚合状态和验证记录。"
        "当前主轨结论为 `实验阻塞`；次级研究面不得升级该结论。\n",
        encoding="utf-8",
    )
    paths = [readme]
    for filename in REVIEW_FILENAMES[1:]:
        path = output_dir / filename
        path.write_text(deterministic_json(payloads[filename]), encoding="utf-8")
        paths.append(path)
    return tuple(paths)


def run_local_workflow(command: str, config: Any) -> tuple[dict[str, Any], Path]:
    """Run one explicit offline workflow and persist its structured status."""
    if command == "build-review-bundle":
        output_dir = Path(config.project_root) / "docs" / "selection_lab" / "review"
        preregistration: dict[str, Any] = {}
        for key, filename in (
            ("previously_used_formation_dates", "previously_used_formation_dates.json"),
            ("feature_dictionary", "feature_dictionary.json"),
            ("split_manifest", "split_manifest.json"),
        ):
            path = output_dir / filename
            if path.is_file():
                preregistration[key] = json.loads(path.read_text(encoding="utf-8"))
        state = {
            "main_conclusion": "实验阻塞",
            "main_track_status": "unavailable",
            "main_track_reason_code": "no_frozen_candidate_chain",
            "gate_conclusion": "not_evaluable",
            "data_through": "2026-08-14",
            "preregistration": preregistration,
        }
        build_review_bundle(state, output_dir)
        status = {
            "status": "completed",
            "reason_code": None,
            "main_conclusion": "实验阻塞",
        }
        return status, output_dir / "verification.json"

    reasons = {
        "build-dataset": "no_frozen_candidate_chain",
        "audit-opportunity-types": "no_evaluable_main_track_dataset",
        "evaluate-baselines": "no_evaluable_main_track_dataset",
        "train-ranker": "no_trainable_main_track_dataset",
        "walk-forward": "no_frozen_model_and_threshold",
    }
    if command not in reasons:
        raise ValueError(f"unknown selection-lab workflow: {command}")
    status = {
        "command": command,
        "status": "blocked",
        "reason_code": reasons[command],
        "main_conclusion": "实验阻塞",
    }
    output = (
        Path(config.local_archive_dir)
        / "selection_lab"
        / f"{command}-status.json"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(deterministic_json(status), encoding="utf-8")
    return status, output
