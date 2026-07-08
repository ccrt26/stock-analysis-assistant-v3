# 股票分析助手 V3 MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 构建一个可以每日自动运行的中国大陆 A 股分析助手 MVP，完成数据获取、清洗、规则约束、候选推荐、重点关注、证据包、后评估登记、静态报告生成，并为 Supabase 与 Cloudflare Pages 部署打好边界。

**Architecture:** Python 负责数据、分析、状态机、证据包、报告生成；Supabase Postgres 作为主事实库，Supabase Storage 保存证据包和选择性原始快照；Cloudflare Pages 只发布静态报告和密码访问层。第一阶段使用小而可运行的模块，不复刻第二版多角色大系统。

**Tech Stack:** Python 3.11+、Typer、Pydantic、Pandas、Jinja2、PyYAML、HTTPX、Supabase Python client、pytest、Supabase SQL migrations、Cloudflare Pages Functions TypeScript。

## Global Constraints

- 项目根目录固定为 `/Users/ccrt/股票分析助手`。
- 日常主命令固定为 `python -m stock_analyzer run-daily`。
- 固定报告入口为 `/Users/ccrt/股票分析助手/reports/index.html`。
- 每日推荐最多 10 只；不足 10 只时不得降低标准凑数。
- 重点关注池可以为空，也可以少于 10 只。
- 推荐语言只能使用：`进入观察`、`继续观察`、`高风险观察`、`降级观察`、`剔除观察`、`数据不足，不形成结论`。
- 大模型只能基于结构化证据改写解释，不能直接读取全市场原始表，不能覆盖硬约束。
- Supabase 是主事实库；本地文件只保存代码、迁移、模板、开发缓存和显式导出。
- Cloudflare Pages 只暴露报告内容，不暴露 token、原始 API、内部日志、规则编辑、数据库后台。
- 后评估必须区分结果评估、方法评估、知识评估，5/20/40 日只是检查点，不是唯一目标。
- 每个任务完成后运行对应测试并提交。

---

## File Structure

- Create: `/Users/ccrt/股票分析助手/pyproject.toml`  
  Python 包、命令、依赖、pytest 配置。
- Create: `/Users/ccrt/股票分析助手/.gitignore`  
  排除 secrets、本地缓存、报告临时文件、`.DS_Store`。
- Create: `/Users/ccrt/股票分析助手/README.md`  
  运行方式、环境变量、Supabase 与 Cloudflare 边界。
- Create: `/Users/ccrt/股票分析助手/src/stock_analyzer/__main__.py`  
  `python -m stock_analyzer` 入口。
- Create: `/Users/ccrt/股票分析助手/src/stock_analyzer/cli.py`  
  Typer CLI，包含 `run-daily`、`health-check`、`render-report`。
- Create: `/Users/ccrt/股票分析助手/src/stock_analyzer/config.py`  
  配置读取、密钥路径、运行日期、环境变量。
- Create: `/Users/ccrt/股票分析助手/src/stock_analyzer/domain/models.py`  
  股票、特征、推荐、关注状态、证据包、评估任务的数据模型。
- Create: `/Users/ccrt/股票分析助手/src/stock_analyzer/data/health.py`  
  凭证、网络、API 响应、字段可用性的四类健康检查。
- Create: `/Users/ccrt/股票分析助手/src/stock_analyzer/data/tushare_source.py`  
  Tushare 连接与字段标准化。
- Create: `/Users/ccrt/股票分析助手/src/stock_analyzer/data/free_sources.py`  
  免费源接口占位实现，先支持健康检查和可扩展协议。
- Create: `/Users/ccrt/股票分析助手/src/stock_analyzer/storage/supabase_client.py`  
  Supabase client 工厂，不在前端暴露 service key。
- Create: `/Users/ccrt/股票分析助手/src/stock_analyzer/storage/repositories.py`  
  数据库写入接口与内存实现，测试先用内存实现。
- Create: `/Users/ccrt/股票分析助手/src/stock_analyzer/knowledge/rule_schema.py`  
  知识规则 schema、加载、校验。
- Create: `/Users/ccrt/股票分析助手/src/stock_analyzer/knowledge/rules.seed.yaml`  
  第一批正式启用规则，先放硬约束、解释、反证、评估钩子。
- Create: `/Users/ccrt/股票分析助手/src/stock_analyzer/analysis/pool.py`  
  全 A 清洗与风险排除。
- Create: `/Users/ccrt/股票分析助手/src/stock_analyzer/analysis/scoring.py`  
  稳健趋势评分和候选排序。
- Create: `/Users/ccrt/股票分析助手/src/stock_analyzer/analysis/recommendation.py`  
  每日推荐生成、最多 10 只、近似入选记录。
- Create: `/Users/ccrt/股票分析助手/src/stock_analyzer/analysis/focus.py`  
  重点关注状态机。
- Create: `/Users/ccrt/股票分析助手/src/stock_analyzer/analysis/evidence.py`  
  证据包生成与原始理由冻结。
- Create: `/Users/ccrt/股票分析助手/src/stock_analyzer/evaluation/tasks.py`  
  5/20/40 日检查点登记、结果/方法/知识评估记录。
- Create: `/Users/ccrt/股票分析助手/src/stock_analyzer/reports/generator.py`  
  静态 HTML 和 JSON 报告生成。
- Create: `/Users/ccrt/股票分析助手/src/stock_analyzer/reports/templates/index.html.j2`  
  首页报告模板。
- Create: `/Users/ccrt/股票分析助手/src/stock_analyzer/reports/templates/stock.html.j2`  
  单股报告模板。
- Create: `/Users/ccrt/股票分析助手/supabase/migrations/202607070001_init_core.sql`  
  初始数据表、索引、RLS 启用。
- Create: `/Users/ccrt/股票分析助手/functions/_middleware.ts`  
  Cloudflare Pages 简单密码门。
- Create: `/Users/ccrt/股票分析助手/tests/fixtures/sample_market.py`  
  小型 A 股样本数据。
- Create: `/Users/ccrt/股票分析助手/tests/**`  
  每个模块的单元测试和一个端到端冒烟测试。

---

### Task 1: 项目骨架与 CLI

**Files:**
- Create: `/Users/ccrt/股票分析助手/pyproject.toml`
- Create: `/Users/ccrt/股票分析助手/.gitignore`
- Create: `/Users/ccrt/股票分析助手/src/stock_analyzer/__init__.py`
- Create: `/Users/ccrt/股票分析助手/src/stock_analyzer/__main__.py`
- Create: `/Users/ccrt/股票分析助手/src/stock_analyzer/cli.py`
- Test: `/Users/ccrt/股票分析助手/tests/test_cli.py`

**Interfaces:**
- Produces: `stock_analyzer.cli.app: typer.Typer`
- Produces: CLI command `python -m stock_analyzer health-check`
- Produces: CLI command `python -m stock_analyzer run-daily --dry-run`

- [ ] **Step 1: Write the failing CLI test**

```python
# /Users/ccrt/股票分析助手/tests/test_cli.py
from typer.testing import CliRunner

from stock_analyzer.cli import app


def test_health_check_command_prints_status():
    result = CliRunner().invoke(app, ["health-check"])
    assert result.exit_code == 0
    assert "credential" in result.stdout
    assert "network" in result.stdout
    assert "api_response" in result.stdout
    assert "field_consumability" in result.stdout


def test_run_daily_dry_run_completes():
    result = CliRunner().invoke(app, ["run-daily", "--dry-run", "--trade-date", "2026-07-07"])
    assert result.exit_code == 0
    assert "daily run dry-run completed for 2026-07-07" in result.stdout
```

- [ ] **Step 2: Run the failing test**

Run: `pytest /Users/ccrt/股票分析助手/tests/test_cli.py -v`  
Expected: FAIL because `stock_analyzer` package does not exist.

- [ ] **Step 3: Create minimal package and CLI**

```python
# /Users/ccrt/股票分析助手/src/stock_analyzer/__main__.py
from .cli import app

if __name__ == "__main__":
    app()
```

```python
# /Users/ccrt/股票分析助手/src/stock_analyzer/cli.py
from datetime import date

import typer

app = typer.Typer(no_args_is_help=True)


@app.command("health-check")
def health_check() -> None:
    typer.echo("credential: unchecked")
    typer.echo("network: unchecked")
    typer.echo("api_response: unchecked")
    typer.echo("field_consumability: unchecked")


@app.command("run-daily")
def run_daily(
    dry_run: bool = typer.Option(False, "--dry-run"),
    trade_date: date = typer.Option(..., "--trade-date"),
) -> None:
    if dry_run:
        typer.echo(f"daily run dry-run completed for {trade_date.isoformat()}")
        return
    typer.echo(f"daily run completed for {trade_date.isoformat()}")
```

- [ ] **Step 4: Add Python project config**

