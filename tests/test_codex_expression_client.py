from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

from stock_analyzer.ops.codex_expression_client import (
    CodexExpressionClient,
    CodexExpressionError,
)
from tests.test_formal_narrative import _payload, _valid_narrative


@dataclass
class RecordedCall:
    command: list[str]
    cwd: Path
    input_text: str
    env: dict[str, str]
    timeout: float


class RecordingRunner:
    def __init__(self, outputs: list[str]):
        self.outputs = list(outputs)
        self.calls: list[RecordedCall] = []

    def __call__(self, command, *, cwd, input_text, env, timeout):
        self.calls.append(
            RecordedCall(
                command=list(command),
                cwd=Path(cwd),
                input_text=input_text,
                env=dict(env),
                timeout=timeout,
            )
        )
        output_path = Path(command[command.index("--output-last-message") + 1])
        output_path.write_text(self.outputs.pop(0), encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")


def _recorded_outputs():
    payload = _payload()
    narrative = _valid_narrative(payload)
    return payload, narrative, [
        *[item.model_dump_json() for item in narrative.stocks],
        narrative.market.model_dump_json(),
    ]


def test_client_uses_approved_model_high_reasoning_and_standard_speed(tmp_path):
    payload, narrative, outputs = _recorded_outputs()
    runner = RecordingRunner(outputs)
    client = CodexExpressionClient(runner=runner, temp_root=tmp_path)

    result = client.express(payload)

    assert result == narrative
    assert len(runner.calls) == len(narrative.stocks) + 1
    command = runner.calls[0].command
    assert command[1] == "exec"
    assert "--ephemeral" in command
    assert "--ignore-user-config" in command
    assert command[command.index("--model") + 1] == "gpt-5.6-sol"
    assert 'model_reasoning_effort="high"' in command
    assert command[command.index("--disable") + 1] == "fast_mode"
    assert "--output-schema" in command
    assert runner.calls[0].cwd != Path.cwd()


def test_client_sends_one_stock_per_call_and_no_runtime_paths(tmp_path):
    payload, narrative, outputs = _recorded_outputs()
    runner = RecordingRunner(outputs)

    CodexExpressionClient(runner=runner, temp_root=tmp_path).express(payload)

    first = runner.calls[0].input_text
    second = runner.calls[1].input_text
    assert narrative.stocks[1].ts_code not in first
    assert narrative.stocks[0].ts_code not in second
    for prompt in (first, second):
        assert ".env.local" not in prompt
        assert "run_receipt" not in prompt
        assert "/Users/" not in prompt


def test_client_does_not_inherit_application_credentials(monkeypatch, tmp_path):
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "secret-sentinel")
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "secret-sentinel")
    monkeypatch.setenv("REPORT_PASSWORD", "secret-sentinel")
    payload, _, outputs = _recorded_outputs()
    runner = RecordingRunner(outputs)

    CodexExpressionClient(runner=runner, temp_root=tmp_path).express(payload)

    child_env = runner.calls[0].env
    assert "SUPABASE_SERVICE_ROLE_KEY" not in child_env
    assert "CLOUDFLARE_API_TOKEN" not in child_env
    assert "REPORT_PASSWORD" not in child_env
    assert "secret-sentinel" not in json.dumps(child_env)


def test_client_retries_only_the_stock_that_violates_numeric_whitelist(tmp_path):
    payload, narrative, _ = _recorded_outputs()
    first = narrative.stocks[0]
    invalid_point = first.analysis_summary.model_copy(
        update={"text": "目标价为 99.99 元。"}
    )
    invalid_first = first.model_copy(update={"analysis_summary": invalid_point})
    runner = RecordingRunner(
        [
            invalid_first.model_dump_json(),
            first.model_dump_json(),
            narrative.stocks[1].model_dump_json(),
            narrative.market.model_dump_json(),
        ]
    )

    result = CodexExpressionClient(runner=runner, temp_root=tmp_path).express(payload)

    assert result == narrative
    assert len(runner.calls) == 4
    assert "previous_output" in runner.calls[1].input_text
    assert narrative.stocks[1].ts_code not in runner.calls[1].input_text


@pytest.mark.parametrize(
    "failure",
    ["nonzero", "timeout", "missing_output", "invalid_json"],
)
def test_client_failures_are_redacted_and_fail_closed(tmp_path, failure):
    payload, _, outputs = _recorded_outputs()

    def failing_runner(command, *, cwd, input_text, env, timeout):
        del cwd, input_text, env, timeout
        output_path = Path(command[command.index("--output-last-message") + 1])
        if failure == "timeout":
            raise subprocess.TimeoutExpired(command, 1, stderr="secret-sentinel")
        if failure == "nonzero":
            return subprocess.CompletedProcess(
                command, 1, stdout="", stderr="secret-sentinel"
            )
        if failure == "invalid_json":
            output_path.write_text("not-json secret-sentinel", encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    client = CodexExpressionClient(runner=failing_runner, temp_root=tmp_path)
    with pytest.raises(CodexExpressionError) as raised:
        client.express(payload)
    assert "secret-sentinel" not in str(raised.value)
