# Tushare Ingestion V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 打通真实 Tushare 主源、有限实时备用源、Supabase 入库、每日候选分析和静态报告发布链路，让生产 `run-daily` 可以基于真实 A 股数据运行，同时禁止样例数据或缓存数据冒充今日决策数据。

**Architecture:** 保持现有 MVP 的小模块结构，在 `stock_analyzer.data` 新增真实 ingestion 层，产出统一的 `MarketDataBundle` 后再交给已有 pool、recommendation、focus、evidence、evaluation、reports 流程。Tushare 是主源，AkShare/Sina/Tencent 只做当前交易日行情备用；历史缓存只用于过往窗口、断点续跑和审计，不参与当前交易日新推荐或关注变更。

**Tech Stack:** Python 3.11+、Typer、Pydantic、Pandas、NumPy、Jinja2、Supabase Python client、pytest、Tushare optional dependency、AkShare optional dependency、HTTPX。

## Global Constraints

- 项目根目录固定为 `/Users/ccrt/股票分析助手`；当前开发工作区通过 `/Users/ccrt/Documents/股票分析助手` 访问。
- 本机日常主命令固定为 `set -a; . ./.env.local; set +a; PYTHONPATH=src .venv/bin/python -m stock_analyzer run-daily --trade-date YYYY-MM-DD`。
- Fixture 模式只能通过 `--fixture-mode` 或 `STOCK_ANALYZER_FIXTURE_MODE=1` 显式启用。
- 生产模式必须读取 `SUPABASE_URL`、`SUPABASE_SERVICE_ROLE_KEY`，不得在聊天、日志、报告、异常中输出 service key。
- Tushare token 读取顺序：先 `TUSHARE_TOKEN`，再 `TUSHARE_TOKEN_PATH`，默认 `/Users/ccrt/.tushare_token`；不得打印 token 原文。
- Tushare 为 V1 主源；AkShare/Sina/Tencent 只能作为当前交易日价格、成交量、成交额备用源。
- 缓存不是备用源；缓存只允许用于历史窗口、断点续跑、后评估审计、数据不可用状态说明。
- 当前交易日没有实时主源或实时备用源时，不生成新推荐、不升级重点关注、不输出正常股票分析报告。
- 每日推荐最多 10 只；不足 10 只时不得降低标准凑数。
- 重点关注池可以为空，也可以少于 10 只。
- 报告必须像股票分析报告，不像系统运行日志；数据源状态只能作为风险披露，不抢占分析主体。
- 每个任务完成后运行对应测试并提交。
- 执行方式按用户确认采用 Subagent-Driven；本计划所有实现和 review 禁止使用 5.4mini。
- Task 1-9 的 implementer 和 reviewer 默认使用 GPT-5.5 xhigh；如果该模型不可用，必须停止并向用户说明，不得自动降级到 mini。
- 每个 subagent 报告必须写明实际使用模型、运行的测试命令、测试结果、是否触碰密钥/外网/数据库。
- 本地执行必须使用项目 `.venv` 中的 Python 3.12：`.venv/bin/python`。
- 当前 `.venv` 只允许保留 Supabase 调试最小依赖；每个任务只能安装本任务明确需要的最小依赖，不得一次性安装 `.[dev,data]`。
- `tushare`、`akshare` 只能在到达真实数据源任务或 live smoke 任务时按需安装；调试 Supabase 或纯 fake-client 单元测试时不得安装它们。
- `.env.local` 只用于本机运行，必须继续被 Git 忽略；不得读取、打印、提交、复制 `SUPABASE_SERVICE_ROLE_KEY` 或 Tushare token 原文。
- 任何数据库写入、外网 smoke、Cloudflare 操作都必须在单元测试和 reviewer gate 通过后执行。

---

## Execution Guardrails

这些规则覆盖所有任务，优先级高于各任务中较旧的命令示例。

### Model Assignment

| Task | Implementer model | Reviewer model | Reason |
| --- | --- | --- | --- |
| Task 1 | GPT-5.5 xhigh | GPT-5.5 xhigh | 数据契约、密钥脱敏、缓存不参与决策的根接口 |
| Task 2 | GPT-5.5 xhigh | GPT-5.5 xhigh | Tushare 字段映射，任何字段错误都会污染全链路 |
| Task 3 | GPT-5.5 xhigh | GPT-5.5 xhigh | 实时备用源和缓存边界是核心风控规则 |
| Task 4 | GPT-5.5 xhigh | GPT-5.5 xhigh | 特征计算直接影响候选质量 |
| Task 5 | GPT-5.5 xhigh | GPT-5.5 xhigh | Supabase schema、RLS、持久化字段必须一次做对 |
| Task 6 | GPT-5.5 xhigh | GPT-5.5 xhigh | 生产 pipeline 是否允许发布报告的核心 gate |
| Task 7 | GPT-5.5 xhigh | GPT-5.5 xhigh | 防止缓存-only 伪装成股票分析报告 |
| Task 8 | GPT-5.5 xhigh | GPT-5.5 xhigh | 真实 smoke、密钥脱敏、生产命令验证 |
| Task 9 | GPT-5.5 xhigh | GPT-5.5 xhigh | Supabase 真实迁移、GitHub/Cloudflare 发布前检查 |
| Final whole-branch review | GPT-5.5 xhigh | GPT-5.5 xhigh | 全链路金融决策系统风险审查 |

如果调度工具没有 GPT-5.5 xhigh 选项，controller 必须停止并询问用户是否允许使用最接近的高能力模型。不得默认降级。

### Environment Policy

- 当前本地 `.venv` 已为 Supabase 调试最小环境：`pydantic` + `supabase`。
- Task 1 可直接使用当前 `.venv`。
- Task 2 如需要 DataFrame 测试，只安装 `pandas>=2.2`，不安装 `tushare`。
- Task 3 的 AkShare/Sina/Tencent 测试必须使用 fake client；不得为了 fake-client 单元测试安装 `akshare`。
- Task 4 如需要计算依赖，只安装 `pandas>=2.2` 和 `numpy>=1.26`。
- Task 5 只需要 `supabase`、`pydantic` 和标准库；不得安装数据源包。
- Task 6 生产 provider 单元测试使用 fake provider；不得访问 Tushare 或 AkShare 外网。
- Task 7 报告边界测试不需要数据源包。
- Task 8 才允许安装 `tushare>=1.4.19` 执行 live Tushare smoke；只有实现真实 AkShare live smoke 时才允许安装 `akshare>=1.14`。
- 所有依赖安装必须写在 subagent 报告中，并说明为什么该任务需要它。

### Quality Gates

- 每个任务必须先写失败测试，记录失败命令和失败原因，再写实现。
- 每个任务必须生成一次 commit；reviewer 只审该任务从 base commit 到 head commit 的 diff。
- reviewer 必须同时给出 `Spec compliance` 和 `Code quality` 两个 verdict。
- 任何 Critical 或 Important finding 必须回到 fixer subagent，修复后 re-review。
- Minor finding 记录到 `.superpowers/sdd/progress.md`，最终 whole-branch review 前统一复查。
- 任何任务如果触碰这些边界，reviewer 必须重点审查：样例数据是否进入生产、缓存是否支撑当前日决策、service key/token 是否泄露、报告是否误导为正式结论、Supabase RLS 是否仍开启。

### Stop Conditions

controller 必须停止并向用户说明，不能继续自动执行的情况：

- 需要从 GPT-5.5 xhigh 降级到 mini 或未知低能力模型。
- 生产运行需要当前日真实数据但 Tushare token 缺失。
- Supabase 写入失败且错误不能通过只读 smoke 定位。
- 任何 live source 返回空数据，而代码试图生成正常推荐报告。
- reviewer 发现计划要求和安全/正确性要求冲突。

---

## File Structure

- Modify: `/Users/ccrt/股票分析助手/src/stock_analyzer/config.py`
  增加 Tushare token 解析、可脱敏的凭证状态、生产 ingestion 配置。
- Create: `/Users/ccrt/股票分析助手/src/stock_analyzer/data/models.py`
  数据源状态、行情行、基础指标行、统一数据包、数据不可用通知模型。
- Create: `/Users/ccrt/股票分析助手/src/stock_analyzer/data/tushare_source.py`
  Tushare client 包装、DataFrame 字段校验、stock_basic/trade_cal/daily/daily_basic 映射。
- Create: `/Users/ccrt/股票分析助手/src/stock_analyzer/data/free_sources.py`
  AkShare/Sina/Tencent 当前交易日行情备用接口，测试用 fake client，不在单元测试访问外网。
- Create: `/Users/ccrt/股票分析助手/src/stock_analyzer/data/cache.py`
  历史缓存权限判断和断点续跑读取边界；明确禁止当前日缓存参与决策。
