#!/usr/bin/env python3
"""Manual CLI for the isolated M0/M1 selection trial."""
from __future__ import annotations

import argparse
import json
import warnings
from datetime import datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from stock_analyzer.ops import selection_parallel as trial
from stock_analyzer.ops import selection_parallel_compact as compact


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
            s.add_argument('--formation-date')
            s.add_argument('--action-date')
            s.add_argument('--reuse-inputs-from', type=Path,
                           help='reuse immutable frozen inputs from a prior day directory')
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
    f.add_argument('--offset', type=int, default=0, help='legacy profile paging only')
    f.add_argument('--group-code', action='append', default=[])
    f.add_argument('--sector-date', action='append', default=[])
    f.add_argument('--sector-snapshots', type=Path)
    f.add_argument('--profile', choices=('legacy','decision'), default='legacy')
    f.add_argument('--output', type=Path, help='decision profile: save the full facts locally')
    f.add_argument('--fields', type=Path, help='JSON {category:{section:[fields]}} projection')
    f.add_argument('--part', help='continuation id issued by a previous decision page')
    f.add_argument('--usage-file', type=Path)
    d = sub.add_parser('discover', help='page frozen company discovery facts or run a query request')
    d.add_argument('--catalog', type=Path, required=True)
    view = d.add_mutually_exclusive_group(required=True)
    view.add_argument('--view', choices=('company',))
    view.add_argument('--request', type=Path, help='JSON request over frozen read-only views')
    d.add_argument('--limit', type=int, default=50)
    d.add_argument('--offset', type=int, default=0)
    d.add_argument('--output-dir', type=Path, help='arm-local dir for persisted query results')
    d.add_argument('--part', help='continuation id for oversized rows (reads the stored result)')
    d.add_argument('--usage-file', type=Path)
    k = sub.add_parser('knowledge', help='read frozen knowledge entries by id')
    k.add_argument('--context', type=Path, required=True)
    k.add_argument('--id', action='append', required=True)
    k.add_argument('--usage-file', type=Path)
    e = sub.add_parser('evidence', help='locate/read frozen official originals')
    e.add_argument('--catalog', type=Path, required=True)
    e.add_argument('--context', type=Path, required=True)
    e.add_argument('--request', type=Path, required=True)
    e.add_argument('--usage-file', type=Path)
    pre = sub.add_parser('preflight', help='offline real-scale acceptance; never launches research')
    pre.add_argument('--config', type=Path, required=True)
    pre.add_argument('--output-dir', type=Path, required=True)
    return p


def _limits_from_catalog(catalog_path: Path) -> dict | None:
    run_path = Path(trial._json(catalog_path)['day_dir']) / 'run.json'
    if run_path.exists():
        return trial._json(run_path).get('limits')
    return None


def _budget(catalog_path: Path | None, usage_file: Path | None):
    if usage_file is None or catalog_path is None:
        return None, None
    return usage_file, _limits_from_catalog(catalog_path)


def _print(output: object, *, catalog_path: Path | None = None, usage_file: Path | None = None) -> None:
    limits = _limits_from_catalog(catalog_path) if usage_file is not None and catalog_path is not None else None
    compact.emit_json(output, usage_file=usage_file, limits=limits)


def main(argv: list[str] | None = None) -> int:
    a = parser().parse_args(argv)
    # Fragmentation diagnostics from the existing financial query are not data errors.
    # Keep machine-readable fact responses usable when a tool combines stdout/stderr.
    warnings.filterwarnings('ignore', category=pd.errors.PerformanceWarning)
    if a.command == 'discover':
        if a.part is not None:
            if a.output_dir is None:
                raise ValueError('--part requires --output-dir (where the query result is stored)')
            output = compact.discover_queries(a.catalog, {'queries': []}, output_dir=a.output_dir, part=a.part)
            _print(output, catalog_path=a.catalog, usage_file=a.usage_file)
        elif a.request is not None:
            if a.output_dir is None:
                raise ValueError('--request requires --output-dir (arm-local query output)')
            request = json.loads(a.request.read_text(encoding='utf-8'))
            output = compact.discover_queries(a.catalog, request, output_dir=a.output_dir)
            _print(output, catalog_path=a.catalog, usage_file=a.usage_file)
        else:
            output = trial.discover_company(a.catalog, limit=a.limit, offset=a.offset)
            _print(output, catalog_path=a.catalog, usage_file=a.usage_file)
    elif a.command == 'facts':
        snapshots = json.loads(a.sector_snapshots.read_text()) if a.sector_snapshots else []
        fields = json.loads(a.fields.read_text(encoding='utf-8')) if a.fields else None
        if a.profile == 'decision':
            if a.offset:
                raise ValueError('--offset is the legacy profile pager; decision profile uses --part')
            output = compact.facts_compact(a.catalog, codes=a.code, categories=a.category or list(trial.CATEGORIES),
                                           group_codes=a.group_code, sector_snapshots=snapshots,
                                           sector_dates=a.sector_date, fields=fields, part=a.part,
                                           output=a.output)
            _print(output, catalog_path=a.catalog, usage_file=a.usage_file)
        else:
            if a.part:
                raise ValueError('--part only applies to --profile decision')
            output = trial.facts(a.catalog, codes=a.code, categories=a.category, offset=a.offset,
                                 group_codes=a.group_code, sector_dates=a.sector_date, sector_snapshots=snapshots)
            _print(output, catalog_path=a.catalog, usage_file=a.usage_file)
    elif a.command == 'knowledge':
        output = compact.knowledge_entries(a.context, a.id)
        _print(output, catalog_path=None, usage_file=None)
        if output['missing_ids']:
            return 2
    elif a.command == 'evidence':
        request = json.loads(a.request.read_text(encoding='utf-8'))
        output = compact.evidence_request(a.catalog, a.context, request)
        _print(output, catalog_path=a.catalog, usage_file=a.usage_file)
    elif a.command == 'init':
        output = trial.init_experiment(a.config)
        _print(output)
    elif a.command == 'prepare':
        output = {'day_dir': str(trial.prepare_day(a.config, as_of=a.as_of, mode=a.mode, replay_id=a.replay_id,
                                                   formation_date=a.formation_date, action_date=a.action_date,
                                                   reuse_inputs_from=a.reuse_inputs_from))}
        _print(output)
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
        _print(output)
    elif a.command == 'outcomes':
        output = {'outcome_dir': str(trial.update_outcomes(a.config, through=a.through))}
        _print(output)
    elif a.command == 'batch':
        output = {'batch_dir': str(trial.prepare_batch(a.config, batch_number=a.number, through=a.through))}
        _print(output)
    elif a.command == 'review-batch':
        trial._require_research(a.config)
        batch = trial.prepare_batch(a.config, batch_number=a.number, through=a.through)
        output = {'report': str(trial.review_batch(batch))}
        _print(output)
    elif a.command == 'preflight':
        output = trial.preflight(a.config, output_dir=a.output_dir)
        _print(output)
        return 1 if output.get('failed_checks') else 0
    elif a.command == 'status':
        output = trial.experiment_status(a.config)
        _print(output)
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
    return 0


if __name__ == '__main__':
    try:
        code = main()
    except SystemExit:
        raise
    except (ValueError, OSError, RuntimeError, json.JSONDecodeError) as error:
        compact.fail_json(type(error).__name__, str(error))
        code = 1
    raise SystemExit(code)
