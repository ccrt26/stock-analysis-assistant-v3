from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import math
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from stock_analyzer.data.research_contracts import ResearchDatasetId


@dataclass(frozen=True)
class TargetedGapClaim:
    knowledge_id: str
    core_theory: str
    source_refs: tuple[str, ...]
    required_facts: tuple[ResearchDatasetId, ...]


@dataclass(frozen=True)
class TargetedGapEvidence:
    knowledge_id: str
    data_usable: bool
    overall_direction: str
    earlier_direction: str
    later_direction: str
    counter_evidence: str
    observations: dict[str, int | float | str]


TARGETED_SOURCE_REFS = frozenset(
    {
        "https://kjs.mof.gov.cn/zt/kjzzss/kuaijizhunzeshishi/200806/"
        "t20080618_46246.htm",
        "10.1016/j.pacfin.2018.10.017",
        "10.1016/j.pacfin.2021.101607",
        "10.1287/mnsc.2023.4904",
        "10.1016/j.irfa.2023.102770",
        "10.1016/j.jacceco.2010.09.001",
    }
)


TARGETED_GAP_CLAIMS = (
    TargetedGapClaim(
        knowledge_id="src_cn_business_segment_materiality",
        core_theory=(
            "公司与热点存在真实联系，不仅需要正式资料证明业务存在，还要核对相关产品或业务分部对收入、成本、"
            "利润和整体经营的实际贡献；概念名称、规划、研发或小额业务不能自动推导为公司整体明显受益。"
        ),
        source_refs=(
            "https://kjs.mof.gov.cn/zt/kjzzss/kuaijizhunzeshishi/200806/"
            "t20080618_46246.htm",
        ),
        required_facts=(
            ResearchDatasetId.COMPANY_PROFILE,
            ResearchDatasetId.MAIN_BUSINESS,
            ResearchDatasetId.INCOME_STATEMENT,
            ResearchDatasetId.ANNOUNCEMENT,
        ),
    ),
    TargetedGapClaim(
        knowledge_id="src_cn_earnings_growth_persistence",
        core_theory=(
            "单期净利润增长不能证明经营趋势成立，需要把总收入、营业利润、归母净利润、经营现金流、毛利率和费用"
            "变化放在连续可比报告期中观察，并区分行业共同变化和公司特有变化，不能把同比增长写成超预期。"
        ),
        source_refs=("10.1016/j.pacfin.2018.10.017",),
        required_facts=(
            ResearchDatasetId.INCOME_STATEMENT,
            ResearchDatasetId.BALANCE_SHEET,
            ResearchDatasetId.CASH_FLOW,
            ResearchDatasetId.FINANCIAL_INDICATOR,
            ResearchDatasetId.INDUSTRY_MEMBER,
        ),
    ),
    TargetedGapClaim(
        knowledge_id="src_cn_relative_valuation_context",
        core_theory=(
            "市盈率、市净率和市销率只有在盈利状态、行业、规模和公司自身历史可比时才有解释意义；估值用于判断市场"
            "已经反映了多少预期和候选承担多高兑现要求，低估值或高估值都不能单独预测未来收益。"
        ),
        source_refs=(
            "10.1016/j.pacfin.2021.101607",
            "10.1287/mnsc.2023.4904",
        ),
        required_facts=(
            ResearchDatasetId.DAILY_BASIC,
            ResearchDatasetId.INDUSTRY_MEMBER,
            ResearchDatasetId.INCOME_STATEMENT,
            ResearchDatasetId.BALANCE_SHEET,
            ResearchDatasetId.CASH_FLOW,
            ResearchDatasetId.FINANCIAL_INDICATOR,
        ),
    ),
    TargetedGapClaim(
        knowledge_id="src_cn_turnaround_financial_consistency",
        core_theory=(
            "困境反转不能只看利润转正，需要同时检查经营结果、经营现金、短期流动性、偿债压力、应收存货、资产减值"
            "和一次性损益；某一维度改善而其他关键维度继续恶化，只能说明局部改善而非反转完成。"
        ),
        source_refs=(
            "10.1016/j.irfa.2023.102770",
            "10.1016/j.jacceco.2010.09.001",
        ),
        required_facts=(
            ResearchDatasetId.INCOME_STATEMENT,
            ResearchDatasetId.BALANCE_SHEET,
            ResearchDatasetId.CASH_FLOW,
            ResearchDatasetId.FINANCIAL_INDICATOR,
        ),
    ),
)