- Create: `/Users/ccrt/股票分析助手/src/stock_analyzer/data/feature_builder.py`
  从 stock_basic、daily、daily_basic 构建 `StockSnapshot` 和 `FeatureSnapshot`。
- Create: `/Users/ccrt/股票分析助手/src/stock_analyzer/data/provider.py`
  编排 Tushare 主源、实时备用源、缓存权限、重试、run records，产出 `MarketDataBundle`。
- Modify: `/Users/ccrt/股票分析助手/src/stock_analyzer/pipeline.py`
  生产模式从 `MarketDataProvider` 取真实数据；fixture 模式继续使用 `_sample_market()`。
- Modify: `/Users/ccrt/股票分析助手/src/stock_analyzer/cli.py`
  生产 `run-daily` 构造真实 provider，不再预先用“ingestion 未实现”拦截。
- Modify: `/Users/ccrt/股票分析助手/src/stock_analyzer/storage/repositories.py`
  支持 market bars、daily basic indicators、data_source_run 的 upsert 和读取。
- Create: `/Users/ccrt/股票分析助手/supabase/migrations/202607080002_ingestion_v1.sql`
  新增行情、基础指标表，扩展 `data_source_run`，保持 RLS service_role policy。
- Modify: `/Users/ccrt/股票分析助手/src/stock_analyzer/reports/generator.py`
  支持 live-backup 警示和 data-unavailable notice；禁止缓存-only 正常报告。
- Modify: `/Users/ccrt/股票分析助手/src/stock_analyzer/reports/templates/index.html.j2`
  首页展示生产/实时备用源状态和数据不可用 notice。
- Modify: `/Users/ccrt/股票分析助手/src/stock_analyzer/reports/templates/stock.html.j2`
  单股页展示证据来源和备用源风险。
- Create: `/Users/ccrt/股票分析助手/tests/test_ingestion_contracts.py`
- Create: `/Users/ccrt/股票分析助手/tests/test_tushare_source.py`
- Create: `/Users/ccrt/股票分析助手/tests/test_cache_policy.py`
- Create: `/Users/ccrt/股票分析助手/tests/test_feature_builder.py`
- Modify: `/Users/ccrt/股票分析助手/tests/test_supabase_schema.py`
- Modify: `/Users/ccrt/股票分析助手/tests/test_repositories.py`
- Modify: `/Users/ccrt/股票分析助手/tests/test_pipeline_smoke.py`
- Modify: `/Users/ccrt/股票分析助手/tests/test_cli.py`
- Modify: `/Users/ccrt/股票分析助手/tests/test_report_generation.py`

---

### Task 1: 数据源契约、配置与脱敏边界

**Files:**
- Modify: `/Users/ccrt/股票分析助手/src/stock_analyzer/config.py`
- Create: `/Users/ccrt/股票分析助手/src/stock_analyzer/data/models.py`
- Test: `/Users/ccrt/股票分析助手/tests/test_ingestion_contracts.py`

**Interfaces:**
- Produces: `AppConfig.resolve_tushare_token() -> str | None`
- Produces: `AppConfig.tushare_token_status() -> str`
- Produces: `SourceGrade`, `SourceStatus`, `DataStatus`, `SourceRunRecord`, `StockBasicRow`, `DailyBar`, `DailyBasicRow`, `MarketDataBundle`, `DataUnavailableNotice`
- Consumed by downstream tasks: `MarketDataBundle.to_pipeline_inputs() -> tuple[list[StockSnapshot], dict[str, str], dict[str, FeatureSnapshot]]`

- [ ] **Step 1: Write failing tests**

```python
# /Users/ccrt/股票分析助手/tests/test_ingestion_contracts.py
from datetime import date

from stock_analyzer.config import AppConfig
from stock_analyzer.data.models import DataStatus, MarketDataBundle, SourceGrade, SourceStatus


def test_tushare_token_prefers_env_and_masks_value(tmp_path):
    token_file = tmp_path / "token.txt"
    token_file.write_text("file-token-123", encoding="utf-8")
    config = AppConfig.load(
        {
            "TUSHARE_TOKEN": "env-token-456",
            "TUSHARE_TOKEN_PATH": str(token_file),
        }
    )

    assert config.resolve_tushare_token() == "env-token-456"
    assert "env-token-456" not in config.tushare_token_status()
    assert config.tushare_token_status() == "present:env"


def test_tushare_token_falls_back_to_file_without_printing_value(tmp_path):
    token_file = tmp_path / "token.txt"
    token_file.write_text("file-token-123\n", encoding="utf-8")
    config = AppConfig.load({"TUSHARE_TOKEN_PATH": str(token_file)})

    assert config.resolve_tushare_token() == "file-token-123"
    assert config.tushare_token_status() == "present:file"


def test_market_data_bundle_requires_live_current_source_for_decisions():
    bundle = MarketDataBundle(
        trade_date=date(2026, 7, 8),
        data_status=DataStatus.CACHE_ONLY_CURRENT_DATE,
        source_grade=SourceGrade.HISTORICAL_CACHE,
        source_versions={"cache": "2026-07-07"},
        stock_basic=[],
        daily_bars=[],
        daily_basic=[],
        source_runs=[],
    )

    assert bundle.can_generate_decisions is False
    assert bundle.to_pipeline_inputs() == ([], {}, {})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest /Users/ccrt/股票分析助手/tests/test_ingestion_contracts.py -v`
Expected: FAIL with import errors for `stock_analyzer.data.models` and missing `resolve_tushare_token`.

- [ ] **Step 3: Add data contracts**

```python
# /Users/ccrt/股票分析助手/src/stock_analyzer/data/models.py
from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field

from stock_analyzer.domain.models import FeatureSnapshot, StockSnapshot


class SourceGrade(str, Enum):
    PRIMARY = "primary"
    LIVE_BACKUP = "live_backup"
    HISTORICAL_CACHE = "historical_cache"


class SourceStatus(str, Enum):
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"


class DataStatus(str, Enum):
    COMPLETE_PRIMARY = "complete_primary"
    COMPLETE_LIVE_BACKUP = "complete_live_backup"
    INSUFFICIENT_LIVE_DATA = "insufficient_live_data"
    CACHE_ONLY_CURRENT_DATE = "cache_only_current_date"


class SourceRunRecord(BaseModel):
    trade_date: date
    source_name: str
    stage: str
    status: SourceStatus
    message: str
    attempt: int = 1
    source_grade: SourceGrade
    data_status: DataStatus
    record_count: int = 0
    field_coverage: dict[str, bool] = Field(default_factory=dict)
    payload: dict[str, object] = Field(default_factory=dict)


class StockBasicRow(BaseModel):
    ts_code: str
    name: str
    exchange: str
    list_date: Optional[date] = None


class DailyBar(BaseModel):
    trade_date: date
    ts_code: str
    open: Optional[float] = None
    high: Optional[float] = None
    low: Optional[float] = None
    close: float
    pre_close: Optional[float] = None
    pct_chg: Optional[float] = None
    vol: Optional[float] = None
    amount: Optional[float] = None
    source_name: str
    source_grade: SourceGrade
    fetched_at: Optional[datetime] = None


class DailyBasicRow(BaseModel):
    trade_date: date
    ts_code: str
    turnover_rate: Optional[float] = None
    total_mv: Optional[float] = None
    circ_mv: Optional[float] = None
    pe_ttm: Optional[float] = None
    pb: Optional[float] = None
    source_name: str
    source_grade: SourceGrade
    fetched_at: Optional[datetime] = None


class DataUnavailableNotice(BaseModel):
    trade_date: date
    reason: str
    last_successful_trade_date: Optional[date] = None
    source_runs: list[SourceRunRecord] = Field(default_factory=list)


class MarketDataBundle(BaseModel):
    trade_date: date
    data_status: DataStatus
    source_grade: SourceGrade
    source_versions: dict[str, str]
    stock_basic: list[StockBasicRow]
    daily_bars: list[DailyBar]
    daily_basic: list[DailyBasicRow]
    source_runs: list[SourceRunRecord] = Field(default_factory=list)
    stocks: list[StockSnapshot] = Field(default_factory=list)
    stock_names: dict[str, str] = Field(default_factory=dict)
    feature_profiles: dict[str, FeatureSnapshot] = Field(default_factory=dict)

    @property
    def can_generate_decisions(self) -> bool:
        return self.data_status in {
            DataStatus.COMPLETE_PRIMARY,
            DataStatus.COMPLETE_LIVE_BACKUP,
        }

    def to_pipeline_inputs(
        self,
    ) -> tuple[list[StockSnapshot], dict[str, str], dict[str, FeatureSnapshot]]:
        if not self.can_generate_decisions:
            return [], {}, {}
        return self.stocks, self.stock_names, self.feature_profiles
```

- [ ] **Step 4: Add config token resolution**

