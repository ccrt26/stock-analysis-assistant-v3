"""Thin trial adapter around the existing selection outcome calculations."""
from __future__ import annotations

from collections import Counter
from pathlib import Path

from tools import export_skill_optimization_dataset as original

HORIZONS = (5, 10, 20)


def _horizon(rows: list[dict], number: int) -> dict:
    by_n = {int(r['trading_day_number']): r for r in rows}
    entry = by_n.get(1) or {}
    end = by_n.get(number) or {}
    result = {f'd{number}_status': 'not_mature', f'd{number}_endpoint_return': None,
              f'd{number}_relative_market_return': None,
              f'd{number}_path_complete': False, f'd{number}_hit_20pct_close': None,
              f'd{number}_mae': None, f'd{number}_max_close_drawdown': None}
    if not rows or max(by_n, default=0) < number:
        return result
    if entry.get('data_status') != 'available' or not entry.get('entry_open_adjusted'):
        result[f'd{number}_status'] = 'no_reliable_entry'
        return result
    if end.get('data_status') != 'available' or end.get('close_return_since_entry') is None:
        result[f'd{number}_status'] = 'missing_endpoint'
    else:
        result[f'd{number}_status'] = 'endpoint_available'
        result[f'd{number}_endpoint_return'] = end['close_return_since_entry']
        result[f'd{number}_relative_market_return'] = end.get('relative_market_return')
    path = [by_n.get(i) for i in range(1, number+1)]
    close_complete = all(r and r.get('data_status') == 'available' and
                         r.get('close_return_since_entry') is not None for r in path)
    result[f'd{number}_path_complete'] = close_complete
    known = [r['close_return_since_entry'] for r in path if r and r.get('close_return_since_entry') is not None]
    if any(value >= original.CLOSE_HIT_20PCT_THRESHOLD for value in known):
        result[f'd{number}_hit_20pct_close'] = True
    elif close_complete:
        result[f'd{number}_hit_20pct_close'] = False
    if close_complete:
        closes = [1 + r['close_return_since_entry'] for r in path]
        peak = closes[0]
        drawdown = 0.0
        for close in closes:
            peak = max(peak, close)
            drawdown = min(drawdown, close / peak - 1)
        result[f'd{number}_max_close_drawdown'] = drawdown
    if all(r and r.get('data_status') == 'available' and r.get('low_return_since_entry') is not None for r in path):
        result[f'd{number}_mae'] = min(r['low_return_since_entry'] for r in path)
    return result


def calculate(warehouse_root: Path, selections: list[dict], through: str) -> tuple[list[dict], dict]:
    """Keep each recommendation, including repeated stocks, as its own event."""
    if not selections:
        return [], {'planned_selections': 0}
    first = min(x['action_date'] for x in selections)
    dates = original.load_trading_dates(warehouse_root, first, through)
    benchmark = original.load_benchmark_daily(warehouse_root, dates)
    subjects = []
    for selection in selections:
        subjects.append({'event_key': f"trial:{selection['run_id']}:{selection['ts_code']}",
                         'formation_date': selection['formation_date'],
                         'action_date': selection['action_date'], 'selection_as_of': selection['as_of'],
                         'ts_code': selection['ts_code'], 'name': selection.get('name') or selection['ts_code']})
    daily = original.build_daily_price_volume_records(warehouse_root, subjects, through, dates, benchmark)
    original.enrich_selections_with_outcomes(subjects, daily, through, dates)
    by_key: dict[str, list[dict]] = {}
    for row in daily:
        by_key.setdefault(row['event_key'], []).append(row)
    out = []
    for item, subject in zip(selections, subjects, strict=True):
        rows = sorted(by_key.get(subject['event_key'], []), key=lambda r: int(r['trading_day_number']))
        result = dict(method_id=item['method_id'], run_id=item['run_id'], mode=item.get('mode', 'prospective'), formation_date=item['formation_date'],
                      action_date=item['action_date'], as_of=item['as_of'], ts_code=item['ts_code'],
                      name=item.get('name') or item['ts_code'], rank=item.get('rank'),
                      role=item.get('role','selected'), candidate_reason=item.get('candidate_reason'),
                      participation_condition=item.get('participation_condition'),
                      condition_event='unverified_without_intraday_order_or_trade',
                      price_path_is_trade=False, through=through,
                      fixed_d20_status=subject.get('fixed_d20_status'),
                      fixed_d20_hit_20pct_close=subject.get('fixed_d20_hit_20pct_close'),
                      fixed_d20_terminal_return=subject.get('fixed_d20_terminal_return'),
                      fixed_d20_market_return=subject.get('fixed_d20_market_return'),
                      fixed_d20_missing_dates=subject.get('fixed_d20_missing_dates'),
                      fixed_d20_mae=subject.get('fixed_d20_mae'),
                      fixed_d20_max_close_drawdown=subject.get('fixed_d20_max_close_drawdown'))
        for number in HORIZONS:
            result.update(_horizon(rows, number))
        out.append(result)
    return out, {'planned_selections': len(selections), 'trading_days': len(dates),
                 'benchmark_days': len(benchmark),
                 'fixed_d20_status_counts': dict(Counter(x['fixed_d20_status'] for x in out))}


