from __future__ import annotations

from html import escape
import json
import os
import re
import shutil
import subprocess
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, field_validator

from stock_analyzer.config import AppConfig
from stock_analyzer.ops.artifacts import DeployArtifactError, prepare_pages_artifact
from stock_analyzer.ops.notify import notify_mac
from stock_analyzer.ops.redaction import redact_secrets
from stock_analyzer.ops.smoke import smoke_report_site
from stock_analyzer.storage.capacity_guard import CapacityStatus


class PublishStatus(str, Enum):
    READY_SKIPPED = "ready_skipped"
    SUCCESS = "success"
    FAILED_RETRYABLE = "failed_retryable"
    FAILED_NEEDS_HUMAN = "failed_needs_human"


class PublishFailureClass(str, Enum):
    NO_PUBLISHABLE_REPORT = "no_publishable_report"
    ZERO_RECOMMENDATIONS = "zero_recommendations"
    NON_TRADING_DAY = "non_trading_day"
    SUPABASE_CAPACITY_STOP = "supabase_capacity_stop"
    CONFIG_MISSING = "config_missing"
    ARTIFACT_INVALID = "artifact_invalid"
    WRANGLER_TEMPORARY_FAILURE = "wrangler_temporary_failure"
    WRANGLER_AUTH_FAILURE = "wrangler_auth_failure"
    SMOKE_FAILED = "smoke_failed"
    ROLLBACK_FAILED = "rollback_failed"
    SECRET_LEAK_BLOCKED = "secret_leak_blocked"

    @property
    def retryable(self) -> bool:
        return self in {
            PublishFailureClass.WRANGLER_TEMPORARY_FAILURE,
            PublishFailureClass.SMOKE_FAILED,
        }


_MAX_PUBLISH_RECOMMENDATIONS = 10
_URL_PATTERN = re.compile(r"https://[^\s]+")
_ARTIFACT_SENSITIVE_VARIABLE_NAMES = (
    "SUPABASE_SERVICE_ROLE_KEY",
    "TUSHARE_TOKEN",
    "CLOUDFLARE_API_TOKEN",
    "DEEPSEEK_API_KEY",
    "BIYING_LICENCE",
)
_ARTIFACT_SECRET_PATTERNS = (
    *(
        re.compile(rf"\b{re.escape(name)}\b", re.IGNORECASE)
        for name in _ARTIFACT_SENSITIVE_VARIABLE_NAMES
    ),
    re.compile(r"\bAuthorization\s*:\s*Bearer\s+[^\s<>&;]+", re.IGNORECASE),
    re.compile(
        r"\b[A-Z0-9_]*(?:KEY|PASSWORD|SECRET|TOKEN)[A-Z0-9_]*\s*[:=]\s*"
        r"['\"]?[A-Za-z0-9._~+/=-]{8,}",
    ),
    re.compile(r"\bsb_secret_[A-Za-z0-9._~+/=-]{8,}", re.IGNORECASE),
)
_PLANNED_SKIP_FAILURE_CLASSES = {
    PublishFailureClass.NO_PUBLISHABLE_REPORT,
    PublishFailureClass.ZERO_RECOMMENDATIONS,
    PublishFailureClass.NON_TRADING_DAY,
}


class PublishPreflightError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        failure_class: PublishFailureClass,
        user_action_required: str,
    ) -> None:
        super().__init__(redact_secrets(message))
        self.failure_class = failure_class
        self.user_action_required = redact_secrets(user_action_required)


def build_publish_capacity_checker(config: AppConfig) -> Callable[[], CapacityStatus]:
    def check_capacity() -> CapacityStatus:
        if not config.has_supabase_config:
            raise PublishPreflightError(
                "Supabase capacity configuration is missing.",
                failure_class=PublishFailureClass.CONFIG_MISSING,
                user_action_required="发布配置不完整；请检查本机生产存储和发布配置。",
            )
        from stock_analyzer.storage.capacity_guard import SupabaseCapacityGuard
        from stock_analyzer.storage.supabase_client import create_supabase_client

        client = create_supabase_client(config)
        return SupabaseCapacityGuard(
            client,
            warn_mb=config.supabase_warn_mb,
            stop_mb=config.supabase_stop_mb,
        ).check()

    return check_capacity


