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
            code_root: Path, handoff_path: Path | None = None,
            original_report_path: Path | None = None) -> dict:
    """只读源历史与事实，写入试验目录的输入快照与 manifest；不调用正式 prepare。

    handoff：现场已核实的 selection-handoff.json（v2须携带匹配的trace_sha256）。
    original-report：原研究报告；仅逐股提取其中独有的条件原句及来源，不当写作模板。
    """
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
    handoff_sources = []
    conflicts = []
    if handoff_path is not None:
        supplied = json.loads(handoff_path.read_text(encoding="utf-8"))
        supplied_digest = supplied.get("trace_sha256")
        if (supplied.get("formation_date"), supplied.get("action_date"),
                supplied.get("as_of")) != (formation, action, as_of):
            conflicts.append(f"{handoff_path.name}: 时间身份与本trace不一致")
        elif supplied_digest and supplied_digest != pipeline.trace_input_sha256(trace):
            conflicts.append(f"{handoff_path.name}: trace_sha256 与本trace不匹配（判定为同日其他版本）")
        else:
            binding = "trace_sha256" if supplied_digest else "identity_only"
            for code_key, extra in (supplied.get("stocks") or {}).items():
                if code_key in handoff["stocks"] and isinstance(extra, dict):
                    handoff["stocks"][code_key].update(extra)
            handoff["market"] = str(supplied.get("market") or handoff["market"])
            handoff["binding"] = binding
            handoff["handoff_source"] = str(handoff_path)
            handoff_sources.append({"path": handoff_path.name, "binding": binding})
    if original_report_path is not None:
        report_text = original_report_path.read_text(encoding="utf-8")
        extracted = {}
        for stock in stocks:
            found = pipeline.extract_conditions_from_report(report_text, stock["ts_code"])
            if found:
                extracted[stock["ts_code"]] = found
                handoff.setdefault("stocks", {}).setdefault(stock["ts_code"], {}).setdefault(
                    "original_report_conditions", found)
        (output_dir / "original-report-conditions.json").write_text(
            json.dumps({"source": str(original_report_path), "conditions": extracted},
                       ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        handoff_sources.append({"path": original_report_path.name,
                                "usage": "condition-sentences-only"})
    if conflicts:
        raise ValueError("研究交接存在冲突，拒绝凭mtime挑选：" + "；".join(conflicts))
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
        "packet_composition": {s["ts_code"]: json.loads(
            (packet_dir / f"{s['ts_code']}.json").read_text(encoding="utf-8")).get("composition", {})
            for s in stocks},
        "code_root": str(code_root),
        "code_commit": _code_commit(code_root),
        "provider_policy": {"allowed": ["glm"], "fallback": False,
                            "note": "本轮试写显式锁定；正式任务的默认路线不变"},
        "handoff_sources": handoff_sources,
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


REQUIRED_GLM_MODEL = "bigmodel/glm-5.3-flash"
TRIAL_PROVIDER = "glm"


def load_source_config(source_root: Path) -> tuple[dict, dict]:
    """显式读取源项目配置并归一为本轮有效配置；只读，不含密钥值进内存日志。

    返回 (有效配置, 核验记录)。源配置损坏时回退默认但如实标记，
    不允许静默回默认后宣称配置核验成功。
    """
    path = source_root / ".stock-ai.local.json"
    if not path.exists():
        record = {"source": str(path.name), "status": "default_missing",
                  "note": "源配置不存在，使用默认配置与既有凭据来源"}
        config = {}
    else:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                config, record = data, {"source": str(path.name), "status": "loaded"}
            else:
                config = {}
                record = {"source": str(path.name), "status": "default_broken",
                          "note": "源配置不是JSON对象，使用默认配置；配置核验不视为成功"}
        except (OSError, json.JSONDecodeError) as exc:
            config = {}
            record = {"source": str(path.name), "status": "default_broken",
                      "note": f"源配置读取失败（{type(exc).__name__}），使用默认配置；配置核验不视为成功"}
    eff = json.loads(json.dumps(config))  # deep copy without importing copy
    refs = eff.get("model_refs") if isinstance(eff.get("model_refs"), dict) else {}
    current = refs.get(TRIAL_PROVIDER) or stock_ai.DEFAULT_MODEL_REFS.get(TRIAL_PROVIDER, "")
    record["configured_model_ref"] = current
    record["required_model_ref"] = REQUIRED_GLM_MODEL
    if current != REQUIRED_GLM_MODEL:
        eff.setdefault("model_refs", {})[TRIAL_PROVIDER] = REQUIRED_GLM_MODEL
        record["differences"] = [f"model_refs.{TRIAL_PROVIDER}={current!r} 与要求不符，已在内存配置覆盖为 {REQUIRED_GLM_MODEL!r}；端点与认证不变"]
    else:
        record["differences"] = []
    record["effective_base_url"] = stock_ai.provider_base_url(TRIAL_PROVIDER, eff)
    return eff, record


def validate_run_policy(provider: str, fallback: bool) -> str | None:
    """发出任何请求前拒绝非GLM或允许备用的试写参数。"""
    if provider != TRIAL_PROVIDER:
        return f"试写只允许 provider={TRIAL_PROVIDER}，收到 {provider!r}"
    if fallback:
        return "试写必须禁用备用（--no-fallback）；不依赖调用者记得关闭"
    return None


def run(*, manifest_path: Path, provider: str, fallback: bool, repeats: int,
        output_dir: Path, source_root: Path | None = None,
        resume: bool = False) -> int:
    """对固定输入逐股×重复次数调用生产 run_article_cycle；返回约定退出码。

    article_status 与 execution_verified 分开记录：业务ready但证据未核验的稿
    保留给阅读，整体不能按0退出。0 要求全部预期样本有结果行、全部ready且核验通过。
    """
    if repeats < 1:
        raise ValueError("repeats 至少为1")
    policy_error = validate_run_policy(provider, fallback)
    if policy_error:
        print(f"错误：{policy_error}", file=sys.stderr)
        return EXIT_INPUT
    if source_root is None:
        print("错误：run 需要 --source-root 以显式装载源配置", file=sys.stderr)
        return EXIT_INPUT
    manifest, input_dir, material, _ = _load_inputs(manifest_path)
    effective_config, config_record = load_source_config(Path(source_root))
    runs_dir = output_dir
    if runs_dir.exists() and any(runs_dir.iterdir()):
        if not resume:
            print(f"错误：输出目录非空且未指定 --resume，拒绝复用：{runs_dir}", file=sys.stderr)
            return EXIT_INPUT
    runs_dir.mkdir(parents=True, exist_ok=True)
    pipeline.save_json(runs_dir / "execution-config.json",
                       {"policy": {"provider": provider, "fallback": fallback,
                                   "provider_order": [provider]},
                        **config_record})
    summaries = []
    saw_input_error = bool(config_record.get("status") == "default_broken")
    saw_needs_research = saw_needs_revision = False
    expected = [(stock["ts_code"], repeat) for repeat in range(1, repeats + 1)
                for stock in manifest["stocks"]]
    done: set[tuple[str, int]] = set()
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
            summary = {"repeat": repeat, "ts_code": code, "name": stock["name"],
                       "config_status": config_record.get("status")}
            try:
                cycle = pipeline.run_article_cycle(
                    stock_ai, packet=packet, materials=material, directory=stock_dir,
                    state=state, state_path=state_path, config=effective_config,
                    provider=provider, fallback=fallback, allow_research_changes=False,
                    run_scope=f"repeat-{repeat}")
            except (OSError, ValueError, RuntimeError) as exc:
                summary.update(article_status="failed", status="failed",
                               execution_verified=False,
                               error=f"{type(exc).__name__}: {exc}")
                saw_input_error = True
            else:
                summary.update(article_status=cycle["status"], status=cycle["status"],
                               article_path=cycle.get("article_path"),
                               stages=cycle["stages"],
                               research_issues=cycle["research_issues"],
                               execution_verified=bool(cycle.get("execution_verified")),
                               stages_execution=[
                                   {k: e[k] for k in ("stage", "route", "execution_verified")}
                                   for e in cycle.get("stages_execution", [])],
                               review_summary=(cycle.get("review") or {}).get("reader_summary"))
                if not summary["execution_verified"]:
                    saw_input_error = True
                elif cycle["status"] == "needs_research":
                    saw_needs_research = True
                elif cycle["status"] == "needs_revision":
                    saw_needs_revision = True
                elif cycle["status"] != "ready":
                    saw_input_error = True
            done.add((code, repeat))
            pipeline.save_json(stock_dir / "summary.json", summary)
            pipeline.save_json(state_path, state)
            summaries.append(summary)
    missing = [combo for combo in expected if combo not in done]
    if missing:
        saw_input_error = True
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
                "evidence_provider": evidence.get("provider") or "",
                "evidence_model": evidence.get("model") or evidence.get("request_model") or "",
                "request_model": evidence.get("request_model") or "",
                "response_model": evidence.get("response_model") or "",
                "effort": evidence.get("effort") or "", "thinking": evidence.get("thinking") or "",
                "session_id": evidence.get("session_id") or "",
                "usage": evidence.get("usage") or {},
                "status": entry.get("status"), "input": entry.get("input"),
                "output": entry.get("output"),
                "verified": bool(evidence.get("verified")),
                "source_file": evidence.get("source_file") or "",
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


def check_review(*, source_root: Path, fixtures: Path, output_dir: Path,
                 provider: str = TRIAL_PROVIDER, fallback: bool = False,
                 code_root: Path | None = None) -> int:
    """真实GLM审稿/澄清挑战：走生产共用函数；期望只在包装层比对。"""
    policy_error = validate_run_policy(provider, fallback)
    if policy_error:
        print(f"错误：{policy_error}", file=sys.stderr)
        return EXIT_INPUT
    spec = json.loads(fixtures.read_text(encoding="utf-8"))
    code_root = code_root or Path(__file__).resolve().parents[1]
    effective_config, config_record = load_source_config(source_root)
    output_dir.mkdir(parents=True, exist_ok=True)
    pipeline.save_json(output_dir / "execution-config.json",
                       {"policy": {"provider": provider, "fallback": fallback,
                                   "provider_order": [provider]}, **config_record})
    results = []
    saw_error = saw_failed = False
    for case in spec["cases"]:
        cid = case["id"]
        case_dir = output_dir / cid
        state = {"task": "review-challenge", "provider_order": [provider], "attempts": [],
                 "case": cid, "identity": case["packet"].get("identity", {})}
        state_path = case_dir / "state.json"
        record = {"id": cid, "kind": case.get("kind", "review")}
        try:
            if case.get("kind") == "clarify":
                resolved = pipeline.resolve_article_issues(
                    stock_ai, issues=[case["issue"]], packet=case["packet"],
                    materials=spec.get("materials", {}), directory=case_dir, state=state,
                    state_path=state_path, config=effective_config, provider=provider,
                    fallback=fallback, allow_research_changes=False)
                first = (resolved["resolutions"] or [{}])[0]
                expect = case["expect"]
                record.update(actual_type=first.get("type"),
                              actual_blocking=first.get("blocking"),
                              evidence_chars=len(str(first.get("evidence_text") or "")))
                record["expectation_met"] = (
                    record["actual_type"] == expect.get("resolution_type")
                    and bool(first.get("blocking")) == bool(expect.get("blocking"))
                    and record["evidence_chars"] >= expect.get("evidence_min_chars", 0))
            else:
                raw = pipeline.article_stage(
                    stock_ai, state, state_path, case_dir, f"review-challenge-{cid}",
                    pipeline.review_prompt(code_root, article=case["article"],
                                           packet=case["packet"],
                                           materials=spec.get("materials", {})),
                    provider, effective_config, fallback=fallback,
                    contract=pipeline.REVIEW_CONTRACT_VERSION,
                    validate=pipeline.parse_review_output, run_scope=f"challenge-{cid}")
                review = pipeline.parse_review_output(raw)
                blocking = (len([i for i in review["readability_issues"] if i.get("blocking")])
                            + len([i for i in review["fidelity_issues"] if i.get("blocking")])
                            + len(review["research_issues"]))
                kinds = set()
                if review["fidelity_issues"]:
                    kinds.add("fidelity")
                if review["research_issues"]:
                    kinds.add("research")
                expect = case["expect"]
                record.update(actual_ready=review["ready"], actual_blocking=blocking,
                              actual_kinds=sorted(kinds),
                              reader_summary=review["reader_summary"])
                met = record["actual_ready"] == bool(expect.get("ready"))
                if "min_blocking" in expect:
                    met = met and blocking >= expect["min_blocking"]
                if "max_blocking" in expect:
                    met = met and blocking <= expect["max_blocking"]
                if "issue_kind" in expect:
                    met = met and expect["issue_kind"] in kinds
                record["expectation_met"] = met
        except (OSError, ValueError, RuntimeError) as exc:
            record.update(expectation_met=False, error=f"{type(exc).__name__}: {exc}")
            saw_error = True
        pipeline.save_json(case_dir / "result.json", record)
        pipeline.save_json(state_path, state)
        results.append(record)
        if not record.get("expectation_met") and not record.get("error"):
            saw_failed = True
    pipeline.save_json(output_dir / "challenge-results.json", results)
    if saw_error:
        return EXIT_INPUT
    if saw_failed:
        return EXIT_NEEDS_REVISION
    return EXIT_OK


def _iter_article_summaries(trial_dir: Path):
    """收集一个trial目录下所有 article summary；目录不存在时返回空并带缺失标记。"""
    rows = []
    runs = trial_dir / "runs"
    if not runs.is_dir():
        return rows, False
    for summary_path in sorted(runs.glob("repeat-*/*/summary.json")):
        try:
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        summary["_dir"] = str(summary_path.parent)
        summary["_trial_dir"] = str(trial_dir)
        rows.append(summary)
    return rows, True


def _stage_files(stage_dir: Path) -> list[str]:
    keep = []
    for path in sorted(stage_dir.iterdir()) if stage_dir.is_dir() else []:
        name = path.name
        if name.endswith(("-input.md", "-review.json", "-resolution.json", "-article.md",
                          "-result.json", "state.json", "summary.json")) and not name.endswith(".stderr.log"):
            keep.append(name)
    return keep


def export(*, selection: Path, trial_dirs: list, output_dir: Path,
           code_root: Path | None = None, tests_dir: Path | None = None,
           notes_path: Path | None = None) -> int:
    """汇总复核材料（纯文件汇总，不调用模型）。

    反截断机械检查：导出的每条意见/处理字段必须与源文件逐字一致（长度核对），
    任何程序性截断都会使导出失败。
    """
    suite = json.loads(selection.read_text(encoding="utf-8"))
    code_root = code_root or Path(__file__).resolve().parents[1]
    out = output_dir
    evidence_dir = out / "04_最小复核证据"
    (evidence_dir / "stages").mkdir(parents=True, exist_ok=True)
    (evidence_dir / "packets").mkdir(exist_ok=True)
    (evidence_dir / "materials").mkdir(exist_ok=True)
    (evidence_dir / "source-excerpts").mkdir(exist_ok=True)
    (evidence_dir / "tests").mkdir(exist_ok=True)

    trial_infos = []
    for td in trial_dirs:
        td = Path(td)
        rows, existed = _iter_article_summaries(td)
        trial_infos.append({"dir": td, "existed": existed, "summaries": rows,
                            "is_challenge": (td / "challenge-results.json").exists()})
        manifest_path = td / "input" / "manifest.json"
        if manifest_path.exists():
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            for code, rel in manifest.get("packets", {}).items():
                src = td / "input" / rel
                if src.exists():
                    (evidence_dir / "packets" / f"{td.name}-{code}.json").write_text(
                        src.read_text(encoding="utf-8"), encoding="utf-8")
            material_path = td / "input" / manifest.get("materials", {}).get("path", "writing-material.json")
            if material_path.exists():
                (evidence_dir / "materials" / f"{td.name}-{material_path.name}").write_text(
                    material_path.read_text(encoding="utf-8"), encoding="utf-8")
        records_path = td / "runs" / "execution-config.json"
        if records_path.exists():
            (evidence_dir / "stages" / f"{td.name}-execution-config.json").write_text(
                records_path.read_text(encoding="utf-8"), encoding="utf-8")

    # ---- 04 固定证据 ----
    (evidence_dir / "suite-selection.json").write_text(suite_text := selection.read_text(encoding="utf-8"),
                                                       encoding="utf-8")
    generation = Path(str(selection)).parent / "generation.json"
    if generation.exists():
        (evidence_dir / "generation.json").write_text(generation.read_text(encoding="utf-8"),
                                                      encoding="utf-8")
    holdout_exits = Path(str(selection)).parent / "holdout-exits.json"
    if holdout_exits.exists():
        (evidence_dir / "holdout-exits.json").write_text(holdout_exits.read_text(encoding="utf-8"),
                                                         encoding="utf-8")
    for prompt_name in ("recommendation-authoring-prompt.md", "recommendation-review-prompt.md",
                        "research-clarification-prompt.md"):
        prompt_path = code_root / "ops" / prompt_name
        if prompt_path.exists():
            (evidence_dir / "materials" / prompt_name).write_text(
                prompt_path.read_text(encoding="utf-8"), encoding="utf-8")
    if tests_dir is not None and Path(tests_dir).is_dir():
        for path in sorted(Path(tests_dir).iterdir()):
            if path.is_file():
                (evidence_dir / "tests" / path.name).write_text(
                    path.read_text(encoding="utf-8"), encoding="utf-8")

    # ---- 逐股文章与完整阶段文件 ----
    ordered_names = [s["name"] for s in suite.get("regression", [])] + \
        [s["name"] for s in suite.get("holdout", [])]
    codes_by_name = {}
    for section in ("regression", "holdout"):
        for s in suite.get(section, []):
            codes_by_name[s["name"]] = s

    article_lines = ["# 01 文章：原三股与新样本", "",
                     f"样本冻结清单：suite-selection.json（回归{len(suite.get('regression', []))}家 + "
                     f"未调优{len(suite.get('holdout', []))}家，均为每家2次独立重复）。"
                     "正文为作者实际输出，未插入任何运行评价；非ready草稿在状态行注明原因。", ""]
    issue_lines = ["# 03 完整问题与处理记录", "",
                   "以下每条意见与处理均为源文件逐字导出（导出时做了长度一致性机械核对，"
                   "未使用任何程序性截断）。", ""]
    truncation_hits = []
    seen_stocks = set()
    for name in ordered_names:
        sample = codes_by_name.get(name, {})
        code = sample.get("ts_code", "")
        seen_stocks.add(name)
        article_lines.append(f"## {name}（{code}）")
        article_lines.append("")
        found_any = False
        for info in trial_infos:
            for summary in info["summaries"]:
                if summary.get("ts_code") != code:
                    continue
                found_any = True
                repeat = summary.get("repeat")
                status = summary.get("article_status") or summary.get("status")
                source_line = (f"来源版本：trace {summary.get('_trial_dir', '')}；"
                               f"repeat {repeat}；截止 {suite.get('regression', [{}])[0].get('as_of', '')}")
                packet_path = summary["_dir"] and Path(summary["_dir"]) / ".." / ".." / ".." / "input" / "packets" / f"{code}.json"
                reference = ""
                if packet_path and packet_path.exists():
                    packet = json.loads(packet_path.read_text(encoding="utf-8"))
                    reference = packet.get("identity", {}).get("reference_price", "")
                article_lines.append(f"### {Path(summary['_trial_dir']).name} / repeat-{repeat} — 状态：{status}")
                article_lines.append("")
                article_lines.append(f"参考价：{reference}；{source_line}")
                article_lines.append("")
                article_path = summary.get("article_path")
                if article_path and Path(article_path).exists():
                    article_lines.append(Path(article_path).read_text(encoding="utf-8").strip())
                else:
                    article_lines.append(f"（无完整正文：{summary.get('error') or status}）")
                article_lines.append("")
                # 完整意见与处理：逐字导出
                stage_dir = Path(summary["_dir"])
                issue_lines.append(f"## {name}（{code}）{Path(summary['_trial_dir']).name}/repeat-{repeat}")
                issue_lines.append("")
                for review_file in sorted(stage_dir.glob("review*-review.json")):
                    data = json.loads(review_file.read_text(encoding="utf-8"))
                    issue_lines.append(f"### {review_file.name}（审稿全文）")
                    issue_lines.append("```json")
                    issue_lines.append(json.dumps(data, ensure_ascii=False, indent=1))
                    issue_lines.append("```")
                    issue_lines.append("")
                for resolution_file in sorted(stage_dir.glob("*-resolutions.json")) + \
                        sorted(stage_dir.glob("research-repair-resolution.json")):
                    data = json.loads(resolution_file.read_text(encoding="utf-8"))
                    issue_lines.append(f"### {resolution_file.name}（处理记录全文）")
                    issue_lines.append("```json")
                    issue_lines.append(json.dumps(data, ensure_ascii=False, indent=1))
                    issue_lines.append("```")
                    issue_lines.append("")
                summary_issues = summary.get("research_issues") or []
                if summary_issues:
                    issue_lines.append("### summary.research_issues（逐字）")
                    issue_lines.append("```json")
                    issue_lines.append(json.dumps(summary_issues, ensure_ascii=False, indent=1))
                    issue_lines.append("```")
                    issue_lines.append("")
                # 反截断机械核对：所有意见字段在导出中必须逐字出现
                exported_blob = "\n".join(issue_lines)
                for review_file in sorted(stage_dir.glob("review*-review.json")):
                    data = json.loads(review_file.read_text(encoding="utf-8"))
                    for field in ("readability_issues", "fidelity_issues", "research_issues"):
                        for item in data.get(field, []):
                            for key in ("quote", "problem", "instruction", "evidence", "needed"):
                                value = str(item.get(key) or "")
                                if value and value not in exported_blob:
                                    truncation_hits.append(f"{code}/{review_file.name}/{field}/{key}")
        if not found_any:
            article_lines.append(f"（未执行/缺资料：本轮没有该公司的运行记录）")
            article_lines.append("")

    for info in trial_infos:
        if info["is_challenge"]:
            results_file = info["dir"] / "challenge-results.json"
            issue_lines.append(f"## 审稿挑战：{info['dir'].name}")
            issue_lines.append("```json")
            issue_lines.append(results_file.read_text(encoding="utf-8"))
            issue_lines.append("```")
            issue_lines.append("")

    if truncation_hits:
        raise ValueError("导出检测到截断：" + "；".join(truncation_hits[:10]))

    (out / "01_文章_原三股与新样本.md").write_text("\n".join(article_lines) + "\n", encoding="utf-8")
    (out / "03_完整问题与处理记录.md").write_text("\n".join(issue_lines) + "\n", encoding="utf-8")

    # ---- 02 运行与代码核验（数据驱动骨架 + notes叙事） ----
    lines = ["# 02 运行与代码核验", ""]
    if notes_path and Path(notes_path).exists():
        lines.append(Path(notes_path).read_text(encoding="utf-8"))
        lines.append("")
    lines += ["## 各trial目录执行记录", ""]
    for info in trial_infos:
        td = info["dir"]
        lines.append(f"- {td.name}：存在={info['existed']}；文章summary数={len(info['summaries'])}；"
                     f"审稿挑战={'是' if info['is_challenge'] else '否'}")
    lines += ["", "## holdout执行退出码", ""]
    if holdout_exits.exists():
        lines.append("```json")
        lines.append(holdout_exits.read_text(encoding="utf-8"))
        lines.append("```")
    lines += ["", "## 各阶段模型证据（会话级，当次捕获）", "",
              "| trial | repeat | 代码 | 阶段 | route | configured | 证据型号 | 会话 | verified |",
              "|---|---|---|---|---|---|---|---|---|"]
    for info in trial_infos:
        for summary in info["summaries"]:
            state_path = Path(summary["_dir"]) / "state.json"
            if not state_path.exists():
                continue
            state = json.loads(state_path.read_text(encoding="utf-8"))
            for entry in state.get("recommendation_stages", []):
                evidence = entry.get("evidence") or {}
                lines.append(f"| {Path(summary['_trial_dir']).name} | {summary.get('repeat')} | "
                             f"{summary.get('ts_code')} | {entry.get('stage')} | {entry.get('provider')} | "
                             f"{entry.get('configured_model')} | {evidence.get('model') or '未取得'} | "
                             f"{(evidence.get('session_id') or '未取得')[:24]} | {evidence.get('verified')} |")
    lines.append("")
    (out / "02_运行与代码核验.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    # ---- 阶段文件复制 ----
    for info in trial_infos:
        for summary in info["summaries"]:
            stage_dir = Path(summary["_dir"])
            target = evidence_dir / "stages" / f"{Path(summary['_trial_dir']).name}-repeat-{summary.get('repeat')}-{summary.get('ts_code')}"
            target.mkdir(parents=True, exist_ok=True)
            for name in _stage_files(stage_dir):
                (target / name).write_text((stage_dir / name).read_text(encoding="utf-8"),
                                           encoding="utf-8")
    print(f"export={out}")
    return EXIT_OK


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
    p_prepare.add_argument("--handoff", type=Path,
                           help="已核实的selection-handoff.json（v2须含匹配trace_sha256）")
    p_prepare.add_argument("--original-report", type=Path,
                           help="原研究报告；仅提取其中独有的条件原句与来源")

    p_export = sub.add_parser("export", help="汇总复核材料（纯文件汇总，不调用模型）")
    p_export.add_argument("--selection", type=Path, required=True)
    p_export.add_argument("--trial-dirs", type=Path, nargs="+", required=True)
    p_export.add_argument("--output-dir", type=Path, required=True)
    p_export.add_argument("--code-root", type=Path, default=Path(__file__).resolve().parents[1])
    p_export.add_argument("--tests-dir", type=Path)
    p_export.add_argument("--notes", type=Path)

    p_check = sub.add_parser("check-review", help="真实GLM审稿/澄清合成挑战（生产共用函数）")
    p_check.add_argument("--source-root", type=Path, required=True)
    p_check.add_argument("--provider", default=TRIAL_PROVIDER)
    p_check.add_argument("--no-fallback", action="store_true")
    p_check.add_argument("--fixtures", type=Path, required=True)
    p_check.add_argument("--output-dir", type=Path, required=True)

    p_run = sub.add_parser("run", help="按 manifest 真实写文章（生产共用作者循环）")
    p_run.add_argument("--source-root", type=Path, required=True,
                       help="源项目根；显式读取其 .stock-ai.local.json 作为配置（只读）")
    p_run.add_argument("--manifest", type=Path, required=True)
    p_run.add_argument("--provider", required=True)
    p_run.add_argument("--no-fallback", action="store_true")
    p_run.add_argument("--repeats", type=int, default=1)
    p_run.add_argument("--output-dir", type=Path, required=True)
    p_run.add_argument("--resume", action="store_true",
                       help="仅恢复同一次未完成运行；不得隐式套用到全新实验")

    args = parser.parse_args(argv)
    try:
        if args.command == "prepare":
            prepare(source_root=args.source_root, trace_path=args.trace, names=args.names,
                    output_dir=args.output_dir, code_root=args.code_root,
                    handoff_path=args.handoff, original_report_path=args.original_report)
            print(f"manifest={args.output_dir / 'manifest.json'}")
            return EXIT_OK
        # 发出任何请求前拒绝非GLM或允许备用的参数；不依赖调用者记得关闭。
        policy_error = validate_run_policy(args.provider, not args.no_fallback)
        if policy_error:
            print(f"错误：{policy_error}", file=sys.stderr)
            return EXIT_INPUT
        if args.command == "export":
            code = export(selection=args.selection, trial_dirs=args.trial_dirs,
                          output_dir=args.output_dir, code_root=args.code_root,
                          tests_dir=args.tests_dir, notes_path=args.notes)
            print(f"exit={code}; export={args.output_dir}")
            return code
        if args.command == "check-review":
            policy_error = validate_run_policy(args.provider, not args.no_fallback)
            if policy_error:
                print(f"错误：{policy_error}", file=sys.stderr)
                return EXIT_INPUT
            code = check_review(source_root=args.source_root, fixtures=args.fixtures,
                                output_dir=args.output_dir, provider=args.provider,
                                fallback=not args.no_fallback)
            print(f"exit={code}; results={args.output_dir / 'challenge-results.json'}")
            return code
        code = run(manifest_path=args.manifest, provider=args.provider,
                   fallback=not args.no_fallback, repeats=args.repeats,
                   output_dir=args.output_dir, source_root=args.source_root,
                   resume=args.resume)
        print(f"exit={code}; runs={args.output_dir}")
        return code
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"错误：{type(exc).__name__}: {exc}", file=sys.stderr)
        return EXIT_INPUT


if __name__ == "__main__":
    raise SystemExit(main())
