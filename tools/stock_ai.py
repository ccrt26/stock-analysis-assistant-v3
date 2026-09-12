#!/usr/bin/env python3
"""股票助手 AI 任务统一本地入口。

两个正式 AI 定时任务（18:45 晚间研究、08:45 次晨安全提醒）由 macOS launchd
启动本程序，本程序按本地路由配置选择模型路线（GLM → DeepSeek 自动接替，
Astra 仅限用户在 Codex App 手动执行）无交互执行原有运行 Prompt：
GLM/DeepSeek 走本机 ZCode CLI（显式模型、API 地址与密钥）。
本入口不提供 Codex/Astra 执行路线。

日期与截止一律以原 forward_selection prepare 的判定为准：本入口只按
调度约定选择 prepare 的调用形态（无参 / --rerun-date），不自行推断交易日。
偏好切换与状态查询不请求任何模型 API。

本地配置 .stock-ai.local.json 不入 Git；密钥只在调用时经环境变量传给子进程，
不打印、不入日志。
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import fcntl
import json
import os
import plistlib
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from zoneinfo import ZoneInfo

SHANGHAI = ZoneInfo("Asia/Shanghai")

# 测试可经环境变量把整个工程根指到临时副本；生产默认仓库根。
PROJECT_ROOT = (
    Path(os.environ["STOCK_AI_PROJECT_ROOT"]).resolve()
    if os.environ.get("STOCK_AI_PROJECT_ROOT")
    else Path(__file__).resolve().parents[1]
)
LOCAL_CONFIG_PATH = PROJECT_ROOT / ".stock-ai.local.json"
AI_ARCHIVE_DIR = PROJECT_ROOT / "local_archive" / "ai_tasks"
STATE_DIR = AI_ARCHIVE_DIR / "state"
INDEX_PATH = AI_ARCHIVE_DIR / "index.jsonl"
LOG_DIR = PROJECT_ROOT / "logs" / "ai_tasks"
LOCK_PATH = AI_ARCHIVE_DIR / "task.lock"

SELECTION_PROMPT = "ops/forward-selection-prompt.md"
MONITOR_PROMPT = "ops/forward-monitor-prompt.md"
PREOPEN_PROMPT = "ops/preopen-safety-prompt.md"
PRISM_TOOL = "tools/render_prism_web.py"

LAUNCHD_TEMPLATE_DIR = PROJECT_ROOT / "ops" / "launchd"
LAUNCHD_TASKS = {
    "nightly": {
        "label": "com.ccrt.stock-analysis-assistant.ai-nightly",
        "hour": 18,
        "minute": 45,
    },
    "preopen": {
        "label": "com.ccrt.stock-analysis-assistant.ai-preopen",
        "hour": 8,
        "minute": 45,
    },
}

DEFAULT_ORDER = ["glm", "deepseek"]
ALL_PROVIDERS = ["glm", "deepseek", "astra"]
# ALL_PROVIDERS 只用于识别历史记录；实际执行只允许 DEFAULT_ORDER 两路。
DEFAULT_MODEL_REFS = {
    "glm": "bigmodel/glm-5.3-flash",
    "deepseek": "deepseek/deepseek-flash",
}
DEFAULT_BASE_URLS = {
    "glm": "https://open.bigmodel.cn/api/anthropic",
    "deepseek": "https://api.deepseek.com/anthropic",
}
KEY_ENV_NAMES = {"glm": "BIGMODEL_API_KEY", "deepseek": "DEEPSEEK_API_KEY"}
PROVIDER_LABELS = {
    "glm": "GLM（ZCode CLI，BigModel 个人套餐 glm-5.3-flash，思考档 max）",
    "deepseek": "DeepSeek（ZCode CLI，官方 API deepseek-flash，默认思考模式）",
    "astra": "Codex Astra（用户手动执行；自动任务不尝试）",
}
ZCODE_CLI_DEFAULT = "/Applications/ZCode.app/Contents/Resources/glm/zcode.cjs"
ZCODE_ROLLOUT_DIR = Path("~/.zcode/cli/rollout").expanduser()

DEFAULT_ORDER_TEXT = "GLM → DeepSeek"

# 调度窗口（上海时间）。晚间研究的窗口语义与原 prepare 一致：
# 18:45–18:55 无参 prepare（可等待前置数据）；≥18:55 按 --rerun-date 明日补跑形态。
NIGHTLY_WINDOW_START = dt.time(18, 45)
NIGHTLY_WINDOW_END = dt.time(18, 55)
PREOPEN_WINDOW_START = dt.time(8, 45)
# 09:30 业务边界由原 preopen_safety.prepare 判定（先交易日、后窗口），
# 启动器不重复实现交易日历；此常量仅作文档。
PREOPEN_WINDOW_END = dt.time(9, 30)

READY_STATUSES = {"ready_for_research", "ready_for_research_limited", "already_selected"}

EXIT_OK = 0
EXIT_FAIL = 2
EXIT_LOCKED = 3
EXIT_USAGE = 4

DEFAULT_PREPARE_TIMEOUT_MINUTES = {"nightly": 15, "preopen": 10}

# 终端 API 错误签名：优先于泛化本地签名（Traceback 包裹的明确 API 额度错误仍接替）。
# 只认明确来源的供应商失败；裸数字与 "model"+"does not exist" 泛词组合不作证据。
PROVIDER_TERMINAL_PATTERNS = [
    "http 401", "http 402", "http 403",
    "http 500", "http 502", "http 503", "http 504",
    "quota exhausted", "insufficient balance", "balance is not enough",
    "invalid api key", "invalid_api_key", "unauthorized",
    "rate limit", "http 429",
    "connection refused", "connection reset",
    "model not found", "unknown model",
    "service unavailable", "provider overloaded",
]
# 整轮取消/中断/超时退出码：先于一切文本判断，不接替（即便旧日志含供应商字样）。
CANCELLATION_EXIT_CODES = {124, 130, 143}
# 具体本地/数据/上下文签名：命中不接替。
LOCAL_SPECIFIC_PATTERNS = [
    "filenotfounderror", "jsondecodeerror", "keyerror", "typeerror",
    "valueerror", "permissionerror", "syntaxerror",
    "snapshot does not exist", "insufficient local data",
    "partition metadata missing", "forward log header is missing",
    "autocompact stopped", "context refilled", "duckdb",
]

# 模型目录覆盖：补正 CLI 元数据（DeepSeek 官方 1M 上下文 / 384K 输出；
# GLM-5.3-flash 1M）。写入用户级 ~/.zcode/cli/config.json（幂等合并）。
MODEL_CATALOG_OVERRIDES = {
    "deepseek/deepseek-flash": {
        "id": "deepseek-flash",
        "kinds": ["anthropic"],
        "modalities": {"input": ["text"], "output": ["text"]},
        "contextWindow": 1000000,
        "maxOutputTokens": 384000,
    },
    "bigmodel/glm-5.3-flash": {
        "id": "glm-5.3-flash",
        "kinds": ["anthropic"],
        "modalities": {"input": ["text", "image"], "output": ["text"]},
        "contextWindow": 1000000,
        "maxOutputTokens": 128000,
    },
}
ZCODE_USER_CONFIG_PATH = Path("~/.zcode/cli/config.json").expanduser()

# 失败/需处理时的通知：macOS 原生通知（osascript，脚本经 stdin、文案走 argv）。
# 命令退出 0 只代表系统接受提交，不代表用户已读。
MAC_NOTIFY_SCRIPT = (
    "on run argv\n"
    "    display notification (item 2 of argv) with title (item 1 of argv)\n"
    "end run\n"
)
MAC_NOTIFY_TITLE = "股票AI任务"
# 正常结果不弹通知；失败/部分完成/取消/错过窗口/占用未执行才提示一次。
NO_NOTIFY_STATUSES = {"完整完成", "正常无需运行"}
# 模型路线证据的预期完整三元组：(providerId, modelId, request.body.model)。
EXPECTED_MODEL_EVIDENCE = {
    "glm": ("bigmodel", "glm-5.3-flash", "glm-5.3-flash"),
    "deepseek": ("deepseek", "deepseek-flash", "deepseek-flash"),
}


def now_shanghai() -> dt.datetime:
    return dt.datetime.now(SHANGHAI)


# ---------------------------------------------------------------- 本地配置


def load_local_config() -> dict:
    if LOCAL_CONFIG_PATH.exists():
        try:
            data = json.loads(LOCAL_CONFIG_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
        except (OSError, json.JSONDecodeError) as exc:
            print(f"警告：本地配置读取失败，按默认配置继续：{exc}", file=sys.stderr)
    return {}


def save_local_config(config: dict) -> None:
    LOCAL_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        dir=str(LOCAL_CONFIG_PATH.parent), prefix=".stock-ai.local.", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(config, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(tmp_name, LOCAL_CONFIG_PATH)
    except BaseException:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)
        raise


def default_preference(config: dict) -> str:
    value = config.get("default_preference", "auto")
    return value if value in {"auto", "glm", "deepseek"} else "auto"


def tonight_override(config: dict, today: dt.date) -> str | None:
    tonight = config.get("tonight")
    if not isinstance(tonight, dict):
        return None
    if tonight.get("date") != today.isoformat():
        return None
    value = tonight.get("preference")
    return value if value in {"glm", "deepseek"} else None


def key_sources(provider: str, config: dict) -> list[dict]:
    override = config.get("key_sources", {})
    if isinstance(override, dict) and isinstance(override.get(provider), list):
        return override[provider]
    return DEFAULT_KEY_SOURCES.get(provider, [])


DEFAULT_KEY_SOURCES = {
    "glm": [
        {"kind": "env", "name": "BIGMODEL_API_KEY"},
        {
            "kind": "json",
            "path": "~/.zcode/v2/config.json",
            "pointer": ["provider", "builtin:bigmodel-coding-plan", "options", "apiKey"],
        },
    ],
    "deepseek": [
        {"kind": "env", "name": "DEEPSEEK_API_KEY"},
        {"kind": "keychain", "service": "stock-analysis-system.deepseek"},
        {"kind": "keychain", "service": "com.llw.deepseek-api"},
    ],
}


def resolve_api_key(provider: str, config: dict) -> tuple[str | None, str]:
    """返回 (密钥, 来源描述)。找不到返回 (None, "")。不打印密钥值。"""
    for source in key_sources(provider, config):
        kind = source.get("kind")
        if kind == "env":
            value = os.environ.get(source.get("name", ""))
            if value:
                return value, f"环境变量 {source.get('name')}"
        elif kind == "json":
            path = Path(os.path.expanduser(source.get("path", "")))
            pointer = source.get("pointer", [])
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                for key in pointer:
                    data = data[key]
                if isinstance(data, str) and data:
                    return data, f"本地凭据文件 {path.name}（{'/'.join(pointer)}）"
            except (OSError, json.JSONDecodeError, KeyError, TypeError):
                continue
        elif kind == "keychain":
            service = source.get("service", "")
            result = subprocess.run(
                ["security", "find-generic-password", "-s", service, "-w"],
                capture_output=True, text=True,
            )
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip(), f"macOS 钥匙串（服务 {service}）"
    return None, ""


def _config_minutes(config: dict, key: str, task: str, default: int) -> int:
    override = config.get(key, {})
    if isinstance(override, dict) and isinstance(override.get(task), (int, float)):
        return int(override[task])
    return default


def prepare_timeout_seconds(task: str, config: dict) -> int:
    return _config_minutes(
        config, "prepare_timeout_minutes", task, DEFAULT_PREPARE_TIMEOUT_MINUTES[task]
    ) * 60


def zcode_command(config: dict) -> list[str]:
    override = config.get("zcode_cli")
    cli = Path(os.path.expanduser(str(override))) if override else Path(ZCODE_CLI_DEFAULT)
    if not cli.exists():
        found = shutil.which("zcode")
        if found:
            return [found]
    node = shutil.which("node") or "/usr/local/bin/node"
    return [node, str(cli)]


def model_ref(provider: str, config: dict) -> str:
    override = (config.get("model_refs") or {}).get(provider)
    return override or DEFAULT_MODEL_REFS[provider]


def provider_base_url(provider: str, config: dict) -> str:
    override = (config.get("base_urls") or {}).get(provider)
    return override or DEFAULT_BASE_URLS[provider]


def model_label(provider: str, config: dict) -> str:
    """配置层面的模型标识；与实际请求证据分开记录。"""
    return model_ref(provider, config)


# ---------------------------------------------------------------- 路由解析


def resolve_provider_order(
    task: str,
    cli_provider: str | None,
    config: dict,
    today: dt.date,
) -> tuple[list[str], str]:
    """返回 (顺序, 说明)。

    自动链路只在 GLM/DeepSeek 之间接替。Astra 由用户在 Codex App 中手动
    执行，本工具的自动任务与接替绝不尝试 Astra。
    """
    if cli_provider:
        order = [cli_provider] + [p for p in DEFAULT_ORDER if p != cli_provider]
        return order, "本次 --provider 指定"
    stored_pref = default_preference(config)
    tonight_pref = tonight_override(config, today) if task == "nightly" else None
    if tonight_pref in {"glm", "deepseek"}:
        first = tonight_pref
        source = f"今晚覆盖（{today.isoformat()}）"
    elif stored_pref in {"glm", "deepseek"}:
        first = stored_pref
        source = "长期默认偏好"
    else:
        first = "glm"
        source = "默认顺序"
    order = [first] + [p for p in DEFAULT_ORDER if p != first]
    return order, source


# ---------------------------------------------------------------- 任务锁


class TaskLock:
    """项目级 AI 任务锁：flock + pid 记录，异常退出可恢复。
    只有一个锁；与数据任务的 research_job_lock（local_warehouse）互不替代。
    """

    def __init__(self) -> None:
        self.handle = None

    def acquire(self) -> tuple[bool, str]:
        AI_ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
        self.handle = open(LOCK_PATH, "a+")
        try:
            fcntl.flock(self.handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.handle.close()
            self.handle = None
            pid = ""
            try:
                pid = LOCK_PATH.read_text(encoding="utf-8").strip()
            except OSError:
                pass
            return False, pid
        self.handle.seek(0)
        self.handle.truncate()
        self.handle.write(str(os.getpid()))
        self.handle.flush()
        return True, ""

    def release(self) -> None:
        if self.handle is None:
            return
        try:
            self.handle.seek(0)
            self.handle.truncate()
            fcntl.flock(self.handle, fcntl.LOCK_UN)
        finally:
            self.handle.close()
            self.handle = None


def describe_lock_holder(pid_text: str) -> str:
    pid_text = pid_text.strip()
    if not pid_text.isdigit():
        return f"未知持有者（{pid_text or '空'}）"
    pid = int(pid_text)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return f"pid {pid}（进程已不存在，锁可安全接管）"
    except PermissionError:
        return f"pid {pid}（仍在运行）"
    except OSError:
        return f"pid {pid}"
    return f"pid {pid}（仍在运行）"


# ---------------------------------------------------------------- state / 索引


def state_path(task: str, slot_date: dt.date, rerun_date: dt.date | None = None) -> Path:
    """夜间任务：正常晚以研究晚命名；显式补跑以行动日命名，互不遮挡。"""
    if task == "nightly" and rerun_date is not None:
        return STATE_DIR / f"{task}-rerun-{rerun_date.isoformat()}.json"
    return STATE_DIR / f"{task}-{slot_date.isoformat()}.json"


def load_state(task: str, slot_date: dt.date, rerun_date: dt.date | None = None) -> dict | None:
    path = state_path(task, slot_date, rerun_date)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    # 任务身份核对：不匹配的旧状态不使用（也不会被覆盖判断误导）。
    if data.get("task") != task:
        return None
    if data.get("slot_date") != slot_date.isoformat():
        return None
    if task == "nightly" and rerun_date is not None and data.get("rerun_date") != rerun_date.isoformat():
        return None
    return data


_LAST_STATE_PATH: Path | None = None


def save_state(path: Path, state: dict) -> None:
    global _LAST_STATE_PATH
    _LAST_STATE_PATH = path
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=".state-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(state, handle, ensure_ascii=False, indent=2)
        os.replace(tmp_name, path)
    except BaseException:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)
        raise


def mark_terminal(task: str, status: str, detail: str, exit_code: int) -> int:
    """异常退出/取消时把最近任务状态落成真实终态，不留 running。

    流程：先落盘终态与错误依据 → Mac 通知一次 → 索引附通知提交结果。
    返回传入的 exit_code（SIGINT=130、SIGTERM=143 等按实际信号保留）。
    """
    state = {}
    if _LAST_STATE_PATH and _LAST_STATE_PATH.exists():
        try:
            loaded = json.loads(_LAST_STATE_PATH.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                state = loaded
        except (OSError, json.JSONDecodeError):
            state = {}
    if not state:
        state = {"task": task, "status": status, "attempts": []}
    state["status"] = status
    result_status = "失败" if status == "failed" else "已取消"
    state["result"] = {
        "status": result_status,
        "detail": detail,
        "stage": "取消" if status != "failed" else "异常退出",
        "finished_at": now_shanghai().isoformat(timespec="seconds"),
    }
    slot_key = _LAST_STATE_PATH.name if _LAST_STATE_PATH else task
    if _LAST_STATE_PATH:
        save_state(_LAST_STATE_PATH, state)
    notification = mac_notify_result(task, slot_key, result_status, detail, state)
    entry = {
        "task": task,
        "slot": _LAST_STATE_PATH.stem.replace(".json", "") if _LAST_STATE_PATH else task,
        "recorded_at": now_shanghai().isoformat(timespec="seconds"),
        "result_status": result_status,
        "detail": detail,
        "stage": state["result"]["stage"],
        "configured_model": state.get("last_model", ""),
        "model_evidence": state.get("model_evidence", {}),
        "attempts": state.get("attempts", []),
        "final_reply": state.get("final_reply", ""),
        "archive": state.get("archive", ""),
        "mac_notification": notification,
    }
    for field in ("formation_date", "action_date", "selection_as_of"):
        if state.get(field):
            entry[field] = state[field]
    append_index(entry)
    print(f"结果：{result_status}\n{detail}")
    return exit_code


def append_index(entry: dict) -> None:
    AI_ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    with INDEX_PATH.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")


def notify_macos(message: str) -> tuple[bool, str]:
    """提交一条 macOS 原生通知；返回 (是否提交成功, 说明)。

    AppleScript 源码经 stdin 传入，标题与正文走 argv（列表参数，不经 shell、
    不拼进脚本源码）；10 秒是本地通知命令的技术超时，不是研究/模型预算。
    提交成功只代表系统接受了通知，不代表用户已读。
    """
    try:
        result = subprocess.run(
            ["/usr/bin/osascript", "-", MAC_NOTIFY_TITLE, message],
            input=MAC_NOTIFY_SCRIPT, capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, f"Mac 通知提交失败：{type(exc).__name__}: {exc}"
    if result.returncode == 0:
        return True, "已提交系统通知（可见性未核验）"
    err = ((result.stderr or "") + (result.stdout or "")).strip()
    return False, f"Mac 通知提交失败（退出码 {result.returncode}）：{err[-200:]}"


def build_task_notice(task: str, slot_key: str, result_status: str,
                      detail: str, state: dict) -> str:
    """确定性通知/记录文本：任务、日期、结果、尝试、简明原因、记录位置。"""
    attempts = state.get("attempts") or []
    tried = "、".join(
        f"{a.get('provider')}({a.get('outcome')})" for a in attempts if a.get("provider")
    ) or "无"
    boundaries = ""
    if state.get("formation_date"):
        boundaries = (
            f"形成日 {state['formation_date']}，行动日 {state['action_date']}，"
            f"截止 {state.get('selection_as_of', '')}。"
        )
    done = state.get("final_reply") or ""
    parts = [
        f"【股票AI任务】{task}（{slot_key.replace('.json', '')}）{result_status}",
    ]
    if boundaries:
        parts.append(boundaries)
    parts.append(f"实际尝试：{tried}；原因：{detail[:200]}")
    parts.append(
        f"已有产物：{done or '无'}；"
        "失败详情与日志见 local_archive/ai_tasks/ 与 logs/ai_tasks/"
        "（可让助手“查看最近一次失败原因”）。"
    )
    return "\n".join(parts)


def mac_notify_result(task: str, slot_key: str, result_status: str,
                      detail: str, state: dict) -> dict:
    """先落盘、后通知：按策略提交一次 Mac 原生通知，返回提交结果记录。

    通知阶段任何异常都不改变业务结论、不触发模型重试、不循环发送。
    """
    record = {
        "notified": False,
        "ok": None,
        "note": "",
        "at": now_shanghai().isoformat(timespec="seconds"),
    }
    if result_status in NO_NOTIFY_STATUSES:
        record["note"] = "正常结果不弹通知"
        return record
    notice = build_task_notice(task, slot_key, result_status, detail, state)
    try:
        ok, note = notify_macos(notice)
    except BaseException as exc:
        ok, note = False, f"Mac 通知提交异常：{type(exc).__name__}: {exc}"
    record.update({"notified": True, "ok": ok, "note": note})
    return record


# ---------------------------------------------------------------- 子进程执行


def terminate_process_group(proc: subprocess.Popen) -> None:
    try:
        os.killpg(proc.pid, signal.SIGTERM)
        proc.wait(timeout=15)
    except (ProcessLookupError, subprocess.TimeoutExpired):
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            pass


def run_bounded(cmd: list[str], timeout_seconds: int | None, cwd: Path | None = None,
                env: dict | None = None) -> tuple[int, str, str]:
    """有界子进程：timeout_seconds=None 表示无限等待（晚间模型执行语义）。
    有界时超时结束整个进程组，不只停止等待。"""
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=cwd or PROJECT_ROOT,
        env=env,
        start_new_session=True,
    )
    try:
        stdout, stderr = proc.communicate(
            timeout=None if timeout_seconds is None else max(1, int(timeout_seconds))
        )
    except subprocess.TimeoutExpired:
        terminate_process_group(proc)
        return 124, "", f"子进程超时（上限 {timeout_seconds} 秒），已结束进程组"
    except BaseException:
        # 取消/中断：先结束子进程组再上抛，避免数据准备等子进程遗留。
        terminate_process_group(proc)
        raise
    return (
        proc.returncode,
        stdout.decode("utf-8", errors="replace"),
        stderr.decode("utf-8", errors="replace"),
    )


# ---------------------------------------------------------------- prepare


def extract_json_object(text: str) -> dict | None:
    for line in reversed(text.splitlines()):
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict) and "status" in data:
            return data
    return None


def valid_prepare_summary(summary: dict | None) -> bool:
    """只有成功、字段齐全的 prepare 才可复用。"""
    if not isinstance(summary, dict) or summary.get("status") not in READY_STATUSES:
        return False
    return bool(
        summary.get("formation_date")
        and summary.get("action_date")
        and summary.get("selection_as_of")
    )


def module_child_env() -> dict:
    """原模块子进程（prepare/补数）的环境：无条件钉住工程根与包解析路径。

    临时工程测试时否则会经 editable 安装解析回生产 src，读到生产归档。
    """
    env = dict(os.environ)
    env["PROJECT_ROOT"] = str(PROJECT_ROOT)
    temp_src = str(PROJECT_ROOT / "src")
    env["PYTHONPATH"] = temp_src + os.pathsep + env.get("PYTHONPATH", "")
    return env


def run_prepare(args: list[str], timeout_seconds: int) -> tuple[int, dict | None, str]:
    """运行一次原有 prepare；有界超时，超时结束进程组。"""
    cmd = [sys.executable, "-u", "-m", "stock_analyzer.ops.forward_selection", "prepare"] + args
    code, stdout, stderr = run_bounded(cmd, timeout_seconds, cwd=PROJECT_ROOT,
                                       env=module_child_env())
    summary = extract_json_object(stdout)
    if summary is None and code == 0:
        summary = {"status": "error", "error": "prepare 未返回 JSON 摘要"}
    if code == 124:
        summary = {"status": "error", "error": stderr.strip() or "prepare 超时"}
    return code, summary, (stdout + stderr)


def run_preopen_prepare(timeout_seconds: int) -> tuple[int, dict | None, str]:
    cmd = [sys.executable, "-u", "-m", "stock_analyzer.ops.preopen_safety", "prepare"]
    code, stdout, stderr = run_bounded(cmd, timeout_seconds, cwd=PROJECT_ROOT,
                                       env=module_child_env())
    return code, extract_json_object(stdout), (stdout + stderr)


def run_pre_research_stage(formation: str, as_of: str, timeout_seconds: int) -> tuple[bool, str]:
    """原补跑文档的定向补数：仅补形成日观察，一次，不循环。"""
    cmd = [
        sys.executable, "-u", "-m", "stock_analyzer", "data", "run-stage",
        "--stage", "pre-research",
        "--data-date", formation,
        "--as-of", as_of,
    ]
    code, _stdout, stderr = run_bounded(cmd, timeout_seconds, cwd=PROJECT_ROOT,
                                        env=module_child_env())
    if code != 0:
        return False, f"pre-research 补数失败（退出码 {code}）：{stderr[-300:]}"
    return True, ""


# ---------------------------------------------------------------- Codex/ZCode 执行


def child_env(provider: str, config: dict) -> dict:
    env = dict(os.environ)
    env["PATH"] = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
    if provider in {"glm", "deepseek"}:
        # 国内端点直连；避免代理变量影响本次模型请求。
        for name in (
            "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
            "http_proxy", "https_proxy", "all_proxy",
        ):
            env.pop(name, None)
    key, _source = resolve_api_key(provider, config)
    if key and provider in KEY_ENV_NAMES:
        env[KEY_ENV_NAMES[provider]] = key
    # 无条件钉住本次工程根与包解析路径；临时副本测试与生产同一语义。
    env["PROJECT_ROOT"] = str(PROJECT_ROOT)
    env["PYTHONPATH"] = str(PROJECT_ROOT / "src") + os.pathsep + env.get("PYTHONPATH", "")
    return env


def parse_zcode_output(jsonl_path: Path) -> dict | None:
    """解析 ZCode --json 输出（整体或多行缩进 JSON，含 "response"/"sessionId"）。"""
    try:
        text = jsonl_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    decoder = json.JSONDecoder()
    starts = [i for i, ch in enumerate(text) if ch == "{"]
    for start in reversed(starts):
        try:
            data, _end = decoder.raw_decode(text[start:])
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict) and "response" in data:
            return data
    return None


def rollout_model_evidence(session_id: str | None) -> dict:
    """从 ZCode 会话请求记录精确提取主请求模型证据。

    只取 event.model.role=='main' 的 providerId/modelId 与 request.body.model；
    压缩等辅助调用按角色区分，不并入。响应侧模型字段存在则附记，
    不存在就注明未提供。取不到返回未核验标记。
    """
    if not session_id:
        return {"verified": False, "provider": "", "model": "", "request_model": "",
                "response_model": "", "effort": "",
                "note": "未取得会话请求记录，模型证据未核验"}
    sid = session_id.removeprefix("sess_")
    path = ZCODE_ROLLOUT_DIR / f"model-io-sess_{sid}.jsonl"
    for _ in range(30):
        if path.exists():
            break
        time.sleep(1)
    if not path.exists():
        return {"verified": False, "provider": "", "model": "", "request_model": "",
                "response_model": "", "effort": "",
                "note": f"未找到请求记录 {path.name}，模型证据未核验"}
    try:
        main_models: set[tuple[str, str, str]] = set()
        response_model = ""
        main_effort = ""
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(event, dict):
                continue
            model = event.get("model")
            body = (event.get("request") or {}).get("body") or {}
            if isinstance(model, dict) and model.get("role") == "main":
                if isinstance(body, dict) and body.get("model"):
                    main_models.add(
                        (str(model.get("providerId", "")),
                         str(model.get("modelId", "")),
                         str(body.get("model", "")))
                    )
                    if not main_effort:
                        main_effort = str(body.get("effort") or body.get("reasoning_effort") or "")
            resp_model = (event.get("response") or {}).get("model") if isinstance(
                event.get("response"), dict) else None
            if isinstance(resp_model, str) and resp_model and not response_model:
                response_model = resp_model
        if main_models:
            provider_ids = {item[0] for item in main_models}
            model_ids = {item[1] for item in main_models}
            request_models = {item[2] for item in main_models}
            consistent = len(main_models) == 1
            return {
                "verified": True,
                "provider": provider_ids.pop() if len(provider_ids) == 1 else "|".join(sorted(provider_ids)),
                "model": model_ids.pop() if len(model_ids) == 1 else "|".join(sorted(model_ids)),
                "request_model": request_models.pop() if len(request_models) == 1 else "|".join(sorted(request_models)),
                "response_model": response_model,
                "effort": main_effort,
                "consistent": consistent,
                "note": f"证据来源 {path.name}（主请求，共 {len(main_models)} 种）",
            }
    except OSError:
        pass
    return {"verified": False, "provider": "", "model": "", "request_model": "",
            "response_model": "", "effort": "",
            "note": "请求记录中未找到主请求模型字段，模型证据未核验"}


CAPACITY_FIELDS = ("contextWindow", "maxOutputTokens")


def ensure_model_catalog_config() -> None:
    """最小合并模型目录覆盖：只更新两路已核验的容量字段。

    保留顶层其他键、modelCatalog 其他键、其他模型覆盖项与条目内非容量键；
    配置不存在时按既有规格新建；读取或结构不合法时报明确配置错误，
    绝不覆盖原文件。已符合时零写入。
    """
    path = ZCODE_USER_CONFIG_PATH
    if not path.exists():
        data: dict = {"modelCatalog": {"overrides": {
            key: dict(entry) for key, entry in MODEL_CATALOG_OVERRIDES.items()
        }}}
    else:
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"ZCode 用户配置不可读，拒绝修改：{path}（{exc}）") from exc
        if not isinstance(loaded, dict):
            raise RuntimeError(f"ZCode 用户配置根对象不是字典，拒绝修改：{path}")
        data = loaded
        catalog = data.get("modelCatalog")
        if catalog is None:
            catalog = {}
        if not isinstance(catalog, dict):
            raise RuntimeError(f"ZCode 用户配置 modelCatalog 不是对象，拒绝修改：{path}")
        overrides = catalog.get("overrides")
        if overrides is None:
            overrides = {}
        if not isinstance(overrides, dict):
            raise RuntimeError(f"ZCode 用户配置 modelCatalog.overrides 不是对象，拒绝修改：{path}")
        changed = False
        for key, entry in MODEL_CATALOG_OVERRIDES.items():
            current = overrides.get(key)
            if current is None:
                overrides[key] = dict(entry)
                changed = True
                continue
            if not isinstance(current, dict):
                raise RuntimeError(f"ZCode 用户配置覆盖项 {key} 不是对象，拒绝修改：{path}")
            for field in CAPACITY_FIELDS:
                if current.get(field) != entry[field]:
                    current[field] = entry[field]
                    changed = True
        if changed:
            catalog["overrides"] = overrides
            data["modelCatalog"] = catalog
        else:
            return
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=".config-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(tmp_name, path)
    except BaseException:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)
        raise


def run_zcode(
    provider: str,
    prompt_path: Path,
    final_path: Path,
    jsonl_path: Path,
    timeout_seconds: int | None,
    config: dict,
) -> tuple[int, str]:
    """ZCode CLI 无界面执行一次；stdout 的 JSON 含最终回复与会话 id。

    timeout_seconds=None 表示无时限：等待模型执行到完成或明确失败。
    """
    ensure_model_catalog_config()
    env = child_env(provider, config)
    env["ZCODE_MODEL"] = model_ref(provider, config)
    env["ZCODE_BASE_URL"] = provider_base_url(provider, config)
    workdir = Path(config.get("_cwd") or PROJECT_ROOT)
    prompt = prompt_path.read_text(encoding="utf-8")
    args = zcode_command(config) + [
        "--prompt", prompt,
        "--cwd", str(workdir),
        "--json",
    ]
    stderr_path = jsonl_path.with_suffix(".stderr.log")
    # 追加本次错误输出，保留此前尝试；直接写文件，中断时也有原始依据。
    with jsonl_path.open("wb") as out_handle, stderr_path.open(
        "r+b" if stderr_path.exists() else "w+b"
    ) as err_handle:
        err_handle.seek(0, os.SEEK_END)
        err_handle.write(f"\n[{now_shanghai().isoformat()}] {provider}\n".encode())
        err_handle.flush()
        start = err_handle.tell()
        code = EXIT_FAIL
        failure_note = ""
        try:
            proc = subprocess.Popen(
                args, stdin=subprocess.DEVNULL, stdout=out_handle, stderr=err_handle,
                env=env, cwd=workdir, start_new_session=True,
            )
            try:
                proc.communicate(timeout=None if timeout_seconds is None else max(1, int(timeout_seconds)))
                code = proc.returncode
            except subprocess.TimeoutExpired:
                terminate_process_group(proc)
                code = 124
                failure_note = f"等待超时（上限 {timeout_seconds} 秒），已终止该路进程组"
            except BaseException:
                terminate_process_group(proc)
                raise
        except KeyboardInterrupt:
            code = 130
            raise
        except SystemExit as exc:
            code = exc.code if isinstance(exc.code, int) else 143
            raise
        finally:
            err_handle.flush()
            err_handle.seek(start)
            stderr_text = err_handle.read().decode("utf-8", errors="replace")
            for name in KEY_ENV_NAMES.values():
                secret = env.get(name)
                if secret:
                    stderr_text = stderr_text.replace(secret, "[REDACTED]")
            err_handle.seek(start)
            err_handle.write(stderr_text.encode())
            err_handle.write(f"\nexit_code={code}\n{failure_note}\n".encode())
            err_handle.truncate()
    if failure_note:
        return code, failure_note + "\n" + stderr_text
    payload = parse_zcode_output(jsonl_path)
    if code == 0:
        if payload and payload.get("response"):
            final_path.write_text(str(payload["response"]), encoding="utf-8")
            state_evidence = rollout_model_evidence(payload.get("sessionId"))
            EvidenceBox.record(provider, state_evidence)
        else:
            return 1, "ZCode 执行结束但未取得最终回复文本"
    return code, stderr_text


class EvidenceBox:
    """单次进程内的模型证据暂存（按 provider 覆盖）。"""

    store: dict[str, dict] = {}

    @classmethod
    def record(cls, provider: str, evidence: dict) -> None:
        cls.store[provider] = evidence

    @classmethod
    def get(cls, provider: str) -> dict:
        return cls.store.get(provider, {})


def run_agent(
    provider: str,
    prompt_path: Path,
    final_path: Path,
    jsonl_path: Path,
    timeout_seconds: int | None,
    config: dict,
) -> tuple[int, str]:
    if provider not in DEFAULT_ORDER:
        raise ValueError(f"本地执行仅支持 GLM/DeepSeek：{provider}")
    return run_zcode(provider, prompt_path, final_path, jsonl_path, timeout_seconds, config)


def run_task_agent(provider: str, prompt: Path, final: Path, events: Path,
                   config: dict, state: dict, path: Path) -> tuple[int, str]:
    """两项正式任务共用一次尝试记录；异常展开前也保存路线、退出码和日志。"""
    attempt = {
        "provider": provider, "outcome": "running",
        "at": now_shanghai().isoformat(timespec="seconds"),
        "stderr_log": str(events.with_suffix(".stderr.log")),
    }
    state["attempts"].append(attempt)
    state["model_provider"] = provider
    state.pop("source_model_mismatch", None)
    # 当前路线尚未取得证据，不能沿用上一次尝试的证据。
    state["model_evidence"] = {"verified": False, "note": "本次尝试尚未取得模型证据"}
    EvidenceBox.store.pop(provider, None)
    save_state(path, state)
    try:
        code, diag = run_agent(provider, prompt, final, events, None, config)
        attempt.update(exit_code=code, outcome="success" if code == 0 else "failed")
        if code != 0:
            category, _ = classify_failure(code, diag)
            attempt["reason"] = f"{category}：{diag[-300:]}"
        return code, diag
    except BaseException as exc:
        code = (130 if isinstance(exc, KeyboardInterrupt) else
                exc.code if isinstance(exc, SystemExit) and isinstance(exc.code, int) else EXIT_FAIL)
        attempt.update(exit_code=code, outcome="cancelled" if code in {130, 143} else "failed",
                       reason=f"{type(exc).__name__}: {exc}")
        raise
    finally:
        save_state(path, state)


def classify_failure(returncode: int, text: str) -> tuple[str, bool]:
    """返回 (类别, 是否可接替)。

    判定顺序：
    1. 取消/中断/整轮超时（退出码 124/130/143、负信号码或 KeyboardInterrupt
       痕迹）→ 不接替；旧日志中的 HTTP 401/402/quota 字样不改变这一点。
    2. 明确来自本次模型执行器终端请求的供应商错误（额度、认证/权限、限流、
       网络中断、服务端 5xx、官方接口型号不可用）→ 接替；
    3. 具体本地/数据/上下文签名 → 不接替；
    4. 其余按未知原因如实失败，不猜成供应商故障。
    裸数字（500/429）与 "model"+"does not exist" 泛词组合不构成供应商证据。
    """
    lowered = text.lower()
    if returncode in CANCELLATION_EXIT_CODES or returncode < 0 or "keyboardinterrupt" in lowered:
        return "取消/中断/超时终止", False
    if any(pattern in lowered for pattern in PROVIDER_TERMINAL_PATTERNS):
        return "供应商不可用/额度不足", True
    if any(pattern in lowered for pattern in LOCAL_SPECIFIC_PATTERNS):
        return "本地/数据/上下文错误", False
    if returncode != 0:
        return f"执行失败（退出码 {returncode}）", False
    return "执行异常", False


# ---------------------------------------------------------------- 产物核对


def frozen_trace_ok(formation: str, action: str, as_of: str) -> tuple[bool, str]:
    path = PROJECT_ROOT / "local_archive" / "forward_selection" / f"research-trace-{formation}.json"
    if not path.exists():
        return False, f"缺少正式轨迹 {path.name}"
    try:
        trace = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return False, f"正式轨迹读取失败：{exc}"
    if trace.get("trace_version") != "daily-research-trace-v4":
        return False, "正式轨迹版本不是 daily-research-trace-v4"
    if trace.get("action_date") != action or trace.get("as_of") != as_of:
        return False, "正式轨迹的行动日/截止与 prepare 原值不一致"
    return True, ""


def monitor_artifacts_status(formation: str) -> tuple[bool, bool]:
    monitor_dir = PROJECT_ROOT / "local_archive" / "forward_monitor"
    ledger = monitor_dir / f"daily-formal-reviews-{formation}.json"
    report = monitor_dir / f"monitor-report-{formation}.json"
    return ledger.exists(), report.exists()


def prism_page_present(formation: str) -> bool:
    """render_prism_web.py 的实际产物：monitor 目录下 dated 页 + 固定 prism.html。"""
    monitor_dir = PROJECT_ROOT / "local_archive" / "forward_monitor"
    dated = monitor_dir / f"prism-report-{formation}.html"
    fixed = monitor_dir / "prism.html"
    return dated.exists() and fixed.exists()


def retry_prism_sync(formation: str, action: str, as_of: str,
                     timeout_seconds: int) -> tuple[bool, str]:
    """权威完成检查：同步命令内部执行 load_completed_archives 核对正式归档。
    接受 unchanged；技术性超时与整轮模型时限无关。
    """
    tool = PROJECT_ROOT / PRISM_TOOL
    code, stdout, stderr = run_bounded(
        [sys.executable, str(tool), "--date", formation,
         "--action-date", action, "--as-of", as_of],
        timeout_seconds, cwd=PROJECT_ROOT, env=module_child_env(),
    )
    output = stdout + stderr
    if code == 0 and ("published=" in output or "unchanged" in output or "status=" in output):
        lines = [line for line in output.strip().splitlines() if line.strip()]
        return True, lines[-1] if lines else ""
    return False, output.strip()[-400:]


def strict_archive_check(formation: str, action: str, as_of: str) -> tuple[bool, str]:
    """复用 render_prism_web.load_completed_archives 的正式归档严格校验。"""
    try:
        import importlib.util as _importlib
        spec = _importlib.spec_from_file_location(
            "stock_ai_render_prism", PROJECT_ROOT / "tools" / "render_prism_web.py")
        if spec is None or spec.loader is None:
            return False, "无法加载 render_prism_web"
        module = _importlib.module_from_spec(spec)
        sys.modules["stock_ai_render_prism"] = module
        spec.loader.exec_module(module)
        renderer, _adapt, _prism = module.load_modules()
        from datetime import date as _date, datetime as _datetime
        report, _snapshot, _inputs = module.load_completed_archives(
            renderer,
            PROJECT_ROOT / "local_archive" / "forward_monitor",
            _date.fromisoformat(formation),
            _date.fromisoformat(action),
            _datetime.fromisoformat(as_of),
        )
        alerts = report.get("alerts", []) if isinstance(report, dict) else []
        return True, f"alerts={len(alerts)}"
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"


def forward_csv_matches_trace(formation: str, action: str, as_of: str) -> tuple[bool, str]:
    """按原程序规则核对 Forward CSV 与冻结轨迹逐字段对应。

    用 forward_selection 现有 _confirmed_active_research_result/_decision_rows
    推导应有行（含合法空选合同），比较代码、名称、身份、命运、优先次序与
    已有静态研究字段；不比较 D20 等后续可变评价字段。
    解析/导入异常转成明确的核对失败，不吞掉、不当成空选。
    """
    try:
        from stock_analyzer.ops.forward_selection import (
            DailyResearchTraceV4,
            _confirmed_active_research_result,
            _decision_rows,
            _read_forward_log,
        )
        csv_path = PROJECT_ROOT / "local_archive" / "forward_selection" / "forward-selection-log.csv"
        if not csv_path.exists():
            return False, "缺少 Forward CSV"
        trace_path = PROJECT_ROOT / "local_archive" / "forward_selection" / f"research-trace-{formation}.json"
        if not trace_path.exists():
            return False, "缺少正式轨迹"
        trace_obj = DailyResearchTraceV4.model_validate(json.loads(trace_path.read_text(encoding="utf-8")))
        forward_result = _confirmed_active_research_result(trace_obj)
        fieldnames, rows = _read_forward_log(csv_path)
        identity_rows = [
            row for row in rows
            if row.get("formation_date") == formation
            and row.get("action_date") == action
            and row.get("as_of") == as_of
        ]
        expected = _decision_rows(
            forward_result,
            fieldnames=fieldnames,
            formation_date=dt.date.fromisoformat(formation),
            action_date=dt.date.fromisoformat(action),
            selection_as_of=dt.datetime.fromisoformat(as_of),
        )
        if len(identity_rows) != len(expected):
            return False, f"行数不一致：CSV {len(identity_rows)} 行，应为 {len(expected)} 行"
        compare_fields = ("ts_code", "name", "final_fate", "priority", "opportunity_type",
                          "selection_reason", "strongest_counterevidence", "nearest_comparison")
        remain = list(identity_rows)
        for want in expected:
            matched = None
            for row in remain:
                if all((row.get(f) or "").strip() == str(want.get(f, "")).strip()
                       for f in compare_fields):
                    matched = row
                    break
            if matched is None:
                diffs = [f for f in compare_fields
                         if (row.get(f) or "").strip() != str(want.get(f, "")).strip()]
                near = [row for row in remain
                        if (row.get("ts_code") or "").strip() == str(want.get("ts_code", "")).strip()]
                detail = near[0] if near else (want_desc := {f: str(want.get(f, ""))[:40] for f in
                                                            ("ts_code", "final_fate") if want.get(f)})
                return False, f"缺少应有行或缺字段一致行（差异字段 {diffs}）：{detail}"
            remain.remove(matched)
        return True, ""
    except Exception as exc:
        return False, f"Forward CSV/正式轨迹核对异常：{type(exc).__name__}: {exc}"


REQUIRED_SECTIONS = (
    "今天的市场情况",
    "正式推荐股票的今日复盘",
    "目前仍开放的正式推荐股票数量",
    "今天明确推荐的股票",
)
STOCK_CODE_PATTERN = r"(\d{6}\.(?:SH|SZ))"
REVIEW_SUBGROUPS = {
    "checkpoint_detail": "关键节点复盘",
    "regular_detail": "今日深入复盘",
    "brief": "今日简评",
}
RECO_BOLD_SUBHEADINGS = ("公司主要做什么", "为什么会选它", "什么情况会让我改变看法")


def _heading_span(normalized: str, heading: str) -> tuple[int, int] | None:
    """按独立 Markdown 标题行定位 `## 标题`；返回 (行首, 行尾)，找不到为 None。"""
    match = re.search(rf"^## {re.escape(heading)}[ \t]*$", normalized, re.MULTILINE)
    return (match.start(), match.end()) if match else None


def _stock_segment(text: str, code: str) -> str | None:
    """分区内某股票的段落（其标题行/加粗行到下一个股票标题行之前）。"""
    heading_iter = list(re.finditer(
        r"^(?:#{3,6}[ \t]*|\*\*)[^#\n]*?（\d{6}\.(?:SH|SZ)）(?:\*\*)?[ \t]*$",
        text, re.MULTILINE))
    for i, m in enumerate(heading_iter):
        if f"（{code}）" not in m.group(0):
            continue
        body_start = text.find("\n", m.start())
        body_start = body_start + 1 if body_start >= 0 else len(text)
        end = heading_iter[i + 1].start() if i + 1 < len(heading_iter) else len(text)
        return text[body_start:end]
    return None


def _formal_recommendation_list(formation: str) -> list[dict] | None:
    """正式推荐名单（confirmed_active 口径，与 Forward CSV 同源）；取不到返回 None。"""
    try:
        from stock_analyzer.ops.forward_selection import (
            DailyResearchTraceV4,
            _confirmed_active_research_result,
        )
        path = (PROJECT_ROOT / "local_archive" / "forward_selection"
                / f"research-trace-{formation}.json")
        trace = DailyResearchTraceV4.model_validate(json.loads(path.read_text(encoding="utf-8")))
        result = _confirmed_active_research_result(trace)
        return list(result.get("selected_stocks") or [])
    except Exception:
        return None


def _recommendation_section_issues(section: str, formation: str) -> list[str]:
    """推荐分区必须与正式名单逐只对应：目录表、### 逐只标题、正文存在性。"""
    issues: list[str] = []
    stocks = _formal_recommendation_list(formation)
    if stocks is None:
        return [f"无法从正式轨迹取得正式推荐名单，推荐分区无法核对（形成日 {formation}）"]
    expected = [(str(s.get("ts_code", "")), str(s.get("name", "")), s.get("priority"))
                for s in stocks]
    try:
        expected.sort(key=lambda item: int(item[2]))
    except (TypeError, ValueError):
        pass
    expected_codes = [code for code, _name, _p in expected]
    headings = [(m.group(1).strip(), m.group(2)) for m in re.finditer(
        rf"^### ([^#\n]+?)（{STOCK_CODE_PATTERN}）[ \t]*$", section, re.MULTILINE)]
    codes = [code for _name, code in headings]
    if not expected:
        # 合法空选：无股票标题、有明确空名单说明，不强迫选股、不填补空缺。
        if headings:
            issues.append("正式名单为空，推荐分区却出现股票标题："
                          + "、".join(f"{name}（{code}）" for name, code in headings))
        if not re.search(r"没有[^。\n]{0,40}推荐|空名单|空表", section):
            issues.append("正式名单为空，推荐分区缺少明确空名单说明")
        return issues
    if len(codes) != len(set(codes)):
        issues.append("推荐分区存在重复的股票标题")
    for name, code in headings:
        if code not in expected_codes:
            issues.append(f"推荐分区出现非正式推荐股票：{name}（{code}）")
    matched = [code for code in codes if code in expected_codes]
    missing = [code for code in expected_codes if code not in matched]
    for code in missing:
        name = next(n for c, n, _p in expected if c == code)
        issues.append(f"推荐分区缺少正式推荐股票正文：{name}（{code}）")
    if not missing and not [code for code in codes if code not in expected_codes] \
            and matched != expected_codes:
        issues.append("推荐分区股票顺序与正式名单不一致")
    if not codes:
        issues.append("正式名单非空但推荐分区没有逐只股票正文（只有目录表或空白）")
    table_codes = [m.group(1) for m in re.finditer(
        rf"^\|[ \t]*\d+[ \t]*\|[^|\n]*?（{STOCK_CODE_PATTERN}）", section, re.MULTILINE)]
    if table_codes and table_codes != expected_codes:
        issues.append("推荐目录表与正式名单不一致")
    heading_iter = list(re.finditer(
        rf"^### ([^#\n]+?)（{STOCK_CODE_PATTERN}）[ \t]*$", section, re.MULTILINE))
    for i, m in enumerate(heading_iter):
        body_start = m.end()
        body_end = heading_iter[i + 1].start() if i + 1 < len(heading_iter) else len(section)
        body = section[body_start:body_end]
        code = m.group(2)
        label = next((n for c, n, _p in expected if c == code), m.group(1))
        for sub in RECO_BOLD_SUBHEADINGS:
            if f"**{sub}**" not in body:
                issues.append(f"推荐正文缺少小标题“{sub}”：{label}（{code}）")
        prose = [line for line in body.splitlines()
                 if line.strip() and not line.strip().startswith(("|", "#", "**", ">"))]
        if not prose:
            issues.append(f"推荐正文没有实际说明文字：{label}（{code}）")
    return issues