```toml
# /Users/ccrt/股票分析助手/pyproject.toml
[build-system]
requires = ["setuptools>=69", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "stock-analysis-assistant"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
  "httpx>=0.27",
  "jinja2>=3.1",
  "numpy>=1.26",
  "pandas>=2.2",
  "pydantic>=2.7",
  "python-dotenv>=1.0",
  "pyyaml>=6.0",
  "supabase>=2.6",
  "typer>=0.12",
]

[project.optional-dependencies]
dev = ["pytest>=8.2", "pytest-cov>=5.0"]
data = ["tushare>=1.4.19", "akshare>=1.14"]

[tool.setuptools.packages.find]
where = ["src"]

[tool.pytest.ini_options]
pythonpath = ["src"]
testpaths = ["tests"]
```

```gitignore
# /Users/ccrt/股票分析助手/.gitignore
.DS_Store
__pycache__/
.pytest_cache/
.venv/
.env
.env.*
!.env.example
reports/
data/cache/
data/raw/
*.pyc
```

- [ ] **Step 5: Run tests**

Run: `pytest /Users/ccrt/股票分析助手/tests/test_cli.py -v`  
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml .gitignore src tests/test_cli.py
git commit -m "feat: add project scaffold and cli"
```

---

### Task 2: 配置、密钥边界与健康检查

**Files:**
- Create: `/Users/ccrt/股票分析助手/src/stock_analyzer/config.py`
- Modify: `/Users/ccrt/股票分析助手/src/stock_analyzer/cli.py`
- Create: `/Users/ccrt/股票分析助手/src/stock_analyzer/data/health.py`
- Test: `/Users/ccrt/股票分析助手/tests/test_config_health.py`

**Interfaces:**
- Produces: `AppConfig.load(env: Mapping[str, str] | None = None) -> AppConfig`
- Produces: `HealthReport.as_lines() -> list[str]`
- Produces: `run_health_checks(config: AppConfig) -> HealthReport`
- Consumes: CLI `health-check`

- [ ] **Step 1: Write failing config and health tests**

```python
# /Users/ccrt/股票分析助手/tests/test_config_health.py
from pathlib import Path

from stock_analyzer.config import AppConfig
from stock_analyzer.data.health import HealthStatus, run_health_checks


def test_config_uses_home_tushare_token_path_when_env_missing():
    config = AppConfig.load(env={})
    assert config.tushare_token_path == Path("/Users/ccrt/.tushare_token")
    assert config.supabase_url is None
    assert config.supabase_service_role_key is None


def test_health_report_has_four_required_categories():
    config = AppConfig.load(env={})
    report = run_health_checks(config)
    categories = {item.category for item in report.items}
    assert categories == {"credential", "network", "api_response", "field_consumability"}
    assert all(item.status in {HealthStatus.OK, HealthStatus.WARN, HealthStatus.FAIL} for item in report.items)
```

- [ ] **Step 2: Run failing tests**

Run: `pytest /Users/ccrt/股票分析助手/tests/test_config_health.py -v`  
Expected: FAIL because config and health modules do not exist.

- [ ] **Step 3: Implement config**

```python
# /Users/ccrt/股票分析助手/src/stock_analyzer/config.py
from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping

from pydantic import BaseModel


class AppConfig(BaseModel):
    project_root: Path = Path("/Users/ccrt/股票分析助手")
    tushare_token_path: Path = Path("/Users/ccrt/.tushare_token")
    supabase_url: str | None = None
    supabase_service_role_key: str | None = None
    reports_dir: Path = Path("/Users/ccrt/股票分析助手/reports")

    @classmethod
    def load(cls, env: Mapping[str, str] | None = None) -> "AppConfig":
        values = os.environ if env is None else env
        return cls(
            tushare_token_path=Path(values.get("TUSHARE_TOKEN_PATH", "/Users/ccrt/.tushare_token")),
            supabase_url=values.get("SUPABASE_URL"),
            supabase_service_role_key=values.get("SUPABASE_SERVICE_ROLE_KEY"),
        )
```

- [ ] **Step 4: Implement health checks**

```python
# /Users/ccrt/股票分析助手/src/stock_analyzer/data/health.py
from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel

from stock_analyzer.config import AppConfig


class HealthStatus(StrEnum):
    OK = "ok"
    WARN = "warn"
    FAIL = "fail"


class HealthItem(BaseModel):
    category: str
    status: HealthStatus
    message: str


class HealthReport(BaseModel):
    items: list[HealthItem]

    def as_lines(self) -> list[str]:
        return [f"{item.category}: {item.status} - {item.message}" for item in self.items]


def run_health_checks(config: AppConfig) -> HealthReport:
    credential_status = HealthStatus.OK if config.tushare_token_path.exists() else HealthStatus.FAIL
    supabase_status = HealthStatus.OK if config.supabase_url and config.supabase_service_role_key else HealthStatus.WARN
    return HealthReport(
        items=[
            HealthItem(category="credential", status=credential_status, message="checked local token path"),
            HealthItem(category="network", status=HealthStatus.WARN, message="network probe not executed in unit mode"),
            HealthItem(category="api_response", status=supabase_status, message="supabase env checked"),
            HealthItem(category="field_consumability", status=HealthStatus.WARN, message="no live schema sample loaded"),
        ]
    )
```

- [ ] **Step 5: Wire CLI health-check**

```python
# /Users/ccrt/股票分析助手/src/stock_analyzer/cli.py
from datetime import date

import typer

from stock_analyzer.config import AppConfig
from stock_analyzer.data.health import run_health_checks

app = typer.Typer(no_args_is_help=True)


@app.command("health-check")
def health_check() -> None:
    report = run_health_checks(AppConfig.load())
    for line in report.as_lines():
        typer.echo(line)


@app.command("run-daily")
def run_daily(
    dry_run: bool = typer.Option(False, "--dry-run"),
    trade_date: date = typer.Option(..., "--trade-date"),
) -> None:
    if dry_run:
        typer.echo(f"daily run dry-run completed for {trade_date.isoformat()}")
        return
    typer.echo(f"daily run completed for {trade_date.isoformat()}")
```

- [ ] **Step 6: Run tests**

Run: `pytest /Users/ccrt/股票分析助手/tests/test_config_health.py /Users/ccrt/股票分析助手/tests/test_cli.py -v`  
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/stock_analyzer/config.py src/stock_analyzer/data/health.py src/stock_analyzer/cli.py tests/test_config_health.py tests/test_cli.py
git commit -m "feat: add config and health checks"
```

---

### Task 3: 领域模型与 Supabase schema

**Files:**
- Create: `/Users/ccrt/股票分析助手/src/stock_analyzer/domain/models.py`
- Create: `/Users/ccrt/股票分析助手/supabase/migrations/202607070001_init_core.sql`
- Test: `/Users/ccrt/股票分析助手/tests/test_domain_models.py`
- Test: `/Users/ccrt/股票分析助手/tests/test_supabase_schema.py`

**Interfaces:**
- Produces: `StockSnapshot`
- Produces: `FeatureSnapshot`
- Produces: `Recommendation`
- Produces: `FocusState`
- Produces: `EvidencePackage`
- Produces: `EvaluationTask`
- Produces: SQL tables named in design section 13

- [ ] **Step 1: Write failing model tests**

```python
# /Users/ccrt/股票分析助手/tests/test_domain_models.py
from datetime import date

import pytest

from stock_analyzer.domain.models import ActionLabel, Recommendation, StockSnapshot


def test_recommendation_allows_only_approved_action_labels():
    rec = Recommendation(
        trade_date=date(2026, 7, 7),
        ts_code="600000.SH",
        name="浦发银行",
        action=ActionLabel.ENTER_OBSERVATION,
        score=72.5,
        reasons=["趋势改善", "流动性充足"],
        risks=["银行板块弹性有限"],
    )
    assert rec.action.value == "进入观察"


def test_stock_snapshot_flags_st_stock():
    stock = StockSnapshot(
        trade_date=date(2026, 7, 7),
        ts_code="000001.SZ",
        name="*ST 示例",
        is_st=True,
        is_suspended=False,
        listing_days=500,
        turnover_rate=1.2,
        amount=300_000_000,
    )
    assert stock.is_hard_excluded is True


def test_invalid_action_label_rejected():
    with pytest.raises(ValueError):
        Recommendation(
            trade_date=date(2026, 7, 7),
            ts_code="600000.SH",
            name="浦发银行",
            action="买入",
            score=88,
            reasons=[],
            risks=[],
        )
```

- [ ] **Step 2: Write failing schema test**

```python
# /Users/ccrt/股票分析助手/tests/test_supabase_schema.py
from pathlib import Path


def test_initial_schema_contains_required_tables_and_rls():
    sql = Path("/Users/ccrt/股票分析助手/supabase/migrations/202607070001_init_core.sql").read_text()
    for table in [
        "market_calendar",
        "stock_master",
        "stock_status_daily",
        "daily_feature_snapshot",
        "recommendation_daily",
        "focus_watchlist_state",
        "evidence_package_index",
        "knowledge_rule",
        "knowledge_rule_match",
        "evaluation_task",
        "evaluation_result",
        "data_source_run",
    ]:
        assert f"create table if not exists public.{table}" in sql.lower()
        assert f"alter table public.{table} enable row level security" in sql.lower()
```