def auxiliary_views(rows: list[dict], trading_dates: list[str]) -> tuple[list[dict], list[dict]]:
    """Descriptive repeated-stock views; neither creates independent samples."""
    first, nonoverlap = [], []
    seen: set[tuple[str, str]] = set()
    last_end: dict[tuple[str, str], str] = {}
    for row in sorted(rows, key=lambda r: (r['action_date'], r['method_id'], r['ts_code'])):
        key = (row['method_id'], row['ts_code'])
        if key not in seen:
            first.append(row)
            seen.add(key)
        if row['action_date'] > last_end.get(key, ''):
            nonoverlap.append(row)
            future = [day for day in trading_dates if day >= row['action_date']]
            last_end[key] = future[19] if len(future) >= 20 else '9999-12-31'
    return first, nonoverlap


def summarize(rows: list[dict], day_states: list[dict] | None = None) -> dict:
    """Program counts and medians, explicitly scoped to prospective trial days."""
    from statistics import median
    day_states = [d for d in (day_states or []) if d.get('mode') == 'prospective']
    normalized = []
    for day in day_states:
        status = day.get('status') if isinstance(day.get('status'), dict) else {m:day.get(m,'not_run') for m in ('M0','M1')}
        qualification = day.get('qualification') or {}
        normalized.append({'action_date':day.get('action_date'), 'status':status, 'qualification':qualification})
    eligible = {(d['action_date'],m) for d in normalized for m in ('M0','M1')
                if d['qualification'].get(m) is True and d['status'].get(m) in {'complete','complete_zero'}}
    forward = [r for r in rows if r.get('mode') == 'prospective' and
               (r.get('action_date'),r.get('method_id')) in eligible]
    for row in rows:
        key = (row['action_date'], row['ts_code'])
        peer = next((x for x in rows if x is not row and
                     (x['action_date'], x['ts_code']) == key and x['method_id'] != row['method_id']), None)
        if peer:
            for n in HORIZONS:
                field = f'd{n}_endpoint_return'
                if row.get(field) is not None and peer.get(field) is not None and abs(float(row[field])-float(peer[field])) > 1e-12:
                    raise ValueError(f'same stock/action has different reference return: {key}/{field}')
    result = {'planned_days': len(normalized),
              'paired_days': sum(all((d['action_date'],m) in eligible for m in ('M0','M1')) for d in normalized),
              'methods': {}}
    for method in ('M0','M1'):
        records = [r for r in forward if r['method_id']==method]
        states = [d['status'].get(method,'not_run') for d in normalized]
        method_summary = {'completed_days': sum((d['action_date'],method) in eligible for d in normalized),
                          'failed_days': sum(x != 'not_run' and (d['action_date'],method) not in eligible
                                             for d,x in zip(normalized,states,strict=True)),
                          'not_run_days': states.count('not_run'),
                          'zero_selection_days': sum(x == 'complete_zero' and (d['action_date'],method) in eligible
                                                     for d,x in zip(normalized,states,strict=True)),
                          'recommendation_events': len(records),
                          'distinct_stocks': len({r['ts_code'] for r in records}),
                          'repeat_events': len(records)-len({r['ts_code'] for r in records}),
                          'horizons': {}}
        for n in HORIZONS:
            available = [r for r in records if r.get(f'd{n}_endpoint_return') is not None]
            complete = [r for r in available if r.get(f'd{n}_path_complete') is True]
            relative = [r for r in available if r.get(f'd{n}_relative_market_return') is not None]
            hits = [r for r in complete if r.get(f'd{n}_hit_20pct_close') is not None]
            maes = [r[f'd{n}_mae'] for r in complete if r.get(f'd{n}_mae') is not None]
            drawdowns = [r[f'd{n}_max_close_drawdown'] for r in complete if r.get(f'd{n}_max_close_drawdown') is not None]
            method_summary['horizons'][f'd{n}'] = {
                'endpoint_denominator': len(available),
                'path_complete_denominator': len(complete),
                'median_endpoint_return': median(float(r[f'd{n}_endpoint_return']) for r in available) if available else None,
                'relative_market_denominator': len(relative),
                'median_relative_market_return': median(float(r[f'd{n}_relative_market_return']) for r in relative) if relative else None,
                'close_20pct_evaluable_denominator': len(hits),
                'close_20pct_hits': sum(r[f'd{n}_hit_20pct_close'] is True for r in hits),
                'median_mae': median(maes) if maes else None,
                'median_max_close_drawdown': median(drawdowns) if drawdowns else None,
            }
        result['methods'][method] = method_summary
    return result