def business_segment_materiality_observations(
    frame: pd.DataFrame,
) -> pd.DataFrame:
    required = {
        "ts_code",
        "report_period",
        "classification",
        "item_name",
        "curr_type",
        "company_curr_type",
        "bz_sales",
        "bz_cost",
        "bz_profit",
        "company_revenue",
        "company_operating_profit",
    }
    missing = sorted(required.difference(frame.columns))
    if missing:
        raise ValueError(f"missing business segment columns: {', '.join(missing)}")

    result = frame.copy()
    result["report_period"] = pd.to_datetime(result["report_period"])
    numeric = (
        "bz_sales",
        "bz_cost",
        "bz_profit",
        "company_revenue",
        "company_operating_profit",
    )
    for column in numeric:
        result[column] = pd.to_numeric(result[column], errors="coerce")

    currency_comparable = (
        result["curr_type"].notna()
        & result["company_curr_type"].notna()
        & result["curr_type"].eq(result["company_curr_type"])
    )
    valid_sales = currency_comparable & result["company_revenue"].gt(0)
    valid_profit = currency_comparable & result["company_operating_profit"].ne(0)
    valid_margin = currency_comparable & result["bz_sales"].gt(0)

    result["sales_share"] = np.where(
        valid_sales,
        result["bz_sales"] / result["company_revenue"],
        np.nan,
    )
    result["profit_share"] = np.where(
        valid_profit,
        result["bz_profit"] / result["company_operating_profit"],
        np.nan,
    )
    result["gross_margin"] = np.where(
        valid_margin,
        (result["bz_sales"] - result["bz_cost"]) / result["bz_sales"],
        np.nan,
    )
    result["ratio_status"] = np.select(
        [~currency_comparable, valid_sales & valid_profit & valid_margin],
        ["currency_mismatch", "comparable"],
        default="invalid_denominator",
    )
    return result.sort_values(
        ["ts_code", "report_period", "classification", "item_name"],
        kind="mergesort",
    ).reset_index(drop=True)


def earnings_growth_persistence_observations(
    frame: pd.DataFrame,
) -> pd.DataFrame:
    required = {
        "ts_code",
        "report_period",
        "industry_code",
        "revenue",
        "operate_profit",
        "n_income_attr_p",
        "n_cashflow_act",
        "total_assets",
        "grossprofit_margin",
        "expense_rate",
    }
    missing = sorted(required.difference(frame.columns))
    if missing:
        raise ValueError(f"missing earnings history columns: {', '.join(missing)}")

    result = frame.copy()
    result["report_period"] = pd.to_datetime(result["report_period"])
    numeric = required.difference(
        {"ts_code", "report_period", "industry_code"}
    )
    for column in numeric:
        result[column] = pd.to_numeric(result[column], errors="coerce")
    result = result.sort_values(
        ["ts_code", "report_period"], kind="mergesort"
    ).reset_index(drop=True)
    company = result.groupby("ts_code", sort=False)
    prior_assets = company["total_assets"].shift(4)

    component_map = {
        "revenue": "revenue_change_scaled",
        "operate_profit": "operating_profit_change_scaled",
        "n_income_attr_p": "net_income_change_scaled",
        "n_cashflow_act": "operating_cash_change_scaled",
    }
    for source, target in component_map.items():
        prior = company[source].shift(4)
        result[target] = (result[source] - prior) / prior_assets.where(
            prior_assets.gt(0)
        )
    result["gross_margin_change"] = (
        result["grossprofit_margin"] - company["grossprofit_margin"].shift(4)
    )
    result["expense_rate_change"] = (
        result["expense_rate"] - company["expense_rate"].shift(4)
    )
    future_income = company["n_income_attr_p"].shift(-4)
    result["next_year_net_income_change_scaled"] = (
        future_income - result["n_income_attr_p"]
    ) / result["total_assets"].where(result["total_assets"].gt(0))

    comparison_columns = tuple(component_map.values()) + (
        "gross_margin_change",
        "expense_rate_change",
    )
    industry_groups = result.groupby(
        ["report_period", "industry_code"], dropna=False, sort=False
    )
    for column in comparison_columns:
        median_name = f"industry_{column.removesuffix('_scaled')}_median"
        result[median_name] = industry_groups[column].transform("median")
        relative_name = f"relative_{column.removesuffix('_scaled')}"
        result[relative_name] = result[column] - result[median_name]

    return result.replace([np.inf, -np.inf], np.nan)


