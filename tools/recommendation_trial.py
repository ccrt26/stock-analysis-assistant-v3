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
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import nightly_report
import recommendation_pipeline as pipeline
import stock_ai
import recommendation_file_io as file_io

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


def _load_resumable_state(state_path: Path, *, manifest: dict, manifest_digest: str, code: str,
                          provider: str, fallback: bool, repeats: int, repeat: int):
    """--resume 恢复同一次运行的原state；身份/输入/策略不符即明确拒绝，不静默混版。"""
    if not state_path.exists():
        return None, None  # 崩溃发生在首次保存前：按新运行处理
    try:
        saved = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return None, f"{state_path} 读取失败（{type(exc).__name__}），拒绝冒充同一次恢复"
    if not isinstance(saved, dict):
        return None, f"{state_path} 不是JSON对象，拒绝恢复"
    expected_policy = {"provider": provider, "fallback": fallback, "provider_order": [provider]}
    checks = (("股票", saved.get("ts_code") == code),
              ("时间身份", saved.get("identity") == manifest["identity"]),
              ("模型策略", saved.get("policy") == expected_policy),
              ("输入身份", saved.get("input_manifest_sha256") == manifest_digest),
              ("重复次数", saved.get("repeats") == repeats and saved.get("repeat") == repeat))
    bad = [name for name, ok in checks if not ok]
    if bad:
        return None, (f"{state_path} 与本次恢复不一致（{'、'.join(bad)}），"
                      "拒绝冒充同一次恢复；如需全新运行请另用输出目录")
    return saved, None