- [ ] **Step 3: Implement domain models**

```python
# /Users/ccrt/股票分析助手/src/stock_analyzer/domain/models.py
from __future__ import annotations

from datetime import date
from enum import StrEnum

from pydantic import BaseModel, Field


class ActionLabel(StrEnum):
    ENTER_OBSERVATION = "进入观察"
    CONTINUE_OBSERVATION = "继续观察"
    HIGH_RISK_OBSERVATION = "高风险观察"
    DOWNGRADE_OBSERVATION = "降级观察"
    EXIT_OBSERVATION = "剔除观察"
    INSUFFICIENT_DATA = "数据不足，不形成结论"


class StockSnapshot(BaseModel):
    trade_date: date
    ts_code: str
    name: str
    is_st: bool = False
    is_suspended: bool = False
    has_delisting_risk: bool = False
    listing_days: int
    turnover_rate: float | None = None
    amount: float | None = None
    official_risk_events: list[str] = Field(default_factory=list)

    @property
    def is_hard_excluded(self) -> bool:
        low_liquidity = (self.turnover_rate is not None and self.turnover_rate < 0.2) or (
            self.amount is not None and self.amount < 50_000_000
        )
        return any(
            [
                self.is_st,
                self.is_suspended,
                self.has_delisting_risk,
                self.listing_days < 120,
                low_liquidity,
                bool(self.official_risk_events),
            ]
        )


class FeatureSnapshot(BaseModel):
    trade_date: date
    ts_code: str
    trend_20d: float
    trend_60d: float
    relative_strength: float
    volatility_20d: float
    liquidity_score: float
    quality_score: float
    market_regime: str
    industry: str | None = None
    data_quality: str = "ok"


class Recommendation(BaseModel):
    trade_date: date
    ts_code: str
    name: str
    action: ActionLabel
    score: float
    reasons: list[str]
    risks: list[str]
    evidence_id: str | None = None


class FocusState(BaseModel):
    trade_date: date
    ts_code: str
    state: ActionLabel
    entry_date: date | None = None
    entry_reason: str | None = None
    invalidation_conditions: list[str] = Field(default_factory=list)
    exit_reason: str | None = None


class EvidencePackage(BaseModel):
    evidence_id: str
    trade_date: date
    ts_code: str
    thesis: str
    support: list[str]
    counter_evidence: list[str]
    matched_rules: list[str]
    invalidation_conditions: list[str]
    source_versions: dict[str, str]


class EvaluationTask(BaseModel):
    trade_date: date
    ts_code: str
    evidence_id: str
    checkpoint_days: int
    evaluation_layer: str
```

- [ ] **Step 4: Create Supabase migration**

```sql
-- /Users/ccrt/股票分析助手/supabase/migrations/202607070001_init_core.sql
create extension if not exists pgcrypto;

create table if not exists public.market_calendar (
  trade_date date primary key,
  is_trading_day boolean not null,
  market text not null default 'CN_A'
);

create table if not exists public.stock_master (
  ts_code text primary key,
  name text not null,
  exchange text not null,
  list_date date
);

create table if not exists public.stock_status_daily (
  trade_date date not null,
  ts_code text not null references public.stock_master(ts_code),
  is_st boolean not null default false,
  is_suspended boolean not null default false,
  has_delisting_risk boolean not null default false,
  listing_days integer not null,
  turnover_rate numeric,
  amount numeric,
  official_risk_events jsonb not null default '[]'::jsonb,
  primary key (trade_date, ts_code)
);

create table if not exists public.daily_feature_snapshot (
  trade_date date not null,
  ts_code text not null references public.stock_master(ts_code),
  features jsonb not null,
  rule_hits jsonb not null default '[]'::jsonb,
  data_quality text not null,
  primary key (trade_date, ts_code)
);

create table if not exists public.recommendation_daily (
  id uuid primary key default gen_random_uuid(),
  trade_date date not null,
  ts_code text not null references public.stock_master(ts_code),
  action text not null,
  score numeric not null,
  reasons jsonb not null,
  risks jsonb not null,
  evidence_id text not null,
  created_at timestamptz not null default now()
);

create table if not exists public.focus_watchlist_state (
  id uuid primary key default gen_random_uuid(),
  trade_date date not null,
  ts_code text not null references public.stock_master(ts_code),
  state text not null,
  entry_date date,
  entry_reason text,
  invalidation_conditions jsonb not null default '[]'::jsonb,
  exit_reason text,
  created_at timestamptz not null default now()
);

create table if not exists public.evidence_package_index (
  evidence_id text primary key,
  trade_date date not null,
  ts_code text not null references public.stock_master(ts_code),
  storage_path text not null,
  sha256 text not null,
  created_at timestamptz not null default now()
);

create table if not exists public.knowledge_rule (
  rule_id text primary key,
  source_grade text not null,
  rule_type text not null,
  source_reference text not null,
  payload jsonb not null,
  enabled boolean not null default true
);

create table if not exists public.knowledge_rule_match (
  id uuid primary key default gen_random_uuid(),
  trade_date date not null,
  ts_code text not null,
  rule_id text not null references public.knowledge_rule(rule_id),
  match_reason text not null
);

create table if not exists public.evaluation_task (
  id uuid primary key default gen_random_uuid(),
  trade_date date not null,
  ts_code text not null,
  evidence_id text not null,
  checkpoint_days integer not null,
  evaluation_layer text not null,
  due_date date not null,
  status text not null default 'pending'
);

create table if not exists public.evaluation_result (
  id uuid primary key default gen_random_uuid(),
  evaluation_task_id uuid not null references public.evaluation_task(id),
  result_payload jsonb not null,
  created_at timestamptz not null default now()
);

create table if not exists public.data_source_run (
  id uuid primary key default gen_random_uuid(),
  trade_date date not null,
  source_name text not null,
  status text not null,
  message text not null,
  created_at timestamptz not null default now()
);

alter table public.market_calendar enable row level security;
alter table public.stock_master enable row level security;
alter table public.stock_status_daily enable row level security;
alter table public.daily_feature_snapshot enable row level security;
alter table public.recommendation_daily enable row level security;
alter table public.focus_watchlist_state enable row level security;
alter table public.evidence_package_index enable row level security;
alter table public.knowledge_rule enable row level security;
alter table public.knowledge_rule_match enable row level security;
alter table public.evaluation_task enable row level security;
alter table public.evaluation_result enable row level security;
alter table public.data_source_run enable row level security;
```

- [ ] **Step 5: Run tests**

Run: `pytest /Users/ccrt/股票分析助手/tests/test_domain_models.py /Users/ccrt/股票分析助手/tests/test_supabase_schema.py -v`  
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/stock_analyzer/domain/models.py supabase/migrations/202607070001_init_core.sql tests/test_domain_models.py tests/test_supabase_schema.py
git commit -m "feat: add domain models and initial supabase schema"
```

---

### Task 4: 测试样本、股票池清洗与硬约束排除

**Files:**
- Create: `/Users/ccrt/股票分析助手/tests/fixtures/sample_market.py`
- Create: `/Users/ccrt/股票分析助手/src/stock_analyzer/analysis/pool.py`
- Test: `/Users/ccrt/股票分析助手/tests/test_pool_filtering.py`

**Interfaces:**
- Consumes: `StockSnapshot`
- Produces: `clean_stock_pool(stocks: list[StockSnapshot]) -> tuple[list[StockSnapshot], list[StockSnapshot]]`

- [ ] **Step 1: Write fixture and failing tests**

```python
# /Users/ccrt/股票分析助手/tests/fixtures/sample_market.py
from datetime import date

from stock_analyzer.domain.models import StockSnapshot


def sample_stocks() -> list[StockSnapshot]:
    trade_date = date(2026, 7, 7)
    return [
        StockSnapshot(trade_date=trade_date, ts_code="600000.SH", name="稳健样本", listing_days=3000, turnover_rate=1.1, amount=400_000_000),
        StockSnapshot(trade_date=trade_date, ts_code="000001.SZ", name="*ST 风险", is_st=True, listing_days=3000, turnover_rate=1.1, amount=400_000_000),
        StockSnapshot(trade_date=trade_date, ts_code="300001.SZ", name="次新样本", listing_days=60, turnover_rate=3.0, amount=500_000_000),
        StockSnapshot(trade_date=trade_date, ts_code="600001.SH", name="低流动性", listing_days=3000, turnover_rate=0.1, amount=20_000_000),
    ]
```

```python
# /Users/ccrt/股票分析助手/tests/test_pool_filtering.py
from stock_analyzer.analysis.pool import clean_stock_pool
from tests.fixtures.sample_market import sample_stocks


def test_clean_stock_pool_excludes_hard_risks():
    included, excluded = clean_stock_pool(sample_stocks())
    assert [stock.ts_code for stock in included] == ["600000.SH"]
    assert {stock.ts_code for stock in excluded} == {"000001.SZ", "300001.SZ", "600001.SH"}
