"""Read-only, point-in-time facts for a small proposed recommendation list.

Selection remains with the research skills. Existing universe-wide observations
are read before cropping; no ranks or industry denominators are recomputed here.
"""
from __future__ import annotations

import argparse
import json
import re
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from stock_analyzer.storage.research_query import ResearchQuery
from stock_analyzer.storage.research_parquet import sha256_file
from stock_analyzer.storage.research_schema import connect_research_warehouse
from stock_analyzer.storage.research_warehouse import ResearchWarehouse

DEFINITIONS = {
    "dates": "所有日期统一为YYYY-MM-DD。窗口列出收益归属交易日；首日收益以之前交易日收盘为基准。",
    "units": "行情价格元，amount成交额元（已经转换，不能再乘1000）；return/ratio/breadth为小数，乘100才是百分比。财务金额、市值total_mv/circ_mv均为元；pe/pe_ttm/pb/ps_ttm为倍数，turnover_rate为百分数；财务同比和利润率原列为百分数。",
    "price_basis": "日线为原始OHLC，仅说明各日价格/高低位置；跨日收益用既有复权派生，不从原始价格另算替代。",
    "amount_ratio_last_20d": "形成日当日成交额/含形成日的近20个交易日平均成交额；1.26表示当日高于20日均额约26%，不是最近20日相对此前20日增长26%。",
    "volume_amplification_days_5d": "最近5个交易日中，当日成交额大于其此前20个交易日平均成交额的天数；虽然字段名有volume，实际比较的是成交额，不是成交股数。",
    "upper_shadow_frequency_5d": "近5日上影长度(high-max(open,close))占当日振幅(high-low)至少25%的交易日比例；0.6表示5天中3天有较明显上影，不是有任何上影的天数比例。",
    "price_location_60d": "当前复权收盘价在含当日的近60个收盘价最大值与最小值间的位置：(close-min)/(max-min)；不是盘中高低点区间，不等于估值或未来上涨空间。",
    "atr_ratio_20d": "近20日真实波幅均值/当前复权收盘价；真实波幅取当日高低差、最高价与前收差绝对值、最低价与前收差绝对值的最大值。表示历史波动尺度，不是未来涨幅。",
    "target_atr_distance_20pct": "0.20/atr_ratio_20d，即20%观察目标约相当于多少个历史平均真实波幅；不是所需天数、上涨概率或承诺。",
    "top3_positive_contribution_1d": "当日行业收益为正的成员中，前三个最大正收益之和/全部正收益之和；单日集中度，不是5日贡献，也不是行业总收益中前三名的占比。",
    "fade_frequency_5d": "近5日(high>open且(close-low)/(high-low)<0.5)的比例；不是盘中从最高价下跌的频率，也不代表没有冲高回落。",
    "largest_positive_day_contribution_5d": "最大正收益日涨幅/5日正收益之和，不是累计复利涨幅的占比。",
    "return_ex_largest_positive_day_5d": "5日中去掉最大正收益日，其余收益复利；最大日并列时取靠后的一天。",
    "return_after_largest_positive_day_5d": "只取最大正收益日之后的收益复利；可能与去掉最大日完全同一窗口，不能重复算独立证据。",
    "industry": "名称、SW2021分类层级、有效成员总数、观察数及各期限覆盖随同行事实提供；所有行业统计来自原全市场历史成员计算，范围可能含不在本轮可选范围的市场成员；不能把另一次筛选得到的人数与此处广度拼接。",
    "absence": "缺资料/读取失败/不可回放与真实没有记录不同；空的事实集合不能推出公司未披露。AI原判断不是已核实事实。",
    "c_inf_fr_operate_a": "同一report_period经营活动现金流入小计，单位元；正的流入小计不代表经营现金净流入。",
    "st_cash_out_act": "同一report_period经营活动现金流出小计，单位元；与流入小计配对核对，不把它当净额。",
    "n_cashflow_act": "同一report_period经营活动产生的现金流量净额，单位元，保留正负符号；它不同于流入或流出小计。",
}


def date_text(value) -> str | None:
    if pd.isna(value):
        return None
    text = str(value).strip()
    if re.fullmatch(r'\d{8}(?:\.0)?', text):
        return datetime.strptime(text[:8], '%Y%m%d').date().isoformat()
    return date.fromisoformat(text[:10]).isoformat()