def _review_section_issues(section: str, formation: str) -> list[str]:
    """复盘分区按账本 review_kind 分组核对：节点/普通详评正文归属、简评表行覆盖。"""
    issues: list[str] = []
    monitor_dir = PROJECT_ROOT / "local_archive" / "forward_monitor"
    try:
        report = json.loads(
            (monitor_dir / f"monitor-report-{formation}.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"详评报告读取失败：{exc}"]
    try:
        ledger = json.loads(
            (monitor_dir / f"daily-formal-reviews-{formation}.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"日评账本读取失败：{exc}"]
    episodes: dict[str, tuple[str, str, str]] = {}
    for alert in report.get("alerts", []):
        code = str(alert.get("ts_code", ""))
        name = str(alert.get("name", ""))
        for episode in alert.get("episode_reviews", []):
            eid = str(episode.get("episode_id", ""))
            body = str(episode.get("current_review") or "").replace("\r\n", "\n").strip()
            episodes[eid] = (code, name, body)
    ledger_reviews = ledger.get("reviews", []) if isinstance(ledger, dict) else []
    kinds = {str(r.get("episode_id", "")): str(r.get("review_kind", "")) for r in ledger_reviews}
    # 子分区标题只在确有该组内容时才必需（合法空选日不误报）。
    needed_kinds = {k for k in kinds.values() if k in REVIEW_SUBGROUPS}
    for eid, (code, name, body) in episodes.items():
        if body and kinds.get(eid) in REVIEW_SUBGROUPS:
            needed_kinds.add(kinds[eid])
    sub_texts: dict[str, str | None] = {}
    subgroup_starts = []
    for kind, label in REVIEW_SUBGROUPS.items():
        match = re.search(rf"^#{{3,6}}[ \t]*{re.escape(label)}.*$", section, re.MULTILINE)
        if match is None:
            if kind in needed_kinds:
                issues.append(f"复盘分区缺少“{label}”子分区标题")
            sub_texts[kind] = None
            continue
        subgroup_starts.append(match.start())
        sub_texts[kind] = (match.start(), match.end())
    for kind in REVIEW_SUBGROUPS:
        item = sub_texts[kind]
        if item is None:
            continue
        start, body_start = item
        later = [s for s in subgroup_starts if s > start]
        end = min(later) if later else len(section)
        sub_texts[kind] = section[body_start:end]
    for eid, (code, name, body) in episodes.items():
        if not body:
            continue
        kind = kinds.get(eid)
        if kind not in REVIEW_SUBGROUPS:
            issues.append(f"详评 episode 未在日评账本分组，无法核对归属：{eid}")
            continue
        if kind == "brief":
            continue  # 简评正文在账本，不在 monitor-report 核对
        sub = sub_texts.get(kind)
        label = REVIEW_SUBGROUPS[kind]
        if sub is None:
            continue  # 分组标题缺失已单独记
        seg = _stock_segment(sub, code)
        if seg is None:
            issues.append(f"合并报告缺少{label}股票段落：{name}（{code}）")
        elif body not in seg:
            issues.append(f"{label}正文未完整对应到 {name}（{code}）段落")
    brief_sub = sub_texts.get("brief")
    if brief_sub is not None:
        for review in ledger_reviews:
            if str(review.get("review_kind", "")) != "brief":
                continue
            eid = str(review.get("episode_id", ""))
            m = re.search(STOCK_CODE_PATTERN, eid)
            code = m.group(1) if m else ""
            if not code:
                continue
            if not re.search(rf"^\|[^|\n]*?（{re.escape(code)}）", brief_sub, re.MULTILINE):
                issues.append(f"简评表缺少股票行：（{code}）")
    return issues


def merged_report_issues(reply_text: str, formation: str, action: str,
                         as_of: str) -> list[str]:
    """核对合并报告：必需总标题按独立标题行识别且顺序正确、市场与生命周期
    分区完整、复盘分区按账本分组核对覆盖、推荐分区与正式名单逐只对应。
    程序只核对合同和对应关系，不判断研究结论本身。"""
    issues: list[str] = []
    normalized = reply_text.replace("\r\n", "\n")
    spans = []
    for heading in REQUIRED_SECTIONS:
        span = _heading_span(normalized, heading)
        spans.append((heading, span))
        if span is None:
            issues.append(f"缺少必需总标题：## {heading}")
    if issues:
        return issues
    positions = [span[0] for _h, span in spans]
    if positions != sorted(positions):
        issues.append("必需总标题顺序不正确")
        return issues
    bounds = {}
    for i, (_heading, (start, end)) in enumerate(spans):
        body_end = spans[i + 1][1][0] if i + 1 < len(spans) else len(normalized)
        bounds[spans[i][0]] = normalized[end:body_end]
    if not any(line.strip() for line in bounds["今天的市场情况"].splitlines()):
        issues.append("市场说明分区为空（不能只有空标题）")
    issues += _review_section_issues(bounds["正式推荐股票的今日复盘"], formation)
    lifecycle = bounds["目前仍开放的正式推荐股票数量"]
    for label in ("主动跟踪", "仅保留评价", "已完成"):
        if not re.search(rf"{label}[：:]\s*\d+", lifecycle):
            issues.append(f"正式推荐生命周期数量缺少“{label}”统计")
    issues += _recommendation_section_issues(bounds["今天明确推荐的股票"], formation)
    return issues


def verify_completed_run(formation: str, action: str, as_of: str,
                         reply_path: Path) -> tuple[bool, list[str], dict[str, list[str]]]:
    """统一完成检查：严格归档校验 + CSV 逐字段核对 + 合并报告核对。

    返回 (是否全部通过, 全部问题, 按检查类别分组)；类别用于据实定级，
    不以错误文案关键词决定成败。
    """
    categories: dict[str, list[str]] = {"archive": [], "csv": [], "report": []}
    arch_ok, arch_reason = strict_archive_check(formation, action, as_of)
    if not arch_ok:
        categories["archive"].append(f"正式归档校验失败：{arch_reason}")
    csv_ok, csv_reason = forward_csv_matches_trace(formation, action, as_of)
    if not csv_ok:
        categories["csv"].append(f"Forward CSV 核对失败：{csv_reason}")
    if not (reply_path.exists() and reply_path.stat().st_size > 0):
        categories["report"].append("缺少完整合并回复")
    else:
        categories["report"] += merged_report_issues(
            reply_path.read_text(encoding="utf-8"), formation, action, as_of)
    issues = categories["archive"] + categories["csv"] + categories["report"]
    return (not issues), issues, categories


def completion_failure(categories: dict[str, list[str]]) -> tuple[str, str]:
    """完成检查未通过时的 (结果状态, 阶段)：报告问题→合并报告待修复；
    CSV/正式归档问题→据实记失败或部分完成。任何类别都不以网页同步放行。"""
    if categories.get("csv"):
        return "失败", "归档核对"
    if categories.get("archive"):
        return "部分完成", "归档核对"
    return "合并报告待修复", "合并报告"


def _normalized_as_of(value: str) -> dt.datetime:
    """as_of 规范化比较：带时区 datetime 统一到上海时区。"""
    moment = dt.datetime.fromisoformat(value)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=SHANGHAI)
    return moment.astimezone(SHANGHAI)


def find_existing_reply(formation: str, action: str, as_of: str) -> tuple[Path, dict] | None:
    """同身份复用：只在既有 state 记录中三项时间身份完全一致（as_of 带时区
    规范化比较）且关联 final_reply 非空的候选里查找，按完成时间新到旧排序，
    对候选做一次完整合并报告核对。缺身份的记录不复用，不从目录名或报告
    正文猜；找不到时返回 None，不静默借用别日结果。"""
    if not STATE_DIR.exists():
        return None
    want = _normalized_as_of(as_of)
    candidates: list[tuple[str, Path, dict]] = []
    for path in sorted(STATE_DIR.glob("nightly*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict) or data.get("task") != "nightly":
            continue
        if data.get("formation_date") != formation or data.get("action_date") != action:
            continue
        recorded_as_of = data.get("selection_as_of")
        if not recorded_as_of:
            continue
        try:
            if _normalized_as_of(str(recorded_as_of)) != want:
                continue
        except (TypeError, ValueError):
            continue
        reply_rel = data.get("final_reply")
        if not reply_rel:
            continue
        reply = PROJECT_ROOT / str(reply_rel)
        try:
            if reply.stat().st_size <= 0:
                continue
        except OSError:
            continue
        finished = str((data.get("result") or {}).get("finished_at", ""))
        candidates.append((finished, reply, data))
    for _finished, reply, data in sorted(candidates, key=lambda item: item[0], reverse=True):
        try:
            text = reply.read_text(encoding="utf-8")
        except OSError:
            continue
        if not merged_report_issues(text, formation, action, as_of):
            return reply, data
    return None


def assess_artifacts(formation: str, action: str, as_of: str,
                     reply_path: str | None = None) -> dict:
    trace_ok, trace_reason = frozen_trace_ok(formation, action, as_of)
    csv_ok, csv_reason = (
        forward_csv_matches_trace(formation, action, as_of) if trace_ok else (False, "")
    )
    ledger_ok, report_ok = monitor_artifacts_status(formation)
    prism_ok = prism_page_present(formation)
    reply_ok = bool(
        reply_path and (PROJECT_ROOT / reply_path).exists()
        and (PROJECT_ROOT / reply_path).stat().st_size > 0
    )
    return {
        "trace_ok": trace_ok,
        "trace_reason": trace_reason,
        "csv_ok": csv_ok,
        "csv_reason": csv_reason,
        "ledger_ok": ledger_ok,
        "report_ok": report_ok,
        "prism_ok": prism_ok,
        "reply_ok": reply_ok,
    }


# ---------------------------------------------------------------- Prompt 组装


def write_nightly_prompt(state: dict, attempt_dir: Path,
                         force_already_selected: bool, art: dict | None = None) -> Path:
    formation = state["formation_date"]
    action = state["action_date"]
    as_of = state["selection_as_of"]
    rerun_note = ""
    if state.get("rerun_mode"):
        rerun_note = (
            "这是对原计划任务的补跑：研究仍使用原计划交易日前一自然日18:30的固定截止；"
            "当前价格不能替代当时的参与条件。按 Prompt 的补跑要求在报告开头补充说明。\n"
        )
    selected_note = ""
    if force_already_selected or state["prepare"].get("status") == "already_selected":
        selected_note = (
            "外层在启动前核对到本形成日的正式轨迹已经冻结（already_selected）："
            "按 Prompt 的 already_selected 分支执行，不得重新选股、不得再写 trace，"
            "只补未完成的复盘、合并报告与展示。\n"
        )
    art = art or {}
    recovery_note = ""
    if art.get("ledger_ok") and art.get("report_ok"):
        recovery_note = (
            "注意：日评账本与详评报告已由上一次执行正式记录。"
            "重复 record 返回 already_recorded 属预期；返回 conflict 时按原记录合同处理，"
            "不得改写已保存正文，也不得把冲突当成已保存。\n"
            "最终复盘与合并报告必须采用本轮正式 Markdown 与唯一正文；"
            "合并时不重写、不删减原推荐背景等已记录内容。\n"
        )
    preamble = (
        "【外层启动说明（启动器生成，非研究内容）】\n"
        "本次任务由本地启动器 tools/stock_ai.py 经 launchd/人工命令启动，"
        "负责按时间启动模型与失败接替；你只执行研究本身。\n"
        "外层已经完成一次 prepare，下面是其 JSON 摘要原文。"
        f"直接使用其中 formation_date={formation}、action_date={action}、"
        f"selection_as_of={as_of} 作为唯一时间边界，不得重复运行 prepare，"
        "不得改变这些值；若边界确认失败，按 Prompt 如实报告错误。\n"
        f"{rerun_note}{selected_note}{recovery_note}"
        "工程内存在较大的 JSON/Markdown 文件：读取时必须分段或按需检索，"
        "禁止一次性读入超长文件，避免上下文溢出。\n"
        "prepare 摘要 JSON：\n"
        f"{json.dumps(state.get('prepare', {}), ensure_ascii=False)}\n"
        "\n请完整读取并严格执行项目根目录下的 " + SELECTION_PROMPT + "，"
        "包括其中引用的 " + MONITOR_PROMPT + "。"
        "不要启动新的模型进程；不要修改代码；不要追加开发收尾说明。\n"
    )
    attempt_dir.mkdir(parents=True, exist_ok=True)
    path = attempt_dir / "prompt.md"
    path.write_text(preamble, encoding="utf-8")
    return path


def write_preopen_prompt(prepare_result: dict, attempt_dir: Path) -> Path:
    preamble = (
        "【外层启动说明（启动器生成，非研究内容）】\n"
        "本次任务由本地启动器 tools/stock_ai.py 启动。"
        "外层已经完成一次 prepare，下面是其 JSON 结果原文与 output_path，"
        "不得重复运行 prepare。\n"
        "prepare JSON：\n"
        f"{json.dumps(prepare_result, ensure_ascii=False)}\n"
        "\n请完整读取并严格执行项目根目录下的 " + PREOPEN_PROMPT + "。"
        "只判断新增公告是否使昨晚参与条件失效或需要谨慎；停牌必须明确提示暂缓参与；"
        "不得重新选股，不得启动新的模型进程。\n"
    )
    attempt_dir.mkdir(parents=True, exist_ok=True)
    path = attempt_dir / "prompt.md"
    path.write_text(preamble, encoding="utf-8")
    return path


def finish_task(
    task: str,
    slot_key: str,
    state: dict,
    result_status: str,
    detail: str,
    exit_code: int,
    stage: str = "",
    log_dir: str = "",
    extra: dict | None = None,
) -> int:
    """统一收尾：先落盘终态与错误依据 → 按策略 Mac 通知一次 → 索引附通知结果。"""
    if result_status == "完整完成":
        matches = state_route_evidence_matches(state)
        if matches is False:
            result_status, exit_code, stage = "完成但模型身份待核对", EXIT_FAIL, "模型执行"
            detail = "已保存模型证据与执行路线不一致；保留产物，不重跑研究。" + detail
        elif matches is None and "未核验" not in detail:
            detail += "；路线证据未核验。"
    state["status"] = "completed" if exit_code == EXIT_OK else "failed"
    state["result"] = {
        "status": result_status,
        "detail": detail,
        "finished_at": now_shanghai().isoformat(timespec="seconds"),
        **({"stage": stage} if stage else {}),
        **(extra or {}),
    }
    save_state(STATE_DIR / slot_key, state)
    notification = mac_notify_result(task, slot_key, result_status, detail, state)
    entry = {
        "task": task,
        "slot": slot_key.replace(".json", ""),
        "recorded_at": now_shanghai().isoformat(timespec="seconds"),
        "result_status": result_status,
        "detail": detail,
        "stage": stage,
        "configured_model": state.get("last_model", ""),
        "model_evidence": state.get("model_evidence", {}),
        "attempts": state.get("attempts", []),
        "final_reply": state.get("final_reply", ""),
        "archive": state.get("archive", ""),
        "mac_notification": notification,
    }
    if log_dir:
        entry["log_dir"] = log_dir
    for field in ("formation_date", "action_date", "selection_as_of"):
        if state.get(field):
            entry[field] = state[field]
    append_index(entry)
    print(f"结果：{result_status}\n{detail}")
    return exit_code


# ---------------------------------------------------------------- 晚间任务


def nightly_prepare_plan(now: dt.datetime, args: argparse.Namespace) -> tuple[list[str], dt.date, dt.date | None, bool]:
    """返回 (prepare 参数, slot_date, rerun_date, rerun_mode)。

    日期判定全部交给原 prepare：
    - 显式 --rerun-date：直接使用用户行动日（合法性由 prepare 校验截止不晚于当前）。
    - 无日期且 18:45 ≤ 时间 < 18:55：原无参 prepare，可等待前置数据。
    - 无日期且 ≥18:55：--rerun-date <入口日期次一自然日>（周五/周六晚由此正常判休市）。
    - 无日期且 <18:45：仍走无参 prepare，由原窗口限制如实拒绝。
    """
    if getattr(args, "rerun_date", None):
        rerun = dt.date.fromisoformat(args.rerun_date)
        return ["--rerun-date", args.rerun_date], rerun - dt.timedelta(days=1), rerun, True
    if NIGHTLY_WINDOW_START <= now.time() < NIGHTLY_WINDOW_END:
        return [], now.date(), None, False
    if now.time() >= NIGHTLY_WINDOW_END:
        tomorrow = now.date() + dt.timedelta(days=1)
        return ["--rerun-date", tomorrow.isoformat()], now.date(), tomorrow, True
    return [], now.date(), None, False


def prepare_arguments_ok(args_used: list[str], summary: dict, rerun_date: dt.date | None) -> bool:
    if not valid_prepare_summary(summary):
        return False
    if rerun_date is not None and summary.get("action_date") != rerun_date.isoformat():
        return False
    return True


def run_nightly(args: argparse.Namespace, config: dict, lock: TaskLock,
                now: dt.datetime | None = None) -> int:
    now = now or now_shanghai()
    today = now.date()
    if getattr(args, "scheduled", False) and now.time() < NIGHTLY_WINDOW_START:
        print(f"结果：正常无需运行\n未到当天 {NIGHTLY_WINDOW_START} 启动窗口，跳过（不猜测昨日任务）。")
        return EXIT_OK

    prepare_args, slot_date, rerun_date, rerun_mode = nightly_prepare_plan(now, args)
    path = state_path("nightly", slot_date, rerun_date)
    state = load_state("nightly", slot_date, rerun_date) or {
        "task": "nightly",
        "slot_date": slot_date.isoformat(),
        "rerun_date": rerun_date.isoformat() if rerun_date else None,
        "status": "running",
        "attempts": [],
    }
    if state.get("status") == "completed":
        result = state.get("result", {})
        if result.get("status") == "正常无需运行":
            # 合法跳过（休市/无需检查）可返回 0，但不声称生成过研究报告。
            print(
                f"结果：正常无需运行\n"
                f"该任务（{path.stem}）为合法跳过，不声称生成过研究报告：{result.get('detail', '')}"
            )
            return EXIT_OK
        identity_ok = bool(
            state.get("formation_date") and state.get("action_date")
            and state.get("selection_as_of") and state.get("final_reply")
        )
        if identity_ok:
            # 旧 completed 不能无条件成功：仍用统一完成检查复核。
            reply_path = PROJECT_ROOT / state["final_reply"]
            ok, issues, categories = verify_completed_run(
                state["formation_date"], state["action_date"],
                state["selection_as_of"], reply_path)
            if ok:
                if state_route_evidence_matches(state) is False:
                    return finish_task("nightly", path.name, state, "完整完成",
                                       "既有归档复核通过，但模型身份问题仍需核对。", EXIT_OK)
                evidence_note = "；路线证据未核验" if state_route_evidence_matches(state) is None else ""
                print(
                    f"结果：完整完成（复核通过）\n"
                    f"该任务（{path.stem}）已完成，不会重新研究：{result.get('detail', '')}{evidence_note}"
                )
                return EXIT_OK
            status_, stage_ = completion_failure(categories)
            return finish_task(
                "nightly", path.name, state, status_,
                "旧完成状态复核未通过：" + "；".join(issues)
                + "。保留研究，不换模型、不重跑。",
                EXIT_FAIL, stage=stage_,
            )
        # 已标“完整完成”却缺时间身份或报告路径：不能直接返回成功。
        return finish_task(
            "nightly", path.name, state, "失败",
            "旧完成状态缺少时间身份或报告路径，不能直接认定为完成"
            f"（formation_date={state.get('formation_date') or '缺失'}，"
            f"final_reply={state.get('final_reply') or '缺失'}）。"
            "请人工核对该任务实际产物；本次不视为成功。",
            EXIT_FAIL, stage="归档核对",
        )
    save_state(path, state)

    prepare_budget = prepare_timeout_seconds("nightly", config)

    # ---- prepare（成功且字段齐全才复用）----
    if valid_prepare_summary(state.get("prepare")) and prepare_arguments_ok(
        prepare_args, state.get("prepare"), rerun_date
    ):
        print("复用已保存且校验通过的 prepare 结果（不重复准备）。")
    else:
        state.pop("prepare", None)
        code, summary, output = run_prepare(prepare_args, prepare_budget)
        attempt_dir = LOG_DIR / f"nightly-{slot_date.isoformat()}"
        attempt_dir.mkdir(parents=True, exist_ok=True)
        (attempt_dir / "prepare.log").write_text(output[-20000:], encoding="utf-8")
        status = (summary or {}).get("status", "error")

        if status == "non_trading_day":
            state["last_prepare_attempt"] = summary or {}
            return finish_task(
                "nightly", path.name, state, "正常无需运行",
                f"{(summary or {}).get('action_date', '')} 不是交易日，晚间任务按规则说明无需生成报告。",
                EXIT_OK, stage="prepare", log_dir=str(attempt_dir),
            )
        if status == "data_not_ready" and rerun_mode:
            formation = (summary or {}).get("formation_date", "")
            as_of = (summary or {}).get("selection_as_of", "")
            if formation and as_of:
                print("data_not_ready：按原补跑文档定向补一次 pre-research 后重试 prepare。")
                ok, reason = run_pre_research_stage(formation, as_of, 1800)
                if not ok:
                    state["last_prepare_attempt"] = summary or {}
                    return finish_task(
                        "nightly", path.name, state, "失败", reason + "（数据问题，不切换模型）",
                        EXIT_FAIL, stage="prepare", log_dir=str(attempt_dir),
                    )
                code, summary, output = run_prepare(prepare_args, prepare_budget)
                (attempt_dir / "prepare.log").write_text(
                    (attempt_dir / "prepare.log").read_text(encoding="utf-8") + "\n===retry===\n" + output[-20000:],
                    encoding="utf-8",
                )
                status = (summary or {}).get("status", "error")

        if status not in READY_STATUSES:
            detail = f"prepare 状态 {status}：{(summary or {}).get('error', '') or '见日志'}"
            state["last_prepare_attempt"] = summary or {}
            return finish_task(
                "nightly", path.name, state, "失败", detail + "（业务/数据问题，不切换模型）",
                EXIT_FAIL, stage="prepare", log_dir=str(attempt_dir),
            )
        if not prepare_arguments_ok(prepare_args, summary, rerun_date):
            return finish_task(
                "nightly", path.name, state, "失败",
                "prepare 返回的行动日与请求不一致，拒绝使用（不切换模型）", EXIT_FAIL,
                stage="prepare", log_dir=str(attempt_dir),
            )
        state["prepare"] = summary
        state["formation_date"] = summary["formation_date"]
        state["action_date"] = summary["action_date"]
        state["selection_as_of"] = summary["selection_as_of"]
        state["rerun_mode"] = rerun_mode or summary.get("run_mode") == "rerun"
        save_state(path, state)

    formation = state["formation_date"]
    action = state["action_date"]
    as_of = state["selection_as_of"]
    archive_dir = AI_ARCHIVE_DIR / "nightly" / (
        f"rerun-{action}" if rerun_mode else slot_date.isoformat()
    )
    reply_target = archive_dir / "final-reply.md"

    # ---- 接替前产物核对 ----
    art = assess_artifacts(formation, action, as_of, str(reply_target) if reply_target.exists() else None)
    if art["trace_ok"] and not art["csv_ok"]:
        return finish_task(
            "nightly", path.name, state, "失败",
            f"Forward CSV 与正式轨迹不一致：{art['csv_reason']}。按已有保存契约处理，不重新发现股票。",
            EXIT_FAIL, stage="归档核对",
        )
    if art["trace_ok"] and art["ledger_ok"] and art["report_ok"] and art["reply_ok"]:
        # 严格核验：统一完成检查（归档 + CSV 逐字段 + 合并报告）后再收尾。
        ok, issues, categories = verify_completed_run(formation, action, as_of, reply_target)
        if ok:
            state["final_reply"] = str(reply_target.relative_to(PROJECT_ROOT))
            state["archive"] = str(archive_dir.relative_to(PROJECT_ROOT))
            synced, sync_msg = retry_prism_sync(formation, action, as_of, 600)
            note = ""
            if synced:
                note = "（首页未切到本历史日）" if "skipped_newer" in sync_msg else ""
                return finish_task(
                    "nightly", path.name, state, "完整完成",
                    "正式归档、合并回复与展示均已存在，严格校验通过，直接收尾，不再调用模型。" + note,
                    EXIT_OK, stage="归档核对",
                )
            return finish_task(
                "nightly", path.name, state, "研究已归档但展示待更新",
                f"归档与合并回复已存在，同步失败：{sync_msg}。只重试同步，不重跑研究。",
                EXIT_FAIL, stage="展示",
            )
        # 归档在但合并报告/CSV 不合格：保留研究，据实定级，不重新发现股票。
        status_, stage_ = completion_failure(categories)
        return finish_task(
            "nightly", path.name, state, status_,
            "；".join(issues) + "。保留研究，不换模型、不重跑、不同步掩盖。",
            EXIT_FAIL, stage=stage_,
        )
    if art["trace_ok"] and art["ledger_ok"] and art["report_ok"]:
        # 同身份复用：既有 state 关联的同身份合并回复时，采用后走同一检查。
        existing = find_existing_reply(formation, action, as_of)
        if existing is not None:
            existing_reply, source_state = existing
            archive_dir.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(existing_reply, reply_target)
            # 来源身份与正文一起复用；不能将来源已知不一致降成“未核验”。
            state["model_provider"] = state_model_provider(source_state)
            state["last_model"] = source_state.get("last_model", "")
            state["model_evidence"] = source_state.get("model_evidence", {})
            state["source_model_mismatch"] = state_route_evidence_matches(source_state) is False
            state["final_reply"] = str(reply_target.relative_to(PROJECT_ROOT))
            state["archive"] = str(archive_dir.relative_to(PROJECT_ROOT))
            ok, issues, categories = verify_completed_run(formation, action, as_of, reply_target)
            if ok:
                synced, sync_msg = retry_prism_sync(formation, action, as_of, 600)
                return finish_task(
                    "nightly", path.name, state,
                    "完整完成" if synced else "研究已归档但展示待更新",
                    "按同身份复用既有合并回复完成收尾" + (
                        "" if synced else f"；同步失败：{sync_msg}"),
                    EXIT_OK if synced else EXIT_FAIL,
                    stage="归档核对" if synced else "展示",
                )
            status_, stage_ = completion_failure(categories)
            return finish_task(
                "nightly", path.name, state, status_,
                "复用后复核未通过：" + "；".join(issues), EXIT_FAIL, stage=stage_,
            )

    # ---- 顺序尝试各模型路线（每家一次；无时限；仅额度/不可用才接替）----
    order, order_source = resolve_provider_order(
        "nightly", args.provider, config, today
    )
    print(f"模型顺序（{order_source}）：{' → '.join(order)}")
    attempt_dir = LOG_DIR / f"nightly-{slot_date.isoformat()}"
    attempt_dir.mkdir(parents=True, exist_ok=True)
    last_fail = "没有已配置的模型路线"

    for index, provider in enumerate(order):
        # 每次接替前重新核对产物，并把当前中间状态写进该路 Prompt。
        art = assess_artifacts(
            formation, action, as_of,
            str(reply_target) if reply_target.exists() else None,
        )
        if art["trace_ok"] and not art["csv_ok"]:
            return finish_task(
                "nightly", path.name, state, "失败",
                f"Forward CSV 与正式轨迹不一致：{art['csv_reason']}。不换模型掩盖。",
                EXIT_FAIL,
            )
        prompt_path = write_nightly_prompt(
            state, attempt_dir,
            force_already_selected=art["trace_ok"], art=art,
        )
        key, _source = resolve_api_key(provider, config)
        if not key:
            state["attempts"].append(
                {"provider": provider, "outcome": "skipped", "reason": "未启动（未配置，允许备用接替）",
                 "at": now_shanghai().isoformat(timespec="seconds")}
            )
            save_state(path, state)
            print(f"- {provider}：未配置（缺密钥），转下一路", flush=True)
            continue
        final_path = attempt_dir / f"final-{provider}.md"
        jsonl_path = attempt_dir / f"events-{provider}.jsonl"
        print(f"- {provider}：启动无界面执行（无时限，执行到完成或明确失败）…", flush=True)
        code, diag = run_task_agent(provider, prompt_path, final_path, jsonl_path, config, state, path)
        evidence = EvidenceBox.get(provider)
        state["last_model"] = evidence.get("model") or model_label(provider, config)
        state["model_evidence"] = evidence or {"verified": False, "note": "未取得模型证据"}
        if code == 0 and final_path.exists() and final_path.stat().st_size > 0:
            save_state(path, state)
            return finish_nightly_success(
                state, path.name, provider, final_path, formation, action, as_of,
                archive_dir, reply_target,
            )
        category, can_fallback = classify_failure(code, diag)
        state["attempts"][-1].update(outcome="failed", reason=f"{category}：{diag[-300:]}")
        save_state(path, state)
        last_fail = f"{provider}：{category}"
        print(f"- {provider}：{category}", flush=True)
        if not can_fallback:
            break  # 本地/数据/取消类失败：不靠换模型掩盖

    tried = "、".join(
        f"{a.get('provider')}({a.get('outcome')})" for a in state.get("attempts", [])
        if a.get("provider")
    ) or "无已尝试路线"
    return finish_task(
        "nightly", path.name, state, "失败",
        f"实际尝试：{tried}；最后状态：{last_fail}。"
        "如需 Astra 补跑，请在 Codex App 中手动执行（读取 "
        + SELECTION_PROMPT + "，沿用原 prepare 边界）。",
        EXIT_FAIL, stage="模型执行", log_dir=str(attempt_dir),
    )


def route_evidence_matches(provider: str, evidence: dict) -> bool | None:
    """路线证据是否与预期三元组一致：True 一致 / False 明确不一致 / None 未核验。

    完整值相等比较（provider、model、request_model），并要求主请求集合一致；
    不使用子串包含，混合型号不算一致。
    """
    if not isinstance(evidence, dict) or not evidence.get("verified"):
        return None
    expected = EXPECTED_MODEL_EVIDENCE.get(provider)
    if not expected:
        return None
    if not evidence.get("consistent", False):
        return False
    actual = (
        str(evidence.get("provider", "")),
        str(evidence.get("model", "")),
        str(evidence.get("request_model", "")),
    )
    return actual == expected


def state_model_provider(state: dict) -> str:
    """从保存的执行路线读取预期模型，不用响应自称反推期望值。"""
    provider = state.get("model_provider") or (state.get("result") or {}).get("provider")
    if provider in ALL_PROVIDERS:
        return provider
    for attempt in reversed(state.get("attempts", [])):
        if attempt.get("outcome") == "success" and attempt.get("provider") in ALL_PROVIDERS:
            return attempt["provider"]
    for provider, ref in DEFAULT_MODEL_REFS.items():
        if state.get("last_model") == ref:
            return provider
    return ""


def state_route_evidence_matches(state: dict) -> bool | None:
    matches = route_evidence_matches(state_model_provider(state), state.get("model_evidence", {}))
    if state.get("source_model_mismatch"):
        return False
    if matches is None and (state.get("result") or {}).get("status") == "完成但模型身份待核对":
        return False
    return matches


def finish_nightly_success(
    state: dict,
    state_name: str,
    provider: str,
    final_path: Path,
    formation: str,
    action: str,
    as_of: str,
    archive_dir: Path,
    reply_target: Path,
    sync_timeout: int = 600,
) -> int:
    archive_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(final_path, reply_target)
    state["final_reply"] = str(reply_target.relative_to(PROJECT_ROOT))
    state["archive"] = str(archive_dir.relative_to(PROJECT_ROOT))
    save_state(STATE_DIR / state_name, state)

    # 统一完成检查：归档严格校验 + CSV 逐字段 + 合并报告核对。
    # 检查未通过时不得以网页发布、文件非空或退出码替代必要检查。
    ok, issues, categories = verify_completed_run(formation, action, as_of, reply_target)
    if not ok:
        status_, stage_ = completion_failure(categories)
        return finish_task(
            "nightly", state_name, state, status_,
            "；".join(issues) + "。保留研究产物与原始问题，不换模型、不重跑、不同步掩盖。",
            EXIT_FAIL, stage=stage_, extra={"provider": provider},
        )
    # 权威同步：接受 unchanged；skipped_newer 注明首页未切。
    synced, sync_msg = retry_prism_sync(formation, action, as_of, sync_timeout)
    if not synced:
        return finish_task(
            "nightly", state_name, state, "研究已归档但展示待更新",
            f"归档完整，网页同步失败：{sync_msg}。只重试同步，不重跑研究。",
            EXIT_FAIL, stage="展示", extra={"provider": provider},
        )
    evidence = state.get("model_evidence", {}) or {}
    matches = route_evidence_matches(provider, evidence)
    if matches is True:
        route_text = "路线证据一致"
    elif matches is False:
        route_text = "路线证据不一致（模型身份待核对）"
    else:
        route_text = "路线证据未核验"
    response_model = str(evidence.get("response_model", "") or "")
    effort = str(evidence.get("effort", "") or "")
    detail = (
        f"模型（配置）{state.get('last_model', provider)}；"
        f"模型证据 {json.dumps(state.get('model_evidence', {}), ensure_ascii=False)}；"
        f"{route_text}；响应型号 {response_model or '未提供'}；思考档 {effort or '未提供'}；"
        f"形成日 {formation}，行动日 {action}，截止 {as_of}。"
    )
    if "skipped_newer" in sync_msg:
        detail += "（固定首页未切到本历史日，保留较新日期页）"
    if matches is False:
        # 明确不一致：保留研究并记录待核对，不宣称验收通过，不自动换模型重做。
        return finish_task(
            "nightly", state_name, state, "完成但模型身份待核对", detail,
            EXIT_FAIL, stage="模型执行", extra={"provider": provider},
        )
    return finish_task(
        "nightly", state_name, state, "完整完成", detail, EXIT_OK,
        stage="模型执行", extra={"provider": provider},
    )


# ---------------------------------------------------------------- 次晨任务


def run_preopen(args: argparse.Namespace, config: dict, lock: TaskLock,
                now: dt.datetime | None = None) -> int:
    now = now or now_shanghai()
    if getattr(args, "scheduled", False) and now.time() < PREOPEN_WINDOW_START:
        print("结果：正常无需运行\n未到 08:45 启动窗口，跳过。")
        return EXIT_OK
    # ≥09:30 不由外层宣称“正常无需运行”：仍运行原 prepare，由它先判本地
    # 交易日、再判错过窗口（该分支不请求公告/停牌）；休市正常跳过，
    # 交易日错过窗口按受限结果处理。PREOPEN_WINDOW_END 只是文档性边界。
    slot_date = now.date()
    path = state_path("preopen", slot_date)
    state = load_state("preopen", slot_date) or {
        "task": "preopen",
        "slot_date": slot_date.isoformat(),
        "status": "running",
        "attempts": [],
    }
    if state.get("status") == "completed":
        result = state.get("result", {})
        if result.get("status") == "完整完成" and state_route_evidence_matches(state) is False:
            return finish_task("preopen", path.name, state, "完整完成",
                               "次晨既有结果的模型身份仍需核对。", EXIT_OK)
        note = "；路线证据未核验" if result.get("status") == "完整完成" and state_route_evidence_matches(state) is None else ""
        print(f"结果：{result.get('status', '已完成')}\n今天次晨提醒已完成：{result.get('detail', '')}{note}")
        return EXIT_OK
    save_state(path, state)

    # 次晨沿用原有 09:30 业务边界（判定在原 prepare 内）；不新增总预算或模型倒计时。
    prepare_budget = prepare_timeout_seconds("preopen", config)
    code, prepare_result, output = run_preopen_prepare(prepare_budget)
    attempt_dir = LOG_DIR / f"preopen-{slot_date.isoformat()}"
    attempt_dir.mkdir(parents=True, exist_ok=True)
    (attempt_dir / "prepare.log").write_text(output[-20000:], encoding="utf-8")
    if prepare_result is None:
        state["last_prepare_attempt"] = {"error": "prepare 未返回 JSON", "exit_code": code}
        return finish_task(
            "preopen", path.name, state, "失败",
            f"prepare 未返回 JSON（退出码 {code}），日志：{attempt_dir / 'prepare.log'}",
            EXIT_FAIL, stage="prepare", log_dir=str(attempt_dir),
        )
    state["prepare"] = prepare_result
    save_state(path, state)

    status = prepare_result.get("status")
    announcements = prepare_result.get("new_announcements") or []
    suspended = prepare_result.get("suspended_stocks") or []
    needs_model = status == "changes_found" or (
        status == "data_limited" and (announcements or suspended)
    )

    def fixed_reply() -> tuple[str, int]:
        if status == "no_action_day":
            return "今天休市，无需开盘前安全检查。", EXIT_OK
        if status == "no_formal_trace":
            return (
                "昨晚没有可以核对的本日正式V4轨迹，开盘前名单检查未完成"
                "（可能是昨晚研究未成功归档）。这不是“没有新变化”，需人工确认昨晚研究状态。"
            ), EXIT_FAIL
        if status == "no_new_changes":
            return "没有发现需要改变昨晚参与条件的新情况", EXIT_OK
        limits = "；".join(prepare_result.get("limitations") or [])
        text = "安全检查受限，未完成项：" + (limits or status)
        if announcements or suspended:
            text += f"（已知：新公告 {len(announcements)} 条，停牌 {len(suspended)} 只）"
        text += "。不得视为“没有变化”。"
        return text, EXIT_FAIL

    if not needs_model:
        text, exit_code = fixed_reply()
        archive_dir = AI_ARCHIVE_DIR / "preopen" / slot_date.isoformat()
        archive_dir.mkdir(parents=True, exist_ok=True)
        (archive_dir / "final-reply.md").write_text(text + "\n", encoding="utf-8")
        return finish_task(
            "preopen", path.name, state,
            "正常无需运行" if exit_code == EXIT_OK else "部分完成",
            text + "（按 Prompt 固定结论直接输出，未消耗模型请求）", exit_code,
            stage="prepare", log_dir=str(attempt_dir),
        )

    order, order_source = resolve_provider_order(
        "preopen", args.provider, config, slot_date
    )
    print(f"模型顺序（{order_source}）：{' → '.join(order)}")
    attempt_dir.mkdir(parents=True, exist_ok=True)
    prompt_path = write_preopen_prompt(prepare_result, attempt_dir)
    last_fail = "没有已配置的模型路线"
    for provider in order:
        key, _source = resolve_api_key(provider, config)
        if not key:
            state["attempts"].append(
                {"provider": provider, "outcome": "skipped", "reason": "未启动（未配置，允许备用接替）",
                 "at": now_shanghai().isoformat(timespec="seconds")}
            )
            save_state(path, state)
            continue
        final_path = attempt_dir / f"final-{provider}.md"
        jsonl_path = attempt_dir / f"events-{provider}.jsonl"
        code, diag = run_task_agent(provider, prompt_path, final_path, jsonl_path, config, state, path)
        evidence = EvidenceBox.get(provider)
        state["last_model"] = evidence.get("model") or model_label(provider, config)
        state["model_evidence"] = evidence or {"verified": False, "note": "未取得模型证据"}
        if code == 0 and final_path.exists() and final_path.stat().st_size > 0:
            archive_dir = AI_ARCHIVE_DIR / "preopen" / slot_date.isoformat()
            archive_dir.mkdir(parents=True, exist_ok=True)
            target = archive_dir / "final-reply.md"
            shutil.copyfile(final_path, target)
            state["final_reply"] = str(target.relative_to(PROJECT_ROOT))
            state["archive"] = str(archive_dir.relative_to(PROJECT_ROOT))
            return finish_task(
                "preopen", path.name, state, "完整完成",
                f"模型（配置）{state['last_model']}；模型证据 "
                f"{json.dumps(state.get('model_evidence', {}), ensure_ascii=False)}；"
                f"已输出安全结论（含 {len(announcements)} 条新公告、{len(suspended)} 只停牌判断）。",
                EXIT_OK, stage="模型执行", extra={"provider": provider},
            )
        category, can_fallback = classify_failure(code, diag)
        state["attempts"][-1].update(outcome="failed", reason=f"{category}：{diag[-300:]}")
        save_state(path, state)
        last_fail = f"{provider}：{category}"
        if not can_fallback:
            break  # 本地/数据/取消类失败：不靠换模型掩盖

    tried = "、".join(
        f"{a.get('provider')}({a.get('outcome')})" for a in state.get("attempts", [])
        if a.get("provider")
    ) or "无已尝试路线"
    return finish_task(
        "preopen", path.name, state, "失败",
        f"实际尝试：{tried}；最后状态：{last_fail}。"
        "如需 Astra 补跑，请在 Codex App 中手动执行（读取 " + PREOPEN_PROMPT + "）。",
        EXIT_FAIL, stage="模型执行", log_dir=str(attempt_dir),
    )


# ---------------------------------------------------------------- 用户命令


def launchctl_labels() -> set[str]:
    try:
        result = subprocess.run(["launchctl", "list"], capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.TimeoutExpired):
        return set()
    return {line.split("\t")[-1] for line in result.stdout.splitlines() if line.strip()}


def _lock_holder_alive() -> bool:
    """锁文件记录的 pid 是否仍是存活进程（只读判断，不杀不夺锁）。"""
    try:
        text = LOCK_PATH.read_text(encoding="utf-8").strip()
    except OSError:
        return False
    if not text.isdigit():
        return False
    try:
        os.kill(int(text), 0)
    except OSError:
        return False
    return True


def cmd_status(_args: argparse.Namespace) -> int:
    config = load_local_config()
    now = now_shanghai()
    today = now.date()
    print("股票助手 AI 任务状态（{} 上海时间）".format(now.isoformat(timespec="seconds")))
    print()
    pref = default_preference(config)
    pref_text = {
        "auto": f"自动（{DEFAULT_ORDER_TEXT} 接替；Astra 仅手动）",
    }.get(pref, f"{PROVIDER_LABELS.get(pref, pref)} 优先")
    print(f"长期默认：{pref_text}")
    override = tonight_override(config, today)
    tonight = config.get("tonight")
    if override:
        print(f"今晚覆盖：{today.isoformat()} 晚间任务优先 {override}（失败后按默认顺序接替；长期默认不变）")
    elif isinstance(tonight, dict) and tonight.get("preference") in {"glm", "deepseek"}:
        print(f"今晚覆盖：{tonight.get('date')}（已过期，不再生效）")
    else:
        print("今晚覆盖：无")
    if LOCK_PATH.exists():
        holder = describe_lock_holder(LOCK_PATH.read_text(encoding="utf-8"))
        running = "仍在运行" in holder
        print(f"当前任务：{'运行中（' + holder + '）' if running else '空闲'}")
    else:
        print("当前任务：空闲")
    print()
    print("模型路线（自动接替顺序）：")
    for provider in DEFAULT_ORDER:
        verify = (config.get("verify") or {}).get(provider)
        verified_text = (
            f"已验证（{verify.get('at', '')[:16]}，配置 {verify.get('configured_model', '')}，"
            f"证据 {verify.get('evidence_model') or '未核验'}）"
            if verify and verify.get("ok") else "未验证（未做真实请求测试）"
        )
        _key, source = resolve_api_key(provider, config)
        print(
            f"  {provider}：ZCode CLI，模型 {model_ref(provider, config)}，"
            f"API {provider_base_url(provider, config)}，密钥来源：{source or '未找到'}，{verified_text}"
        )
    print("  手工补跑：在 Codex 中执行原 Prompt；本地启动器不调用 Astra。")
    print()
    entries = []
    if INDEX_PATH.exists():
        lines = INDEX_PATH.read_text(encoding="utf-8").splitlines()
        entries = [line for line in lines if line.strip()]
    parsed = []
    for line in entries:
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if entry.get("notification_update"):
            previous = next((old for old in reversed(parsed)
                             if old.get("recorded_at") == entry.get("recorded_at")
                             and old.get("task") == entry.get("task")
                             and old.get("slot") == entry.get("slot")), None)
            if previous is not None:
                previous.update(entry)
                continue
        parsed.append(entry)
    print("最近任务结果：")
    if not parsed:
        print("  暂无记录")
    for entry in parsed:
        print(
            "  {slot}：{result_status}（{detail}）".format(
                slot=entry.get("slot"),
                result_status=entry.get("result_status"),
                detail=(entry.get("detail") or "")[:80],
            )
        )
    # 旧 running 状态如实提示：确认无任务进程在运行时不自动重跑。
    stale = []
    if STATE_DIR.exists() and not _lock_holder_alive():
        for state_file in sorted(STATE_DIR.glob("*.json")):
            try:
                data = json.loads(state_file.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(data, dict) and data.get("status") == "running":
                stale.append(state_file.stem)
    if stale:
        print()
        print("注意：以下任务状态仍为 running，但当前没有任务进程在运行"
              "（上次异常遗留，不会自动重跑）：")
        for name in stale:
            print(f"  {name}")
    # 最近一次失败/需处理记录：日期、阶段、原因、已有产物与日志位置。
    attention = {"失败", "部分完成", "合并报告待修复", "研究已归档但展示待更新",
                 "完成但模型身份待核对", "已取消", "未执行（任务锁被占用）"}
    last_failure = next((e for e in reversed(parsed) if e.get("result_status") in attention), None)
    if last_failure:
        print()
        print("最近一次失败/需处理记录（也可直接让助手“查看最近一次失败原因”）：")
        print(f"  日期槽位：{last_failure.get('slot') or last_failure.get('task')}")
        print(f"  阶段：{last_failure.get('stage') or '未记录'}；结果：{last_failure.get('result_status')}")
        print(f"  原因：{(last_failure.get('detail') or '')[:160]}")
        print(f"  已有产物：{last_failure.get('final_reply') or '无'}")
        print(f"  日志：{last_failure.get('log_dir') or 'logs/ai_tasks/'}；记录：{INDEX_PATH.name}")
        print("  补跑：让助手按原 prepare 边界补跑，或在 Codex 中手动执行对应 Prompt。")
    print()
    launch_dir = Path.home() / "Library" / "LaunchAgents"
    loaded = launchctl_labels()
    for task, info in LAUNCHD_TASKS.items():
        plist_path = launch_dir / f"{info['label']}.plist"
        state_text = ["已安装" if plist_path.exists() else "未安装"]
        if info["label"] in loaded:
            state_text.append("已加载")
        print(f"计划 {task}（{info['hour']:02d}:{info['minute']:02d}）：{'，'.join(state_text)}")
    print()
    print("Codex automation 本地定义（历史对话仍显示不代表自动调度仍存在）：")
    automations_dir = Path.home() / ".codex" / "automations"
    found = False
    if automations_dir.exists():
        for auto_dir in sorted(automations_dir.iterdir()):
            cfg = auto_dir / "automation.toml"
            if not cfg.exists():
                continue
            found = True
            name_m = re.search(r'name\s*=\s*"([^"]+)"', cfg.read_text(encoding="utf-8"))
            status_m = re.search(r'status\s*=\s*"([^"]+)"', cfg.read_text(encoding="utf-8"))
            print(f"  {auto_dir.name}：{name_m.group(1) if name_m else auto_dir.name}"
                  f"（{status_m.group(1) if status_m else '状态未知'}）")
    if not found:
        print("  当前目录没有 Codex automation 定义。")
    print()
    print("结果与日志位置：local_archive/ai_tasks/（结果索引与最终回复）、logs/ai_tasks/（执行日志）。")
    return EXIT_OK


def cmd_use(args: argparse.Namespace) -> int:
    config = load_local_config()
    value = args.value
    if value == "auto":
        config["default_preference"] = "auto"
        config["tonight"] = None
        save_local_config(config)
        print(f"已设置：恢复默认 {DEFAULT_ORDER_TEXT}（自动接替不使用 Astra），并清除尚未执行的今晚覆盖。")
        return EXIT_OK
    config["default_preference"] = value
    save_local_config(config)
    rest = [p for p in DEFAULT_ORDER if p != value]
    text = f"已设置：长期默认 {value} 优先，失败后按 {' → '.join(rest)} 接替。"
    if tonight_override(config, now_shanghai().date()):
        text += f" 注意：今晚覆盖（{tonight_override(config, now_shanghai().date())} 优先）仍然生效，优先于长期默认。"
    print(text)
    return EXIT_OK


def cmd_tonight(args: argparse.Namespace) -> int:
    config = load_local_config()
    today = now_shanghai().date()
    if args.value == "clear":
        config["tonight"] = None
        save_local_config(config)
        print("已清除今晚覆盖；晚间任务恢复按长期默认顺序执行。")
        return EXIT_OK
    slot_state = load_state("nightly", today)
    if slot_state and slot_state.get("status") == "completed":
        result = slot_state.get("result", {})
        print(
            f"今晚（{today.isoformat()}）任务已经完成（{result.get('status')}），"
            "不会重新研究、不会中途更换模型。"
        )
        return EXIT_OK
    config["tonight"] = {"date": today.isoformat(), "preference": args.value}
    save_local_config(config)
    rest = [p for p in DEFAULT_ORDER if p != args.value]
    print(
        f"已设置：{today.isoformat()} 晚间任务优先 {args.value}，失败后按 {' → '.join(rest)} 接替；"
        "次晨提醒与长期默认不变。"
    )
    return EXIT_OK


# ---------------------------------------------------------------- 安装


def render_plist(task: str) -> bytes:
    info = LAUNCHD_TASKS[task]
    template = LAUNCHD_TEMPLATE_DIR / f"{info['label']}.plist.example"
    text = template.read_text(encoding="utf-8").replace("__PROJECT_ROOT__", str(PROJECT_ROOT))
    return text.encode("utf-8")


def cmd_install(args: argparse.Namespace) -> int:
    tz = Path("/etc/localtime").resolve().as_posix()
    if "Asia/Shanghai" not in tz:
        print(f"结果：未安装\n系统时区不是 Asia/Shanghai（/etc/localtime → {tz}），按现有规则停止安装，不自行改时区。")
        return EXIT_FAIL
    launch_dir = Path.home() / "Library" / "LaunchAgents"
    uid = os.getuid()
    plan = []
    for task, info in LAUNCHD_TASKS.items():
        target = launch_dir / f"{info['label']}.plist"
        plan.append((task, info, target, render_plist(task)))
    print("【安装预览】")
    for _task, info, target, _data in plan:
        print(f"  写入 {target}")
        print(f"  launchctl bootstrap gui/{uid} {target}（已存在则先 bootout 更新）")
        print(f"  计划时间每天 {info['hour']:02d}:{info['minute']:02d}，RunAtLoad=false，KeepAlive=false，不立即触发研究")
    if not args.apply:
        print("仅预览；确认后执行：./.venv/bin/python tools/stock_ai.py install --apply")
        return EXIT_OK
    launch_dir.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    loaded = launchctl_labels()
    for _task, info, target, data in plan:
        target.write_bytes(data)
        if info["label"] in loaded:
            subprocess.run(
                ["launchctl", "bootout", f"gui/{uid}", str(target)],
                capture_output=True, text=True,
            )
        result = subprocess.run(
            ["launchctl", "bootstrap", f"gui/{uid}", str(target)],
            capture_output=True, text=True,
        )
        if result.returncode != 0 and "already bootstrapped" not in result.stderr:
            print(f"结果：失败\nlaunchctl bootstrap {info['label']} 失败：{result.stderr.strip()}")
            return EXIT_FAIL
        print(f"已加载 {info['label']}")
    print("安装完成。日志写入 logs/ai_tasks/。")
    return EXIT_OK


def cmd_uninstall(_args: argparse.Namespace) -> int:
    uid = os.getuid()
    launch_dir = Path.home() / "Library" / "LaunchAgents"
    for info in LAUNCHD_TASKS.values():
        target = launch_dir / f"{info['label']}.plist"
        subprocess.run(
            ["launchctl", "bootout", f"gui/{uid}", str(target)],
            capture_output=True, text=True,
        )
        if target.exists():
            target.unlink()
        print(f"已移除 {info['label']}")
    print("卸载完成。恢复旧 Codex 定时方式见 ops/stock-ai-usage.md。")
    return EXIT_OK


# ---------------------------------------------------------------- 真实验证


def cmd_verify(args: argparse.Namespace) -> int:
    provider = args.provider
    config = load_local_config()
    key, source = resolve_api_key(provider, config)
    if not key:
        print(f"结果：未验证\n{provider} 缺少可用密钥，无法真实测试。")
        return EXIT_FAIL
    print(f"密钥来源：{source}")
    workspace = Path(tempfile.mkdtemp(prefix="stock-ai-verify-"))
    input_path = workspace / "verify-input.txt"
    input_path.write_text("输入数字：19\n", encoding="utf-8")
    expected = 19 * 6 + 7
    prompt = (
        "这是能力测试，不是研究任务。请：\n"
        f"1. 读取工作目录中的 verify-input.txt，取得其中的输入数字；\n"
        f"2. 用 python3 计算它乘以 6 再加 7；\n"
        f"3. 把『结果: <数字>』一行写入工作目录中的 result.txt；\n"
        "4. 简短报告完成后立即结束，不要做其他事，不要启动其他模型。\n"
    )
    prompt_path = workspace / "prompt.txt"
    prompt_path.write_text(prompt, encoding="utf-8")
    final_path = workspace / "final.md"
    jsonl_path = workspace / "events.jsonl"

    config_for_run = dict(config)
    config_for_run["_cwd"] = str(workspace)
    code, diag = run_agent(
        provider, prompt_path, final_path, jsonl_path,
        timeout_seconds=420, config=config_for_run,
    )
    result_path = workspace / "result.txt"
    result_text = result_path.read_text(encoding="utf-8").strip() if result_path.exists() else ""
    payload = parse_zcode_output(jsonl_path) or {}
    evidence = rollout_model_evidence(payload.get("sessionId"))
    evidence_model = evidence.get("model", "") or evidence.get("request_model", "")
    evidence_ok = route_evidence_matches(provider, evidence) is True
    ok = (
        code == 0
        and str(expected) in result_text
        and final_path.exists()
        and final_path.stat().st_size > 0
        and evidence_ok
    )
    record = {
        "at": now_shanghai().isoformat(timespec="seconds"),
        "ok": ok,
        "configured_model": model_label(provider, config),
        "evidence_model": evidence_model,
        "evidence_provider": evidence.get("provider", ""),
        "evidence_note": evidence.get("note", ""),
        "workspace": str(workspace),
    }
    fresh = load_local_config()
    fresh.setdefault("verify", {})[provider] = record
    save_local_config(fresh)
    if ok:
        print(f"结果：通过\n{provider} 真实执行成功：读取文件、执行计算（结果 {expected} 正确）、写出 result.txt 并正常结束。")
        print(f"配置模型：{record['configured_model']}；实际请求证据：provider={evidence.get('provider','')} "
              f"model={evidence_model}（{record['evidence_note']}）")
        return EXIT_OK
    print(f"结果：未通过\n退出码 {code}；result.txt={result_text[:100]!r}；模型证据：{evidence_model or '未核验'}；诊断：{diag[-400:]}")
    print(f"工作目录保留于 {workspace} 供检查。")
    return EXIT_FAIL


# ---------------------------------------------------------------- 入口


def dry_run_nightly(args: argparse.Namespace, config: dict) -> int:
    now = now_shanghai()
    today = now.date()
    order, source = resolve_provider_order("nightly", args.provider, config, today)
    prepare_args, _slot, rerun_date, _mode = nightly_prepare_plan(now, args)
    prepare_cmd = (
        f"{sys.executable} -m stock_analyzer.ops.forward_selection prepare "
        + " ".join(prepare_args)
    ).strip()
    print("【预览】晚间正式研究（不请求 API、不运行 prepare、不写任何产物）")
    print(f"任务：run nightly{' --scheduled' if args.scheduled else ''}")
    print(f"prepare 形态：{' '.join(prepare_args) if prepare_args else '无参（窗口内）'}"
          + (f"（补跑行动日 {rerun_date}）" if rerun_date else ""))
    print(f"模型顺序（{source}）：{' → '.join(order)}")
    for provider in order:
        _key, key_source = resolve_api_key(provider, config)
        print(f"  {provider}: ZCode CLI 模型 {model_ref(provider, config)}，密钥：{key_source or '未找到'}")
    print(f"Prompt 路径：{SELECTION_PROMPT}（含 {MONITOR_PROMPT}）")
    print("执行时限：无（执行到完成或明确失败；仅额度不足/不可用才接替）")
    print("计划动作：prepare → 按序无界面执行（每家一次）→ 同步命令核对归档 → 结果索引与通知")
    return EXIT_OK


def dry_run_preopen(args: argparse.Namespace, config: dict) -> int:
    today = now_shanghai().date()
    order, source = resolve_provider_order("preopen", args.provider, config, today)
    print("【预览】次晨安全提醒（不请求 API、不运行 prepare、不写任何产物）")
    print(f"任务：run preopen{' --scheduled' if args.scheduled else ''}")
    print(f"模型顺序（{source}）：{' → '.join(order)}")
    print(f"prepare 命令：{sys.executable} -m stock_analyzer.ops.preopen_safety prepare")
    print(f"Prompt 路径：{PREOPEN_PROMPT}")
    print("计划动作：prepare → 无需解释状态直接输出；仅新公告/停牌需判断时按序无界面执行")
    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="股票助手 AI 任务统一本地入口（模型切换、状态查询、定时任务执行）"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("status", help="查看当前默认、今晚覆盖、运行状态与最近结果（不请求 API）")

    use = sub.add_parser("use", help="修改长期默认模型偏好")
    use.add_argument("value", choices=["glm", "deepseek", "auto"])

    tonight = sub.add_parser("tonight", help="只修改今晚晚间任务的首选模型")
    tonight.add_argument("value", choices=["glm", "deepseek", "clear"])

    run = sub.add_parser("run", help="执行晚间研究或次晨提醒")
    run.add_argument("task", choices=["nightly", "preopen"])
    run.add_argument("--provider", choices=["glm", "deepseek"], default=None)
    run.add_argument("--rerun-date", default=None, metavar="YYYY-MM-DD",
                     help="原计划推荐日期（行动日）；与 forward_selection prepare 同义")
    run.add_argument("--scheduled", action="store_true",
                     help="由 launchd 调用；套用启动窗口检查")
    run.add_argument("--dry-run", action="store_true", help="只打印计划，不请求 API、不写产物")

    install = sub.add_parser("install", help="安装/更新两个 AI LaunchAgent（默认预览）")
    install.add_argument("--apply", action="store_true", help="实际写入并加载")
    install.set_defaults(func=cmd_install)

    sub.add_parser("uninstall", help="移除两个 AI LaunchAgent").set_defaults(func=cmd_uninstall)

    verify = sub.add_parser("verify", help="对一路模型做小型真实能力测试（隔离目录，含模型证据核验）")
    verify.add_argument("--provider", required=True, choices=["glm", "deepseek"])
    verify.set_defaults(func=cmd_verify)
    return parser


def _raise_signal_exit(signum: int, _frame: object) -> None:
    """SIGTERM → 按信号转为退出异常：经正常异常展开触发既有子进程组清理。
    处理函数内不写文件、不发通知。"""
    raise SystemExit(128 + signum)


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except (AttributeError, ValueError):
        pass
    args = build_parser().parse_args(argv)
    command = args.command
    if command == "status":
        return cmd_status(args)
    if command == "use":
        return cmd_use(args)
    if command == "tonight":
        return cmd_tonight(args)
    if command == "install":
        return cmd_install(args)
    if command == "uninstall":
        return cmd_uninstall(args)
    if command == "verify":
        return cmd_verify(args)
    config = load_local_config()
    if getattr(args, "dry_run", False):
        # dry-run 不取锁、不写状态、不运行 prepare/模型。
        if args.task == "nightly":
            return dry_run_nightly(args, config)
        return dry_run_preopen(args, config)
    lock = TaskLock()
    ok, holder = lock.acquire()
    if not ok:
        # 不覆盖持锁任务的状态，不杀它、不夺锁；只记录本次未执行并通知。
        detail = (f"已有 AI 任务在运行（{describe_lock_holder(holder)}），"
                  "本次启动未执行；原任务不受影响。")
        entry = {
            "task": args.task,
            "slot": args.rerun_date or now_shanghai().date().isoformat(),
            "recorded_at": now_shanghai().isoformat(timespec="microseconds"),
            "result_status": "未执行（任务锁被占用）",
            "detail": detail,
            "stage": "启动",
            "mac_notification": {"notified": False, "ok": False, "note": "已记录未执行，通知待提交"},
        }
        append_index(entry)
        notification = mac_notify_result(
            args.task, entry["slot"], entry["result_status"], detail, {})
        # 现有索引追加通知结果，不改持锁 state，也不重写其他任务的并发记录。
        append_index({**entry, "notification_update": True, "mac_notification": notification})
        print(f"结果：未执行（任务锁被占用）\n{detail}")
        return EXIT_LOCKED
    previous_handler = None
    try:
        previous_handler = signal.signal(signal.SIGTERM, _raise_signal_exit)
    except (ValueError, OSError):
        previous_handler = None
    try:
        if args.task == "nightly":
            return run_nightly(args, config, lock)
        return run_preopen(args, config, lock)
    except KeyboardInterrupt:
        return mark_terminal(args.task, "cancelled",
                             "任务被中断（SIGINT）；已停止本次子进程组，不自动接替或重跑。", 130)
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code, int) and exc.code else 143
        return mark_terminal(args.task, "cancelled",
                             f"任务被终止（退出码 {code}）；已停止本次子进程组，不自动接替或重跑。",
                             code)
    except Exception as exc:
        return mark_terminal(args.task, "failed",
                             f"启动器异常退出：{type(exc).__name__}: {exc}", EXIT_FAIL)
    finally:
        if previous_handler is not None:
            try:
                signal.signal(signal.SIGTERM, previous_handler)
            except (ValueError, OSError):
                pass
        lock.release()


if __name__ == "__main__":
    raise SystemExit(main())