```

- [ ] **Step 2: Run failing test**

Run: `pytest /Users/ccrt/股票分析助手/tests/test_pool_filtering.py -v`  
Expected: FAIL because `analysis.pool` does not exist.

- [ ] **Step 3: Implement pool filtering**

```python
# /Users/ccrt/股票分析助手/src/stock_analyzer/analysis/pool.py
from __future__ import annotations

from stock_analyzer.domain.models import StockSnapshot


def clean_stock_pool(stocks: list[StockSnapshot]) -> tuple[list[StockSnapshot], list[StockSnapshot]]:
    included: list[StockSnapshot] = []
    excluded: list[StockSnapshot] = []
    for stock in stocks:
        if stock.is_hard_excluded:
            excluded.append(stock)
        else:
            included.append(stock)
    return included, excluded
```

- [ ] **Step 4: Run tests**

Run: `pytest /Users/ccrt/股票分析助手/tests/test_pool_filtering.py /Users/ccrt/股票分析助手/tests/test_domain_models.py -v`  
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/stock_analyzer/analysis/pool.py tests/fixtures/sample_market.py tests/test_pool_filtering.py
git commit -m "feat: add stock pool hard constraint filtering"
```

---

### Task 5: 知识规则 schema 与第一批正式规则

**Files:**
- Create: `/Users/ccrt/股票分析助手/src/stock_analyzer/knowledge/rule_schema.py`
- Create: `/Users/ccrt/股票分析助手/src/stock_analyzer/knowledge/rules.seed.yaml`
- Test: `/Users/ccrt/股票分析助手/tests/test_knowledge_rules.py`

**Interfaces:**
- Produces: `KnowledgeRule`
- Produces: `load_rules(path: Path) -> list[KnowledgeRule]`
- Produces: rule fields `rule_id`, `source_reference`, `source_grade`, `rule_type`, `applicable_scenarios`, `forbidden_scenarios`, `data_requirements`, `report_phrasing`, `evaluation_method`, `downgrade_conditions`

- [ ] **Step 1: Write failing tests**

```python
# /Users/ccrt/股票分析助手/tests/test_knowledge_rules.py
from pathlib import Path

from stock_analyzer.knowledge.rule_schema import load_rules


def test_seed_rules_have_required_fields():
    rules = load_rules(Path("/Users/ccrt/股票分析助手/src/stock_analyzer/knowledge/rules.seed.yaml"))
    assert len(rules) >= 4
    for rule in rules:
        assert rule.rule_id
        assert rule.source_reference
        assert rule.source_grade in {"S", "A", "B"}
        assert rule.rule_type in {"hard_constraint", "explanation", "counter_evidence", "evaluation"}
        assert rule.data_requirements
        assert rule.evaluation_method


def test_official_s_rule_can_be_hard_constraint():
    rules = load_rules(Path("/Users/ccrt/股票分析助手/src/stock_analyzer/knowledge/rules.seed.yaml"))
    official_rules = [rule for rule in rules if rule.source_grade == "S" and rule.rule_type == "hard_constraint"]
    assert {rule.rule_id for rule in official_rules} >= {"OFFICIAL_ST_EXCLUDE", "OFFICIAL_DELISTING_RISK_EXCLUDE"}
```

- [ ] **Step 2: Run failing tests**

Run: `pytest /Users/ccrt/股票分析助手/tests/test_knowledge_rules.py -v`  
Expected: FAIL because knowledge module does not exist.

- [ ] **Step 3: Implement rule schema**

```python
# /Users/ccrt/股票分析助手/src/stock_analyzer/knowledge/rule_schema.py
from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel


class KnowledgeRule(BaseModel):
    rule_id: str
    source_reference: str
    source_grade: Literal["S", "A", "B"]
    rule_type: Literal["hard_constraint", "explanation", "counter_evidence", "evaluation"]
    applicable_scenarios: list[str]
    forbidden_scenarios: list[str]
    data_requirements: list[str]
    report_phrasing: str
    evaluation_method: str
    downgrade_conditions: list[str]


def load_rules(path: Path) -> list[KnowledgeRule]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    return [KnowledgeRule.model_validate(item) for item in payload["rules"]]
```

- [ ] **Step 4: Add seed rules**

```yaml
# /Users/ccrt/股票分析助手/src/stock_analyzer/knowledge/rules.seed.yaml
rules:
  - rule_id: OFFICIAL_ST_EXCLUDE
    source_reference: "沪深交易所风险警示与退市相关规则"
    source_grade: S
    rule_type: hard_constraint
    applicable_scenarios: ["股票被标记 ST 或 *ST"]
    forbidden_scenarios: ["仅因短期波动被市场讨论"]
    data_requirements: ["stock_status_daily.is_st"]
    report_phrasing: "该股票触发风险警示硬约束，系统不形成积极观察结论。"
    evaluation_method: "检查被排除股票是否出现高波动诱导信号，评估硬约束是否阻止了高风险误报。"
    downgrade_conditions: ["官方规则口径变化", "数据源 ST 标识长期错误"]
  - rule_id: OFFICIAL_DELISTING_RISK_EXCLUDE
    source_reference: "沪深交易所退市与重大风险提示相关规则"
    source_grade: S
    rule_type: hard_constraint
    applicable_scenarios: ["存在退市风险或重大官方风险事件"]
    forbidden_scenarios: ["普通业绩波动但没有官方风险标识"]
    data_requirements: ["stock_status_daily.has_delisting_risk", "stock_status_daily.official_risk_events"]
    report_phrasing: "该股票存在官方重大风险边界，系统剔除观察。"
    evaluation_method: "复盘被剔除标的后续风险扩散情况，验证硬约束覆盖率。"
    downgrade_conditions: ["风险事件字段误判率超过 20%", "官方规则口径变化"]
  - rule_id: RESEARCH_TREND_CONFIRMATION
    source_reference: "技术交易规则在中国市场表现研究"
    source_grade: A
    rule_type: explanation
    applicable_scenarios: ["20 日趋势与 60 日趋势同向", "相对强度高于市场中位数"]
    forbidden_scenarios: ["涨停后一日孤立冲高", "成交额低于流动性阈值"]
    data_requirements: ["daily_feature_snapshot.features.trend_20d", "daily_feature_snapshot.features.trend_60d", "daily_feature_snapshot.features.relative_strength"]
    report_phrasing: "趋势证据支持继续观察，但不能单独构成推荐。"
    evaluation_method: "按市场 regime 分组评估趋势信号在 5/20/40 日的相对收益和失效率。"
    downgrade_conditions: ["连续两个市场 regime 中假突破率高于 60%"]
  - rule_id: COUNTER_LOW_LIQUIDITY_NOISE
    source_reference: "成交量与流动性风险研究"
    source_grade: A
    rule_type: counter_evidence
    applicable_scenarios: ["成交额偏低", "换手率极低", "价格信号来自少量成交"]
    forbidden_scenarios: ["成交额连续高于阈值且盘口稳定"]
    data_requirements: ["stock_status_daily.turnover_rate", "stock_status_daily.amount"]
    report_phrasing: "流动性不足削弱价格信号可信度。"
    evaluation_method: "比较低流动性候选与正常流动性候选的假信号率。"
    downgrade_conditions: ["低流动性过滤导致稳定错过高质量机会且跨样本成立"]
```

- [ ] **Step 5: Run tests**

Run: `pytest /Users/ccrt/股票分析助手/tests/test_knowledge_rules.py -v`  
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/stock_analyzer/knowledge/rule_schema.py src/stock_analyzer/knowledge/rules.seed.yaml tests/test_knowledge_rules.py
git commit -m "feat: add knowledge rule schema and seed rules"
```

---

### Task 6: 轻量特征、稳健评分与每日推荐

**Files:**
- Create: `/Users/ccrt/股票分析助手/src/stock_analyzer/analysis/scoring.py`
- Create: `/Users/ccrt/股票分析助手/src/stock_analyzer/analysis/recommendation.py`
- Test: `/Users/ccrt/股票分析助手/tests/test_recommendation.py`

**Interfaces:**
- Consumes: `FeatureSnapshot`
- Produces: `score_feature(feature: FeatureSnapshot) -> float`
- Produces: `generate_recommendations(features: list[FeatureSnapshot], stock_names: dict[str, str], limit: int = 10) -> RecommendationResult`
- Produces: `RecommendationResult.recommendations`
- Produces: `RecommendationResult.near_misses`

- [ ] **Step 1: Write failing recommendation tests**

```python
# /Users/ccrt/股票分析助手/tests/test_recommendation.py
from datetime import date

from stock_analyzer.analysis.recommendation import generate_recommendations
from stock_analyzer.domain.models import ActionLabel, FeatureSnapshot


def feature(ts_code: str, trend20: float, trend60: float, rs: float, liquidity: float, quality: float) -> FeatureSnapshot:
    return FeatureSnapshot(
        trade_date=date(2026, 7, 7),
        ts_code=ts_code,
        trend_20d=trend20,
        trend_60d=trend60,
        relative_strength=rs,
        volatility_20d=0.25,
        liquidity_score=liquidity,
        quality_score=quality,
        market_regime="sideways",
        industry="测试行业",
        data_quality="ok",
    )