def _expanding_percentile(series: pd.Series) -> pd.Series:
    values = pd.to_numeric(series, errors="coerce")
    output: list[float] = []
    for index, value in enumerate(values):
        history = values.iloc[: index + 1].dropna()
        if pd.isna(value) or history.empty:
            output.append(np.nan)
        else:
            output.append(float(history.le(value).sum() / len(history)))
    return pd.Series(output, index=series.index, dtype="float64")


def relative_valuation_context_observations(
    frame: pd.DataFrame,
) -> pd.DataFrame:
    required = {
        "formation_date",
        "ts_code",
        "industry_code",
        "pe_ttm",
        "pb",
        "ps_ttm",
        "total_mv",
        "n_income_attr_p",
        "roe",
        "revenue_growth",
        "cash_quality",
    }
    missing = sorted(required.difference(frame.columns))
    if missing:
        raise ValueError(f"missing valuation context columns: {', '.join(missing)}")

    result = frame.copy()
    result["formation_date"] = pd.to_datetime(result["formation_date"])
    numeric = required.difference(
        {"formation_date", "ts_code", "industry_code"}
    )
    for column in numeric:
        result[column] = pd.to_numeric(result[column], errors="coerce")
    result = result.sort_values(
        ["ts_code", "formation_date"], kind="mergesort"
    ).reset_index(drop=True)
    result["profitability_state"] = np.select(
        [result["n_income_attr_p"].gt(0), result["n_income_attr_p"].le(0)],
        ["profitable", "loss"],
        default="unknown",
    )

    metric_map = {
        "pe_ttm": "pe",
        "pb": "pb",
        "ps_ttm": "ps",
    }
    peer_keys = ["formation_date", "industry_code", "profitability_state"]
    result["peer_group_size"] = result.groupby(
        peer_keys, dropna=False, sort=False
    )["ts_code"].transform("size")
    for source, label in metric_map.items():
        valid_column = f"_{label}_valid_value"
        result[f"{label}_status"] = np.where(
            result[source].gt(0), "valid", "invalid_nonpositive"
        )
        result[valid_column] = result[source].where(result[source].gt(0))
        result[f"peer_{label}_percentile"] = result.groupby(
            peer_keys, dropna=False, sort=False
        )[valid_column].rank(method="average", pct=True)
        result[f"history_{label}_percentile"] = result.groupby(
            "ts_code", sort=False, group_keys=False
        )[valid_column].transform(_expanding_percentile)
        result = result.drop(columns=valid_column)

    result["market_cap_percentile"] = result.groupby(
        "formation_date", sort=False
    )["total_mv"].rank(method="average", pct=True)
    return result.sort_values(
        ["formation_date", "ts_code"], kind="mergesort"
    ).reset_index(drop=True)