def records(frame: pd.DataFrame, fields: list[str] | None = None) -> list[dict]:
    if fields is not None:
        frame = frame[[f for f in fields if f in frame.columns]]
    frame = frame.copy()
    for col in frame.columns:
        if col.endswith('date') or col in {'report_period', 'valid_from', 'valid_to'}:
            frame[col] = frame[col].map(date_text)
        elif col in {'available_at', 'announcement_time'}:
            frame[col] = frame[col].map(lambda x: pd.to_datetime(x, utc=True).tz_convert('Asia/Shanghai').isoformat() if pd.notna(x) else None)
    return json.loads(frame.to_json(orient='records', date_format='iso', force_ascii=False))


def selected_result(trace: dict) -> dict:
    from stock_analyzer.ops.forward_selection import DailyResearchTraceV4, _confirmed_active_research_result
    return _confirmed_active_research_result(DailyResearchTraceV4.model_validate(trace))


def window_dates(sessions: list[str], price: dict) -> dict:
    out = {f'{n}d': {'first_return_session': sessions[-n] if len(sessions) >= n else None,
                         'last_return_session': sessions[-1] if sessions else None,
                         'base_close_date': sessions[-n-1] if len(sessions) > n else None,
                         'session_count': min(n, len(sessions))} for n in (1, 3, 5, 20, 60)}
    offset = price.get('sessions_since_largest_positive_day_5d')
    if offset is not None and len(sessions) >= 5:
        offset = int(offset)
        if 0 <= offset < 5:
            day = sessions[-1-offset]
            out['largest_positive_day_5d'] = day
            out['ex_largest_positive_day_5d'] = [d for d in sessions[-5:] if d != day]
            out['after_largest_positive_day_5d'] = [d for d in sessions[-5:] if d > day]
    return out


def derived_at(warehouse: ResearchWarehouse, feature: str, formation: str, cutoff: datetime) -> pd.DataFrame:
    with connect_research_warehouse(warehouse.duckdb_path, read_only=True) as connection:
        rows = connection.execute(
            'select relative_path,input_manifest_json,file_sha256 from research_derived_partitions '
            'where feature_set=? and analysis_date=? order by committed_at desc',
            [feature, formation]).fetchall()
    for path, manifest, digest in rows:
        fact = json.loads(manifest).get('fact_snapshot', {})
        stamp = fact.get('as_of')
        if stamp and datetime.fromisoformat(stamp) == cutoff:
            source = warehouse.root / path
            if sha256_file(source) != digest:
                raise ValueError(f'{feature}原派生文件与既有元数据不一致')
            return pd.read_parquet(source)
    raise ValueError(f'{feature}没有与本轮截止一致的原全市场派生结果')


FINANCIAL_DATASETS = ("income_statement", "balance_sheet", "cash_flow", "financial_indicator")
FACT_CATEGORIES = {
    "financial": set(FINANCIAL_DATASETS),
    "company": {"company_profile", "main_business", "announcement"},
    "price": {"equity_daily", "daily_basic"},
    "industry": {"industry_member"},
}


def build_context(root: Path, trace: dict, *, extra_codes: list[str] = (), cited_text: str = "",
                  periods: list[str] = ()) -> dict:
    result = selected_result(trace)
    comparisons = cited_text + ' ' + ' '.join(s.get('nearest_comparison', '') for s in result['selected_stocks'])
    candidates = result.get('nearest_nonselections', []) + trace.get('candidate_ledger', [])
    neighbors = [c['ts_code'] for c in candidates if c['ts_code'] in comparisons or
                 (c.get('name') and c['name'] in comparisons)]
    codes = list(dict.fromkeys([s['ts_code'] for s in result['selected_stocks']] + neighbors + list(extra_codes)))
    return _context(root, trace, result, codes, cited_text=cited_text, periods=periods)


def candidate_context(root: Path, codes: list[str], *, formation_date: str, as_of: str,
                      categories=("financial", "company", "price", "industry"), periods=(),
                      sector_dates=()) -> dict:
    """On-demand facts before any selection judgment or draft exists."""
    unknown = set(categories) - set(FACT_CATEGORIES)
    if unknown or not codes:
        raise ValueError(f'需要候选代码及有效类别；未知类别：{sorted(unknown)}')
    request = {'formation_date': formation_date, 'as_of': as_of,
               'market_search_context': {}, 'candidate_ledger': [], 'decision_trace': []}
    return _context(root, request, {'selected_stocks': []}, list(dict.fromkeys(codes)),
                    categories=categories, periods=periods, sector_dates=sector_dates)