def run(*, manifest_path: Path, provider: str, fallback: bool, repeats: int,
        output_dir: Path, source_root: Path | None = None,
        resume: bool = False) -> int:
    """对固定输入逐股×重复次数调用生产 run_article_cycle；返回约定退出码。

    article_status 与 execution_verified 分开记录：业务ready但证据未核验的稿
    保留给阅读，整体不能按0退出。0 要求全部预期样本有结果行、全部ready且核验通过。
    --resume 只恢复同一次未完成运行：读取原state（含已用预算与调用历史），
    核对股票/身份/输入/策略一致后继续；不匹配即拒绝，不得新建state覆盖历史。
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
    manifest_digest = _sha256(manifest_path)
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
            state_path = stock_dir / "state.json"
            state = None
            if resume:
                state, reject = _load_resumable_state(
                    state_path, manifest=manifest, manifest_digest=manifest_digest, code=code,
                    provider=provider, fallback=fallback, repeats=repeats, repeat=repeat)
                if reject:
                    print(f"错误：{reject}", file=sys.stderr)
                    return EXIT_INPUT
            if state is None:
                state = {"task": "recommendation-trial", "provider_order": [provider],
                         "attempts": [], "repeat": repeat, "ts_code": code,
                         "identity": manifest["identity"],
                         "policy": {"provider": provider, "fallback": fallback,
                                    "provider_order": [provider]},
                         "input_manifest_sha256": manifest_digest, "repeats": repeats}
            summary = {"repeat": repeat, "ts_code": code, "name": stock["name"],
                       "config_status": config_record.get("status"),
                       "resumed_state": resume and state_path.exists()}
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
            elif case.get("kind") == "full_chain":
                record.update(**_full_chain_case(
                    case=case, cid=cid, case_dir=case_dir, state=state, state_path=state_path,
                    spec=spec, code_root=code_root, effective_config=effective_config,
                    provider=provider, fallback=fallback))
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


def _full_chain_case(*, case: dict, cid: str, case_dir: Path, state: dict, state_path: Path,
                     spec: dict, code_root: Path, effective_config: dict, provider: str,
                     fallback: bool) -> dict:
    """C4全链（V1.2 A4/S5.2）：审稿初稿→澄清→有效包→作者修改→复审，全程生产共用函数。

    期望只在包装层比对：初稿不ready、处理非阻塞、初始包逐字未改、修订文数字归属
    正确、复审ready且误报未再出现。
    """
    import copy as _copy

    def stage(stage_name, prompt, contract, validate):
        raw = pipeline.article_stage(
            stock_ai, state, state_path, case_dir, stage_name, prompt, provider,
            effective_config, fallback=fallback, contract=contract, validate=validate,
            run_scope=f"chain-{cid}")
        return pipeline.parse_author_output(raw) if contract == pipeline.AUTHOR_CONTRACT_VERSION \
            else raw

    expect = case["expect"]
    packet_before = _copy.deepcopy(case["packet"])
    materials = spec.get("materials", {})
    # 步1：审稿初稿（稿件问题必须被发现）
    first_raw = stage(f"review-chain-{cid}-draft",
                      pipeline.review_prompt(code_root, article=case["article"],
                                             packet=case["packet"], materials=materials),
                      pipeline.REVIEW_CONTRACT_VERSION, pipeline.parse_review_output)
    first_review = pipeline.parse_review_output(first_raw)
    first_blocking = (len([i for i in first_review["readability_issues"] if i.get("blocking")])
                      + len([i for i in first_review["fidelity_issues"] if i.get("blocking")])
                      + len(first_review["research_issues"]))
    # 步2：澄清稿件问题（澄清会话可带只读取证工具）
    resolved = pipeline.resolve_article_issues(
        stock_ai, issues=[case["issue"]], packet=case["packet"], materials=materials,
        directory=case_dir, state=state, state_path=state_path, config=effective_config,
        provider=provider, fallback=fallback, allow_research_changes=False)
    first_resolution = (resolved["resolutions"] or [{}])[0]
    # 步3：有效包（初始包必须逐字未改）
    effective = pipeline.build_effective_packet(
        case["packet"], [r for r in resolved["resolutions"] if not r.get("blocking")])
    initial_unchanged = packet_before == case["packet"]
    pipeline.save_json(case_dir / "packet-initial.json", packet_before)
    pipeline.save_json(case_dir / "packet-effective.json", effective)
    pipeline.save_json(case_dir / "issue-resolutions.json", resolved["resolutions"])
    # 步4：作者按同一有效材料与处理结论修改
    revision_issues = [i for i in first_review["readability_issues"] + first_review["fidelity_issues"]
                       if i.get("blocking")]
    author_raw = stage(f"author-chain-{cid}",
                       pipeline.author_prompt(code_root, packet=effective, materials=materials,
                                              prior_article=case["article"],
                                              revision_issues=revision_issues,
                                              issue_resolutions=resolved["resolutions"]),
                       pipeline.AUTHOR_CONTRACT_VERSION, pipeline.parse_author_output)
    revised = author_raw["article"]
    (case_dir / "revised-article.md").write_text(revised + "\n", encoding="utf-8")
    # 步5：复审（面对同一有效包与处理结论）
    final_raw = stage(f"review-chain-{cid}-final",
                      pipeline.review_prompt(code_root, article=revised, packet=effective,
                                             materials=materials,
                                             issue_resolutions=resolved["resolutions"]),
                      pipeline.REVIEW_CONTRACT_VERSION, pipeline.parse_review_output)
    final_review = pipeline.parse_review_output(final_raw)

    def pairs_ok(text: str, pairs, should_exist: bool) -> bool:
        # 同一子句内核对归属（不跨逗号/句号），避免跨子句误配。
        for name, number in pairs:
            found = bool(__import__("re").search(
                __import__("re").escape(str(name)) + r"[^。，；]{0,40}" + __import__("re").escape(str(number)), text))
            if found != should_exist:
                return False
        return True

    record = {
        "draft_ready": first_review["ready"],
        "draft_blocking": first_blocking,
        "actual_type": first_resolution.get("type"),
        "actual_resolution_blocking": bool(first_resolution.get("blocking")),
        "initial_packet_unchanged": initial_unchanged,
        "final_ready": final_review["ready"],
        "final_blocking": (len([i for i in final_review["readability_issues"] if i.get("blocking")])
                           + len([i for i in final_review["fidelity_issues"] if i.get("blocking")])
                           + len(final_review["research_issues"])),
    }
    met = (record["draft_ready"] == bool(expect.get("draft_ready"))
           and record["draft_blocking"] >= int(expect.get("draft_min_blocking", 0))
           and record["actual_type"] == expect.get("resolution_type")
           and record["actual_resolution_blocking"] == bool(expect.get("resolution_blocking"))
           and record["initial_packet_unchanged"]
           and record["final_ready"] == bool(expect.get("final_ready"))
           and record["final_blocking"] <= int(expect.get("final_max_blocking", 0))
           and pairs_ok(revised, expect.get("must_pair", []), True)
           and pairs_ok(revised, expect.get("must_not_pair", []), False))
    record["expectation_met"] = met
    return record


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
    fixed = ("packet-initial.json", "packet-effective.json", "issue-resolutions.json",
             "issues-open.json", "state.json", "summary.json")
    for path in sorted(stage_dir.iterdir()) if stage_dir.is_dir() else []:
        name = path.name
        if name in fixed or name.endswith(("-input.md", "-review.json", "-resolution.json",
                                           "-resolutions.json", "-article.md", "-result.json")) \
                and not name.endswith(".stderr.log"):
            keep.append(name)
    return keep


def export(*, selection: Path, trial_dirs: list, output_dir: Path,
           code_root: Path | None = None, tests_dir: Path | None = None,
           notes_path: Path | None = None, expected_samples_path: Path | None = None,
           commands_path: Path | None = None, production_reports: list | None = None,
           run_root: Path | None = None) -> int:
    """汇总复核材料（纯文件汇总，不调用模型）：GLM_V12_复核包结构（V1.2 A4/S5.4）。

    各阶段实际输入、原始模型回复、解析结果、review/issue_checks、resolution、
    initial/effective packet、state与执行证据全部带出；字段缺失如实标缺失。
    反截断机械检查：导出的每条意见/处理字段必须与源文件逐字一致（回读结构相等），
    任何程序性截断都会使导出失败。审稿挑战目录按挑战结构读取（无runs/summary）。
    """
    suite = json.loads(selection.read_text(encoding="utf-8"))
    code_root = code_root or Path(__file__).resolve().parents[1]
    out = output_dir
    evidence_dir = out / "evidence"
    samples_dir = evidence_dir / "samples"
    (samples_dir).mkdir(parents=True, exist_ok=True)
    (evidence_dir / "materials").mkdir(exist_ok=True)
    (evidence_dir / "source-excerpts").mkdir(exist_ok=True)
    (evidence_dir / "tests").mkdir(exist_ok=True)
    for optional in (("expected_samples.json", expected_samples_path),
                     ("commands.jsonl", commands_path)):
        name, source = optional
        if source is not None and Path(source).exists():
            (evidence_dir / name).write_text(Path(source).read_text(encoding="utf-8"),
                                             encoding="utf-8")
    for source in production_reports or []:
        source = Path(source)
        if source.exists():
            (evidence_dir / source.name).write_text(source.read_text(encoding="utf-8"),
                                                    encoding="utf-8")

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
                    (samples_dir / f"{td.name}-{code}-initial-packet.json").write_text(
                        src.read_text(encoding="utf-8"), encoding="utf-8")
            material_path = td / "input" / manifest.get("materials", {}).get("path", "writing-material.json")
            if material_path.exists():
                (evidence_dir / "materials" / f"{td.name}-{material_path.name}").write_text(
                    material_path.read_text(encoding="utf-8"), encoding="utf-8")
            excerpt_dir = td / "input" / "original-report-conditions.json"
            if excerpt_dir.exists():
                (evidence_dir / "source-excerpts" / f"{td.name}-{excerpt_dir.name}").write_text(
                    excerpt_dir.read_text(encoding="utf-8"), encoding="utf-8")
        records_path = td / "runs" / "execution-config.json"
        if records_path.exists():
            (evidence_dir / "materials" / f"{td.name}-execution-config.json").write_text(
                records_path.read_text(encoding="utf-8"), encoding="utf-8")

    # ---- 固定证据 ----
    (evidence_dir / "suite-selection.json").write_text(selection.read_text(encoding="utf-8"),
                                                       encoding="utf-8")
    generation = Path(str(selection)).parent / "generation.json"
    if generation.exists():
        (evidence_dir / "generation.json").write_text(generation.read_text(encoding="utf-8"),
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

    # ---- 逐股正文与状态：按 expected_samples（或缺省全部summary）列全，不挑最好 ----
    suite_codes = {}
    for section in ("regression", "holdout"):
        for s in suite.get(section, []):
            suite_codes[s["name"]] = s
    expected_rows = []
    if expected_samples_path is not None and Path(expected_samples_path).exists():
        expected_payload = json.loads(Path(expected_samples_path).read_text(encoding="utf-8"))
        if isinstance(expected_payload, dict):
            expected_payload = expected_payload.get("samples") or []
        expected_rows = expected_payload if isinstance(expected_payload, list) else []

    article_lines = ["# 01 六个样本正文与状态", "",
                     "正文为作者实际输出，未插入任何运行评价；失败样本同时给出最后成功写出"
                     "的草稿（注明未采用）与全部失败原响应；字段缺失如实标注。", ""]
    issue_lines = ["# 03 完整问题与处理记录", "",
                   "以下每条意见、审稿issue_checks与处理均为源文件逐字导出"
                   "（写入后做回读结构相等核对，未使用任何程序性截断）。", ""]
    truncation_hits = []
    exported_pairs = set()

    def sample_blocks(summary):
        """单个样本的正文块与逐字问题记录块。"""
        nonlocal truncation_hits
        repeat = summary.get("repeat")
        code = summary.get("ts_code")
        status = summary.get("article_status") or summary.get("status")
        stage_dir = Path(summary["_dir"])
        trial_name = Path(summary["_trial_dir"]).name
        blocks = [f"### {trial_name} / repeat-{repeat} — 状态：{status}"]
        state_path = stage_dir / "state.json"
        if state_path.exists():
            try:
                failed_stages = [e.get("stage") for e in
                                 json.loads(state_path.read_text(encoding="utf-8"))
                                 .get("recommendation_stages", [])
                                 if e.get("status") in ("failed", "model_mismatch")]
                if failed_stages:
                    blocks[0] += f"（含历史失败尝试 {sorted(set(failed_stages))}，原文见FAILED-*与state.json；按原state恢复）"
            except (OSError, ValueError, json.JSONDecodeError):
                pass
        blocks.append("")
        article_path = summary.get("article_path")
        if article_path and Path(article_path).exists():
            blocks.append(Path(article_path).read_text(encoding="utf-8").strip())
        else:
            blocks.append(f"（无采用正文：{summary.get('error') or status}；"
                          f"最后草稿见 evidence/samples/{trial_name}-repeat-{repeat}-{code}/）")
        blocks.append("")
        roundtrip = []
        issue_blocks = [f"## {summary.get('name')}（{code}）{trial_name}/repeat-{repeat}", ""]
        for review_file in sorted(stage_dir.glob("review*-review.json")):
            data = json.loads(review_file.read_text(encoding="utf-8"))
            issue_blocks.append(f"### {review_file.name}（审稿全文，含issue_checks）")
            issue_blocks.append("```json")
            block = json.dumps(data, ensure_ascii=False, indent=1)
            issue_blocks.append(block)
            issue_blocks.append("```")
            issue_blocks.append("")
            roundtrip.append((data, block))
        for resolution_file in (sorted(stage_dir.glob("*-resolutions.json"))
                                + sorted(stage_dir.glob("*-resolution.json"))):
            if resolution_file.name.endswith("-result.json"):
                continue
            data = json.loads(resolution_file.read_text(encoding="utf-8"))
            issue_blocks.append(f"### {resolution_file.name}（处理记录全文）")
            issue_blocks.append("```json")
            block = json.dumps(data, ensure_ascii=False, indent=1)
            issue_blocks.append(block)
            issue_blocks.append("```")
            issue_blocks.append("")
            roundtrip.append((data, block))
        summary_issues = summary.get("research_issues") or []
        if summary_issues:
            issue_blocks.append("### summary.research_issues（逐字）")
            issue_blocks.append("```json")
            block = json.dumps(summary_issues, ensure_ascii=False, indent=1)
            issue_blocks.append(block)
            issue_blocks.append("```")
            issue_blocks.append("")
            roundtrip.append((summary_issues, block))
        for source_data, block in roundtrip:
            try:
                if json.loads(block) != source_data:
                    truncation_hits.append(f"{code}: 回读不等于源数据")
            except json.JSONDecodeError:
                truncation_hits.append(f"{code}: 导出块损坏")
        return blocks, issue_blocks

    for row in expected_rows or []:
        name = row.get("name") or ""
        code = row.get("ts_code") or ""
        article_lines.append(f"## {name}（{code}）")
        article_lines.append("")
        found_any = False
        for info in trial_infos:
            for summary in info["summaries"]:
                if summary.get("ts_code") != code or summary.get("repeat") != row.get("repeat"):
                    continue
                found_any = True
                exported_pairs.add((code, summary.get("repeat")))
                blocks, issue_blocks = sample_blocks(summary)
                article_lines.extend(blocks)
                issue_lines.extend(issue_blocks)
        if not found_any:
            article_lines.append(f"（未执行/缺记录：expected_samples 声明但未找到对应summary）")
            article_lines.append("")
    for info in trial_infos:
        for summary in info["summaries"]:
            key = (summary.get("ts_code"), summary.get("repeat"))
            if key in exported_pairs or expected_rows:
                continue
            blocks, issue_blocks = sample_blocks(summary)
            article_lines.append(f"## {summary.get('name')}（{summary.get('ts_code')}）")
            article_lines.append("")
            article_lines.extend(blocks)
            issue_lines.extend(issue_blocks)

    # 审稿挑战目录按挑战结构读取：无runs/summary，逐case导出全部产物。
    for info in trial_infos:
        if not info["is_challenge"]:
            continue
        td = info["dir"]
        results_file = td / "challenge-results.json"
        issue_lines.append(f"## 审稿挑战：{td.name}")
        issue_lines.append("```json")
        issue_lines.append(results_file.read_text(encoding="utf-8"))
        issue_lines.append("```")
        issue_lines.append("")
        for case_dir in sorted(p for p in td.iterdir() if p.is_dir()):
            target = samples_dir / f"challenge-{td.name}-{case_dir.name}"
            target.mkdir(parents=True, exist_ok=True)
            for path in sorted(case_dir.iterdir()):
                if path.is_file():
                    (target / path.name).write_text(path.read_text(encoding="utf-8"),
                                                    encoding="utf-8")

    if truncation_hits:
        raise ValueError("导出检测到截断：" + "；".join(truncation_hits[:10]))

    # ---- 阶段文件复制（含state与执行证据、initial/effective packet） ----
    for info in trial_infos:
        for summary in info["summaries"]:
            stage_dir = Path(summary["_dir"])
            trial_name = Path(summary["_trial_dir"]).name
            target = samples_dir / f"{trial_name}-repeat-{summary.get('repeat')}-{summary.get('ts_code')}"
            target.mkdir(parents=True, exist_ok=True)
            for name in _stage_files(stage_dir):
                (target / name).write_text((stage_dir / name).read_text(encoding="utf-8"),
                                           encoding="utf-8")
            # 失败原响应：与result.raw不一致的原始模型输出（校验失败/被重试的尝试，
            # 其原文只存在于transport输出文件，不在任何result内）。
            for raw in sorted(stage_dir.glob("*-glm.md")):
                stage_stem = raw.name[:-len("-glm.md")]
                base_stage = re.sub(r"-retry-\d+$", "", stage_stem)
                result_path = stage_dir / f"{base_stage}-result.json"
                if not result_path.exists():
                    continue
                try:
                    consumed_raw = json.loads(result_path.read_text(encoding="utf-8")).get("raw")
                except (OSError, ValueError):
                    continue
                if raw.read_text(encoding="utf-8") == consumed_raw:
                    continue  # 被消费的当次原文已在result内
                failure_note = {"file": raw.name, "base_stage": base_stage,
                                "note": "失败原响应（该尝试未通过校验未被消费；消费的是后续重试）"}
                (target / f"FAILED-{raw.name}").write_text(
                    json.dumps(failure_note, ensure_ascii=False) + "\n\n"
                    + raw.read_text(encoding="utf-8"), encoding="utf-8")

    (out / "01_六个样本正文与状态.md").write_text("\n".join(article_lines) + "\n", encoding="utf-8")
    (out / "03_完整问题与处理记录.md").write_text("\n".join(issue_lines) + "\n", encoding="utf-8")
    if run_root is not None:
        daily = Path(run_root) / "00_日常运行与责任核对.md"
        if daily.exists():
            (out / "00_日常运行与责任核对.md").write_text(daily.read_text(encoding="utf-8"),
                                                          encoding="utf-8")
    lines = ["# 02 逐项验收结果", ""]
    if notes_path and Path(notes_path).exists():
        lines.append(Path(notes_path).read_text(encoding="utf-8"))
        lines.append("")
    else:
        lines.append("（未提供逐项验收说明；见evidence/下的原始证据。）")
    (out / "02_逐项验收结果.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"export={out}")
    return EXIT_OK


def replay_files(*, source_root: Path, packet_path: Path, source_manifest: Path, guide: Path,
                 examples: list[Path], output_dir: Path, provider: str, fallback: bool,
                 repeats: int, resume: bool = False) -> int:
    """Frozen historical input -> real handoff-only -> shared article lifecycle."""
    if provider != 'astra' or fallback or repeats != 1:
        raise ValueError('replay-files 只允许 astra、--no-fallback、--repeats 1')
    code_root = Path(__file__).resolve().parents[1]
    if guide.read_bytes() != (code_root / file_io.GUIDE).read_bytes():
        raise ValueError('传入指南与候选唯一简明指南不一致')
    packet = pipeline.read_json(packet_path)
    source = pipeline.read_json(source_manifest)
    ident = packet['identity']
    if any(ident.get(k) != v for k, v in source['identity'].items()):
        raise ValueError('原研究包与来源 manifest 日期身份不一致')
    if source.get('stocks') != [{'name': ident['name'], 'ts_code': ident['ts_code']}]:
        raise ValueError('只接受来源 manifest 指定的唯一股票')
    if packet.get('authoring_note'):
        raise ValueError('历史回放输入不得含旧 authoring_note')
    packet_digest = _sha256(packet_path)
    original_digest = (source.get('v14_baseline_binding') or {}).get('copied_packet_sha256')
    if original_digest and original_digest != packet_digest:
        raise ValueError('实际原研究包字节与来源 manifest 指纹不符')
    material = pipeline.writing_material(source_root, ident['as_of'], [ident['ts_code']],
        teaching_root=code_root, profile=file_io.PROFILE, example_paths=examples)
    if len(material['examples']) != len(examples) or material['gaps']:
        raise ValueError('回放范文不满足已认可、原截止、排除本股及最多两篇条件')
    config_path = source_root / '.stock-ai.local.json'
    config = pipeline.read_json(config_path) if config_path.exists() else {}
    config['recommendation_authoring_profile'] = file_io.PROFILE
    config['_resume_files'] = resume
    inputs = [{'path': str(p.resolve()), 'sha256': _sha256(p), 'bytes': p.stat().st_size}
              for p in [packet_path, source_manifest, guide, *examples]]
    policy = {'provider': 'astra', 'model': file_io.MODEL, 'effort': file_io.EFFORT,
              'fallback': False, 'profile': file_io.PROFILE, 'repeats': 1,
              'expression_limit': 1, 'clarification_limit': 1}
    manifest = {'identity': ident, 'inputs': inputs, 'policy': policy,
                'generation_commit': _code_commit(code_root), 'contracts': file_io.CONTRACTS,
                'config_source': str(config_path.resolve()),
                'binding': {'kind': 'original_packet', 'packet_sha256': packet_digest,
                            'packet_content_sha256': file_io.digest(file_io.dumps(packet)),
                            'identity': ident, 'source': str(packet_path.resolve())},
                'trace_binding': '未读取核验完整 trace；仅绑定实际 packet，原 manifest trace 字段是历史元数据'}
    output_dir = output_dir.resolve()
    state_path = output_dir / 'state.json'
    manifest_path = output_dir / 'manifest.json'
    if output_dir.exists():
        if not resume:
            raise ValueError('输出目录已存在；禁止覆盖或隐式新抽样')
        if not manifest_path.exists() or pipeline.read_json(manifest_path) != manifest:
            raise ValueError('恢复输入、来源、源码版本或执行配置改变')
        state = pipeline.read_json(state_path)
        if state.get('terminal_status'):
            raise ValueError('此运行已终态；不能使用 --resume 重采样')
    else:
        if resume:
            raise ValueError('恢复目录不存在，不能新建一次冒充恢复')
        output_dir.mkdir(parents=True)
        pipeline.save_json(manifest_path, manifest)
        state = {'provider_order': ['astra'], 'unavailable_providers': {}, 'attempts': [],
                 'policy': policy, 'generation_commit': manifest['generation_commit']}
        stock_ai.save_state(state_path, state)
        snap = output_dir / 'input'
        snap.mkdir()
        for index, path in enumerate([packet_path, source_manifest, guide, *examples]):
            (snap / f'{index:02d}-{path.name}').write_bytes(path.read_bytes())
        pipeline.save_json(output_dir / 'writing-material.json', material)
    summary = {'status': 'running', 'adopted': False, 'policy': policy,
               'generation_commit': manifest['generation_commit'], 'article': None,
               'quality': '待用户与 ChatGPT 复核；程序 ready 不代表文章已认可'}
    try:
        bound_packet, issues = pipeline.generate_file_handoff(stock_ai, packet=packet,
            materials=material, source_binding=manifest['binding'], directory=output_dir / 'handoff',
            state=state, state_path=state_path, config=config)
        resolved = {'resolutions': [], 'blocking': []}
        if issues:
            # A research issue is not itself a decision that research must change.
            # Use the existing resolver; never infer severity from prose keywords.
            resolved = pipeline.resolve_article_issues(stock_ai, issues=issues, packet=bound_packet,
                materials=material, directory=output_dir / 'article', state=state, state_path=state_path,
                config=config, provider='astra', fallback=False, allow_research_changes=False,
                clarification_limit=1, run_scope='replay-files')
            pipeline.save_json(output_dir / 'handoff-issue-resolutions.json', resolved)
        if resolved['blocking']:
            summary.update(status='needs_research', research_issues=issues,
                           issue_resolutions=resolved['resolutions'])
        else:
            summary.update(pipeline.run_article_cycle(stock_ai, packet=bound_packet, materials=material,
                directory=output_dir / 'article', state=state, state_path=state_path, config=config,
                provider='astra', fallback=False, allow_research_changes=False, expression_limit=1,
                clarification_limit=1, run_scope='replay-files', prior_resolutions=resolved['resolutions']))
            # Adoption refers to this candidate flow only, never formal/user acceptance.
            summary['flow_ready'] = summary.pop('adopted', False)
            summary['adopted'] = False
    except Exception as exc:
        summary.update(status='failed', error=f'{type(exc).__name__}: {exc}')
        stages = list(output_dir.glob('**/*-result.json'))
        if any(pipeline.read_json(p).get('terminal_status') == 'execution_unverified' for p in stages):
            summary['status'] = 'execution_unverified'
    except BaseException:
        pipeline.save_json(output_dir / 'summary.json', {**summary, 'status': 'interrupted'})
        raise
    if not summary.get('article'):
        drafts = list((output_dir / 'article').glob('author-*-files-*/output/article.md'))
        partials = list((output_dir / 'article').glob('author-*-files-*/output/partial.md'))
        candidates = [p for p in drafts + partials if p.is_file() and p.stat().st_size]
        if candidates:
            latest = max(candidates, key=lambda p: p.stat().st_mtime_ns)
            summary.update(article=latest.read_text(encoding='utf-8'), article_path=str(latest),
                           draft_source='最后可见原始输出，未采用')
        else:
            summary['draft_source'] = '未找到可见作者草稿；不补造'
    if summary.get('article'):
        name = '01_唯一流程稿.md' if summary['status'] == 'ready' else '最后草稿_未通过.md'
        (output_dir / name).write_text(summary['article'], encoding='utf-8')
    summary['actual_stages'] = state.get('recommendation_stages', [])
    state['terminal_status'] = summary['status']
    stock_ai.save_state(state_path, state)
    pipeline.save_json(output_dir / 'summary.json', summary)
    return EXIT_OK if summary['status'] == 'ready' else (EXIT_NEEDS_RESEARCH if summary['status'] == 'needs_research' else EXIT_NEEDS_REVISION)


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
    p_export.add_argument("--expected-samples", type=Path, dest="expected_samples_path",
                          help="expected_samples.json：本轮明确声明的全部预期样本行")
    p_export.add_argument("--commands", type=Path, dest="commands_path",
                          help="commands.jsonl：prepare/run实际退出码记录")
    p_export.add_argument("--production-report", type=Path, action="append",
                          dest="production_reports", default=None,
                          help="production-before/after.json等只读盘点（可多次）")
    p_export.add_argument("--run-root", type=Path,
                          help="本轮RUN_ROOT；复制00_日常运行与责任核对.md")

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

    p_files = sub.add_parser('replay-files', help='Astra 文件流程：原研究交接与共享单篇作者循环')
    for flag in ('source-root', 'packet', 'source-manifest', 'guide', 'output-dir'):
        p_files.add_argument('--' + flag, type=Path, required=True)
    p_files.add_argument('--examples', type=Path, nargs='+', required=True)
    p_files.add_argument('--provider', required=True)
    p_files.add_argument('--no-fallback', action='store_true')
    p_files.add_argument('--repeats', type=int, default=1)
    p_files.add_argument('--resume', action='store_true')

    args = parser.parse_args(argv)
    try:
        if args.command == 'replay-files':
            return replay_files(source_root=args.source_root, packet_path=args.packet,
                source_manifest=args.source_manifest, guide=args.guide, examples=args.examples,
                output_dir=args.output_dir, provider=args.provider, fallback=not args.no_fallback,
                repeats=args.repeats, resume=args.resume)
        if args.command == "prepare":
            prepare(source_root=args.source_root, trace_path=args.trace, names=args.names,
                    output_dir=args.output_dir, code_root=args.code_root,
                    handoff_path=args.handoff, original_report_path=args.original_report)
            print(f"manifest={args.output_dir / 'manifest.json'}")
            return EXIT_OK
        if args.command == "export":
            code = export(selection=args.selection, trial_dirs=args.trial_dirs,
                          output_dir=args.output_dir, code_root=args.code_root,
                          tests_dir=args.tests_dir, notes_path=args.notes,
                          expected_samples_path=args.expected_samples_path,
                          commands_path=args.commands_path,
                          production_reports=args.production_reports,
                          run_root=args.run_root)
            print(f"exit={code}; export={args.output_dir}")
            return code
        # 发出任何请求前拒绝非GLM或允许备用的参数；不依赖调用者记得关闭。
        policy_error = validate_run_policy(args.provider, not args.no_fallback)
        if policy_error:
            print(f"错误：{policy_error}", file=sys.stderr)
            return EXIT_INPUT
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
