#!/usr/bin/env python3
"""Generate the two Astra launch scripts from the frozen trial config.

The scripts are deliverables, not runners: this tool only writes them. Each
script first calls the REAL read-only `check-launch` gate, then executes the
frozen select sequence through run_select (background + wait so the TERM/INT
trap can stop exactly the executor this script started; that executor reaps
its own process group). set -euo pipefail is kept but is never the gate.

Environment overrides exist for ENGINEERING ACCEPTANCE ONLY (fake select CLI,
temp config, snapshot code root): ASTRA_PY, ASTRA_CODE_ROOT, ASTRA_CONFIG,
ASTRA_SELECT_TOOL. check-launch itself always runs the real code under
ASTRA_CODE_ROOT and is never mocked.
"""
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path


def _head(code_root: Path) -> str:
    return subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=code_root, check=True,
                          capture_output=True, text=True).stdout.strip()


def _select_call(replay_id: str, action_date: str, method: str) -> str:
    return f"run_select {method} {replay_id} {action_date}"


def generate(config_path: Path, output_dir: Path) -> dict:
    config_path = Path(config_path)
    cfg = json.loads(config_path.read_text(encoding='utf-8'))
    code_root = Path(cfg['code_root'])
    head = _head(code_root)
    cases = cfg['replay_cases']
    limits = cfg.get('limits', {})
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    def body(cases_subset: list[dict], gate_phase: str) -> str:
        lines = [
            '#!/bin/bash',
            '# 由 tools/selection_launch_scripts.py 生成的 Astra 启动脚本（交付材料）。',
            f'# 声明最终 HEAD：{head}',
            '# 启动前必须先运行 check-launch（真实只读门槛）；任何一步失败即停止，不自动重跑。',
            'set -euo pipefail',
            '',
            "PY=\"${ASTRA_PY:-/Users/ccrt/股票分析助手/.venv/bin/python}\"",
            'CODE_ROOT="${ASTRA_CODE_ROOT:-' + str(code_root) + '}"',
            'CFG="${ASTRA_CONFIG:-' + str(config_path) + '}"',
            'SELECT_TOOL="${ASTRA_SELECT_TOOL:-tools/selection_parallel.py}"',
            '# 工程验收覆盖项（假select CLI/临时配置/快照代码根）仅供验收；check-launch 恒为真实代码。',
            '',
            'CHILD_PID=0',
            'cleanup() {',
            '  if [ "$CHILD_PID" -gt 0 ] && kill -0 "$CHILD_PID" 2>/dev/null; then',
            '    kill -TERM "$CHILD_PID" 2>/dev/null || true',
            '    wait "$CHILD_PID" 2>/dev/null || true',
            '    CHILD_PID=0',
            '  fi',
            '}',
            'trap cleanup TERM INT',
            '',
            'run_select() {',
            '  local method="$1" replay="$2" day="$3"',
            '  echo "[$(date +%H:%M:%S)] select $method $replay ($day)"',
            '  (cd "$CODE_ROOT" && PYTHONPATH="$CODE_ROOT/src:$CODE_ROOT/tools:$CODE_ROOT" \\',
            '    exec "$PY" "$SELECT_TOOL" select --config "$CFG" \\',
            f'      --action-date "$day" --method "$method" --replay-id "$replay") &',
            '  CHILD_PID=$!',
            '  wait "$CHILD_PID"',
            '  local status=$?',
            '  CHILD_PID=0',
            '  if [ "$status" -ne 0 ]; then',
            '    echo "select $method $replay 失败（exit $status）：停止当日与后续；证据在 work/$replay/$method/attempt-*/" >&2',
            "    return \"$status\"",
            '  fi',
            '}',
            '',
            'cd "$CODE_ROOT"',
            'echo "== check-launch（真实只读门槛：合同/首日资格/前置条件）=="',
            f'PYTHONPATH="$CODE_ROOT/src:$CODE_ROOT/tools:$CODE_ROOT" "$PY" tools/selection_parallel.py \\',
            f'  check-launch --config "$CFG" --phase {gate_phase}',
            'echo "check-launch 通过。"',
            '',
        ]
        for case in cases_subset:
            lines.append(f"# {case['action_date']}（replay {case['replay_id']}，顺序 "
                         f"{'先A后B' if case['method_order'] == ['M0', 'M1'] else '先B后A'}）")
            lines.append(f'echo "== 进入 {case["action_date"]} =="')
            # re-run the gate before each later day: first pair must stay qualified
            # and every completed day must be qualified
            if gate_phase == 'remaining' and case is not cases_subset[0]:
                lines.append('PYTHONPATH="$CODE_ROOT/src:$CODE_ROOT/tools:$CODE_ROOT" "$PY" '
                             'tools/selection_parallel.py \\')
                lines.append('  check-launch --config "$CFG" --phase remaining')
            for method in case['method_order']:
                lines.append(_select_call(case['replay_id'], case['action_date'], method))
            lines.append('')
        lines.append('echo "全部完成。运行后核对：status 命令查看各日 M0/M1 为 complete/complete_zero。"')
        return '\n'.join(lines) + '\n'

    first = cases[0]
    first_script = output_dir / 'Astra_首日一对.sh'
    first_script.write_text(body([first], 'first-pair'), encoding='utf-8')
    remaining_script = output_dir / 'Astra_剩余四日.sh'
    remaining_script.write_text(body(cases[1:], 'remaining'), encoding='utf-8')
    for script in (first_script, remaining_script):
        script.chmod(0o755)
    return {'first_pair': str(first_script), 'remaining': str(remaining_script),
            'declared_head': head,
            'replay_ids': [c['replay_id'] for c in cases],
            'limits': limits,
            'note': '脚本为交付材料；GLM工程阶段不执行；research_enabled 由用户手动开启'}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    result = generate(args.config, args.output_dir)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