def turnaround_financial_consistency_observations(
    frame: pd.DataFrame,
) -> pd.DataFrame:
    required = {
        "ts_code",
        "report_period",
        "revenue",
        "operate_profit",
        "n_income_attr_p",
        "n_cashflow_act",
        "total_assets",
        "total_cur_assets",
        "total_cur_liab",
        "total_liab",
        "money_cap",
        "st_borr",
        "non_cur_liab_due_1y",
        "accounts_receiv",
        "inventories",
        "assets_impair_loss",
        "non_oper_income",
    }
    missing = sorted(required.difference(frame.columns))
    if missing:
        raise ValueError(f"missing turnaround columns: {', '.join(missing)}")

    result = frame.copy()
    result["report_period"] = pd.to_datetime(result["report_period"])
    numeric = required.difference({"ts_code", "report_period"})
    for column in numeric:
        result[column] = pd.to_numeric(result[column], errors="coerce")
    result = result.sort_values(
        ["ts_code", "report_period"], kind="mergesort"
    ).reset_index(drop=True)
    company = result.groupby("ts_code", sort=False)
    prior_assets = company["total_assets"].shift(4).where(lambda value: value.gt(0))

    result["operating_result_change"] = (
        result["operate_profit"] - company["operate_profit"].shift(4)
    ) / prior_assets
    result["operating_cash_change"] = (
        result["n_cashflow_act"] - company["n_cashflow_act"].shift(4)
    ) / prior_assets

    current_ratio = result["total_cur_assets"] / result["total_cur_liab"].where(
        result["total_cur_liab"].gt(0)
    )
    result["liquidity_change"] = current_ratio - current_ratio.groupby(
        result["ts_code"], sort=False
    ).shift(4)

    debt_pressure = (
        result["st_borr"]
        + result["non_cur_liab_due_1y"]
        - result["money_cap"]
    ) / result["total_assets"].where(result["total_assets"].gt(0))
    result["debt_pressure_change"] = debt_pressure - debt_pressure.groupby(
        result["ts_code"], sort=False
    ).shift(4)

    working_capital_pressure = (
        result["accounts_receiv"] + result["inventories"]
    ) / result["total_assets"].where(result["total_assets"].gt(0))
    result["receivable_inventory_pressure_change"] = (
        working_capital_pressure
        - working_capital_pressure.groupby(result["ts_code"], sort=False).shift(4)
    )

    quality_pressure = (
        result["assets_impair_loss"] - result["non_oper_income"]
    ) / result["total_assets"].where(result["total_assets"].gt(0))
    result["impairment_nonoperating_change"] = (
        quality_pressure
        - quality_pressure.groupby(result["ts_code"], sort=False).shift(4)
    )

    contradictions = pd.concat(
        [
            result["operating_cash_change"].le(0),
            result["liquidity_change"].le(0),
            result["debt_pressure_change"].ge(0),
            result["receivable_inventory_pressure_change"].ge(0),
            result["impairment_nonoperating_change"].ge(0),
        ],
        axis=1,
    ).sum(axis=1)
    result["contradiction_count"] = contradictions.where(
        result["operating_result_change"].notna()
    ).astype("Int64")
    return result.replace([np.inf, -np.inf], np.nan)


def _fact_paths(root: Path, name: str) -> list[str]:
    paths = sorted((Path(root) / "facts" / name).rglob("*.parquet"))
    if not paths:
        raise FileNotFoundError(f"no governed fact partitions found for {name}")
    return [str(path) for path in paths]


def _query_frame(sql: str, parameters: list[object]) -> pd.DataFrame:
    with duckdb.connect(":memory:") as connection:
        return connection.execute(sql, parameters).fetchdf()


