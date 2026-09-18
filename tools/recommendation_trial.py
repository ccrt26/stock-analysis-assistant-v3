#!/usr/bin/env python3
"""人工验收试写入口：固定原时点研究输入，调用生产共用作者函数真实写文章。

只负责准备/固定试验输入、读取原配置但不修改、调用 run_article_cycle、保存文章与证据。
默认 expression-only：不提供正式 prepare、record、freeze、公司介绍、渲染或发布能力。
真实研究、文章与日志只写本地试验目录，不进入正式 trace/CSV/复盘/页面。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import nightly_report
import recommendation_pipeline as pipeline
import stock_ai

EXIT_OK = 0
EXIT_INPUT = 2
EXIT_NEEDS_RESEARCH = 3
EXIT_NEEDS_REVISION = 4


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _code_commit(code_root: Path) -> str:
    try:
        result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=code_root,
                                capture_output=True, text=True, timeout=30)
        if result.returncode == 0:
            return result.stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        pass
    return "unknown（无Git元数据）"


def prepare(*, source_root: Path, trace_path: Path, names: list[str], output_dir: Path,
            code_root: Path) -> dict:
    """只读源历史与事实，写入试验目录的输入快照与 manifest；不调用正式 prepare。"""
    if not names:
        raise ValueError("至少指定一只股票名称")
    trace = json.loads(trace_path.read_text(encoding="utf-8"))
    formation, action, as_of = pipeline.identity(trace)
    result = pipeline.selected_result(trace)
    by_name = {s["name"]: s for s in result["selected_stocks"]}
    stocks = []
    for name in names:
        stock = by_name.get(name)
        if stock is None:
            raise ValueError(f"{name} 不在本版正式名单中；可用：{sorted(by_name)}")
        stocks.append({"name": stock["name"], "ts_code": stock["ts_code"]})
    output_dir.mkdir(parents=True, exist_ok=True)
    snapshot = output_dir / "source-trace.json"
    snapshot.write_text(json.dumps(trace, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    handoff = pipeline.handoff_from_trace(trace)
    cited = handoff["market"] + " " + " ".join(
        filter(None, (s.get("nearest_comparison") for s in result["selected_stocks"])))
    context = pipeline.build_context(source_root, trace, cited_text=cited)
    packet_dir = output_dir / "packets"
    packet_dir.mkdir(parents=True, exist_ok=True)
    for stock in stocks:
        packet = pipeline.build_article_packet(trace=trace, context=context,
                                               ts_code=stock["ts_code"], research_handoff=handoff)
        (packet_dir / f"{stock['ts_code']}.json").write_text(
            json.dumps(packet, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    material = pipeline.writing_material(source_root, as_of, list(context["facts"]),
                                         teaching_root=code_root)
    material_path = output_dir / "writing-material.json"
    material_path.write_text(json.dumps(material, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    context_dir = output_dir / "context"
    context_dir.mkdir(exist_ok=True)
    (context_dir / "recommendation-context.json").write_text(
        json.dumps(context, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    manifest = {
        "identity": {"formation_date": formation, "action_date": action, "as_of": as_of},
        "source": {"trace_path": str(trace_path), "trace_sha256": _sha256(trace_path),
                   "trace_version": trace.get("trace_version"),
                   "snapshot": "source-trace.json（本轮只读快照）"},
        "stocks": stocks,
        "packets": {s["ts_code"]: f"packets/{s['ts_code']}.json" for s in stocks},
        "materials": {"path": "writing-material.json", "examples": [e["source"] for e in material["examples"]],
                      "reading_guide_chars": material["component_chars"]["reading_guide"],
                      "teaching_chars": material["component_chars"]["teaching"],
                      "gaps": material["gaps"]},
        "packet_chars": {s["ts_code"]: len((packet_dir / f"{s['ts_code']}.json").read_text(encoding="utf-8"))
                         for s in stocks},
        "code_root": str(code_root),
        "code_commit": _code_commit(code_root),
        "provider_policy": {"allowed": ["glm"], "fallback": False,
                            "note": "本轮试写显式锁定；正式任务的默认路线不变"},
        "authoring_contract": {"author": pipeline.AUTHOR_CONTRACT_VERSION,
                               "review": pipeline.REVIEW_CONTRACT_VERSION},
        "created_at": datetime.now().astimezone().isoformat(),
    }
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def _load_inputs(manifest_path: Path) -> tuple[dict, Path, dict, Path]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    input_dir = manifest_path.parent
    material = json.loads((input_dir / manifest["materials"]["path"]).read_text(encoding="utf-8"))
    return manifest, input_dir, material, input_dir


def run(*, manifest_path: Path, provider: str, fallback: bool, repeats: int,
        output_dir: Path) -> int:
    """对固定输入逐股×重复次数调用生产 run_article_cycle；返回约定退出码。"""
    if repeats < 1:
        raise ValueError("repeats 至少为1")
    manifest, input_dir, material, _ = _load_inputs(manifest_path)
    runs_dir = output_dir
    runs_dir.mkdir(parents=True, exist_ok=True)
    summaries = []
    saw_input_error = saw_needs_research = saw_needs_revision = False
    for repeat in range(1, repeats + 1):
        repeat_dir = runs_dir / f"repeat-{repeat}"
        for stock in manifest["stocks"]:
            code = stock["ts_code"]
            packet = json.loads((input_dir / manifest["packets"][code]).read_text(encoding="utf-8"))
            stock_dir = repeat_dir / code.replace(".", "-")
            state = {"task": "recommendation-trial", "provider_order": [provider],
                     "attempts": [], "repeat": repeat, "ts_code": code,
                     "identity": manifest["identity"]}
            state_path = stock_dir / "state.json"
            summary = {"repeat": repeat, "ts_code": code, "name": stock["name"]}
            try:
                cycle = pipeline.run_article_cycle(
                    stock_ai, packet=packet, materials=material, directory=stock_dir,
                    state=state, state_path=state_path, config={}, provider=provider,
                    fallback=fallback, allow_research_changes=False)
            except (OSError, ValueError, RuntimeError) as exc:
                summary.update(status="failed", error=f"{type(exc).__name__}: {exc}")
                saw_input_error = True
            else:
                summary.update(status=cycle["status"], article_path=cycle.get("article_path"),
                               stages=cycle["stages"], research_issues=cycle["research_issues"],
                               review_summary=(cycle.get("review") or {}).get("reader_summary"))
                if cycle["status"] == "needs_research":
                    saw_needs_research = True
                elif cycle["status"] == "needs_revision":
                    saw_needs_revision = True
                elif cycle["status"] != "ready":
                    saw_input_error = True
            pipeline.save_json(stock_dir / "summary.json", summary)
            pipeline.save_json(state_path, state)
            summaries.append(summary)
    evidence = _evidence_lines(runs_dir)
    _write_eval_files(runs_dir.parent, manifest, summaries, evidence, provider, fallback)
    if saw_input_error:
        return EXIT_INPUT
    if saw_needs_research:
        return EXIT_NEEDS_RESEARCH
    if saw_needs_revision:
        return EXIT_NEEDS_REVISION
    return EXIT_OK


def _evidence_lines(runs_dir: Path) -> list[dict]:
    """从各阶段state收集模型证据；区分 configured_model 与 evidence_model。"""
    rows = []
    for state_path in sorted(runs_dir.glob("repeat-*/**/state.json")):
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for entry in state.get("recommendation_stages", []):
            evidence = entry.get("evidence") or {}
            rows.append({
                "repeat": state.get("repeat"), "ts_code": state.get("ts_code"),
                "stage": entry.get("stage"), "provider": entry.get("provider"),
                "configured_model": entry.get("configured_model"),
                "evidence_model": evidence.get("model") or evidence.get("request_model") or "",
                "response_model": evidence.get("response_model") or "",
                "session_id": evidence.get("session_id") or "",
                "status": entry.get("status"), "input": entry.get("input"),
                "output": entry.get("output"),
                "verified": bool(evidence.get("verified")),
                "note": evidence.get("note") or "",
            })
    return rows


def _write_eval_files(trial_dir: Path, manifest: dict, summaries: list[dict],
                      evidence: list[dict], provider: str, fallback: bool) -> None:
    identity = manifest["identity"]
    lines = ["# 交给ChatGPT评估_文章", "",
             f"形成日 {identity['formation_date']}；行动日 {identity['action_date']}；截止 {identity['as_of']}。",
             "同一固定原时点研究、同一通用Prompt与同一模型配置，两个独立重复。", ""]
    for stock in manifest["stocks"]:
        code = stock["ts_code"]
        lines.append(f"## {stock['name']}（{code}）")
        lines.append("")
        for summary in [s for s in summaries if s["ts_code"] == code]:
            lines.append(f"### repeat-{summary['repeat']}（状态：{summary['status']}）")
            lines.append("")
            packet = json.loads((trial_dir / "input" / manifest["packets"][code]).read_text(encoding="utf-8"))
            reference = packet["identity"].get("reference_price")
            lines.append(f"参考价：{reference}；代码 {code}；截止 {identity['as_of']}。")
            lines.append("")
            article_path = summary.get("article_path")
            if article_path and Path(article_path).exists():
                lines.append(Path(article_path).read_text(encoding="utf-8").strip())
            else:
                lines.append(f"（无采用正文：{summary.get('error') or summary.get('research_issues') or summary['status']}）")
            lines.append("")
    (trial_dir / "交给ChatGPT评估_文章.md").write_text("\n".join(lines), encoding="utf-8")

    notes = ["# 交给ChatGPT评估_运行说明", "",
             f"- 模型路线：{provider}，fallback={'开' if fallback else '关（False）'}；"
             f"供应商策略固定为 {manifest['provider_policy']['allowed']}。",
             f"- 代码：CODE_ROOT={manifest['code_root']}，commit={manifest['code_commit']}。",
             f"- 研究来源：{manifest['source']['trace_path']}（sha256 {manifest['source']['trace_sha256'][:16]}…，"
             f"版本 {manifest['source']['trace_version']}，身份 {identity['formation_date']}/{identity['action_date']}/{identity['as_of']}）。",
             f"- 两次重复使用同一 manifest 输入（同版快照），范文：{('、'.join(manifest['materials']['examples'])) or '无'}；"
             f"阅读指南 {manifest['materials']['reading_guide_chars']} 字符，教学 {manifest['materials']['teaching_chars']} 字符。",
             "- 每股输入字符数：" + "；".join(
                 f"{s['name']}({s['ts_code']}) {manifest['packet_chars'][s['ts_code']]}"
                 for s in manifest["stocks"]) + "。",
             "", "## 逐股状态", ""]
    for summary in summaries:
        notes.append(f"- repeat-{summary['repeat']} {summary['name']}（{summary['ts_code']}）：{summary['status']}；"
                     f"阶段 {'→'.join(summary.get('stages') or [])}。")
        if summary.get("research_issues"):
            notes.append(f"  - 未决研究问题：{json.dumps(summary['research_issues'], ensure_ascii=False)}")
        if summary.get("error"):
            notes.append(f"  - 错误：{summary['error']}")
    notes += ["", "## 模型证据", ""]
    if evidence:
        notes.append("| repeat | 代码 | 阶段 | 路线 | 配置型号 | 证据型号 | 会话 | 状态 |")
        notes.append("|---|---|---|---|---|---|---|---|")
        for row in evidence:
            notes.append(f"| {row['repeat']} | {row['ts_code']} | {row['stage']} | {row['provider']} | "
                         f"{row['configured_model']} | {row['evidence_model'] or row['response_model'] or '未取得'} | "
                         f"{row['session_id'] or '未取得'} | {row['status']} |")
        unverified = [r for r in evidence if not r["verified"]]
        if unverified:
            notes.append("")
            notes.append(f"注意：{len(unverified)} 条阶段证据未完整核验（模型身份未完整核验），见各 stage 输入/输出文件。")
    else:
        notes.append("未取得任何模型证据。")
    notes += ["", f"- 命中缓存说明：每个 repeat 使用独立目录（repeat-N/代码），不跨重复复用；"
              "同目录内同输入身份的阶段复用见 stage-result.json 的 input_identity。",
              "- 原正式产物未改动：本工具不调用正式 prepare/record/freeze/渲染/发布。", ""]
    (trial_dir / "交给ChatGPT评估_运行说明.md").write_text("\n".join(notes), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_prepare = sub.add_parser("prepare", help="固定试验输入并生成 manifest（只读源历史）")
    p_prepare.add_argument("--source-root", type=Path, required=True)
    p_prepare.add_argument("--trace", type=Path, required=True)
    p_prepare.add_argument("--names", nargs="+", required=True, metavar="NAME")
    p_prepare.add_argument("--output-dir", type=Path, required=True)
    p_prepare.add_argument("--code-root", type=Path,
                           default=Path(__file__).resolve().parents[1])

    p_run = sub.add_parser("run", help="按 manifest 真实写文章（生产共用作者循环）")
    p_run.add_argument("--manifest", type=Path, required=True)
    p_run.add_argument("--provider", required=True)
    p_run.add_argument("--no-fallback", action="store_true")
    p_run.add_argument("--repeats", type=int, default=1)
    p_run.add_argument("--output-dir", type=Path, required=True)

    args = parser.parse_args(argv)
    try:
        if args.command == "prepare":
            prepare(source_root=args.source_root, trace_path=args.trace, names=args.names,
                    output_dir=args.output_dir, code_root=args.code_root)
            print(f"manifest={args.output_dir / 'manifest.json'}")
            return EXIT_OK
        code = run(manifest_path=args.manifest, provider=args.provider,
                   fallback=not args.no_fallback, repeats=args.repeats,
                   output_dir=args.output_dir)
        print(f"exit={code}; runs={args.output_dir}")
        return code
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"错误：{type(exc).__name__}: {exc}", file=sys.stderr)
        return EXIT_INPUT


if __name__ == "__main__":
    raise SystemExit(main())