def breadth_evidence(rows: list[dict], windows: dict) -> list[dict]:
    result = []
    for row in rows:
        for horizon in (1, 3, 5, 20):
            ratio = row.get(f'breadth_{horizon}d')
            denominator = row.get(f'horizon_observed_member_count_{horizon}d')
            count = None
            if ratio is not None and denominator:
                product = ratio * denominator
                if abs(product - round(product)) < 1e-6:
                    count = round(product)
            result.append({**{k: row.get(k) for k in ('group_code','group_name','group_type','level','member_count')},
                'window': f'{horizon}d', 'dates': windows.get(f'{horizon}d'),
                'positive_count': count, 'valid_denominator': denominator, 'ratio': ratio,
                'count_source': '原 breadth × 同期限 horizon_observed_member_count；不重算成员范围'})
    return result


def _context(root: Path, trace: dict, result: dict, codes: list[str], *,
             categories=("financial", "company", "price", "industry"), cited_text="", periods=(), sector_dates=()) -> dict:
    formation = date.fromisoformat(trace['formation_date']).isoformat()
    action = date.fromisoformat(trace['action_date']).isoformat() if trace.get('action_date') else None
    cutoff = datetime.fromisoformat(trace['as_of'])
    if cutoff.tzinfo is None:
        raise ValueError('as_of必须有时区')
    if date.fromisoformat(formation) > cutoff.astimezone(ZoneInfo("Asia/Shanghai")).date():
        raise ValueError('形成日不能晚于截止')
    stocks = result['selected_stocks']
    wanted = set().union(*(FACT_CATEGORIES[c] for c in categories))
    # Only the caller's cited years/periods extend the bounded current comparison set.
    cited_years = set(re.findall(r'(?<!\d)(20\d{2})(?!\d)', cited_text))
    gaps: list[dict] = []
    output = {'identity': {'formation_date': formation, 'action_date': action, 'as_of': trace['as_of']},
              'definitions': DEFINITIONS, 'proposed_judgment': {'market': trace['market_search_context'],
              'result': result, 'candidates': [c for c in trace['candidate_ledger'] if c['ts_code'] in codes]},
              'facts': {}, 'gaps': gaps}
    decision_ids = {d for c in trace['candidate_ledger'] if c['ts_code'] in codes
                    for d in c['research_thesis']['decision_ids']}
    output['proposed_judgment']['decisions'] = [d for d in trace['decision_trace']
                                               if d.get('decision_id') in decision_ids]
    if not codes:
        return output
    warehouse = ResearchWarehouse(root / 'local_warehouse', read_only=True)
    query = ResearchQuery(warehouse)

    def read(dataset: str, *, partitions=None, financial=False) -> pd.DataFrame:
        if dataset != 'trade_calendar' and dataset not in wanted:
            return pd.DataFrame()
        try:
            frame = (query.comparable_financials_as_of(dataset, cutoff) if financial else
                     query.dataset_partitions_as_of(dataset, partitions, cutoff) if partitions is not None else
                     query.dataset_as_of(dataset, cutoff))
            if frame.empty:
                gaps.append({'source': dataset, 'status': 'no_available_rows', 'meaning': '原截止可取得的本地行为空，不代表公司无事实'})
            return frame
        except (ValueError, OSError, RuntimeError) as exc:
            gaps.append({'source': dataset, 'status': 'query_failed', 'detail': str(exc)})
            return pd.DataFrame()

    sessions = []
    if set(categories) & {'price', 'industry'}:
        calendar = read('trade_calendar', partitions=[str(y) for y in range(int(formation[:4])-1, int(formation[:4])+1)])
        if calendar.empty:
            raise ValueError('缺少可回放交易日历，不能推测比较窗口')
        dates = pd.to_datetime(calendar['cal_date']).dt.strftime('%Y-%m-%d')
        sessions = sorted(set(dates[(calendar['is_open'].astype(str).isin(['1','True','1.0'])) & (dates <= formation)]))[-61:]
        if not sessions or sessions[-1] != formation:
            raise ValueError('形成日不在可用交易日历')
    frames = {'equity_daily': read('equity_daily', partitions=sessions),
              'industry_member': read('industry_member'), 'company_profile': read('company_profile'),
              'daily_basic': read('daily_basic', partitions=[formation])}
    for dataset in FINANCIAL_DATASETS:
        frames[dataset] = read(dataset, financial=True)
    frames['main_business'] = read('main_business')
    frames['announcement'] = read('announcement')
    derived = {}
    for feature in ('market_context', 'sector_hotspot', 'price_analysis_context'):
        if not set(categories) & {'price', 'industry'}:
            derived[feature] = pd.DataFrame()
            continue
        try:
            derived[feature] = derived_at(warehouse, feature, formation, cutoff)
        except (ValueError, OSError, RuntimeError) as exc:
            gaps.append({'source': feature, 'status': 'unavailable_at_cutoff', 'detail': str(exc)})
            derived[feature] = pd.DataFrame()
    output['market_facts'] = records(derived['market_context'])
    metadata = ['available_at', 'source_name', 'source_endpoint', 'quality_status']
    fields = {
        'equity_daily': ['trade_date','open','high','low','close','pre_close','vol','amount'],
        'daily_basic': ['trade_date','close','pe','pe_ttm','pb','ps_ttm','total_mv','circ_mv','turnover_rate','turnover_rate_f'],
        'industry_member': ['industry_system','level','industry_code','industry_name','valid_from','valid_to'],
        'company_profile': ['com_name','main_business','business_scope','valid_from','profile_snapshot_date'],
        'income_statement': ['report_period','ann_date','f_ann_date','report_type','comparable_selection_rule','total_revenue','revenue','n_income_attr_p'],
        'balance_sheet': ['report_period','ann_date','f_ann_date','comparable_selection_rule','total_assets','total_liab','total_hldr_eqy_exc_min_int','money_cap'],
        'cash_flow': ['report_period','ann_date','f_ann_date','comparable_selection_rule','c_inf_fr_operate_a','st_cash_out_act','n_cashflow_act'],
        'financial_indicator': ['report_period','ann_date','netprofit_yoy','dt_netprofit_yoy','ocf_yoy','grossprofit_margin'],
        'main_business': ['report_period','classification','item_name','bz_item','bz_sales','bz_profit','curr_type','availability_limitation'],
        'announcement': ['announcement_time','title','url','announcement_title','announcement_url'],
    }
    for code in codes:
        fact = {'financial_availability': {}}
        for dataset, frame in frames.items():
            if dataset not in wanted:
                continue
            part = frame[frame['ts_code'] == code].copy() if 'ts_code' in frame else pd.DataFrame()
            if dataset == 'industry_member' and not part.empty:
                start = pd.to_datetime(part['valid_from'], errors='coerce').dt.strftime('%Y-%m-%d')
                end = pd.to_datetime(part['valid_to'], errors='coerce').dt.strftime('%Y-%m-%d')
                part = part[(start <= formation) & (end.isna() | (end >= formation))]
            if dataset in FINANCIAL_DATASETS:
                all_periods = sorted(set(part['report_period'].map(date_text))) if 'report_period' in part else []
                failed = any(g.get('source') == dataset and g.get('status') == 'query_failed' for g in gaps)
                fact['financial_availability'][dataset] = {
                    'status': 'query_failed' if failed else 'available' if all_periods else 'coverage_insufficient',
                    'available_periods': all_periods, 'latest_period': all_periods[-1] if all_periods else None,
                    'meaning': '本地原截止可得期间，不代表公司全部公开披露期间'}
            if 'report_period' in part:
                normalized = part['report_period'].map(date_text)
                available = sorted(set(normalized))
                retained = set(available[-1 if dataset == 'main_business' else -5:])
                retained.update(p for p in available if p in periods or p[:4] in cited_years)
                part = part.assign(report_period=normalized)[normalized.isin(retained)].sort_values('report_period')
            if dataset == 'equity_daily' and not part.empty:
                part = part.sort_values('trade_date')
            if dataset == 'announcement' and not part.empty:
                ordered = part.sort_values('available_at')
                title_column = next((k for k in ('title','announcement_title') if k in ordered), None)
                if title_column:
                    # A burst of issuance notices must not hide the latest report
                    # titles; metadata can establish disclosure, not its economics.
                    reports = ordered[ordered[title_column].fillna('').str.contains(
                        '半年度报告|年度报告|季度报告|业绩预告|业绩快报', regex=True)].tail(8)
                    part = pd.concat([reports, ordered.tail(20)]).drop_duplicates().sort_values('available_at')
                else:
                    part = ordered.tail(20)
            fact[dataset] = records(part, fields[dataset] + metadata)
            if part.empty:
                failed = any(g.get('source') == dataset and g.get('status') == 'query_failed' for g in gaps)
                gaps.append({'source': dataset, 'ts_code': code, 'status': 'query_failed' if failed else 'coverage_insufficient', 'meaning': '本地原截止资料缺项，不推断未披露'})
        prices = derived['price_analysis_context']
        fact['price_observations'] = records(prices[prices['ts_code'] == code]) if 'ts_code' in prices else []
        price = next(iter(fact['price_observations']), {})
        fact['comparison_windows'] = window_dates(sessions, price)
        groups = {r['industry_code'] for r in fact.get('industry_member', []) if r.get('level') == 'L2'}
        if price.get('primary_industry_code'):
            groups.add(price['primary_industry_code'])
        sectors = derived['sector_hotspot']
        cited = json.dumps({
            'candidate': [c for c in trace['candidate_ledger'] if c['ts_code'] == code],
            'result': [c for c in stocks if c['ts_code'] == code],
            'decisions': [d for d in trace['decision_trace'] if d.get('ts_code') == code],
        }, ensure_ascii=False) + cited_text
        if 'group_name' in sectors and 'group_code' in sectors:
            groups.update(row['group_code'] for row in sectors.to_dict('records')
                          if row['group_code'] in cited or (row.get('group_type') == 'industry' and row.get('level') in {'L2','L3'} and isinstance(row['group_name'],str) and len(row['group_name']) >= 2 and row['group_name'] in cited))
        fact['industry_observations'] = records(sectors[sectors['group_code'].isin(groups)]) if 'group_code' in sectors else []
        fact['industry_breadth'] = breadth_evidence(fact['industry_observations'], fact['comparison_windows'])
        if sector_dates:
            fact['industry_series'] = []
            for day in sorted(set(sector_dates)):
                # Each original daily snapshot retains its own cutoff; never use a later snapshot.
                day_cutoff = datetime.fromisoformat(day + 'T18:30:00+08:00')
                if day > formation or day_cutoff > cutoff:
                    raise ValueError('行业序列不能越过本轮截止')
                try:
                    prior = derived_at(warehouse, 'sector_hotspot', day, day_cutoff)
                    observed = records(prior[prior['group_code'].isin(groups)]) if 'group_code' in prior else []
                    prior_windows = window_dates([d for d in sessions if d <= day], {})
                    fact['industry_series'].append({'analysis_date': day, 'as_of': day_cutoff.isoformat(),
                        'observations': observed, 'breadth': breadth_evidence(observed, prior_windows)})
                except (ValueError, OSError, RuntimeError) as exc:
                    gaps.append({'source':'sector_hotspot', 'analysis_date':day, 'status':'unavailable_at_cutoff', 'detail':str(exc)})
        output['facts'][code] = fact
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--trace', type=Path)
    parser.add_argument('--code', action='append', default=[])
    parser.add_argument('--formation-date')
    parser.add_argument('--as-of')
    parser.add_argument('--category', choices=FACT_CATEGORIES, action='append')
    parser.add_argument('--period', action='append', default=[])
    parser.add_argument('--sector-date', action='append', default=[])
    parser.add_argument('--root', type=Path, help='只读事实源项目')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--compare-code', action='append', default=[])
    args = parser.parse_args()
    root = args.root or Path(__file__).resolve().parents[3]
    if args.trace:
        data = build_context(root, json.loads(args.trace.read_text()), extra_codes=args.compare_code, periods=args.period)
    else:
        if not args.formation_date or not args.as_of:
            parser.error('候选验证需要 --code / --formation-date / --as-of')
        data = candidate_context(root, args.code, formation_date=args.formation_date, as_of=args.as_of,
            categories=args.category or tuple(FACT_CATEGORIES), periods=args.period, sector_dates=args.sector_date)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n')
    print(f'context={args.output}; gaps={len(data["gaps"])}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
