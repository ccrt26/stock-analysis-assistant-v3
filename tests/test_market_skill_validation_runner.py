from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path

import pytest


_SCRIPT = Path(__file__).parents[1] / "tools" / "run_market_skill_validation.py"
_SPEC = importlib.util.spec_from_file_location("market_skill_validation_runner", _SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)


def test_runner_refuses_a_changed_frozen_hypothesis_file(tmp_path: Path) -> None:
    _SPEC.loader.exec_module(_MODULE)
    hypothesis = tmp_path / "hypotheses.yaml"
    checksum = tmp_path / "hypotheses.sha256"
    hypothesis.write_text("frozen: true\n", encoding="utf-8")
    digest = hashlib.sha256(hypothesis.read_bytes()).hexdigest()
    checksum.write_text(f"{digest}  hypotheses.yaml\n", encoding="utf-8")

    assert _MODULE._verify_hypothesis_freeze(hypothesis, checksum) == digest

    hypothesis.write_text("frozen: false\n", encoding="utf-8")
    with pytest.raises(ValueError, match="frozen hypothesis checksum mismatch"):
        _MODULE._verify_hypothesis_freeze(hypothesis, checksum)