class PublishMode(str, Enum):
    MANUAL_ONCE = "manual_once"
    AUTO = "auto"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class PublishState(BaseModel):
    trade_date: date | None
    status: PublishStatus
    mode: PublishMode
    started_at: datetime = Field(default_factory=_utc_now)
    finished_at: datetime | None = None
    published_url: str | None = None
    report_site_url: str | None = None
    recommendations: int | None = None
    failure_class: PublishFailureClass | None = None
    rollback_performed: bool = False
    auto_publish_enabled: bool = False
    last_known_good_path: str | None = None
    summary_for_user: str
    user_action_required: str | None = None
    error_message_redacted: str | None = None
    checks: tuple[str, ...] = ()

    @field_validator(
        "published_url",
        "report_site_url",
        "last_known_good_path",
        "summary_for_user",
        "user_action_required",
        "error_message_redacted",
    )
    @classmethod
    def _redact_text(cls, value: str | None) -> str | None:
        return redact_secrets(value) if value is not None else None

    def write_json(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = _redact_payload(self.model_dump(mode="json"))
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )


def render_publish_status_page(state: PublishState, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    trade_date_text = state.trade_date.isoformat() if state.trade_date else "暂无"
    problem_text = state.user_action_required or "无"
    if state.status == PublishStatus.SUCCESS:
        status_text = "成功"
    elif state.status == PublishStatus.READY_SKIPPED:
        status_text = "未发布"
    else:
        status_text = "需要处理"
    link_html = (
        f'<a href="{escape(state.report_site_url)}">{escape(state.report_site_url)}</a>'
        if state.report_site_url
        else "未配置"
    )
    html = f"""<!doctype html>
<html lang="zh-CN">
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>股票分析助手发布状态</title>
<body>
<h1>发布状态</h1>
<p>当前线上报告日期：{escape(trade_date_text)}</p>
<p>最近一次发布：{escape(status_text)}</p>
<p>线上报告链接：{link_html}</p>
<p>待处理问题：{escape(problem_text)}</p>
<p>{escape(state.summary_for_user)}</p>
</body>
</html>
"""
    output_path.write_text(html, encoding="utf-8")
    return output_path


@dataclass(frozen=True)
class PublishConfig:
    project_root: Path
    report_site_url: str
    cloudflare_pages_project_name: str
    report_password_env: str
    report_session_secret_env: str
    cloudflare_token_env: str
    cloudflare_account_id_env: str
    auto_publish_flag_path: Path
    state_path: Path
    status_page_path: Path
    last_known_good_dir: Path

    @classmethod
    def from_app_config(cls, config: AppConfig) -> "PublishConfig":
        root = config.project_root
        return cls(
            project_root=root,
            report_site_url=config.report_site_url or "",
            cloudflare_pages_project_name=config.cloudflare_pages_project_name or "",
            report_password_env=config.report_password_env,
            report_session_secret_env=config.report_session_secret_env,
            cloudflare_token_env=config.cloudflare_token_env,
            cloudflare_account_id_env=config.cloudflare_account_id_env,
            auto_publish_flag_path=root / "logs" / "publish" / "auto-publish-enabled.json",
            state_path=root / "logs" / "publish" / "latest-status.json",
            status_page_path=root / "logs" / "publish" / "status.html",
            last_known_good_dir=root / "local_archive" / "publish" / "last-known-good",
        )


@dataclass(frozen=True)
class PublishCandidate:
    trade_date: date
    recommendations: int
    job_status_path: Path
    reports_dir: Path


@dataclass(frozen=True)
class WranglerResult:
    exit_code: int
    stdout_redacted: str
    stderr_redacted: str
    deployment_url: str | None


def load_publish_candidate(
    config: PublishConfig,
    trade_date: date | None = None,
) -> PublishCandidate:
    status_path = config.project_root / "logs" / "run-daily" / "latest-status.json"
    if not status_path.is_file():
        raise PublishPreflightError(
            "No Phase 1 production status file was found.",
            failure_class=PublishFailureClass.NO_PUBLISHABLE_REPORT,
            user_action_required="今天还没有可发布报告；先等待生产流程成功完成。",
        )

    try:
        payload = json.loads(status_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PublishPreflightError(
            "Phase 1 production status file is malformed.",
            failure_class=PublishFailureClass.ARTIFACT_INVALID,
            user_action_required="生产状态文件无法读取；请先人工检查本机运行状态，暂不发布。",
        ) from exc
    if not isinstance(payload, dict):
        raise PublishPreflightError(
            "Phase 1 production status payload is not an object.",
            failure_class=PublishFailureClass.ARTIFACT_INVALID,
            user_action_required="生产状态文件格式异常；请先人工检查本机运行状态，暂不发布。",
        )
    try:
        status_trade_date = date.fromisoformat(str(payload.get("trade_date")))
    except (TypeError, ValueError) as exc:
        raise PublishPreflightError(
            "Phase 1 production status trade date is malformed.",
            failure_class=PublishFailureClass.ARTIFACT_INVALID,
            user_action_required="生产状态日期异常；请先人工检查本机运行状态，暂不发布。",
        ) from exc
    if trade_date is not None and status_trade_date != trade_date:
        raise PublishPreflightError(
            f"Latest production status is for {status_trade_date}, not {trade_date}.",
            failure_class=PublishFailureClass.NO_PUBLISHABLE_REPORT,
            user_action_required="今天还没有可发布报告；如需补发历史日期，请人工指定日期并先确认报告存在。",
        )

    run_status = str(payload.get("status"))
    recommendation_value = payload.get("recommendations")
    if run_status == "skipped_non_trading_day":
        raise PublishPreflightError(
            "Latest production status is non-trading day.",
            failure_class=PublishFailureClass.NON_TRADING_DAY,
            user_action_required="今天不是交易日，不发布新报告；线上保留上一版。",
        )

    recommendations = _parse_recommendation_count(recommendation_value)
    if run_status == "success_no_recommendations":
        if recommendations is None:
            raise PublishPreflightError(
                "Latest production zero-recommendation payload is malformed.",
                failure_class=PublishFailureClass.ARTIFACT_INVALID,
                user_action_required="生产状态和推荐数格式异常；请人工检查，先不要发布。",
            )
        if recommendations == 0:
            raise PublishPreflightError(
                "Latest production status has zero recommendations.",
                failure_class=PublishFailureClass.ZERO_RECOMMENDATIONS,
                user_action_required="当天无推荐，不发布新报告；线上保留上一版。",
            )
        raise PublishPreflightError(
            "Latest production status has an invalid zero-recommendation payload.",
            failure_class=PublishFailureClass.NO_PUBLISHABLE_REPORT,
            user_action_required="生产状态和推荐数不一致；请人工检查，先不要发布。",
        )
    if run_status != "success_with_recommendations":
        raise PublishPreflightError(
            f"Latest production status is {run_status}.",
            failure_class=PublishFailureClass.NO_PUBLISHABLE_REPORT,
            user_action_required="今天生产流程还没有成功完成，暂不发布。",
        )
    if recommendations is None:
        raise PublishPreflightError(
            "Latest production recommendation count is malformed.",
            failure_class=PublishFailureClass.ARTIFACT_INVALID,
            user_action_required="生产状态推荐数格式异常；请人工检查，先不要发布。",
        )
    if recommendations == 0:
        raise PublishPreflightError(
            "Latest production status has zero recommendations.",
            failure_class=PublishFailureClass.ZERO_RECOMMENDATIONS,
            user_action_required="当天无推荐，不发布新报告；线上保留上一版。",
        )
    if not 1 <= recommendations <= _MAX_PUBLISH_RECOMMENDATIONS:
        raise PublishPreflightError(
            f"Latest production recommendation count is {recommendation_value!r}.",
            failure_class=PublishFailureClass.NO_PUBLISHABLE_REPORT,
            user_action_required="推荐数异常，超出 1 到 10 的发布范围；请人工检查，先不要发布。",
        )

    reports_dir = config.project_root / "reports"
    daily_index = reports_dir / "daily" / status_trade_date.isoformat() / "index.html"
    if not (reports_dir / "index.html").is_file() or not daily_index.is_file():
        raise PublishPreflightError(
            "Report files are missing.",
            failure_class=PublishFailureClass.NO_PUBLISHABLE_REPORT,
            user_action_required="报告文件缺失；请先重新生成当天报告。",
        )

    return PublishCandidate(
        trade_date=status_trade_date,
        recommendations=recommendations,
        job_status_path=status_path,
        reports_dir=reports_dir,
    )


def preflight_publish(
    config: PublishConfig,
    candidate: PublishCandidate,
    *,
    env: Mapping[str, str] | None = None,
    capacity_checker: Callable[[], CapacityStatus] | None = None,
) -> tuple[str, ...]:
    values = os.environ if env is None else env
    missing_count = 0
    if not config.report_site_url:
        missing_count += 1
    if not config.cloudflare_pages_project_name:
        missing_count += 1
    for env_name in (
        config.report_password_env,
        config.report_session_secret_env,
        config.cloudflare_token_env,
        config.cloudflare_account_id_env,
    ):
        if not str(values.get(env_name, "")).strip():
            missing_count += 1
    if missing_count:
        raise PublishPreflightError(
            f"Missing publish configuration ({missing_count} item(s)).",
            failure_class=PublishFailureClass.CONFIG_MISSING,
            user_action_required="发布配置不完整；请检查本机 .env.local 中的 Cloudflare 和报告密码配置。",
        )

    checks = ["config_present"]
    if capacity_checker is not None:
        try:
            capacity = capacity_checker()
        except PublishPreflightError:
            raise
        except Exception as exc:
            raise PublishPreflightError(
                "Supabase capacity check failed.",
                failure_class=PublishFailureClass.SUPABASE_CAPACITY_STOP,
                user_action_required="Supabase 容量检查失败；请人工检查生产数据库连接和容量。",
            ) from exc
        checks.append(f"supabase_capacity={capacity.size_mb:.1f}MB")
        if capacity.stop_large_writes:
            raise PublishPreflightError(
                f"Supabase capacity stop at {capacity.size_mb:.1f} MB.",
                failure_class=PublishFailureClass.SUPABASE_CAPACITY_STOP,
                user_action_required=(
                    f"Supabase 容量已到 {capacity.size_mb:.1f} MB，停止发布；"
                    "请先处理容量问题。"
                ),
            )
    return tuple(checks)


def prepare_publish_artifact(
    config: PublishConfig,
    prepare_artifact: Callable[[Path, Path], Path] | None = None,
) -> Path:
    output_dir = config.project_root / "dist" / "pages"
    if output_dir.exists():
        shutil.rmtree(output_dir)
    prepare_func = prepare_artifact or prepare_pages_artifact
    return prepare_func(config.project_root, output_dir)


def validate_publish_artifact_content(artifact_dir: Path) -> None:
    if not artifact_dir.is_dir():
        raise PublishPreflightError(
            "Deploy artifact directory was not created.",
            failure_class=PublishFailureClass.ARTIFACT_INVALID,
            user_action_required="发布包没有生成成功；请先重新生成报告发布包。",
        )
    for path in sorted(artifact_dir.rglob("*")):
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            text = path.read_bytes().decode("utf-8", errors="ignore")
        except OSError as exc:
            raise PublishPreflightError(
                "Deploy artifact could not be scanned.",
                failure_class=PublishFailureClass.ARTIFACT_INVALID,
                user_action_required="发布包无法完成本地安全扫描；请先人工检查发布包。",
            ) from exc
        for pattern in _ARTIFACT_SECRET_PATTERNS:
            if pattern.search(text):
                raise PublishPreflightError(
                    "Sensitive content detected in deploy artifact.",
                    failure_class=PublishFailureClass.SECRET_LEAK_BLOCKED,
                    user_action_required=(
                        "发布包疑似包含凭据或敏感配置；请重新生成报告并人工检查发布包，"
                        "确认没有密钥内容后再发布。"
                    ),
                )


def run_wrangler_deploy(
    config: PublishConfig,
    artifact_dir: Path,
    *,
    env: Mapping[str, str] | None = None,
    runner: Callable[..., subprocess.CompletedProcess[str]] | None = None,
) -> WranglerResult:
    command = [
        "npx",
        "wrangler",
        "pages",
        "deploy",
        str(artifact_dir),
        "--project-name",
        config.cloudflare_pages_project_name,
    ]
    values = dict(os.environ if env is None else env)
    run = runner or subprocess.run
    completed = run(
        command,
        cwd=config.project_root,
        env=values,
        text=True,
        capture_output=True,
        check=False,
    )
    stdout = redact_secrets(completed.stdout or "", explicit_secrets=values.values())
    stderr = redact_secrets(completed.stderr or "", explicit_secrets=values.values())
    deployment_url = _extract_deployment_url(f"{stdout}\n{stderr}")
    return WranglerResult(
        exit_code=int(completed.returncode),
        stdout_redacted=stdout,
        stderr_redacted=stderr,
        deployment_url=deployment_url,
    )


def is_auto_publish_enabled(config: PublishConfig) -> bool:
    if not config.auto_publish_flag_path.is_file():
        return False
    try:
        payload = json.loads(config.auto_publish_flag_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if not isinstance(payload, dict):
        return False
    return bool(payload.get("enabled"))


def set_auto_publish_enabled(config: PublishConfig, enabled: bool) -> None:
    config.auto_publish_flag_path.parent.mkdir(parents=True, exist_ok=True)
    config.auto_publish_flag_path.write_text(
        json.dumps({"enabled": enabled}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def publish_report_site(
    config: PublishConfig,
    *,
    mode: PublishMode,
    trade_date: date | None = None,
    env: Mapping[str, str] | None = None,
    capacity_checker: Callable[[], CapacityStatus] | None = None,
    prepare_artifact: Callable[[Path, Path], Path] | None = None,
    deploy_runner: Callable[..., WranglerResult] | None = None,
    smoke_func: Callable[..., Any] | None = None,
    notify_func: Callable[..., Any] | None = None,
    notify_enabled: bool = False,
) -> PublishState:
    started_at = _utc_now()
    checks: list[str] = []
    values = os.environ if env is None else env
    candidate: PublishCandidate | None = None

    try:
        candidate = load_publish_candidate(config, trade_date=trade_date)
        checks.extend(
            preflight_publish(
                config,
                candidate,
                env=values,
                capacity_checker=capacity_checker,
            )
        )

        artifact_dir = prepare_publish_artifact(config, prepare_artifact=prepare_artifact)
        checks.append("artifact_prepared")
        validate_publish_artifact_content(artifact_dir)
        checks.append("artifact_secret_scan_passed")

        try:
            deploy = _deploy_with_one_retry(
                config,
                artifact_dir,
                env=values,
                deploy_runner=deploy_runner,
            )
        except Exception as exc:
            return _write_publish_failure(
                config,
                mode,
                started_at,
                candidate,
                PublishFailureClass.WRANGLER_TEMPORARY_FAILURE,
                "发布失败：Cloudflare 上传过程中出现异常。",
                "请检查 Cloudflare 配置和本机网络后再重试。",
                checks,
                rollback_performed=False,
                error_message=str(exc),
                notify_func=notify_func,
                notify_enabled=notify_enabled,
            )
        checks.append("wrangler_deployed")
        if deploy.exit_code != 0:
            return _write_publish_failure(
                config,
                mode,
                started_at,
                candidate,
                _classify_wrangler_failure(deploy),
                "发布失败：Cloudflare 上传没有成功。",
                "请检查 Cloudflare 凭据、项目名和网络连接后再重试。",
                checks,
                rollback_performed=False,
                error_message=deploy.stderr_redacted or deploy.stdout_redacted,
                notify_func=notify_func,
                notify_enabled=notify_enabled,
            )

        try:
            smoke = (smoke_func or smoke_report_site)(
                config.report_site_url,
                values.get(config.report_password_env),
                expected_trade_date=candidate.trade_date,
            )
        except Exception as exc:
            return _write_publish_failure(
                config,
                mode,
                started_at,
                candidate,
                PublishFailureClass.SMOKE_FAILED,
                "发布后线上检查异常，系统未确认新站点可用。",
                "请查看本地发布状态页，并人工检查线上报告访问。",
                checks,
                rollback_performed=False,
                error_message=str(exc),
                notify_func=notify_func,
                notify_enabled=notify_enabled,
            )
        checks.extend(smoke.checks)
        if not smoke.passed:
            rollback_error = None
            try:
                rollback_ok = _rollback_last_known_good(
                    config,
                    values,
                    deploy_runner,
                    smoke_func,
                )
            except Exception as exc:
                rollback_ok = False
                rollback_error = str(exc)
            summary = (
                "发布后线上检查失败，系统已回退上一版正常报告。"
                if rollback_ok
                else "发布后线上检查失败，且自动回退失败。"
            )
            return _write_publish_failure(
                config,
                mode,
                started_at,
                candidate,
                PublishFailureClass.SMOKE_FAILED
                if rollback_ok
                else PublishFailureClass.ROLLBACK_FAILED,
                summary,
                "请查看本地发布状态页，并检查 Cloudflare 密码配置或报告日期。",
                checks,
                rollback_performed=rollback_ok,
                error_message=rollback_error or smoke.fix_suggestion,
                notify_func=notify_func,
                notify_enabled=notify_enabled,
            )

        _save_last_known_good(artifact_dir, config.last_known_good_dir)
        set_auto_publish_enabled(config, True)
        state = PublishState(
            trade_date=candidate.trade_date,
            status=PublishStatus.SUCCESS,
            mode=mode,
            started_at=started_at,
            finished_at=_utc_now(),
            published_url=deploy.deployment_url or config.report_site_url,
            report_site_url=config.report_site_url,
            recommendations=candidate.recommendations,
            failure_class=None,
            rollback_performed=False,
            auto_publish_enabled=True,
            last_known_good_path=str(config.last_known_good_dir),
            summary_for_user=(
                f"发布成功：线上报告 {candidate.trade_date.isoformat()}，"
                f"链接：{config.report_site_url}"
            ),
            user_action_required=None,
            error_message_redacted=None,
            checks=tuple(checks),
        )
        state.write_json(config.state_path)
        render_publish_status_page(state, config.status_page_path)
        return state
    except DeployArtifactError as exc:
        return _write_publish_failure(
            config,
            mode,
            started_at,
            candidate,
            PublishFailureClass.ARTIFACT_INVALID,
            "发布包生成失败，系统未上传到 Cloudflare。",
            "请先重新生成报告发布包，并人工确认发布包完整。",
            checks,
            rollback_performed=False,
            error_message=str(exc),
            notify_func=notify_func,
            notify_enabled=notify_enabled,
        )
    except PublishPreflightError as exc:
        status = _status_for_preflight_failure(exc.failure_class)
        state = PublishState(
            trade_date=trade_date,
            status=status,
            mode=mode,
            started_at=started_at,
            finished_at=_utc_now(),
            published_url=None,
            report_site_url=config.report_site_url,
            recommendations=None,
            failure_class=exc.failure_class,
            rollback_performed=False,
            auto_publish_enabled=is_auto_publish_enabled(config),
            last_known_good_path=(
                str(config.last_known_good_dir) if config.last_known_good_dir.exists() else None
            ),
            summary_for_user=str(exc),
            user_action_required=exc.user_action_required,
            error_message_redacted=str(exc),
            checks=tuple(checks),
        )
        state.write_json(config.state_path)
        render_publish_status_page(state, config.status_page_path)
        if status == PublishStatus.FAILED_NEEDS_HUMAN:
            _notify_publish_failure_if_enabled(
                state,
                notify_func=notify_func,
                notify_enabled=notify_enabled,
            )
        return state


def _extract_deployment_url(text: str) -> str | None:
    for match in _URL_PATTERN.finditer(text):
        value = match.group(0).rstrip(".,)")
        if ".pages.dev" in value:
            return value
    return None


def _deploy_with_one_retry(
    config: PublishConfig,
    artifact_dir: Path,
    *,
    env: Mapping[str, str],
    deploy_runner: Callable[..., WranglerResult] | None,
) -> WranglerResult:
    deploy_func = deploy_runner or run_wrangler_deploy
    first = deploy_func(config, artifact_dir, env=env)
    if first.exit_code == 0 or not _is_temporary_wrangler_failure(first):
        return first
    return deploy_func(config, artifact_dir, env=env)


def _rollback_last_known_good(
    config: PublishConfig,
    env: Mapping[str, str],
    deploy_runner: Callable[..., WranglerResult] | None,
    smoke_func: Callable[..., Any] | None,
) -> bool:
    if not config.last_known_good_dir.is_dir():
        return False
    deploy_func = deploy_runner or run_wrangler_deploy
    deploy = deploy_func(config, config.last_known_good_dir, env=env)
    if deploy.exit_code != 0:
        return False
    smoke = (smoke_func or smoke_report_site)(
        config.report_site_url,
        env.get(config.report_password_env),
        expected_trade_date=None,
    )
    return bool(smoke.passed)


def _write_publish_failure(
    config: PublishConfig,
    mode: PublishMode,
    started_at: datetime,
    candidate: PublishCandidate,
    failure_class: PublishFailureClass,
    summary: str,
    user_action_required: str,
    checks: list[str],
    *,
    rollback_performed: bool,
    error_message: str | None,
    notify_func: Callable[..., Any] | None,
    notify_enabled: bool,
) -> PublishState:
    state = PublishState(
        trade_date=candidate.trade_date,
        status=PublishStatus.FAILED_NEEDS_HUMAN,
        mode=mode,
        started_at=started_at,
        finished_at=_utc_now(),
        published_url=None,
        report_site_url=config.report_site_url,
        recommendations=candidate.recommendations,
        failure_class=failure_class,
        rollback_performed=rollback_performed,
        auto_publish_enabled=is_auto_publish_enabled(config),
        last_known_good_path=str(config.last_known_good_dir)
        if config.last_known_good_dir.exists()
        else None,
        summary_for_user=summary,
        user_action_required=user_action_required,
        error_message_redacted=error_message,
        checks=tuple(checks),
    )
    state.write_json(config.state_path)
    render_publish_status_page(state, config.status_page_path)
    _notify_publish_failure_if_enabled(
        state,
        notify_func=notify_func,
        notify_enabled=notify_enabled,
    )
    return state


def _status_for_preflight_failure(
    failure_class: PublishFailureClass,
) -> PublishStatus:
    if failure_class in _PLANNED_SKIP_FAILURE_CLASSES:
        return PublishStatus.READY_SKIPPED
    return PublishStatus.FAILED_NEEDS_HUMAN


def _notify_publish_failure_if_enabled(
    state: PublishState,
    *,
    notify_func: Callable[..., Any] | None,
    notify_enabled: bool,
) -> None:
    if notify_enabled:
        try:
            (notify_func or notify_mac)(
                "股票分析助手发布需要处理",
                state.summary_for_user,
                enabled=True,
            )
        except Exception:
            pass


def _is_temporary_wrangler_failure(result: WranglerResult) -> bool:
    combined = f"{result.stdout_redacted}\n{result.stderr_redacted}".lower()
    return any(
        marker in combined
        for marker in ("timeout", "temporar", "network", "5xx", "econnreset")
    )


def _classify_wrangler_failure(result: WranglerResult) -> PublishFailureClass:
    combined = f"{result.stdout_redacted}\n{result.stderr_redacted}".lower()
    if _is_temporary_wrangler_failure(result):
        return PublishFailureClass.WRANGLER_TEMPORARY_FAILURE
    if any(marker in combined for marker in ("auth", "unauthorized", "forbidden", "token")):
        return PublishFailureClass.WRANGLER_AUTH_FAILURE
    return PublishFailureClass.WRANGLER_TEMPORARY_FAILURE


def _replace_tree(source: Path, target: Path) -> None:
    if source.resolve() == target.resolve():
        return
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(source, target)


def _save_last_known_good(artifact_dir: Path, target_dir: Path) -> None:
    target_dir.parent.mkdir(parents=True, exist_ok=True)
    _replace_tree(artifact_dir, target_dir)


def _redact_payload(value: Any) -> Any:
    if isinstance(value, str):
        return redact_secrets(value)
    if isinstance(value, list):
        return [_redact_payload(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_redact_payload(item) for item in value)
    if isinstance(value, dict):
        return {key: _redact_payload(item) for key, item in value.items()}
    return value


def _parse_recommendation_count(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