```python
# /Users/ccrt/股票分析助手/src/stock_analyzer/config.py
# Add field to AppConfig:
tushare_token: Optional[str] = None

# In AppConfig.load(), pass:
tushare_token=values.get("TUSHARE_TOKEN"),

# Add methods inside AppConfig:
def resolve_tushare_token(self) -> Optional[str]:
    if self.tushare_token:
        return self.tushare_token.strip()
    if self.tushare_token_path.exists():
        token = self.tushare_token_path.read_text(encoding="utf-8").strip()
        return token or None
    return None

def tushare_token_status(self) -> str:
    if self.tushare_token:
        return "present:env"
    if self.tushare_token_path.exists() and self.tushare_token_path.read_text(encoding="utf-8").strip():
        return "present:file"
    return "missing"
```

- [ ] **Step 5: Run tests**

Run: `.venv/bin/python -m pytest /Users/ccrt/股票分析助手/tests/test_ingestion_contracts.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/stock_analyzer/config.py src/stock_analyzer/data/models.py tests/test_ingestion_contracts.py
git commit -m "feat: add ingestion contracts and token resolution"
```

---

### Task 2: Tushare 主源映射和字段校验

**Files:**
- Create: `/Users/ccrt/股票分析助手/src/stock_analyzer/data/tushare_source.py`
- Test: `/Users/ccrt/股票分析助手/tests/test_tushare_source.py`

**Interfaces:**
- Consumes: `StockBasicRow`, `DailyBar`, `DailyBasicRow`, `SourceGrade`
- Produces: `TushareMarketDataSource.fetch_stock_basic() -> list[StockBasicRow]`
- Produces: `TushareMarketDataSource.fetch_trade_calendar(start_date: date, end_date: date) -> dict[date, bool]`
- Produces: `TushareMarketDataSource.fetch_daily(trade_date: date) -> list[DailyBar]`
- Produces: `TushareMarketDataSource.fetch_daily_basic(trade_date: date) -> list[DailyBasicRow]`

- [ ] **Step 1: Write failing tests with fake Tushare client**

```python
# /Users/ccrt/股票分析助手/tests/test_tushare_source.py
from datetime import date

import pandas as pd
import pytest

from stock_analyzer.data.models import SourceGrade
from stock_analyzer.data.tushare_source import MissingTushareField, TushareMarketDataSource


class FakeTusharePro:
    def stock_basic(self, **kwargs):
        return pd.DataFrame(
            [{"ts_code": "600000.SH", "name": "浦发银行", "exchange": "SSE", "list_date": "19991110"}]
        )

    def trade_cal(self, **kwargs):
        return pd.DataFrame(
            [{"cal_date": "20260708", "is_open": 1}, {"cal_date": "20260709", "is_open": 0}]
        )

    def daily(self, **kwargs):
        return pd.DataFrame(
            [{
                "ts_code": "600000.SH",
                "trade_date": "20260708",
                "open": 10.0,
                "high": 10.5,
                "low": 9.9,
                "close": 10.2,
                "pre_close": 10.0,
                "pct_chg": 2.0,
                "vol": 100000.0,
                "amount": 102000.0,
            }]
        )

    def daily_basic(self, **kwargs):
        return pd.DataFrame(
            [{
                "ts_code": "600000.SH",
                "trade_date": "20260708",
                "turnover_rate": 1.1,
                "total_mv": 1000000.0,
                "circ_mv": 900000.0,
                "pe_ttm": 6.5,
                "pb": 0.7,
            }]
        )


def test_tushare_maps_stock_daily_and_basic_rows():
    source = TushareMarketDataSource(token="secret", pro=FakeTusharePro())

    stock = source.fetch_stock_basic()[0]
    daily = source.fetch_daily(date(2026, 7, 8))[0]
    daily_basic = source.fetch_daily_basic(date(2026, 7, 8))[0]

    assert stock.ts_code == "600000.SH"
    assert stock.list_date == date(1999, 11, 10)
    assert daily.trade_date == date(2026, 7, 8)
    assert daily.source_name == "tushare"
    assert daily.source_grade == SourceGrade.PRIMARY
    assert daily_basic.turnover_rate == 1.1


def test_tushare_missing_required_field_fails_clearly():
    class BadPro(FakeTusharePro):
        def daily(self, **kwargs):
            return pd.DataFrame([{"ts_code": "600000.SH", "trade_date": "20260708"}])

    source = TushareMarketDataSource(token="secret", pro=BadPro())

    with pytest.raises(MissingTushareField) as excinfo:
        source.fetch_daily(date(2026, 7, 8))

    assert "close" in str(excinfo.value)
    assert "secret" not in str(excinfo.value)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest /Users/ccrt/股票分析助手/tests/test_tushare_source.py -v`
Expected: FAIL because `tushare_source.py` does not exist.

- [ ] **Step 3: Add Tushare source**

```python
# /Users/ccrt/股票分析助手/src/stock_analyzer/data/tushare_source.py
from __future__ import annotations

from datetime import date
from typing import Iterable, Optional

import pandas as pd

from stock_analyzer.data.models import DailyBar, DailyBasicRow, SourceGrade, StockBasicRow


class MissingTushareField(RuntimeError):
    pass


class TushareUnavailable(RuntimeError):
    pass


class TushareMarketDataSource:
    def __init__(self, token: str, pro: Optional[object] = None) -> None:
        self.source_name = "tushare"
        self.token = token
        self.pro = pro or _create_tushare_pro(token)

    def fetch_stock_basic(self) -> list[StockBasicRow]:
        df = self.pro.stock_basic(
            exchange="",
            list_status="L",
            fields="ts_code,name,exchange,list_date",
        )
        _require_columns(df, ["ts_code", "name", "exchange", "list_date"], "stock_basic")
        return [
            StockBasicRow(
                ts_code=str(row.ts_code),
                name=str(row.name),
                exchange=str(row.exchange),
                list_date=_parse_yyyymmdd(row.list_date),
            )
            for row in df.itertuples(index=False)
        ]

    def fetch_trade_calendar(self, start_date: date, end_date: date) -> dict[date, bool]:
        df = self.pro.trade_cal(
            exchange="SSE",
            start_date=_format_yyyymmdd(start_date),
            end_date=_format_yyyymmdd(end_date),
            fields="cal_date,is_open",
        )
        _require_columns(df, ["cal_date", "is_open"], "trade_cal")
        return {
            _parse_yyyymmdd(row.cal_date): int(row.is_open) == 1
            for row in df.itertuples(index=False)
        }

    def fetch_daily(self, trade_date: date) -> list[DailyBar]:
        df = self.pro.daily(trade_date=_format_yyyymmdd(trade_date))
        required = ["ts_code", "trade_date", "close", "amount"]
        _require_columns(df, required, "daily")
        return [
            DailyBar(
                trade_date=_parse_yyyymmdd(row.trade_date),
                ts_code=str(row.ts_code),
                open=_optional_float(row, "open"),
                high=_optional_float(row, "high"),
                low=_optional_float(row, "low"),
                close=float(row.close),
                pre_close=_optional_float(row, "pre_close"),
                pct_chg=_optional_float(row, "pct_chg"),
                vol=_optional_float(row, "vol"),
                amount=_optional_float(row, "amount"),
                source_name=self.source_name,
                source_grade=SourceGrade.PRIMARY,
            )
            for row in df.itertuples(index=False)
        ]

    def fetch_daily_basic(self, trade_date: date) -> list[DailyBasicRow]:
        df = self.pro.daily_basic(trade_date=_format_yyyymmdd(trade_date))
        _require_columns(df, ["ts_code", "trade_date", "turnover_rate"], "daily_basic")
        return [
            DailyBasicRow(
                trade_date=_parse_yyyymmdd(row.trade_date),
                ts_code=str(row.ts_code),
                turnover_rate=_optional_float(row, "turnover_rate"),
                total_mv=_optional_float(row, "total_mv"),
                circ_mv=_optional_float(row, "circ_mv"),
                pe_ttm=_optional_float(row, "pe_ttm"),
                pb=_optional_float(row, "pb"),
                source_name=self.source_name,
                source_grade=SourceGrade.PRIMARY,
            )
            for row in df.itertuples(index=False)
        ]


def _create_tushare_pro(token: str):
    try:
        import tushare as ts
    except ImportError as exc:
        raise TushareUnavailable("tushare package is not installed; install tushare before live source access") from exc
    ts.set_token(token)
    return ts.pro_api()


def _require_columns(df: pd.DataFrame, names: Iterable[str], stage: str) -> None:
    missing = [name for name in names if name not in df.columns]
    if missing:
        raise MissingTushareField(f"Tushare {stage} response missing fields: {', '.join(missing)}")


def _parse_yyyymmdd(value) -> date:
    text = str(value)
    return date(int(text[0:4]), int(text[4:6]), int(text[6:8]))


def _format_yyyymmdd(value: date) -> str:
    return value.strftime("%Y%m%d")


def _optional_float(row, name: str) -> Optional[float]:
    if not hasattr(row, name):
        return None
    value = getattr(row, name)
    if pd.isna(value):
        return None
    return float(value)
```