def test_generate_recommendations_caps_at_10_and_records_near_misses():
    features = [feature(f"600{i:03d}.SH", 0.08, 0.12, 0.7, 0.8, 0.7) for i in range(15)]
    names = {item.ts_code: f"样本{i}" for i, item in enumerate(features)}
    result = generate_recommendations(features, names, limit=10)
    assert len(result.recommendations) == 10
    assert len(result.near_misses) == 5
    assert all(item.action == ActionLabel.ENTER_OBSERVATION for item in result.recommendations)


def test_generate_recommendations_does_not_fill_quota_with_weak_scores():
    features = [feature("600000.SH", 0.01, -0.01, 0.2, 0.8, 0.7)]
    result = generate_recommendations(features, {"600000.SH": "弱样本"}, limit=10)
    assert result.recommendations == []
    assert result.near_misses == []
```

- [ ] **Step 2: Run failing tests**

Run: `pytest /Users/ccrt/股票分析助手/tests/test_recommendation.py -v`  
Expected: FAIL because recommendation module does not exist.

- [ ] **Step 3: Implement scoring**

```python
# /Users/ccrt/股票分析助手/src/stock_analyzer/analysis/scoring.py
from __future__ import annotations

from stock_analyzer.domain.models import FeatureSnapshot


def score_feature(feature: FeatureSnapshot) -> float:
    trend_score = max(feature.trend_20d, 0) * 250 + max(feature.trend_60d, 0) * 180
    strength_score = feature.relative_strength * 30
    liquidity_score = feature.liquidity_score * 20
    quality_score = feature.quality_score * 20
    volatility_penalty = max(feature.volatility_20d - 0.35, 0) * 60
    return round(trend_score + strength_score + liquidity_score + quality_score - volatility_penalty, 2)
```

- [ ] **Step 4: Implement recommendation generation**

```python
# /Users/ccrt/股票分析助手/src/stock_analyzer/analysis/recommendation.py
from __future__ import annotations

from pydantic import BaseModel

from stock_analyzer.analysis.scoring import score_feature
from stock_analyzer.domain.models import ActionLabel, FeatureSnapshot, Recommendation


class RecommendationResult(BaseModel):
    recommendations: list[Recommendation]
    near_misses: list[Recommendation]


def generate_recommendations(
    features: list[FeatureSnapshot],
    stock_names: dict[str, str],
    limit: int = 10,
    threshold: float = 70.0,
    near_miss_threshold: float = 60.0,
) -> RecommendationResult:
    scored = sorted(((score_feature(item), item) for item in features if item.data_quality == "ok"), reverse=True, key=lambda pair: pair[0])
    recommendations: list[Recommendation] = []
    near_misses: list[Recommendation] = []
    for score, feature in scored:
        rec = Recommendation(
            trade_date=feature.trade_date,
            ts_code=feature.ts_code,
            name=stock_names.get(feature.ts_code, feature.ts_code),
            action=ActionLabel.ENTER_OBSERVATION,
            score=score,
            reasons=["20 日与 60 日趋势改善", "相对强度和流动性满足观察要求"],
            risks=["需要后续确认趋势不是一日噪声"],
        )
        if score >= threshold and len(recommendations) < limit:
            recommendations.append(rec)
        elif score >= near_miss_threshold:
            near_misses.append(rec)
    return RecommendationResult(recommendations=recommendations, near_misses=near_misses)
```

- [ ] **Step 5: Run tests**

Run: `pytest /Users/ccrt/股票分析助手/tests/test_recommendation.py -v`  
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/stock_analyzer/analysis/scoring.py src/stock_analyzer/analysis/recommendation.py tests/test_recommendation.py
git commit -m "feat: add robust scoring and daily recommendations"
```

---

### Task 7: 重点关注状态机

**Files:**
- Create: `/Users/ccrt/股票分析助手/src/stock_analyzer/analysis/focus.py`
- Test: `/Users/ccrt/股票分析助手/tests/test_focus_state_machine.py`

**Interfaces:**
- Consumes: `Recommendation`
- Consumes: `FocusState`
- Produces: `update_focus_watchlist(existing: list[FocusState], recommendations: list[Recommendation], invalidated_codes: set[str]) -> list[FocusState]`

- [ ] **Step 1: Write failing state-machine tests**

```python
# /Users/ccrt/股票分析助手/tests/test_focus_state_machine.py
from datetime import date

from stock_analyzer.analysis.focus import update_focus_watchlist
from stock_analyzer.domain.models import ActionLabel, FocusState, Recommendation


def rec(code: str, score: float = 82.0) -> Recommendation:
    return Recommendation(
        trade_date=date(2026, 7, 7),
        ts_code=code,
        name=code,
        action=ActionLabel.ENTER_OBSERVATION,
        score=score,
        reasons=["趋势持续", "行业支持"],
        risks=["需要确认"],
    )


def test_recommendation_enters_focus_only_when_score_strong():
    result = update_focus_watchlist(existing=[], recommendations=[rec("600000.SH", 82)], invalidated_codes=set())
    assert len(result) == 1
    assert result[0].state == ActionLabel.ENTER_OBSERVATION
    assert result[0].entry_date == date(2026, 7, 7)


def test_existing_focus_continues_when_not_recommended_today():
    existing = [
        FocusState(
            trade_date=date(2026, 7, 6),
            ts_code="600000.SH",
            state=ActionLabel.ENTER_OBSERVATION,
            entry_date=date(2026, 7, 6),
            entry_reason="原始证据成立",
            invalidation_conditions=["跌破关键支撑"],
        )
    ]
    result = update_focus_watchlist(existing=existing, recommendations=[], invalidated_codes=set())
    assert result[0].state == ActionLabel.CONTINUE_OBSERVATION


def test_invalidated_focus_exits():
    existing = [
        FocusState(
            trade_date=date(2026, 7, 6),
            ts_code="600000.SH",
            state=ActionLabel.ENTER_OBSERVATION,
            entry_date=date(2026, 7, 6),
            entry_reason="原始证据成立",
            invalidation_conditions=["跌破关键支撑"],
        )
    ]
    result = update_focus_watchlist(existing=existing, recommendations=[], invalidated_codes={"600000.SH"})
    assert result[0].state == ActionLabel.EXIT_OBSERVATION
    assert result[0].exit_reason == "触发预设失效条件"
```

- [ ] **Step 2: Run failing tests**

Run: `pytest /Users/ccrt/股票分析助手/tests/test_focus_state_machine.py -v`  
Expected: FAIL because focus module does not exist.

- [ ] **Step 3: Implement focus state machine**

```python
# /Users/ccrt/股票分析助手/src/stock_analyzer/analysis/focus.py
from __future__ import annotations

from stock_analyzer.domain.models import ActionLabel, FocusState, Recommendation


def update_focus_watchlist(
    existing: list[FocusState],
    recommendations: list[Recommendation],
    invalidated_codes: set[str],
    enter_threshold: float = 80.0,
) -> list[FocusState]:
    by_code = {item.ts_code: item for item in existing}
    output: list[FocusState] = []

    for old in existing:
        if old.ts_code in invalidated_codes:
            output.append(
                old.model_copy(
                    update={
                        "state": ActionLabel.EXIT_OBSERVATION,
                        "exit_reason": "触发预设失效条件",
                    }
                )
            )
        else:
            output.append(old.model_copy(update={"state": ActionLabel.CONTINUE_OBSERVATION}))

    for rec in recommendations:
        if rec.ts_code in by_code or rec.score < enter_threshold:
            continue
        output.append(
            FocusState(
                trade_date=rec.trade_date,
                ts_code=rec.ts_code,
                state=ActionLabel.ENTER_OBSERVATION,
                entry_date=rec.trade_date,
                entry_reason="推荐分数强且支持证据满足重点关注门槛",
                invalidation_conditions=["核心趋势证据消失", "出现官方重大风险", "反证强于支持证据"],
            )
        )
    return output
```

- [ ] **Step 4: Run tests**

Run: `pytest /Users/ccrt/股票分析助手/tests/test_focus_state_machine.py -v`  
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/stock_analyzer/analysis/focus.py tests/test_focus_state_machine.py
git commit -m "feat: add focus watchlist state machine"
```

---

### Task 8: 证据包冻结与评估任务登记

**Files:**
- Create: `/Users/ccrt/股票分析助手/src/stock_analyzer/analysis/evidence.py`
- Create: `/Users/ccrt/股票分析助手/src/stock_analyzer/evaluation/tasks.py`
- Test: `/Users/ccrt/股票分析助手/tests/test_evidence_evaluation.py`

**Interfaces:**
- Consumes: `Recommendation`
- Produces: `build_evidence_package(recommendation: Recommendation, matched_rules: list[str]) -> EvidencePackage`
- Produces: `create_evaluation_tasks(package: EvidencePackage) -> list[EvaluationTask]`

- [ ] **Step 1: Write failing tests**

```python
# /Users/ccrt/股票分析助手/tests/test_evidence_evaluation.py
from datetime import date