def load_business_segment_panel(
    root: Path,
    analysis_date: date,
) -> pd.DataFrame:
    sql = """
        with main_visible as (
          select ts_code, cast(report_period as date) report_period,
                 classification, item_name, curr_type,
                 bz_sales, bz_cost, bz_profit,
                 cast(available_at as timestamp) available_at,
                 revision_no
          from read_parquet(?, union_by_name=true, hive_partitioning=false)
          where cast(available_at as timestamp) < cast(? as date) + interval 1 day
          qualify row_number() over (
            partition by ts_code, report_period, classification, item_name
            order by cast(available_at as timestamp) desc, revision_no desc
          ) = 1
        ), income_visible as (
          select ts_code, cast(report_period as date) report_period,
                 coalesce(revenue, total_revenue) company_revenue,
                 operate_profit company_operating_profit,
                 cast(available_at as timestamp) income_available_at,
                 revision_no
          from read_parquet(?, union_by_name=true, hive_partitioning=false)
          where cast(available_at as timestamp) < cast(? as date) + interval 1 day
          qualify row_number() over (
            partition by ts_code, report_period
            order by cast(available_at as timestamp) desc, revision_no desc
          ) = 1
        )
        select m.*, 'CNY' company_curr_type,
               i.company_revenue, i.company_operating_profit,
               greatest(m.available_at, i.income_available_at) available_at
        from main_visible m
        join income_visible i using (ts_code, report_period)
        order by ts_code, report_period, classification, item_name
    """
    frame = _query_frame(
        sql,
        [
            _fact_paths(root, "main_business"),
            analysis_date,
            _fact_paths(root, "income_statement"),
            analysis_date,
        ],
    )
    frame["report_period"] = pd.to_datetime(frame["report_period"])
    frame["available_at"] = pd.to_datetime(frame["available_at"])
    return frame.drop(columns=["revision_no"], errors="ignore")


def load_financial_history_panel(
    root: Path,
    analysis_date: date,
) -> pd.DataFrame:
    sql = """
        with income as (
          select ts_code, cast(report_period as date) report_period,
                 coalesce(revenue, total_revenue) revenue,
                 operate_profit, n_income_attr_p,
                 sell_exp, admin_exp, fin_exp,
                 assets_impair_loss, non_oper_income,
                 cast(available_at as timestamp) available_at,
                 revision_no
          from read_parquet(?, union_by_name=true, hive_partitioning=false)
          where cast(available_at as timestamp) < cast(? as date) + interval 1 day
          qualify row_number() over (
            partition by ts_code, report_period
            order by cast(available_at as timestamp) desc, revision_no desc
          ) = 1
        ), balance as (
          select ts_code, cast(report_period as date) report_period,
                 total_assets, total_cur_assets, total_cur_liab, total_liab,
                 money_cap, st_borr, non_cur_liab_due_1y,
                 coalesce(accounts_receiv, acc_receivable) accounts_receiv,
                 inventories,
                 cast(available_at as timestamp) available_at,
                 revision_no
          from read_parquet(?, union_by_name=true, hive_partitioning=false)
          where cast(available_at as timestamp) < cast(? as date) + interval 1 day
          qualify row_number() over (
            partition by ts_code, report_period
            order by cast(available_at as timestamp) desc, revision_no desc
          ) = 1
        ), cash as (
          select ts_code, cast(report_period as date) report_period,
                 n_cashflow_act,
                 cast(available_at as timestamp) available_at,
                 revision_no
          from read_parquet(?, union_by_name=true, hive_partitioning=false)
          where cast(available_at as timestamp) < cast(? as date) + interval 1 day
          qualify row_number() over (
            partition by ts_code, report_period
            order by cast(available_at as timestamp) desc, revision_no desc
          ) = 1
        ), indicator as (
          select ts_code, cast(report_period as date) report_period,
                 grossprofit_margin, roe, or_yoy revenue_growth,
                 cast(available_at as timestamp) available_at,
                 revision_no
          from read_parquet(?, union_by_name=true, hive_partitioning=false)
          where cast(available_at as timestamp) < cast(? as date) + interval 1 day
          qualify row_number() over (
            partition by ts_code, report_period
            order by cast(available_at as timestamp) desc, revision_no desc
          ) = 1
        ), combined as (
          select i.ts_code, i.report_period, i.revenue, i.operate_profit,
                 i.n_income_attr_p, c.n_cashflow_act, b.total_assets,
                 f.grossprofit_margin,
                 100 * (coalesce(i.sell_exp, 0) + coalesce(i.admin_exp, 0)
                        + coalesce(i.fin_exp, 0)) / nullif(i.revenue, 0)
                   expense_rate,
                 f.roe, f.revenue_growth,
                 c.n_cashflow_act / nullif(abs(i.n_income_attr_p), 0) cash_quality,
                 b.total_cur_assets, b.total_cur_liab, b.total_liab,
                 b.money_cap, b.st_borr, b.non_cur_liab_due_1y,
                 b.accounts_receiv, b.inventories,
                 i.assets_impair_loss, i.non_oper_income,
                 greatest(i.available_at, b.available_at, c.available_at,
                          f.available_at) available_at
          from income i
          join balance b using (ts_code, report_period)
          join cash c using (ts_code, report_period)
          join indicator f using (ts_code, report_period)
        ), members as (
          select ts_code, industry_code, cast(valid_from as date) valid_from,
                 cast(valid_to as date) valid_to,
                 cast(available_at as timestamp) available_at,
                 revision_no
          from read_parquet(?, union_by_name=true, hive_partitioning=false)
          where industry_system = 'SW2021' and level = 'L1'
            and cast(available_at as timestamp) < cast(? as date) + interval 1 day
        )
        select c.*, m.industry_code
        from combined c
        left join members m
          on m.ts_code = c.ts_code
         and c.report_period >= m.valid_from
         and (m.valid_to is null or c.report_period <= m.valid_to)
         and m.available_at <= c.available_at
        qualify row_number() over (
          partition by c.ts_code, c.report_period
          order by m.valid_from desc nulls last,
                   m.available_at desc nulls last,
                   m.revision_no desc nulls last
        ) = 1
        order by c.ts_code, c.report_period
    """
    frame = _query_frame(
        sql,
        [
            _fact_paths(root, "income_statement"),
            analysis_date,
            _fact_paths(root, "balance_sheet"),
            analysis_date,
            _fact_paths(root, "cash_flow"),
            analysis_date,
            _fact_paths(root, "financial_indicator"),
            analysis_date,
            _fact_paths(root, "industry_member"),
            analysis_date,
        ],
    )
    frame["report_period"] = pd.to_datetime(frame["report_period"])
    frame["available_at"] = pd.to_datetime(frame["available_at"])
    return frame


