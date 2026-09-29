#!/usr/bin/env python3
"""Format existing guarded outcome outputs into delivery tables; never
calculates returns or selects stocks. Paths come from --config/--output-dir."""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from stock_analyzer.ops.selection_parallel import _check_run_contract, _json, _qualification


def read_csv_rows(path: Path) -> list[dict]:
    with path.open(encoding='utf-8-sig', newline='') as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = list(dict.fromkeys(key for row in rows for key in row)) or ['no_rows']
    with path.open('w', encoding='utf-8-sig', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def format_tables(config_path: Path, outcomes_dir: Path, output_dir: Path,
                  *, condition_evaluation: Path | None = None) -> dict:
    cfg = _json(config_path)
    root = config_path.parent
    for case in cfg['replay_cases']:
        day = root / 'smoke' / case['replay_id']
        _check_run_contract(_json(day / 'run.json'), cfg)
        if not all(_qualification(day, m)['qualified'] for m in case['method_order']):
            raise ValueError('ten qualified decisions required before formatting result tables')
    allout = read_csv_rows(outcomes_dir / 'outcomes.csv')
    candidates = read_csv_rows(outcomes_dir / 'candidate-outcomes.csv')
    universe_lookup = {(r['action_date'], r['ts_code']): r
                       for r in read_csv_rows(outcomes_dir / 'universe-outcomes.csv')}
    summary = _json(outcomes_dir / 'group-summary.json')['groups']
    conditions = _json(condition_evaluation) if condition_evaluation and condition_evaluation.exists() else []
    condition_map = {(r['action_date'], r['method_id'], r['ts_code']): r for r in conditions}
    output_dir.mkdir(parents=True, exist_ok=True)
    rows, diff = [], []
    for case in cfg['replay_cases']:
        results = {m: _json(root / 'smoke' / case['replay_id'] / m / 'result.json')
                   for m in case['method_order']}
        universe = {x['ts_code']: x['name']
                    for x in _json(root / 'smoke' / case['replay_id'] / 'inputs/universe.json')}
        candidate_maps = {m: {x['ts_code']: x for x in result['candidates']}
                          for m, result in results.items()}
        for method, result in results.items():
            selected = {x['ts_code']: x for x in result['selected']}
            if not selected:
                rows.append({'action_date': case['action_date'], 'method_id': method,
                             'row_type': 'complete_zero',
                             'no_selection_reason': result.get('no_selection_reason'),
                             'reference_is_trade': False})
            for row in allout:
                if row['action_date'] == case['action_date'] and row['method_id'] == method:
                    stock = selected[row['ts_code']]
                    rows.append({**row, 'row_type': 'formal_selected_reference',
                                 **{k: stock.get(k) for k in
                                    ('primary_reason', 'strongest_counter_evidence', 'nearest_comparison',
                                     'participation_condition', 'change_condition')},
                                 **condition_map.get((case['action_date'], method, row['ts_code']),
                                                     {'condition_status': '尚未人工核对'}),
                                 'reference_is_trade': False})
            conditional = {x['ts_code'] if isinstance(x, dict) else x
                           for x in result.get('conditional_events', [])}
            for code in conditional:
                row = next((r for r in candidates if r['action_date'] == case['action_date']
                            and r['method_id'] == method and r['ts_code'] == code), {})
                rows.append({**row, 'action_date': case['action_date'], 'method_id': method,
                             'ts_code': code, 'name': universe.get(code),
                             'row_type': 'conditional_event_reference_only_not_selected',
                             'candidate_reason': candidate_maps[method][code].get('short_reason'),
                             'reference_is_trade': False})
        for code in sorted(set(candidate_maps.get('M0', {})) | set(candidate_maps.get('M1', {}))):
            a, b = candidate_maps['M0'].get(code), candidate_maps['M1'].get(code)
            reference = universe_lookup.get((case['action_date'], code), {})
            diff.append({'action_date': case['action_date'], 'ts_code': code, 'name': universe.get(code),
                         'discovery_relation': 'both' if a and b else 'A_only' if a else 'B_only',
                         'A_discovered_by': json.dumps(a.get('discovered_by') if a else [], ensure_ascii=False),
                         'B_discovered_by': json.dumps(b.get('discovered_by') if b else [], ensure_ascii=False),
                         'A_fate': a.get('final_fate') if a else None,
                         'B_fate': b.get('final_fate') if b else None,
                         'A_reason': a.get('short_reason') if a else None,
                         'B_reason': b.get('short_reason') if b else None,
                         **{k: reference.get(k) for k in
                            ('d5_endpoint_return', 'd10_endpoint_return', 'd20_endpoint_return',
                             'fixed_d20_hit_20pct_close', 'fixed_d20_mae', 'fixed_d20_status')}})
    write_csv(output_dir / '02_A-B逐条结果.csv', rows)
    write_csv(output_dir / '04_发现与取舍差异表.csv', diff)
    group_rows = []
    for name in ('M0', 'M1', 'S_A', 'S_B', 'U'):
        group = summary.get(name, {})
        for view, view_summary in group.get('views', {}).items():
            for metric, values in view_summary.get('metrics', {}).items():
                group_rows.append({'group': name, 'view': view, 'records': view_summary.get('records'),
                                   'distinct_stocks': view_summary.get('distinct_stocks'),
                                   'complete_d20_paths': view_summary.get('complete_d20_paths'),
                                   'zero_selection_days': group.get('zero_selection_days'),
                                   'daily_counts': json.dumps(group.get('daily_counts', {}), ensure_ascii=False),
                                   'metric': metric,
                                   **{k: v for k, v in values.items() if k != 'per_date_mean'},
                                   'per_date_mean': json.dumps(values.get('per_date_mean', {}), ensure_ascii=False),
                                   'zero_selection_is_cash_return': False})
    write_csv(output_dir / '03_组别总表.csv', group_rows)
    return {'rows': len(rows), 'diff_rows': len(diff), 'group_rows': len(group_rows),
            'output_dir': str(output_dir)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--outcomes-dir', type=Path, required=True,
                        help='revision directory holding outcomes.csv and its extras')
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--condition-evaluation', type=Path)
    args = parser.parse_args()
    result = format_tables(args.config, args.outcomes_dir, args.output_dir,
                           condition_evaluation=args.condition_evaluation)
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