from stock_analyzer.analysis.evidence import build_evidence_package
from stock_analyzer.domain.models import ActionLabel, Recommendation
from stock_analyzer.evaluation.tasks import create_evaluation_tasks


def test_evidence_package_freezes_original_reasoning():
    rec = Recommendation(
        trade_date=date(2026, 7, 7),
        ts_code="600000.SH",
        name="浦发银行",
        action=ActionLabel.ENTER_OBSERVATION,
        score=83,
        reasons=["趋势改善"],
        risks=["银行板块弹性有限"],
    )
    package = build_evidence_package(rec, matched_rules=["RESEARCH_TREND_CONFIRMATION"])
    assert package.evidence_id == "2026-07-07-600000.SH"
    assert package.thesis.startswith("浦发银行")
    assert package.support == ["趋势改善"]
    assert package.counter_evidence == ["银行板块弹性有限"]
    assert package.matched_rules == ["RESEARCH_TREND_CONFIRMATION"]


def test_create_evaluation_tasks_has_three_layers_and_three_windows():
    package = build_evidence_package(
        Recommendation(
            trade_date=date(2026, 7, 7),
            ts_code="600000.SH",
            name="浦发银行",
            action=ActionLabel.ENTER_OBSERVATION,
            score=83,
            reasons=["趋势改善"],
            risks=["银行板块弹性有限"],
        ),
        matched_rules=["RESEARCH_TREND_CONFIRMATION"],
    )
    tasks = create_evaluation_tasks(package)
    assert {(task.checkpoint_days, task.evaluation_layer) for task in tasks} == {
        (5, "result"),
        (20, "result"),
        (40, "result"),
        (20, "method"),
        (40, "method"),
        (40, "knowledge"),
    }
```

- [ ] **Step 2: Run failing tests**

Run: `pytest /Users/ccrt/股票分析助手/tests/test_evidence_evaluation.py -v`  
Expected: FAIL because evidence and evaluation modules do not exist.

- [ ] **Step 3: Implement evidence package builder**

```python
# /Users/ccrt/股票分析助手/src/stock_analyzer/analysis/evidence.py
from __future__ import annotations

from stock_analyzer.domain.models import EvidencePackage, Recommendation


def build_evidence_package(recommendation: Recommendation, matched_rules: list[str]) -> EvidencePackage:
    evidence_id = f"{recommendation.trade_date.isoformat()}-{recommendation.ts_code}"
    return EvidencePackage(
        evidence_id=evidence_id,
        trade_date=recommendation.trade_date,
        ts_code=recommendation.ts_code,
        thesis=f"{recommendation.name}进入 2-8 周观察，原始分数 {recommendation.score}",
        support=list(recommendation.reasons),
        counter_evidence=list(recommendation.risks),
        matched_rules=list(matched_rules),
        invalidation_conditions=["核心趋势证据消失", "出现官方重大风险", "反证强于支持证据"],
        source_versions={"recommendation": evidence_id},
    )
```

- [ ] **Step 4: Implement evaluation task registration**

```python
# /Users/ccrt/股票分析助手/src/stock_analyzer/evaluation/tasks.py
from __future__ import annotations

from stock_analyzer.domain.models import EvaluationTask, EvidencePackage


def create_evaluation_tasks(package: EvidencePackage) -> list[EvaluationTask]:
    schedule = [
        (5, "result"),
        (20, "result"),
        (40, "result"),
        (20, "method"),
        (40, "method"),
        (40, "knowledge"),
    ]
    return [
        EvaluationTask(
            trade_date=package.trade_date,
            ts_code=package.ts_code,
            evidence_id=package.evidence_id,
            checkpoint_days=days,
            evaluation_layer=layer,
        )
        for days, layer in schedule
    ]
```

- [ ] **Step 5: Run tests**

Run: `pytest /Users/ccrt/股票分析助手/tests/test_evidence_evaluation.py -v`  
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/stock_analyzer/analysis/evidence.py src/stock_analyzer/evaluation/tasks.py tests/test_evidence_evaluation.py
git commit -m "feat: freeze evidence and register evaluation tasks"
```

---

### Task 9: 存储仓库接口与 Supabase 写入边界

**Files:**
- Create: `/Users/ccrt/股票分析助手/src/stock_analyzer/storage/supabase_client.py`
- Create: `/Users/ccrt/股票分析助手/src/stock_analyzer/storage/repositories.py`
- Test: `/Users/ccrt/股票分析助手/tests/test_repositories.py`

**Interfaces:**
- Produces: `create_supabase_client(config: AppConfig) -> Client`
- Produces: `AnalysisRepository`
- Produces: `InMemoryAnalysisRepository`
- Produces methods `save_recommendations`, `save_focus_states`, `save_evidence_packages`, `save_evaluation_tasks`

- [ ] **Step 1: Write failing repository tests**

```python
# /Users/ccrt/股票分析助手/tests/test_repositories.py
from datetime import date

from stock_analyzer.domain.models import ActionLabel, EvaluationTask, EvidencePackage, FocusState, Recommendation
from stock_analyzer.storage.repositories import InMemoryAnalysisRepository


def test_in_memory_repository_saves_daily_outputs():
    repo = InMemoryAnalysisRepository()
    recommendation = Recommendation(
        trade_date=date(2026, 7, 7),
        ts_code="600000.SH",
        name="浦发银行",
        action=ActionLabel.ENTER_OBSERVATION,
        score=80,
        reasons=["趋势改善"],
        risks=["需要确认"],
        evidence_id="2026-07-07-600000.SH",
    )
    focus = FocusState(trade_date=date(2026, 7, 7), ts_code="600000.SH", state=ActionLabel.ENTER_OBSERVATION)
    evidence = EvidencePackage(
        evidence_id="2026-07-07-600000.SH",
        trade_date=date(2026, 7, 7),
        ts_code="600000.SH",
        thesis="观察",
        support=["趋势改善"],
        counter_evidence=["需要确认"],
        matched_rules=[],
        invalidation_conditions=[],
        source_versions={},
    )
    task = EvaluationTask(
        trade_date=date(2026, 7, 7),
        ts_code="600000.SH",
        evidence_id=evidence.evidence_id,
        checkpoint_days=5,
        evaluation_layer="result",
    )
    repo.save_recommendations([recommendation])
    repo.save_focus_states([focus])
    repo.save_evidence_packages([evidence])
    repo.save_evaluation_tasks([task])
    assert len(repo.recommendations) == 1
    assert len(repo.focus_states) == 1
    assert len(repo.evidence_packages) == 1
    assert len(repo.evaluation_tasks) == 1
```

- [ ] **Step 2: Run failing test**

Run: `pytest /Users/ccrt/股票分析助手/tests/test_repositories.py -v`  
Expected: FAIL because storage modules do not exist.

- [ ] **Step 3: Implement repository protocol and memory implementation**

```python
# /Users/ccrt/股票分析助手/src/stock_analyzer/storage/repositories.py
from __future__ import annotations

from typing import Protocol

from stock_analyzer.domain.models import EvaluationTask, EvidencePackage, FocusState, Recommendation


class AnalysisRepository(Protocol):
    def save_recommendations(self, recommendations: list[Recommendation]) -> None: ...
    def save_focus_states(self, states: list[FocusState]) -> None: ...
    def save_evidence_packages(self, packages: list[EvidencePackage]) -> None: ...
    def save_evaluation_tasks(self, tasks: list[EvaluationTask]) -> None: ...


class InMemoryAnalysisRepository:
    def __init__(self) -> None:
        self.recommendations: list[Recommendation] = []
        self.focus_states: list[FocusState] = []
        self.evidence_packages: list[EvidencePackage] = []
        self.evaluation_tasks: list[EvaluationTask] = []

    def save_recommendations(self, recommendations: list[Recommendation]) -> None:
        self.recommendations.extend(recommendations)

    def save_focus_states(self, states: list[FocusState]) -> None:
        self.focus_states.extend(states)

    def save_evidence_packages(self, packages: list[EvidencePackage]) -> None:
        self.evidence_packages.extend(packages)

    def save_evaluation_tasks(self, tasks: list[EvaluationTask]) -> None:
        self.evaluation_tasks.extend(tasks)
```

- [ ] **Step 4: Implement Supabase client factory**

```python
# /Users/ccrt/股票分析助手/src/stock_analyzer/storage/supabase_client.py
from __future__ import annotations

from supabase import Client, create_client

from stock_analyzer.config import AppConfig


def create_supabase_client(config: AppConfig) -> Client:
    if not config.supabase_url or not config.supabase_service_role_key:
        raise ValueError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are required for Supabase writes")
    return create_client(config.supabase_url, config.supabase_service_role_key)
```

- [ ] **Step 5: Run tests**