def load_valuation_history_panel(
    root: Path,
    analysis_date: date,
) -> pd.DataFrame:
    sql = """
        with visible as (
          select cast(trade_date as date) formation_date, ts_code,
                 pe_ttm, pb, ps_ttm, total_mv,
                 cast(available_at as timestamp) available_at,
                 revision_no
          from read_parquet(?, union_by_name=true, hive_partitioning=false)
          where cast(available_at as timestamp) < cast(? as date) + interval 1 day
          qualify row_number() over (
            partition by trade_date, ts_code
            order by cast(available_at as timestamp) desc, revision_no desc
          ) = 1
        ), dated as (
          select *, dense_rank() over (order by formation_date) session_no,
                 max(formation_date) over () latest_date
          from visible
        ), sampled as (
          select * from dated
          where (session_no - 1) % 20 = 0 or formation_date = latest_date
        ), members as (
          select ts_code, industry_code, cast(valid_from as date) valid_from,
                 cast(valid_to as date) valid_to,
                 cast(available_at as timestamp) member_available_at,
                 revision_no member_revision_no
          from read_parquet(?, union_by_name=true, hive_partitioning=false)
          where industry_system = 'SW2021' and level = 'L1'
            and cast(available_at as timestamp) < cast(? as date) + interval 1 day
        )
        select s.formation_date, s.ts_code, s.pe_ttm, s.pb, s.ps_ttm,
               s.total_mv, s.available_at, m.industry_code
        from sampled s
        left join members m
          on m.ts_code = s.ts_code
         and s.formation_date >= m.valid_from
         and (m.valid_to is null or s.formation_date <= m.valid_to)
         and m.member_available_at < s.formation_date + interval 1 day
        qualify row_number() over (
          partition by s.formation_date, s.ts_code
          order by m.valid_from desc nulls last,
                   m.member_available_at desc nulls last,
                   m.member_revision_no desc nulls last
        ) = 1
        order by s.ts_code, s.formation_date
    """
    daily = _query_frame(
        sql,
        [
            _fact_paths(root, "daily_basic"),
            analysis_date,
            _fact_paths(root, "industry_member"),
            analysis_date,
        ],
    )
    daily["formation_date"] = pd.to_datetime(daily["formation_date"])
    daily["available_at"] = pd.to_datetime(daily["available_at"])
    financial = load_financial_history_panel(root, analysis_date)
    financial = financial.loc[
        :,
        [
            "ts_code",
            "available_at",
            "n_income_attr_p",
            "roe",
            "revenue_growth",
            "cash_quality",
        ],
    ].rename(columns={"available_at": "financial_available_at"})

    merged: list[pd.DataFrame] = []
    for ts_code, daily_group in daily.groupby("ts_code", sort=True):
        finance_group = financial.loc[financial["ts_code"] == ts_code].sort_values(
            "financial_available_at", kind="mergesort"
        )
        left = daily_group.sort_values("formation_date", kind="mergesort")
        if finance_group.empty:
            left = left.assign(
                financial_available_at=pd.NaT,
                n_income_attr_p=np.nan,
                roe=np.nan,
                revenue_growth=np.nan,
                cash_quality=np.nan,
            )
        else:
            left = pd.merge_asof(
                left,
                finance_group.drop(columns="ts_code"),
                left_on="formation_date",
                right_on="financial_available_at",
                direction="backward",
                allow_exact_matches=True,
            )
        merged.append(left)
    if not merged:
        return daily.assign(
            financial_available_at=pd.NaT,
            n_income_attr_p=np.nan,
            roe=np.nan,
            revenue_growth=np.nan,
            cash_quality=np.nan,
        )
    return pd.concat(merged, ignore_index=True).sort_values(
        ["formation_date", "ts_code"], kind="mergesort"
    ).reset_index(drop=True)