- [ ] **Step 4: Run tests**

Run: `.venv/bin/python -m pytest /Users/ccrt/股票分析助手/tests/test_tushare_source.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/stock_analyzer/data/tushare_source.py tests/test_tushare_source.py
git commit -m "feat: map tushare market data"
```

---

### Task 3: 实时备用源与缓存权限守门

**Files:**
- Create: `/Users/ccrt/股票分析助手/src/stock_analyzer/data/free_sources.py`
- Create: `/Users/ccrt/股票分析助手/src/stock_analyzer/data/cache.py`
- Test: `/Users/ccrt/股票分析助手/tests/test_cache_policy.py`

**Interfaces:**
- Produces: `LiveBackupSource.fetch_daily(trade_date: date) -> list[DailyBar]`
- Produces: `CachePolicy.can_use_for_historical_window(record_trade_date: date, target_trade_date: date) -> bool`
- Produces: `CachePolicy.can_use_for_current_decision(record_trade_date: date, target_trade_date: date) -> bool`

- [ ] **Step 1: Write failing tests**

```python
# /Users/ccrt/股票分析助手/tests/test_cache_policy.py
from datetime import date

from stock_analyzer.data.cache import CachePolicy
from stock_analyzer.data.free_sources import LiveBackupDailySource
from stock_analyzer.data.models import DailyBar, SourceGrade


class FakeBackupClient:
    def fetch_rows(self, trade_date):
        return [
            {
                "ts_code": "600000.SH",
                "close": 10.2,
                "amount": 102000.0,
                "vol": 100000.0,
            }
        ]


def test_cache_allows_past_window_but_forbids_current_decision():
    policy = CachePolicy()

    assert policy.can_use_for_historical_window(date(2026, 7, 7), date(2026, 7, 8)) is True
    assert policy.can_use_for_current_decision(date(2026, 7, 8), date(2026, 7, 8)) is False


def test_live_backup_daily_source_marks_rows_as_live_backup():
    source = LiveBackupDailySource(name="akshare", client=FakeBackupClient())

    rows = source.fetch_daily(date(2026, 7, 8))

    assert rows == [
        DailyBar(
            trade_date=date(2026, 7, 8),
            ts_code="600000.SH",
            close=10.2,
            vol=100000.0,
            amount=102000.0,
            source_name="akshare",
            source_grade=SourceGrade.LIVE_BACKUP,
        )
    ]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest /Users/ccrt/股票分析助手/tests/test_cache_policy.py -v`
Expected: FAIL because `cache.py` and `free_sources.py` do not exist.

- [ ] **Step 3: Add cache policy**

```python
# /Users/ccrt/股票分析助手/src/stock_analyzer/data/cache.py
from __future__ import annotations

from datetime import date


class CachePolicy:
    def can_use_for_historical_window(
        self,
        record_trade_date: date,
        target_trade_date: date,
    ) -> bool:
        return record_trade_date < target_trade_date

    def can_use_for_current_decision(
        self,
        record_trade_date: date,
        target_trade_date: date,
    ) -> bool:
        return False
```

- [ ] **Step 4: Add live backup source wrapper**

```python
# /Users/ccrt/股票分析助手/src/stock_analyzer/data/free_sources.py
from __future__ import annotations

from datetime import date
from typing import Protocol

from stock_analyzer.data.models import DailyBar, SourceGrade


class BackupDailyClient(Protocol):
    def fetch_rows(self, trade_date: date) -> list[dict]: ...


class LiveBackupDailySource:
    def __init__(self, name: str, client: BackupDailyClient) -> None:
        self.name = name
        self.client = client

    def fetch_daily(self, trade_date: date) -> list[DailyBar]:
        rows = self.client.fetch_rows(trade_date)
        return [
            DailyBar(
                trade_date=trade_date,
                ts_code=str(row["ts_code"]),
                close=float(row["close"]),
                vol=_optional_float(row, "vol"),
                amount=_optional_float(row, "amount"),
                source_name=self.name,
                source_grade=SourceGrade.LIVE_BACKUP,
            )
            for row in rows
        ]


def _optional_float(row: dict, key: str) -> float | None:
    value = row.get(key)
    return None if value is None else float(value)
```

- [ ] **Step 5: Run tests**

Run: `.venv/bin/python -m pytest /Users/ccrt/股票分析助手/tests/test_cache_policy.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/stock_analyzer/data/cache.py src/stock_analyzer/data/free_sources.py tests/test_cache_policy.py
git commit -m "feat: separate live backup from cache policy"
```

---

### Task 4: 特征构建与数据质量硬门槛

**Files:**
- Create: `/Users/ccrt/股票分析助手/src/stock_analyzer/data/feature_builder.py`
- Test: `/Users/ccrt/股票分析助手/tests/test_feature_builder.py`

**Interfaces:**
- Consumes: `StockBasicRow`, `DailyBar`, `DailyBasicRow`
- Produces: `build_market_bundle(...) -> MarketDataBundle`
- Produces: `InsufficientFeatureCoverage`

- [ ] **Step 1: Write failing tests**

```python
# /Users/ccrt/股票分析助手/tests/test_feature_builder.py
from datetime import date, timedelta

import pytest

from stock_analyzer.data.feature_builder import InsufficientFeatureCoverage, build_market_bundle
from stock_analyzer.data.models import DailyBar, DailyBasicRow, DataStatus, SourceGrade, StockBasicRow


def _bars(ts_code="600000.SH"):
    start = date(2026, 4, 1)
    return [
        DailyBar(
            trade_date=start + timedelta(days=i),
            ts_code=ts_code,
            close=10.0 + i * 0.1,
            amount=100000000.0 + i,
            source_name="tushare",
            source_grade=SourceGrade.PRIMARY,
        )
        for i in range(70)
    ]


def test_build_market_bundle_creates_stock_and_feature_profiles():
    trade_date = date(2026, 6, 9)
    bundle = build_market_bundle(
        trade_date=trade_date,
        stock_basic=[
            StockBasicRow(ts_code="600000.SH", name="浦发银行", exchange="SSE", list_date=date(1999, 11, 10))
        ],
        daily_bars=_bars(),
        daily_basic=[
            DailyBasicRow(
                trade_date=trade_date,
                ts_code="600000.SH",
                turnover_rate=1.2,
                total_mv=1000000,
                source_name="tushare",
                source_grade=SourceGrade.PRIMARY,
            )
        ],
        data_status=DataStatus.COMPLETE_PRIMARY,
        source_grade=SourceGrade.PRIMARY,
        source_versions={"tushare": "daily:2026-06-09"},
        source_runs=[],
    )

    stocks, stock_names, features = bundle.to_pipeline_inputs()

    assert stocks[0].ts_code == "600000.SH"
    assert stocks[0].listing_days > 120
    assert stock_names["600000.SH"] == "浦发银行"
    assert features["600000.SH"].trend_20d > 0
    assert features["600000.SH"].trend_60d > 0
    assert features["600000.SH"].data_quality == "ok"


def test_current_trade_date_bar_is_required_for_decisions():
    with pytest.raises(InsufficientFeatureCoverage) as excinfo:
        build_market_bundle(
            trade_date=date(2026, 7, 8),
            stock_basic=[StockBasicRow(ts_code="600000.SH", name="浦发银行", exchange="SSE")],
            daily_bars=_bars(),
            daily_basic=[],
            data_status=DataStatus.COMPLETE_PRIMARY,
            source_grade=SourceGrade.PRIMARY,
            source_versions={"tushare": "daily:2026-07-07"},
            source_runs=[],
        )

    assert "current trade date" in str(excinfo.value)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest /Users/ccrt/股票分析助手/tests/test_feature_builder.py -v`
Expected: FAIL because `feature_builder.py` does not exist.

- [ ] **Step 3: Add feature builder**

