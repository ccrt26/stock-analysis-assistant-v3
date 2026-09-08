"""Attach existing local market rows and upstream deep-review keys to a report.
No network or stock research. Python standard library only.
"""
from __future__ import annotations
import argparse
import copy
import csv
import json
import math
import re
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

try:
    import web_display_contract
except ImportError:  # 本文件可能被 spec_from_file_location 以独立模块加载
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import web_display_contract

DEFAULT_CODES = ['000001.SH', '399001.SZ', '399006.SZ', '000688.SH']
INDEX_NAMES = {'000001.SH':'上证指数','399001.SZ':'深证成指','399006.SZ':'创业板指','000688.SH':'科创50','899050.BJ':'北证50'}


def date_iso(value: str) -> str:
    value = str(value)
    if re.fullmatch(r'\d{8}', value):
        return f'{value[:4]}-{value[4:6]}-{value[6:]}'
    if re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
        return value
    raise ValueError(f'Expected YYYY-MM-DD or YYYYMMDD, got {value!r}')


def number(value: Any) -> float | None:
    if value is None or value == '':
        return None
    if isinstance(value, bool):
        raise ValueError('Boolean is not a price')
    result = float(value)
    if not math.isfinite(result):
        raise ValueError('Price must be finite or null')
    return result


def read_snapshot_text(text: str) -> dict[str, Any]:
    """Read JSON, PRISM HTML, or the original `const DATA = {...};` report."""
    text = text.lstrip('\ufeff').strip()
    if text.startswith('{'):
        data = json.loads(text)
    else:
        match = re.search(r'<script\b[^>]*\bid=["\']snapshot["\'][^>]*>(.*?)</script>', text, re.S)
        if match:
            data = json.loads(match.group(1))
        else:
            match = re.search(r'\bconst\s+DATA\s*=\s*', text)
            if not match:
                raise ValueError('No JSON snapshot or const DATA object found')
            data, _ = json.JSONDecoder().raw_decode(text[match.end():])
    for field in ('analysis_date','dates','stocks','market'):
        if field not in data:
            raise ValueError(f'Snapshot missing field {field}')
    return data


def enrich_snapshot(snapshot: Mapping[str, Any], *, market_rows: Sequence[Mapping[str, Any]] | None = None,
                    deep_selection: Mapping[str, Any] | None = None,
                    market_codes: Sequence[str] | None = None,
                    deep_limit: int = 8) -> dict[str, Any]:
    """Copy metadata, never alter quotes, recommendation references, or reviews.

    market_rows: existing index_daily-like rows, values in actual index points.
    Required: ts_code/code, trade_date, close. pre_close/previousClose is optional.
    The caller is responsible for the source and publication cutoff of its data.
    """
    if not 0 <= deep_limit <= 8:
        raise ValueError('deep_limit must be between 0 and 8')
    d = copy.deepcopy(dict(snapshot))
    d['presentation'] = {**d.get('presentation', {}), 'deepLimit': deep_limit,
                         'marketCodes': list(market_codes or DEFAULT_CODES)}
    # Remove obsolete demo-only preferences: these are not research selections.
    for k in ('demoShowcase','heroKeys','cardKeys'):
        d['presentation'].pop(k, None)
    if market_rows is not None:
        rows_by_code: dict[str, dict[str, dict[str, Any]]] = {}
        for row in market_rows:
            code = row.get('ts_code') or row.get('code')
            if not code:
                raise ValueError('Market row missing ts_code/code')
            date = date_iso(str(row['trade_date']))
            if date > d['analysis_date']:
                continue  # future data is neither plotted nor used for this date
            normalized = {'code':code,'trade_date':date,'close':number(row.get('close')),
                          'previousClose':number(row.get('previousClose',row.get('pre_close'))),
                          'name':row.get('name') or INDEX_NAMES.get(code,code),
                          'source':row.get('source') or '接入方提供的本地指数日线'}
            daily = rows_by_code.setdefault(code,{})
            if date in daily and daily[date] != normalized:
                raise ValueError(f'Conflicting index rows: {code} {date}')
            daily[date] = normalized
        result = []
        for code, daily in rows_by_code.items():
            newest = max(daily)
            selected = dict(daily[newest])
            # 日期定位用完整 ISO（sessionDates 优先；旧 MM-DD 走受约束的兼容转换）。
            dates = web_display_contract.resolve_session_dates(
                d.get('dates'), d['analysis_date'], d.get('sessionDates'))
            selected['series'] = [daily.get(date,{}).get('close') for date in dates if date<=d['analysis_date']]
            result.append(selected)
        d['marketIndices'] = result
    if deep_selection is not None:
        d['dailyDeepReview'] = copy.deepcopy(dict(deep_selection))
    return d


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot', type=Path, required=True, help='Existing JSON or original HTML report')
    parser.add_argument('--market', type=Path, help='Existing market rows as JSON list or UTF-8 CSV')
    parser.add_argument('--deep', type=Path, help='Optional JSON: {date, recordKeys}; do not invent the list')
    parser.add_argument('--indices', default=','.join(DEFAULT_CODES))
    parser.add_argument('--deep-limit', type=int, default=8)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    snapshot = read_snapshot_text(args.snapshot.read_text(encoding='utf-8-sig'))
    market_rows = None
    if args.market:
        if args.market.suffix.lower()=='.csv':
            with args.market.open(encoding='utf-8-sig',newline='') as stream:
                market_rows = list(csv.DictReader(stream))
        else:
            market_rows = json.loads(args.market.read_text(encoding='utf-8-sig'))
    deep = json.loads(args.deep.read_text(encoding='utf-8-sig')) if args.deep else None
    result = enrich_snapshot(snapshot, market_rows=market_rows, deep_selection=deep,
                             market_codes=args.indices.split(','), deep_limit=args.deep_limit)
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(args.out)

if __name__=='__main__':
    main()