Run: `pytest /Users/ccrt/股票分析助手/tests/test_repositories.py -v`  
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/stock_analyzer/storage/supabase_client.py src/stock_analyzer/storage/repositories.py tests/test_repositories.py
git commit -m "feat: add analysis repository boundary"
```

---

### Task 10: 静态报告生成

**Files:**
- Create: `/Users/ccrt/股票分析助手/src/stock_analyzer/reports/generator.py`
- Create: `/Users/ccrt/股票分析助手/src/stock_analyzer/reports/templates/index.html.j2`
- Create: `/Users/ccrt/股票分析助手/src/stock_analyzer/reports/templates/stock.html.j2`
- Test: `/Users/ccrt/股票分析助手/tests/test_report_generation.py`

**Interfaces:**
- Consumes: `Recommendation`
- Consumes: `FocusState`
- Produces: `render_reports(output_dir: Path, recommendations: list[Recommendation], focus_states: list[FocusState]) -> None`
- Produces: `reports/index.html`
- Produces: `reports/data/latest.json`

- [ ] **Step 1: Write failing report tests**

```python
# /Users/ccrt/股票分析助手/tests/test_report_generation.py
from datetime import date

from stock_analyzer.domain.models import ActionLabel, FocusState, Recommendation
from stock_analyzer.reports.generator import render_reports


def test_render_reports_creates_fixed_entry_and_hides_secrets(tmp_path):
    rec = Recommendation(
        trade_date=date(2026, 7, 7),
        ts_code="600000.SH",
        name="浦发银行",
        action=ActionLabel.ENTER_OBSERVATION,
        score=81,
        reasons=["趋势改善"],
        risks=["需要确认"],
    )
    focus = FocusState(trade_date=date(2026, 7, 7), ts_code="600000.SH", state=ActionLabel.ENTER_OBSERVATION)
    render_reports(tmp_path, [rec], [focus])
    html = (tmp_path / "index.html").read_text(encoding="utf-8")
    json_text = (tmp_path / "data" / "latest.json").read_text(encoding="utf-8")
    assert "浦发银行" in html
    assert "进入观察" in html
    assert "SUPABASE_SERVICE_ROLE_KEY" not in html
    assert "TUSHARE_TOKEN" not in html
    assert "浦发银行" in json_text
```

- [ ] **Step 2: Run failing test**

Run: `pytest /Users/ccrt/股票分析助手/tests/test_report_generation.py -v`  
Expected: FAIL because report generator does not exist.

- [ ] **Step 3: Implement report generator**

```python
# /Users/ccrt/股票分析助手/src/stock_analyzer/reports/generator.py
from __future__ import annotations

import json
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from stock_analyzer.domain.models import FocusState, Recommendation