```python
# /Users/ccrt/股票分析助手/src/stock_analyzer/data/feature_builder.py
from __future__ import annotations

from datetime import date
from statistics import pstdev

from stock_analyzer.data.models import (
    DailyBar,
    DailyBasicRow,
    DataStatus,
    MarketDataBundle,
    SourceGrade,
    SourceRunRecord,
    StockBasicRow,
)
from stock_analyzer.domain.models import FeatureSnapshot, StockSnapshot


class InsufficientFeatureCoverage(RuntimeError):
    pass


def build_market_bundle(
    *,
    trade_date: date,
    stock_basic: list[StockBasicRow],
    daily_bars: list[DailyBar],
    daily_basic: list[DailyBasicRow],
    data_status: DataStatus,
    source_grade: SourceGrade,
    source_versions: dict[str, str],
    source_runs: list[SourceRunRecord],
) -> MarketDataBundle:
    bars_by_code: dict[str, list[DailyBar]] = {}
    for bar in daily_bars:
        bars_by_code.setdefault(bar.ts_code, []).append(bar)
    basics_by_code = {item.ts_code: item for item in daily_basic if item.trade_date == trade_date}
    current_codes = {bar.ts_code for bar in daily_bars if bar.trade_date == trade_date}
    if not current_codes and data_status in {DataStatus.COMPLETE_PRIMARY, DataStatus.COMPLETE_LIVE_BACKUP}:
        raise InsufficientFeatureCoverage("current trade date live bars are required for decisions")

    stocks: list[StockSnapshot] = []
    feature_profiles: dict[str, FeatureSnapshot] = {}
    stock_names: dict[str, str] = {}
    for stock in stock_basic:
        stock_names[stock.ts_code] = stock.name
        current_basic = basics_by_code.get(stock.ts_code)
        current_bars = sorted(bars_by_code.get(stock.ts_code, []), key=lambda item: item.trade_date)
        if stock.ts_code not in current_codes or len(current_bars) < 61:
            continue
        listing_days = _listing_days(stock.list_date, trade_date)
        status = StockSnapshot(
            trade_date=trade_date,
            ts_code=stock.ts_code,
            name=stock.name,
            listing_days=listing_days,
            turnover_rate=current_basic.turnover_rate if current_basic else None,
            amount=current_bars[-1].amount,
        )
        stocks.append(status)
        feature_profiles[stock.ts_code] = FeatureSnapshot(
            trade_date=trade_date,
            ts_code=stock.ts_code,
            trend_20d=_trend(current_bars, 20),
            trend_60d=_trend(current_bars, 60),
            relative_strength=_trend(current_bars, 20),
            volatility_20d=_volatility(current_bars[-20:]),
            liquidity_score=_liquidity_score(current_bars[-1].amount),
            quality_score=0.7 if current_basic else 0.5,
            market_regime="unknown",
            data_quality="ok" if current_basic else "missing_daily_basic",
        )
    return MarketDataBundle(
        trade_date=trade_date,
        data_status=data_status,
        source_grade=source_grade,
        source_versions=source_versions,
        stock_basic=stock_basic,
        daily_bars=daily_bars,
        daily_basic=daily_basic,
        source_runs=source_runs,
        stocks=stocks,
        stock_names=stock_names,
        feature_profiles=feature_profiles,
    )


def _listing_days(list_date: date | None, trade_date: date) -> int:
    if list_date is None:
        return 9999
    return max((trade_date - list_date).days, 0)


def _trend(bars: list[DailyBar], window: int) -> float:
    start = bars[-window - 1].close
    end = bars[-1].close
    return 0.0 if start == 0 else (end - start) / start


def _volatility(bars: list[DailyBar]) -> float:
    closes = [bar.close for bar in bars]
    returns = [(closes[i] - closes[i - 1]) / closes[i - 1] for i in range(1, len(closes)) if closes[i - 1] != 0]
    return pstdev(returns) if len(returns) > 1 else 0.0


def _liquidity_score(amount: float | None) -> float:
    if amount is None:
        return 0.0
    return min(amount / 500000000.0, 1.0)
```

- [ ] **Step 4: Run tests**

Run: `.venv/bin/python -m pytest /Users/ccrt/股票分析助手/tests/test_feature_builder.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/stock_analyzer/data/feature_builder.py tests/test_feature_builder.py
git commit -m "feat: build features from real market data"
```

---

### Task 5: Supabase ingestion schema and repository persistence

**Files:**
- Create: `/Users/ccrt/股票分析助手/supabase/migrations/202607080002_ingestion_v1.sql`
- Modify: `/Users/ccrt/股票分析助手/src/stock_analyzer/storage/repositories.py`
- Modify: `/Users/ccrt/股票分析助手/tests/test_supabase_schema.py`
- Modify: `/Users/ccrt/股票分析助手/tests/test_repositories.py`

**Interfaces:**
- Produces repository methods:
  `save_market_bars(bars: list[DailyBar]) -> None`,
  `save_daily_basic_indicators(rows: list[DailyBasicRow]) -> None`,
  `save_data_source_runs(rows: list[SourceRunRecord]) -> None`
- Keeps existing `AnalysisRepository` methods backward-compatible for current tests.

- [ ] **Step 1: Add failing schema assertions**

```python
# Add to /Users/ccrt/股票分析助手/tests/test_supabase_schema.py
INGESTION_SCHEMA_PATH = (
    Path(__file__).resolve().parents[1]
    / "supabase"
    / "migrations"
    / "202607080002_ingestion_v1.sql"
)


def test_ingestion_schema_adds_market_data_tables_and_run_columns():
    sql = INGESTION_SCHEMA_PATH.read_text().lower()
    compact_sql = re.sub(r"\s+", " ", sql)

    for table in ["market_price_daily", "daily_basic_indicator"]:
        assert f"create table if not exists public.{table}" in sql
        assert f"alter table public.{table} enable row level security" in sql
        assert f"create policy {table}_service_role_all" in sql

    for column in ["stage", "attempt", "source_grade", "data_status", "record_count", "field_coverage", "payload"]:
        assert f"add column if not exists {column}" in compact_sql
```

- [ ] **Step 2: Add failing repository test**

```python
# Add to /Users/ccrt/股票分析助手/tests/test_repositories.py
from stock_analyzer.data.models import DailyBar, DailyBasicRow, DataStatus, SourceGrade, SourceRunRecord, SourceStatus


def test_in_memory_repository_upserts_ingestion_rows():
    repo = InMemoryAnalysisRepository()
    bar = DailyBar(
        trade_date=date(2026, 7, 8),
        ts_code="600000.SH",
        close=10.2,
        amount=100000000,
        source_name="tushare",
        source_grade=SourceGrade.PRIMARY,
    )
    basic = DailyBasicRow(
        trade_date=date(2026, 7, 8),
        ts_code="600000.SH",
        turnover_rate=1.2,
        source_name="tushare",
        source_grade=SourceGrade.PRIMARY,
    )
    run = SourceRunRecord(
        trade_date=date(2026, 7, 8),
        source_name="tushare",
        stage="daily",
        status=SourceStatus.SUCCESS,
        message="ok",
        source_grade=SourceGrade.PRIMARY,
        data_status=DataStatus.COMPLETE_PRIMARY,
        record_count=1,
    )

    repo.save_market_bars([bar])
    repo.save_daily_basic_indicators([basic])
    repo.save_data_source_runs([run])

    assert repo.market_bars == [bar]
    assert repo.daily_basic_indicators == [basic]
    assert repo.data_source_runs == [run]
```

- [ ] **Step 3: Run tests to verify failure**

Run: `.venv/bin/python -m pytest /Users/ccrt/股票分析助手/tests/test_supabase_schema.py /Users/ccrt/股票分析助手/tests/test_repositories.py -v`
Expected: FAIL for missing migration and repository methods.

- [ ] **Step 4: Add migration**

```sql
-- /Users/ccrt/股票分析助手/supabase/migrations/202607080002_ingestion_v1.sql
create table if not exists public.market_price_daily (
  trade_date date not null,
  ts_code text not null references public.stock_master(ts_code),
  open numeric,
  high numeric,
  low numeric,
  close numeric not null,
  pre_close numeric,
  pct_chg numeric,
  vol numeric,
  amount numeric,
  source_name text not null,
  source_grade text not null,
  fetched_at timestamptz not null default now(),
  primary key (trade_date, ts_code)
);

create table if not exists public.daily_basic_indicator (
  trade_date date not null,
  ts_code text not null references public.stock_master(ts_code),
  turnover_rate numeric,
  total_mv numeric,
  circ_mv numeric,
  pe_ttm numeric,
  pb numeric,
  source_name text not null,
  source_grade text not null,
  fetched_at timestamptz not null default now(),
  primary key (trade_date, ts_code)
);

alter table public.data_source_run add column if not exists stage text not null default 'unknown';
alter table public.data_source_run add column if not exists attempt integer not null default 1;
alter table public.data_source_run add column if not exists source_grade text not null default 'primary';
alter table public.data_source_run add column if not exists data_status text not null default 'insufficient_live_data';
alter table public.data_source_run add column if not exists record_count integer not null default 0;
alter table public.data_source_run add column if not exists field_coverage jsonb not null default '{}'::jsonb;
alter table public.data_source_run add column if not exists payload jsonb not null default '{}'::jsonb;

alter table public.market_price_daily enable row level security;
alter table public.daily_basic_indicator enable row level security;

create policy market_price_daily_service_role_all on public.market_price_daily
  for all
  to service_role
  using (true)
  with check (true);

create policy daily_basic_indicator_service_role_all on public.daily_basic_indicator
  for all
  to service_role
  using (true)
  with check (true);
```

