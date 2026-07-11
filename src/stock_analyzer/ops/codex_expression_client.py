from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from pydantic import ValidationError

from stock_analyzer.ops.formal_narrative import (
    FormalNarrative,
    MarketNarrative,
    StockNarrative,
    build_stock_analysis_requests,
    validate_formal_narrative,
)


class CodexExpressionError(RuntimeError):
    pass


@dataclass(frozen=True)
class CodexExpressionConfig:
    binary: str = ""
    model: str = "gpt-5.6-sol"
    reasoning_effort: str = "high"
    timeout_seconds: float = 600.0

    def resolved_binary(self) -> str:
        return self.binary or shutil.which("codex") or "codex"


Runner = Callable[..., subprocess.CompletedProcess[str]]


def _subprocess_runner(
    command: list[str],
    *,
    cwd: Path,
    input_text: str,
    env: dict[str, str],
    timeout: float,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        input=input_text,
        env=env,
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )


class CodexExpressionClient:
    def __init__(
        self,
        *,
        config: CodexExpressionConfig | None = None,
        runner: Runner = _subprocess_runner,
        temp_root: Path | None = None,
    ) -> None:
        self.config = config or CodexExpressionConfig()
        self.runner = runner
        self.temp_root = Path(temp_root) if temp_root is not None else None

    def express(self, payload: Any) -> FormalNarrative:
        requests = build_stock_analysis_requests(payload)
        stocks = [
            self._invoke(
                schema=StockNarrative.model_json_schema(),
                response_type=StockNarrative,
                prompt=self._stock_prompt(request.model_dump(mode="json")),
            )
            for request in requests
        ]
        market_context = [
            {
                "ts_code": request.ts_code,
                "evidence_id": request.evidence_id,
                "market_board": [
                    module
                    for module in request.evidence["modules"]
                    if module["module"] == "market_board"
                ],
                "decision": request.decision_lock.model_dump(mode="json"),
            }
            for request in requests
        ]
        market = self._invoke(
            schema=MarketNarrative.model_json_schema(),
            response_type=MarketNarrative,
            prompt=self._market_prompt(market_context),
        )
        narrative = FormalNarrative(market=market, stocks=stocks)
        return validate_formal_narrative(payload, narrative)

    def _invoke(self, *, schema: dict[str, Any], response_type, prompt: str):
        try:
            with tempfile.TemporaryDirectory(
                prefix="stock-analyzer-codex-",
                dir=self.temp_root,
            ) as temporary:
                workdir = Path(temporary)
                schema_path = workdir / "response.schema.json"
                output_path = workdir / "response.json"
                schema_path.write_text(
                    json.dumps(schema, ensure_ascii=False),
                    encoding="utf-8",
                )
                command = [
                    self.config.resolved_binary(),
                    "exec",
                    "--ephemeral",
                    "--ignore-user-config",
                    "--skip-git-repo-check",
                    "--sandbox",
                    "read-only",
                    "--model",
                    self.config.model,
                    "-c",
                    f'model_reasoning_effort="{self.config.reasoning_effort}"',
                    "--disable",
                    "fast_mode",
                    "--output-schema",
                    str(schema_path),
                    "--output-last-message",
                    str(output_path),
                    "-",
                ]
                completed = self.runner(
                    command,
                    cwd=workdir,
                    input_text=prompt,
                    env=_codex_environment(),
                    timeout=self.config.timeout_seconds,
                )
                if completed.returncode != 0:
                    raise CodexExpressionError("formal Codex analysis failed")
                if not output_path.is_file():
                    raise CodexExpressionError("formal Codex analysis produced no output")
                return response_type.model_validate_json(
                    output_path.read_text(encoding="utf-8")
                )
        except CodexExpressionError:
            raise
        except subprocess.TimeoutExpired as exc:
            raise CodexExpressionError("formal Codex analysis timed out") from exc
        except (OSError, ValueError, ValidationError, json.JSONDecodeError) as exc:
            raise CodexExpressionError("formal Codex analysis output is invalid") from exc

    @staticmethod
    def _stock_prompt(request: dict[str, Any]) -> str:
        return json.dumps(
            {
                "instructions": [
                    "只分析 input 中这一只股票。",
                    "知识规则优先；规则未覆盖时可做明确标注为推断的分析。",
                    "不得新增事实、价格、证据 ID 或改变 decision_lock。",
                    "输出必须严格符合给定 JSON Schema。",
                ],
                "input": request,
            },
            ensure_ascii=False,
            sort_keys=True,
        )

    @staticmethod
    def _market_prompt(context: list[dict[str, Any]]) -> str:
        return json.dumps(
            {
                "instructions": [
                    "只概括已提供的市场与板块证据和冻结决策分布。",
                    "不得重排股票、改变个股结论或新增市场事实。",
                    "输出必须严格符合给定 JSON Schema。",
                ],
                "input": context,
            },
            ensure_ascii=False,
            sort_keys=True,
        )


def _codex_environment() -> dict[str, str]:
    allowed = (
        "HOME",
        "PATH",
        "TMPDIR",
        "CODEX_HOME",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "NO_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
        "no_proxy",
    )
    return {name: os.environ[name] for name in allowed if os.environ.get(name)}


__all__ = [
    "CodexExpressionClient",
    "CodexExpressionConfig",
    "CodexExpressionError",
]