def _stable_number(value: float | int) -> float | int | str:
    if isinstance(value, (float, np.floating)):
        if not math.isfinite(float(value)):
            return "not_available"
        return round(float(value), 12)
    return int(value)


def _direction(value: float) -> str:
    if not math.isfinite(value):
        return "not_available"
    if value > 0:
        return "positive"
    if value < 0:
        return "negative"
    return "flat"


def _split_metric(
    frame: pd.DataFrame,
    date_column: str,
    metric,
) -> tuple[float, float, float]:
    usable = frame.dropna(subset=[date_column]).copy()
    if usable.empty:
        return (math.nan, math.nan, math.nan)
    midpoint = usable[date_column].sort_values().iloc[len(usable) // 2]

    def evaluate(part: pd.DataFrame) -> float:
        if part.empty:
            return math.nan
        value = metric(part)
        return math.nan if pd.isna(value) else float(value)

    return (
        evaluate(usable),
        evaluate(usable.loc[usable[date_column] <= midpoint]),
        evaluate(usable.loc[usable[date_column] > midpoint]),
    )


def validate_targeted_gap_claims(
    warehouse_root: Path,
    *,
    analysis_date: date = date(2026, 7, 14),
) -> tuple[TargetedGapEvidence, ...]:
    root = Path(warehouse_root)
    business = business_segment_materiality_observations(
        load_business_segment_panel(root, analysis_date)
    )
    financial = load_financial_history_panel(root, analysis_date)
    earnings = earnings_growth_persistence_observations(financial)
    valuation = relative_valuation_context_observations(
        load_valuation_history_panel(root, analysis_date)
    )
    turnaround = turnaround_financial_consistency_observations(financial)

    business_usable = business.loc[business["ratio_status"] == "comparable"]
    business_counts = _split_metric(
        business,
        "report_period",
        lambda part: float(part["ratio_status"].eq("comparable").mean()),
    )

    earnings_usable = earnings.dropna(
        subset=["net_income_change_scaled", "next_year_net_income_change_scaled"]
    )
    earnings_corr = _split_metric(
        earnings_usable,
        "report_period",
        lambda part: part["net_income_change_scaled"].corr(
            part["next_year_net_income_change_scaled"]
        ),
    )

    valuation_counts = _split_metric(
        valuation,
        "formation_date",
        lambda part: float(part["peer_pe_percentile"].notna().mean()),
    )

    turnaround_usable = turnaround.loc[
        turnaround["operating_result_change"].gt(0)
        & turnaround["contradiction_count"].notna()
    ]
    turnaround_counts = _split_metric(
        turnaround_usable,
        "report_period",
        lambda part: float(part["contradiction_count"].gt(0).mean()),
    )

    return (
        TargetedGapEvidence(
            knowledge_id="src_cn_business_segment_materiality",
            data_usable=not business_usable.empty,
            overall_direction=_direction(business_counts[0]),
            earlier_direction=_direction(business_counts[1]),
            later_direction=_direction(business_counts[2]),
            counter_evidence=(
                "分类口径可能重叠，且币种、缺失利润或公司总额分母会阻止占比计算。"
            ),
            observations={
                "rows": len(business),
                "comparable_rows": len(business_usable),
                "comparable_share": _stable_number(business_counts[0]),
            },
        ),
        TargetedGapEvidence(
            knowledge_id="src_cn_earnings_growth_persistence",
            data_usable=not earnings_usable.empty,
            overall_direction=_direction(earnings_corr[0]),
            earlier_direction=_direction(earnings_corr[1]),
            later_direction=_direction(earnings_corr[2]),
            counter_evidence=(
                "单期方向可能被下一报告期反转，行业共同变化和现金背离必须分开保留。"
            ),
            observations={
                "rows": len(earnings),
                "comparable_rows": len(earnings_usable),
                "overall_persistence_correlation": _stable_number(earnings_corr[0]),
            },
        ),
        TargetedGapEvidence(
            knowledge_id="src_cn_relative_valuation_context",
            data_usable=bool(valuation["peer_pe_percentile"].notna().any()),
            overall_direction=_direction(valuation_counts[0]),
            earlier_direction=_direction(valuation_counts[1]),
            later_direction=_direction(valuation_counts[2]),
            counter_evidence=(
                "亏损、负值、可比组过窄和微盘污染会使估值位置失去解释力。"
            ),
            observations={
                "rows": len(valuation),
                "peer_pe_comparable_rows": int(
                    valuation["peer_pe_percentile"].notna().sum()
                ),
                "peer_pe_comparable_share": _stable_number(valuation_counts[0]),
            },
        ),
        TargetedGapEvidence(
            knowledge_id="src_cn_turnaround_financial_consistency",
            data_usable=not turnaround_usable.empty,
            overall_direction=_direction(turnaround_counts[0]),
            earlier_direction=_direction(turnaround_counts[1]),
            later_direction=_direction(turnaround_counts[2]),
            counter_evidence=(
                "利润改善可同时伴随现金、流动性、短债或营运资产压力恶化。"
            ),
            observations={
                "rows": len(turnaround),
                "operating_improvement_rows": len(turnaround_usable),
                "improvement_with_contradiction_share": _stable_number(
                    turnaround_counts[0]
                ),
            },
        ),
    )


__all__ = [
    "TARGETED_GAP_CLAIMS",
    "TARGETED_SOURCE_REFS",
    "TargetedGapClaim",
    "TargetedGapEvidence",
    "business_segment_materiality_observations",
    "earnings_growth_persistence_observations",
    "load_business_segment_panel",
    "load_financial_history_panel",
    "load_valuation_history_panel",
    "relative_valuation_context_observations",
    "turnaround_financial_consistency_observations",
    "validate_targeted_gap_claims",
]