- [ ] **Step 5: Extend repository protocol and in-memory repository**

```python
# /Users/ccrt/股票分析助手/src/stock_analyzer/storage/repositories.py
# Add imports:
from stock_analyzer.data.models import DailyBar, DailyBasicRow, SourceRunRecord

# Add protocol methods:
def save_market_bars(self, bars: List[DailyBar]) -> None: ...
def save_daily_basic_indicators(self, rows: List[DailyBasicRow]) -> None: ...
def save_data_source_runs(self, rows: List[SourceRunRecord]) -> None: ...

# Add InMemoryAnalysisRepository fields in __init__:
market_bars: Optional[List[DailyBar]] = None,
daily_basic_indicators: Optional[List[DailyBasicRow]] = None,
data_source_runs: Optional[List[SourceRunRecord]] = None,
self.market_bars = list(market_bars or [])
self.daily_basic_indicators = list(daily_basic_indicators or [])
self.data_source_runs = list(data_source_runs or [])

# Add methods:
def save_market_bars(self, bars: List[DailyBar]) -> None:
    self.market_bars = _upsert_model_list(
        self.market_bars,
        bars,
        key=lambda item: (item.trade_date, item.ts_code),
    )

def save_daily_basic_indicators(self, rows: List[DailyBasicRow]) -> None:
    self.daily_basic_indicators = _upsert_model_list(
        self.daily_basic_indicators,
        rows,
        key=lambda item: (item.trade_date, item.ts_code),
    )

def save_data_source_runs(self, rows: List[SourceRunRecord]) -> None:
    self.data_source_runs.extend(rows)
```

- [ ] **Step 6: Extend Supabase repository**

```python
# /Users/ccrt/股票分析助手/src/stock_analyzer/storage/repositories.py
def save_market_bars(self, bars: List[DailyBar]) -> None:
    rows = [
        {
            "trade_date": item.trade_date.isoformat(),
            "ts_code": item.ts_code,
            "open": item.open,
            "high": item.high,
            "low": item.low,
            "close": item.close,
            "pre_close": item.pre_close,
            "pct_chg": item.pct_chg,
            "vol": item.vol,
            "amount": item.amount,
            "source_name": item.source_name,
            "source_grade": item.source_grade.value,
        }
        for item in bars
    ]
    if rows:
        self.client.table("market_price_daily").upsert(rows, on_conflict="trade_date,ts_code").execute()

def save_daily_basic_indicators(self, rows: List[DailyBasicRow]) -> None:
    payload = [
        {
            "trade_date": item.trade_date.isoformat(),
            "ts_code": item.ts_code,
            "turnover_rate": item.turnover_rate,
            "total_mv": item.total_mv,
            "circ_mv": item.circ_mv,
            "pe_ttm": item.pe_ttm,
            "pb": item.pb,
            "source_name": item.source_name,
            "source_grade": item.source_grade.value,
        }
        for item in rows
    ]
    if payload:
        self.client.table("daily_basic_indicator").upsert(payload, on_conflict="trade_date,ts_code").execute()

def save_data_source_runs(self, rows: List[SourceRunRecord]) -> None:
    payload = [
        {
            "trade_date": item.trade_date.isoformat(),
            "source_name": item.source_name,
            "stage": item.stage,
            "status": item.status.value,
            "message": item.message,
            "attempt": item.attempt,
            "source_grade": item.source_grade.value,
            "data_status": item.data_status.value,
            "record_count": item.record_count,
            "field_coverage": item.field_coverage,
            "payload": item.payload,
        }
        for item in rows
    ]
    if payload:
        self.client.table("data_source_run").insert(payload).execute()
```

- [ ] **Step 7: Run tests**

Run: `.venv/bin/python -m pytest /Users/ccrt/股票分析助手/tests/test_supabase_schema.py /Users/ccrt/股票分析助手/tests/test_repositories.py -v`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add supabase/migrations/202607080002_ingestion_v1.sql src/stock_analyzer/storage/repositories.py tests/test_supabase_schema.py tests/test_repositories.py
git commit -m "feat: persist ingestion source data"
```

---

### Task 6: Provider 编排、重试和生产 pipeline 接入

**Files:**
- Create: `/Users/ccrt/股票分析助手/src/stock_analyzer/data/provider.py`
- Modify: `/Users/ccrt/股票分析助手/src/stock_analyzer/pipeline.py`
- Modify: `/Users/ccrt/股票分析助手/src/stock_analyzer/cli.py`
- Modify: `/Users/ccrt/股票分析助手/tests/test_pipeline_smoke.py`
- Modify: `/Users/ccrt/股票分析助手/tests/test_cli.py`

**Interfaces:**
- Produces: `MarketDataProvider.load(trade_date: date) -> MarketDataBundle`
- Produces: `build_production_market_data_provider(config: AppConfig) -> MarketDataProvider`
- Modifies: `run_daily_pipeline(..., market_data_provider: Optional[MarketDataProvider] = None)`

- [ ] **Step 1: Add failing pipeline tests**

```python
# Add to /Users/ccrt/股票分析助手/tests/test_pipeline_smoke.py
from stock_analyzer.data.models import DataStatus, MarketDataBundle, SourceGrade
from stock_analyzer.pipeline import _sample_market


class FakeProductionProvider:
    def load(self, trade_date):
        stocks, stock_names, feature_profiles = _sample_market(trade_date)
        return MarketDataBundle(
            trade_date=trade_date,
            data_status=DataStatus.COMPLETE_PRIMARY,
            source_grade=SourceGrade.PRIMARY,
            source_versions={"fake-live": trade_date.isoformat()},
            stock_basic=[],
            daily_bars=[],
            daily_basic=[],
            stocks=stocks,
            stock_names=stock_names,
            feature_profiles=feature_profiles,
            source_runs=[],
        )


def test_run_daily_pipeline_production_uses_provider_and_persists_real_bundle(tmp_path):
    repo = InMemoryAnalysisRepository()

    result = run_daily_pipeline(
        date(2026, 7, 7),
        tmp_path,
        repository=repo,
        fixture_mode=False,
        market_data_provider=FakeProductionProvider(),
    )

    assert result.recommendations
    assert repo.recommendations
    assert (tmp_path / "index.html").exists()
```

- [ ] **Step 2: Add failing CLI test**

```python
# Add to /Users/ccrt/股票分析助手/tests/test_cli.py
from stock_analyzer.data.models import DataStatus, MarketDataBundle, SourceGrade
from stock_analyzer.pipeline import _sample_market


class FakeProductionProvider:
    def load(self, trade_date):
        stocks, stock_names, feature_profiles = _sample_market(trade_date)
        return MarketDataBundle(
            trade_date=trade_date,
            data_status=DataStatus.COMPLETE_PRIMARY,
            source_grade=SourceGrade.PRIMARY,
            source_versions={"fake-live": trade_date.isoformat()},
            stock_basic=[],
            daily_bars=[],
            daily_basic=[],
            stocks=stocks,
            stock_names=stock_names,
            feature_profiles=feature_profiles,
            source_runs=[],
        )


def test_run_daily_with_supabase_config_calls_production_provider(monkeypatch):
    repo = RecordingRepository()
    monkeypatch.setenv("SUPABASE_URL", "https://supabase.example.test")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "fake-service-role-key")
    monkeypatch.setenv("TUSHARE_TOKEN", "fake-tushare-token")
    monkeypatch.setattr("stock_analyzer.cli._analysis_repository", lambda config, **kwargs: repo)
    monkeypatch.setattr("stock_analyzer.cli.build_production_market_data_provider", lambda config: FakeProductionProvider())

    result = CliRunner().invoke(app, ["run-daily", "--trade-date", "2026-07-07"])

    assert result.exit_code == 0
    assert "daily run completed for 2026-07-07" in result.stdout
    assert "fake-tushare-token" not in result.output
```

- [ ] **Step 3: Run tests to verify failure**

Run: `.venv/bin/python -m pytest /Users/ccrt/股票分析助手/tests/test_pipeline_smoke.py /Users/ccrt/股票分析助手/tests/test_cli.py -v`
Expected: FAIL because `market_data_provider` and `build_production_market_data_provider` are missing.

- [ ] **Step 4: Add provider interface**

```python
# /Users/ccrt/股票分析助手/src/stock_analyzer/data/provider.py
from __future__ import annotations

from datetime import date
from typing import Protocol

from stock_analyzer.config import AppConfig
from stock_analyzer.data.models import DataStatus, MarketDataBundle, SourceGrade, SourceRunRecord, SourceStatus
from stock_analyzer.data.tushare_source import TushareMarketDataSource


class CurrentLiveDataUnavailable(RuntimeError):
    pass


class MarketDataProvider(Protocol):
    def load(self, trade_date: date) -> MarketDataBundle: ...


