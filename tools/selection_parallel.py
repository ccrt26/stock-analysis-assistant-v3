#!/usr/bin/env python3
"""Manual CLI for the isolated M0/M1 selection trial."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from stock_analyzer.ops import selection_parallel as trial


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='command', required=True)
    for name in ('init','prepare','select','outcomes','batch','review-batch','status','daily'):
        s = sub.add_parser(name)
        s.add_argument('--config', type=Path, required=True)
        if name == 'prepare':
            s.add_argument('--as-of', required=True)
            s.add_argument('--mode', choices=('prospective','replay_smoke'), required=True)
            s.add_argument('--replay-id')
        if name == 'select':
            s.add_argument('--action-date', required=True)
            s.add_argument('--method', choices=('M0','M1'), required=True)
            s.add_argument('--replay-id')
        if name in ('outcomes','batch','review-batch'):
            s.add_argument('--through', required=True)
        if name in ('batch','review-batch'):
            s.add_argument('--number', type=int, required=True)
        if name == 'daily':
            s.add_argument('--date', required=True, help='auto uses Asia/Shanghai 18:30; other dates are unsupported')
    f = sub.add_parser('facts', help='read frozen-source facts to stdout only')
    f.add_argument('--catalog', type=Path, required=True)
    f.add_argument('--code', action='append', required=True)
    f.add_argument('--category', action='append', choices=trial.CATEGORIES)
    f.add_argument('--offset', type=int, default=0)
    d = sub.add_parser('discover', help='page frozen company discovery facts')
    d.add_argument('--catalog', type=Path, required=True)
    d.add_argument('--view', choices=('company',), required=True)
    d.add_argument('--limit', type=int, default=50)
    d.add_argument('--offset', type=int, default=0)
    return p


def main(argv: list[str] | None = None) -> int:
    a = parser().parse_args(argv)
    if a.command == 'discover':
        output = trial.discover_company(a.catalog, limit=a.limit, offset=a.offset)
    elif a.command == 'facts':
        output = trial.facts(a.catalog, codes=a.code, categories=a.category, offset=a.offset)
    elif a.command == 'init':
        output = trial.init_experiment(a.config)
    elif a.command == 'prepare':
        output = {'day_dir': str(trial.prepare_day(a.config, as_of=a.as_of, mode=a.mode, replay_id=a.replay_id))}
    elif a.command == 'select':
        trial._require_research(a.config)
        cfg = trial._cfg(a.config)
        root = trial._trial(cfg)
        candidates = [p.parent for p in list((root/'daily').glob('*/run.json')) + list((root/'smoke').glob('*/run.json'))
                      if trial._json(p)['action_date'] == a.action_date and
                      (a.replay_id is None or p.parent.name == a.replay_id)]
        if len(candidates) != 1:
            raise ValueError('expected exactly one prepared trial day; specify --replay-id for same-day replays')
        output = trial.run_arm(candidates[0], method=a.method)
    elif a.command == 'outcomes':
        output = {'outcome_dir': str(trial.update_outcomes(a.config, through=a.through))}
    elif a.command == 'batch':
        output = {'batch_dir': str(trial.prepare_batch(a.config, batch_number=a.number, through=a.through))}
    elif a.command == 'review-batch':
        trial._require_research(a.config)
        batch = trial.prepare_batch(a.config, batch_number=a.number, through=a.through)
        output = {'report': str(trial.review_batch(batch))}
    elif a.command == 'status':
        output = trial.experiment_status(a.config)
    else:
        if a.date != 'auto':
            raise ValueError('daily only accepts --date auto; explicit history uses prepare --mode replay_smoke')
        trial._require_research(a.config)
        now = datetime.now(ZoneInfo('Asia/Shanghai'))
        if now.time() < time(18, 30):
            output = {'status': 'before_18_30_cutoff', 'today': now.date().isoformat()}
        else:
            cfg = trial._cfg(a.config)
            tomorrow = (now.date() + timedelta(days=1)).isoformat()
            open_days = trial._calendar(Path(cfg['warehouse_root']), tomorrow, tomorrow)
            if not open_days:
                outcomes = trial.update_outcomes(a.config, through=now.date().isoformat())
                output = {'status': 'next_day_closed_no_new_selection', 'outcomes': str(outcomes)}
            else:
                cutoff = datetime.combine(now.date(), time(18, 30), ZoneInfo('Asia/Shanghai'))
                day = trial.prepare_day(a.config, as_of=cutoff.isoformat(), mode='prospective')
                trial.run_arm(day, method='M0')
                trial.run_arm(day, method='M1')
                outcomes = trial.update_outcomes(a.config, through=now.date().isoformat())
                output = {'status': 'complete', 'day_dir': str(day), 'outcomes': str(outcomes)}
    print(json.dumps(output, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