def render_reports(output_dir: Path, recommendations: list[Recommendation], focus_states: list[FocusState]) -> None:
    template_dir = Path(__file__).parent / "templates"
    env = Environment(loader=FileSystemLoader(template_dir), autoescape=select_autoescape(["html"]))
    output_dir.mkdir(parents=True, exist_ok=True)
    data_dir = output_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    payload = {
        "recommendations": [item.model_dump(mode="json") for item in recommendations],
        "focus_states": [item.model_dump(mode="json") for item in focus_states],
    }
    (data_dir / "latest.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    html = env.get_template("index.html.j2").render(recommendations=recommendations, focus_states=focus_states)
    (output_dir / "index.html").write_text(html, encoding="utf-8")
```

- [ ] **Step 4: Add templates**

```html
<!-- /Users/ccrt/股票分析助手/src/stock_analyzer/reports/templates/index.html.j2 -->
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>股票观察报告</title>
</head>
<body>
  <main>
    <h1>股票观察报告</h1>
    <section>
      <h2>今日推荐</h2>
      {% for item in recommendations %}
      <article>
        <h3>{{ item.name }} {{ item.ts_code }}</h3>
        <p>{{ item.action.value }}，评分 {{ item.score }}</p>
        <p>理由：{{ "；".join(item.reasons) }}</p>
        <p>风险：{{ "；".join(item.risks) }}</p>
      </article>
      {% else %}
      <p>今日没有符合标准的推荐。</p>
      {% endfor %}
    </section>
    <section>
      <h2>重点关注</h2>
      {% for item in focus_states %}
      <article>
        <h3>{{ item.ts_code }}</h3>
        <p>{{ item.state.value }}</p>
      </article>
      {% else %}
      <p>当前没有重点关注股票。</p>
      {% endfor %}
    </section>
  </main>
</body>
</html>
```

```html
<!-- /Users/ccrt/股票分析助手/src/stock_analyzer/reports/templates/stock.html.j2 -->
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{{ stock_name }} 股票报告</title>
</head>
<body>
  <main>
    <h1>{{ stock_name }}</h1>
    <p>{{ conclusion }}</p>
  </main>
</body>
</html>
```

- [ ] **Step 5: Run tests**

Run: `pytest /Users/ccrt/股票分析助手/tests/test_report_generation.py -v`  
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/stock_analyzer/reports/generator.py src/stock_analyzer/reports/templates/index.html.j2 src/stock_analyzer/reports/templates/stock.html.j2 tests/test_report_generation.py
git commit -m "feat: generate static report artifacts"
```

---

### Task 11: run-daily 编排端到端冒烟

**Files:**
- Modify: `/Users/ccrt/股票分析助手/src/stock_analyzer/cli.py`
- Create: `/Users/ccrt/股票分析助手/src/stock_analyzer/pipeline.py`
- Test: `/Users/ccrt/股票分析助手/tests/test_pipeline_smoke.py`

**Interfaces:**
- Produces: `run_daily_pipeline(trade_date: date, output_dir: Path, dry_run: bool = False) -> DailyRunResult`
- Consumes: pool filtering, recommendation, focus, evidence, evaluation, repository, report generation

- [ ] **Step 1: Write failing pipeline test**

```python
# /Users/ccrt/股票分析助手/tests/test_pipeline_smoke.py
from datetime import date

from stock_analyzer.pipeline import run_daily_pipeline


def test_run_daily_pipeline_creates_report_and_evaluation_tasks(tmp_path):
    result = run_daily_pipeline(date(2026, 7, 7), tmp_path, dry_run=False)
    assert result.trade_date.isoformat() == "2026-07-07"
    assert len(result.recommendations) <= 10
    assert len(result.evaluation_tasks) >= len(result.recommendations) * 3
    assert (tmp_path / "index.html").exists()
    assert (tmp_path / "data" / "latest.json").exists()
```

- [ ] **Step 2: Run failing test**

Run: `pytest /Users/ccrt/股票分析助手/tests/test_pipeline_smoke.py -v`  
Expected: FAIL because pipeline does not exist.

- [ ] **Step 3: Implement pipeline with deterministic sample data**

```python
# /Users/ccrt/股票分析助手/src/stock_analyzer/pipeline.py
from __future__ import annotations

from datetime import date
from pathlib import Path

from pydantic import BaseModel

from stock_analyzer.analysis.evidence import build_evidence_package
from stock_analyzer.analysis.focus import update_focus_watchlist
from stock_analyzer.analysis.recommendation import generate_recommendations
from stock_analyzer.domain.models import EvaluationTask, FeatureSnapshot, FocusState, Recommendation
from stock_analyzer.evaluation.tasks import create_evaluation_tasks
from stock_analyzer.reports.generator import render_reports
from stock_analyzer.storage.repositories import InMemoryAnalysisRepository


class DailyRunResult(BaseModel):
    trade_date: date
    recommendations: list[Recommendation]
    focus_states: list[FocusState]
    evaluation_tasks: list[EvaluationTask]


def _sample_features(trade_date: date) -> tuple[list[FeatureSnapshot], dict[str, str]]:
    features = [
        FeatureSnapshot(
            trade_date=trade_date,
            ts_code="600000.SH",
            trend_20d=0.08,
            trend_60d=0.12,
            relative_strength=0.75,
            volatility_20d=0.22,
            liquidity_score=0.9,
            quality_score=0.7,
            market_regime="sideways",
            industry="银行",
        )
    ]
    return features, {"600000.SH": "浦发银行"}


def run_daily_pipeline(trade_date: date, output_dir: Path, dry_run: bool = False) -> DailyRunResult:
    features, stock_names = _sample_features(trade_date)
    recommendation_result = generate_recommendations(features, stock_names)
    recommendations = recommendation_result.recommendations
    focus_states = update_focus_watchlist(existing=[], recommendations=recommendations, invalidated_codes=set())
    evidence_packages = [build_evidence_package(item, matched_rules=["RESEARCH_TREND_CONFIRMATION"]) for item in recommendations]
    evaluation_tasks = [task for package in evidence_packages for task in create_evaluation_tasks(package)]

    repo = InMemoryAnalysisRepository()
    repo.save_recommendations(recommendations)
    repo.save_focus_states(focus_states)
    repo.save_evidence_packages(evidence_packages)
    repo.save_evaluation_tasks(evaluation_tasks)

    if not dry_run:
        render_reports(output_dir, recommendations, focus_states)

    return DailyRunResult(
        trade_date=trade_date,
        recommendations=recommendations,
        focus_states=focus_states,
        evaluation_tasks=evaluation_tasks,
    )
```

- [ ] **Step 4: Wire CLI to pipeline**

```python
# /Users/ccrt/股票分析助手/src/stock_analyzer/cli.py
from datetime import date

import typer

from stock_analyzer.config import AppConfig
from stock_analyzer.data.health import run_health_checks
from stock_analyzer.pipeline import run_daily_pipeline

app = typer.Typer(no_args_is_help=True)


@app.command("health-check")
def health_check() -> None:
    report = run_health_checks(AppConfig.load())
    for line in report.as_lines():
        typer.echo(line)


@app.command("run-daily")
def run_daily(
    dry_run: bool = typer.Option(False, "--dry-run"),
    trade_date: date = typer.Option(..., "--trade-date"),
) -> None:
    config = AppConfig.load()
    result = run_daily_pipeline(trade_date, config.reports_dir, dry_run=dry_run)
    typer.echo(f"daily run completed for {result.trade_date.isoformat()}")
    typer.echo(f"recommendations: {len(result.recommendations)}")
    typer.echo(f"evaluation_tasks: {len(result.evaluation_tasks)}")
```

- [ ] **Step 5: Run smoke tests**

Run: `pytest /Users/ccrt/股票分析助手/tests/test_pipeline_smoke.py /Users/ccrt/股票分析助手/tests/test_cli.py -v`  
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/stock_analyzer/pipeline.py src/stock_analyzer/cli.py tests/test_pipeline_smoke.py
git commit -m "feat: orchestrate daily analysis pipeline"
```

---

### Task 12: Cloudflare Pages 密码门

**Files:**
- Create: `/Users/ccrt/股票分析助手/functions/_middleware.ts`
- Create: `/Users/ccrt/股票分析助手/tests/test_cloudflare_middleware.py`

**Interfaces:**
- Produces: Cloudflare Pages middleware requiring `REPORT_PASSWORD` and `REPORT_SESSION_SECRET`
- Allows: `/login` password form
- Allows: authenticated signed session cookie `report_session`

- [ ] **Step 1: Write static middleware safety test**

```python
# /Users/ccrt/股票分析助手/tests/test_cloudflare_middleware.py
from pathlib import Path


def test_cloudflare_middleware_uses_password_and_cookie_without_secrets_in_html():
    text = Path("/Users/ccrt/股票分析助手/functions/_middleware.ts").read_text(encoding="utf-8")
    assert "REPORT_PASSWORD" in text
    assert "REPORT_SESSION_SECRET" in text
    assert "report_session" in text
    assert "report_session=ok" not in text
    assert "SUPABASE_SERVICE_ROLE_KEY" not in text
    assert "TUSHARE_TOKEN" not in text
```

- [ ] **Step 2: Run failing test**

Run: `pytest /Users/ccrt/股票分析助手/tests/test_cloudflare_middleware.py -v`  
Expected: FAIL because middleware file does not exist.

- [ ] **Step 3: Add middleware**

```ts
// /Users/ccrt/股票分析助手/functions/_middleware.ts
type Env = {
  REPORT_PASSWORD?: string;
  REPORT_SESSION_SECRET?: string;
};

export const onRequest: PagesFunction<Env> = async (context) => {
  const request = context.request;
  const url = new URL(request.url);
  const cookie = request.headers.get("Cookie") || "";
  const passwordSecret = context.env.REPORT_PASSWORD;
  const sessionSecret = context.env.REPORT_SESSION_SECRET;
  const session = getCookieValue(cookie, "report_session");

  if (!passwordSecret || !sessionSecret) {
    return new Response("", { status: 503 });
  }

  if (await isValidSession(session, sessionSecret)) {
    return context.next();
  }

  if (url.pathname === "/login" && request.method === "POST") {
    const form = await request.formData();
    const password = String(form.get("password") || "");
    if (timingSafeEqual(password, passwordSecret)) {
      const sessionValue = await createSessionValue(sessionSecret);
      return new Response("", {
        status: 302,
        headers: {
          "Location": "/",
          "Set-Cookie": `report_session=${sessionValue}; HttpOnly; Secure; SameSite=Lax; Path=/; Max-Age=604800`,
        },
      });
    }
  }

  if (url.pathname === "/login") {
    return new Response(
      "<!doctype html><html lang=\"zh-CN\"><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\"><title>报告访问</title><form method=\"post\"><input name=\"password\" type=\"password\" autocomplete=\"current-password\"><button>进入报告</button></form></html>",
      { headers: { "Content-Type": "text/html; charset=utf-8" } },
    );
  }

  return new Response("", { status: 302, headers: { "Location": "/login" } });
};
```

- [ ] **Step 4: Run test**

Run: `pytest /Users/ccrt/股票分析助手/tests/test_cloudflare_middleware.py -v`  
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add functions/_middleware.ts tests/test_cloudflare_middleware.py
git commit -m "feat: add cloudflare report password gate"
```

---

### Task 13: 文档、运行说明与第一阶段验收

**Files:**
- Create: `/Users/ccrt/股票分析助手/README.md`
- Modify: `/Users/ccrt/股票分析助手/docs/superpowers/specs/2026-07-07-stock-analysis-assistant-v3-design.md`
- Test: full test suite

**Interfaces:**
- Produces: README commands for local run, Supabase env, Cloudflare Pages report publishing
- Produces: documented acceptance checklist

- [ ] **Step 1: Add README**

```markdown
# 股票分析助手 V3

这是一个面向中国大陆 A 股的报告优先型分析助手。系统用于生成观察建议、重点关注状态、证据包和后评估任务，不用于自动交易。

## 本地运行

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev,data]"
python -m stock_analyzer health-check
python -m stock_analyzer run-daily --fixture-mode --trade-date 2026-07-07
```

## 密钥

- Tushare token 默认读取 `/Users/ccrt/.tushare_token`。
- Supabase 写入使用 `SUPABASE_URL` 和 `SUPABASE_SERVICE_ROLE_KEY`。
- Cloudflare Pages 报告访问使用 `REPORT_PASSWORD` 和 `REPORT_SESSION_SECRET`。
- 不要把任何 token 写入 Git。

## 报告

固定入口是 `reports/index.html`。Cloudflare Pages 只发布报告成品，不发布原始数据、日志、规则编辑器、数据库后台。

## 第一阶段验收

- `python -m stock_analyzer health-check` 能输出四类健康状态。
- `python -m stock_analyzer run-daily --fixture-mode --trade-date 2026-07-07` 能生成带 fixture 标记的 `reports/index.html`。
- 不带 `--fixture-mode` 的生产 `run-daily` 在真实行情接入完成前应清晰失败。
- 每日推荐数量不超过 10 只。
- 重点关注状态和推荐状态分离。
- 每条推荐生成证据包和评估任务。
- 报告内容不包含 `TUSHARE_TOKEN`、`SUPABASE_SERVICE_ROLE_KEY`。
```

- [ ] **Step 2: Run full tests**

Run: `pytest /Users/ccrt/股票分析助手/tests -v`  
Expected: PASS.

- [ ] **Step 3: Run CLI smoke command**

Run: `python -m stock_analyzer run-daily --fixture-mode --trade-date 2026-07-07`
Expected: command exits 0 and creates a fixture-labeled `/Users/ccrt/股票分析助手/reports/index.html`.

- [ ] **Step 4: Verify report does not leak secrets**

Run: `rg -n "TUSHARE_TOKEN|SUPABASE_SERVICE_ROLE_KEY|DEEPSEEK_API_KEY|BIYING_LICENCE" /Users/ccrt/股票分析助手/reports`  
Expected: no matches.

- [ ] **Step 5: Commit**

```bash
git add README.md docs/superpowers/specs/2026-07-07-stock-analysis-assistant-v3-design.md
git commit -m "docs: add mvp runbook and acceptance checklist"
```

---

## Execution Order

1. Task 1 creates a runnable Python skeleton.
2. Task 2 adds configuration and health boundaries.
3. Task 3 locks domain models and Supabase schema.
4. Task 4 implements hard-risk stock-pool filtering.
5. Task 5 turns knowledge into formal rules.
6. Task 6 creates precise daily recommendations.
7. Task 7 separates recommendations from focus watchlist.
8. Task 8 freezes evidence and registers scientific evaluation tasks.
9. Task 9 defines the storage boundary for Supabase.
10. Task 10 generates report artifacts.
11. Task 11 wires the daily pipeline.
12. Task 12 adds report access control for Cloudflare Pages.
13. Task 13 documents and verifies the MVP.

## Self-Review

- Spec coverage: data acquisition boundary, stock-pool filtering, knowledge rules, analysis scoring, recommendation limit, focus state machine, evidence freezing, post-evaluation, Supabase storage, Cloudflare report exposure, and fixed report entry all map to tasks above.
- Placeholder scan: this plan gives concrete file paths, function signatures, commands, and expected results.
- Type consistency: `Recommendation`, `FocusState`, `EvidencePackage`, `EvaluationTask`, `ActionLabel`, `run_daily_pipeline`, and `render_reports` are introduced before downstream tasks consume them.