class TushareProvider:
    def __init__(self, source: TushareMarketDataSource) -> None:
        self.source = source

    def load(self, trade_date: date) -> MarketDataBundle:
        stock_basic = self.source.fetch_stock_basic()
        daily_bars = self.source.fetch_daily(trade_date)
        daily_basic = self.source.fetch_daily_basic(trade_date)
        runs = [
            SourceRunRecord(
                trade_date=trade_date,
                source_name="tushare",
                stage="daily",
                status=SourceStatus.SUCCESS,
                message="ok",
                source_grade=SourceGrade.PRIMARY,
                data_status=DataStatus.COMPLETE_PRIMARY,
                record_count=len(daily_bars),
            )
        ]
        if not daily_bars:
            raise CurrentLiveDataUnavailable(f"Tushare returned no current daily bars for {trade_date.isoformat()}")
        return MarketDataBundle(
            trade_date=trade_date,
            data_status=DataStatus.COMPLETE_PRIMARY,
            source_grade=SourceGrade.PRIMARY,
            source_versions={"tushare": f"daily:{trade_date.isoformat()}"},
            stock_basic=stock_basic,
            daily_bars=daily_bars,
            daily_basic=daily_basic,
            source_runs=runs,
        )


def build_production_market_data_provider(config: AppConfig) -> MarketDataProvider:
    token = config.resolve_tushare_token()
    if not token:
        raise CurrentLiveDataUnavailable("Tushare token is missing and no live backup provider is configured")
    return TushareProvider(TushareMarketDataSource(token=token))
```

- [ ] **Step 5: Modify pipeline production path**

```python
# /Users/ccrt/股票分析助手/src/stock_analyzer/pipeline.py
# Add parameter:
market_data_provider: Optional[MarketDataProvider] = None,

# Replace production guard and sample selection with:
if fixture_mode or dry_run:
    stocks, stock_names, feature_profiles = _sample_market(trade_date)
else:
    if market_data_provider is None:
        raise ProductionDataSourceUnavailable(PRODUCTION_DATA_SOURCE_UNAVAILABLE_MESSAGE)
    bundle = market_data_provider.load(trade_date)
    if not bundle.can_generate_decisions:
        raise ProductionDataSourceUnavailable("Current live data is unavailable; no production decisions were generated.")
    stocks, stock_names, feature_profiles = bundle.to_pipeline_inputs()
    if persist:
        repository.save_stock_master(stocks)
        repository.save_market_bars(bundle.daily_bars)
        repository.save_daily_basic_indicators(bundle.daily_basic)
        repository.save_data_source_runs(bundle.source_runs)
```

- [ ] **Step 6: Modify CLI production path**

```python
# /Users/ccrt/股票分析助手/src/stock_analyzer/cli.py
# Import:
from stock_analyzer.data.provider import CurrentLiveDataUnavailable, build_production_market_data_provider

# In run_daily(), remove the unconditional _fail(PRODUCTION_DATA_SOURCE_UNAVAILABLE_MESSAGE).
# Before calling run_daily_pipeline:
market_data_provider = None
if not effective_fixture_mode and not dry_run:
    try:
        market_data_provider = build_production_market_data_provider(config)
    except CurrentLiveDataUnavailable as exc:
        _fail(str(exc))

# Pass to run_daily_pipeline:
market_data_provider=market_data_provider,
```

- [ ] **Step 7: Run tests**

Run: `.venv/bin/python -m pytest /Users/ccrt/股票分析助手/tests/test_pipeline_smoke.py /Users/ccrt/股票分析助手/tests/test_cli.py -v`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add src/stock_analyzer/data/provider.py src/stock_analyzer/pipeline.py src/stock_analyzer/cli.py tests/test_pipeline_smoke.py tests/test_cli.py
git commit -m "feat: connect production pipeline to market provider"
```

---

### Task 7: 缓存-only 数据不可用 notice 和报告边界

**Files:**
- Modify: `/Users/ccrt/股票分析助手/src/stock_analyzer/reports/generator.py`
- Modify: `/Users/ccrt/股票分析助手/src/stock_analyzer/reports/templates/index.html.j2`
- Modify: `/Users/ccrt/股票分析助手/src/stock_analyzer/reports/templates/stock.html.j2`
- Modify: `/Users/ccrt/股票分析助手/tests/test_report_generation.py`
- Modify: `/Users/ccrt/股票分析助手/tests/test_pipeline_smoke.py`

**Interfaces:**
- Produces: `render_data_unavailable_notice(output_dir: Path, notice: DataUnavailableNotice) -> None`
- Modifies: `render_reports(..., data_status: DataStatus | None = None, source_versions: dict[str, str] | None = None)`

- [ ] **Step 1: Write failing report test**

```python
# Add to /Users/ccrt/股票分析助手/tests/test_report_generation.py
from stock_analyzer.data.models import DataUnavailableNotice
from stock_analyzer.reports.generator import render_data_unavailable_notice


def test_data_unavailable_notice_does_not_create_stock_analysis_pages(tmp_path):
    notice = DataUnavailableNotice(
        trade_date=date(2026, 7, 8),
        reason="current live data unavailable",
        last_successful_trade_date=date(2026, 7, 7),
    )

    render_data_unavailable_notice(tmp_path, notice)

    latest = json.loads((tmp_path / "data" / "latest.json").read_text(encoding="utf-8"))
    html = (tmp_path / "index.html").read_text(encoding="utf-8")

    assert latest["report_mode"] == "data_unavailable"
    assert latest["recommendations"] == []
    assert "不生成新的股票分析结论" in html
    assert not (tmp_path / "daily" / "2026-07-08" / "stocks").exists()
```

- [ ] **Step 2: Run test to verify failure**

Run: `.venv/bin/python -m pytest /Users/ccrt/股票分析助手/tests/test_report_generation.py -v`
Expected: FAIL because `render_data_unavailable_notice` does not exist.

- [ ] **Step 3: Add notice renderer**

```python
# /Users/ccrt/股票分析助手/src/stock_analyzer/reports/generator.py
from stock_analyzer.data.models import DataUnavailableNotice


def render_data_unavailable_notice(output_dir: Path, notice: DataUnavailableNotice) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    data_dir = output_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "trade_date": notice.trade_date.isoformat(),
        "report_mode": "data_unavailable",
        "is_fixture": False,
        "warning": "当日实时数据不可用，不生成新的股票分析结论。",
        "reason": notice.reason,
        "last_successful_trade_date": notice.last_successful_trade_date.isoformat()
        if notice.last_successful_trade_date
        else None,
        "recommendations": [],
        "focus_states": [],
        "evidence_packages": [],
        "recommendation_details": [],
    }
    (data_dir / "latest.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    template_dir = Path(__file__).parent / "templates"
    env = Environment(loader=FileSystemLoader(template_dir), autoescape=select_autoescape(["html"]))
    html = env.get_template("index.html.j2").render(
        trade_date=notice.trade_date,
        recommendation_details=[],
        focus_states=[],
        is_fixture=False,
        fixture_warning=None,
        data_unavailable_notice=notice,
    )
    (output_dir / "index.html").write_text(html, encoding="utf-8")
    daily_dir = output_dir / "daily" / notice.trade_date.isoformat()
    daily_dir.mkdir(parents=True, exist_ok=True)
    (daily_dir / "index.html").write_text(html, encoding="utf-8")
```

- [ ] **Step 4: Update index template for notice**

```jinja2
{# /Users/ccrt/股票分析助手/src/stock_analyzer/reports/templates/index.html.j2 #}
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>股票观察报告</title>
</head>
<body>
  <main>
{% if data_unavailable_notice %}
    <h1>{{ trade_date.isoformat() }} 数据不可用</h1>
    <section role="alert">
      <h2>当日实时数据不可用</h2>
      <p>不生成新的股票分析结论。</p>
      {% if data_unavailable_notice.last_successful_trade_date %}
      <p>最近一次成功数据日期：{{ data_unavailable_notice.last_successful_trade_date.isoformat() }}</p>
      {% endif %}
    </section>
{% else %}
    <h1>股票观察报告</h1>
    {% if is_fixture %}
    <section role="alert">
      <h2>Fixture/sample report</h2>
      <p>{{ fixture_warning }}</p>
    </section>
    {% endif %}

    <section>
      <h2>今日推荐</h2>
      {% for item in recommendation_details %}
      <article>
        <h3><a href="{{ item.stock_page }}">{{ item.name }} {{ item.ts_code }}</a></h3>
        <p>{{ item.action }}，评分 {{ item.score }}</p>
        <h4>发生了什么</h4>
        <p>{{ item.what_happened }}</p>
        <h4>支撑证据</h4>
        <ul>{% for line in item.evidence.support %}<li>{{ line }}</li>{% endfor %}</ul>
        <h4>反证与风险</h4>
        <ul>{% for line in item.evidence.counter_evidence %}<li>{{ line }}</li>{% endfor %}</ul>
        <h4>确认信号</h4>
        <ul>{% for line in item.evidence.confirmation_signals %}<li>{{ line }}</li>{% endfor %}</ul>
        <h4>失效信号</h4>
        <ul>{% for line in item.evidence.invalidation_signals %}<li>{{ line }}</li>{% endfor %}</ul>
        <h4>观察计划</h4>
        <ul>{% for line in item.observation_plan %}<li>{{ line }}</li>{% endfor %}</ul>
        <h4>证据与规则引用</h4>
        <p>证据：{{ item.evidence.evidence_id or "未记录" }}</p>
        <p>规则：{{ "；".join(item.evidence.rule_references) or "未匹配规则" }}</p>
        <h4>数据可信度</h4>
        <p>{{ item.evidence.data_credibility }}</p>
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
{% endif %}
  </main>
</body>
</html>
```

- [ ] **Step 5: Run report tests**

Run: `.venv/bin/python -m pytest /Users/ccrt/股票分析助手/tests/test_report_generation.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/stock_analyzer/reports/generator.py src/stock_analyzer/reports/templates/index.html.j2 src/stock_analyzer/reports/templates/stock.html.j2 tests/test_report_generation.py tests/test_pipeline_smoke.py
git commit -m "feat: render data unavailable notice safely"
```

---

### Task 8: CLI 健康检查、真实 smoke 和全量验证

**Files:**
- Modify: `/Users/ccrt/股票分析助手/src/stock_analyzer/data/health.py`
- Modify: `/Users/ccrt/股票分析助手/src/stock_analyzer/cli.py`
- Modify: `/Users/ccrt/股票分析助手/tests/test_config_health.py`
- Modify: `/Users/ccrt/股票分析助手/tests/test_cli.py`
- Modify: `/Users/ccrt/股票分析助手/README.md`

**Interfaces:**
- Produces CLI: `PYTHONPATH=src .venv/bin/python -m stock_analyzer health-check`
- Produces CLI: `PYTHONPATH=src .venv/bin/python -m stock_analyzer health-check --live-tushare-smoke`
- Keeps default health-check offline except credential file existence and config shape.

- [ ] **Step 1: Add failing health test**

```python
# Add to /Users/ccrt/股票分析助手/tests/test_config_health.py
def test_health_check_masks_tushare_token(monkeypatch):
    monkeypatch.setenv("TUSHARE_TOKEN", "secret-token-value")

    report = run_health_checks(AppConfig.load())
    lines = "\n".join(report.as_lines())

    assert "present:env" in lines
    assert "secret-token-value" not in lines
```

- [ ] **Step 2: Run test to verify failure**

Run: `.venv/bin/python -m pytest /Users/ccrt/股票分析助手/tests/test_config_health.py -v`
Expected: FAIL until health check reports masked Tushare credential status.

- [ ] **Step 3: Update health checks**

```python
# /Users/ccrt/股票分析助手/src/stock_analyzer/data/health.py
# In credential check output, include:
f"tushare_token: {config.tushare_token_status()}"
# Do not include config.resolve_tushare_token() in any line.
```

- [ ] **Step 4: Add CLI live smoke option**

```python
# /Users/ccrt/股票分析助手/src/stock_analyzer/cli.py
@app.command("health-check")
def health_check(
    live_tushare_smoke: bool = typer.Option(False, "--live-tushare-smoke"),
) -> None:
    config = AppConfig.load()
    report = run_health_checks(config)
    for line in report.as_lines():
        typer.echo(line)
    if live_tushare_smoke:
        token = config.resolve_tushare_token()
        if not token:
            _fail("Tushare token missing; set TUSHARE_TOKEN or TUSHARE_TOKEN_PATH")
        source = TushareMarketDataSource(token=token)
        rows = source.fetch_daily(date(2026, 7, 8))
        typer.echo(f"live_tushare_smoke: rows={len(rows)}")
```

- [ ] **Step 5: Run unit tests**

Run: `.venv/bin/python -m pytest /Users/ccrt/股票分析助手/tests/test_config_health.py /Users/ccrt/股票分析助手/tests/test_cli.py -v`
Expected: PASS.

- [ ] **Step 6: Run full local verification**

Run: `.venv/bin/python -m pytest`
Expected: PASS under Python 3.12 from project `.venv`. Do not use the system Python on this machine, because it is Python 3.9.6 and the project requires Python 3.11+.

- [ ] **Step 7: Install only the live-smoke data dependency**

Run: `.venv/bin/python -m pip install 'tushare>=1.4.19'`
Expected: PASS. Do not install `akshare` in this step; AkShare is only needed when implementing or smoke-testing the live backup source.

- [ ] **Step 8: Run live Tushare smoke**

Run: `PYTHONPATH=src .venv/bin/python -m stock_analyzer health-check --live-tushare-smoke`
Expected: PASS with `live_tushare_smoke: rows=<positive integer>` or a clear Tushare API error that does not print the token.

- [ ] **Step 9: Run production daily after Supabase env vars are configured locally**

Run: `set -a; . ./.env.local; set +a; PYTHONPATH=src .venv/bin/python -m stock_analyzer run-daily --trade-date 2026-07-08`
Expected: If live data is available, command exits 0, writes Supabase rows, and writes `/Users/ccrt/股票分析助手/reports/index.html`. If live data is unavailable, command exits nonzero and no normal recommendation report is published.

- [ ] **Step 10: Commit**

```bash
git add src/stock_analyzer/data/health.py src/stock_analyzer/cli.py tests/test_config_health.py tests/test_cli.py README.md
git commit -m "feat: add ingestion health checks and smoke path"
```

---

### Task 9: Supabase migration, GitHub sync, and report exposure checkpoint

**Files:**
- Modify only if verification finds a concrete code defect in files touched by Tasks 1-8.

**Interfaces:**
- Consumes: migrations from Task 5.
- Consumes: production report generated by Task 8.
- Produces: pushed branch on GitHub main or PR branch, depending on final integration choice.

- [ ] **Step 1: Apply Supabase migration**

Run through Supabase connector or CLI against project `npklfuknflckilxehiob`: apply `/Users/ccrt/股票分析助手/supabase/migrations/202607080002_ingestion_v1.sql`.
Expected: migration succeeds; existing `202607070001_init_core.sql` tables remain; RLS stays enabled.

- [ ] **Step 2: Verify Supabase security advisor**

Run Supabase database lints/security advisor for project `npklfuknflckilxehiob`.
Expected: no critical RLS or exposed service key findings caused by V1 migration.

- [ ] **Step 3: Verify production rows**

After a successful live run, query row counts for:

```sql
select count(*) from public.market_price_daily where trade_date = '2026-07-08';
select count(*) from public.daily_basic_indicator where trade_date = '2026-07-08';
select count(*) from public.recommendation_daily where trade_date = '2026-07-08';
select count(*) from public.evidence_package_index where trade_date = '2026-07-08';
select count(*) from public.evaluation_task where trade_date = '2026-07-08';
```

Expected: market rows are positive; recommendation rows are between 0 and 10; evidence and evaluation rows match any recommendations created.

- [ ] **Step 4: Verify no fake data leaked into production**

Run: `rg -n "Fixture/sample|local sample data|浦发银行|贵州茅台|_sample_market" /Users/ccrt/股票分析助手/reports /Users/ccrt/股票分析助手/src/stock_analyzer/pipeline.py`
Expected: reports contain no fixture warning and production path in `pipeline.py` only calls `_sample_market()` under `fixture_mode` or `dry_run`.

- [ ] **Step 5: Verify Cloudflare-ready output**

Run: `test -f /Users/ccrt/股票分析助手/reports/index.html`
Expected: command exits 0 after successful live report generation. Cloudflare Pages can expose only `/reports` static output and password middleware, while Supabase keys stay in local env or Cloudflare secrets.

- [ ] **Step 6: Push**

```bash
git status --short
git push origin HEAD:main
```

Expected: working tree clean before push; GitHub repository `https://github.com/ccrt26/stock-analysis-assistant-v3` receives all V1 implementation commits.

---

## Self-Review Checklist

- Spec coverage: Tushare token, Tushare datasets, realtime backup, cache non-decision rule, Supabase persistence, report behavior, max 10 recommendations, no sample production data, and live smoke all map to tasks.
- Placeholder scan: plan contains no unspecified task names, no missing paths, all interfaces are defined above, and no instruction generates conclusions from cache.
- Type consistency: `MarketDataBundle`, `DataStatus`, `SourceGrade`, `SourceRunRecord`, `DailyBar`, and `DailyBasicRow` are defined before downstream tasks consume them.
- Risk checkpoint: Task 6 and Task 7 require reviewer attention because they decide whether a production run can publish a report.
