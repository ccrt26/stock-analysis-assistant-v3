"""Read-only presentation of manually authored method studies and batch readiness.

No causal prose generation, method mutation, or archive writing. Dated HTML reads
only authored revisions available at its own cutoff; live readiness is post-hoc.
"""
from __future__ import annotations
import csv
import json
from collections import Counter
from datetime import date, datetime
from zoneinfo import ZoneInfo
from pathlib import Path


def timestamp(value: str) -> datetime:
    value = datetime.fromisoformat(value)
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError('method review timestamp requires timezone')
    return value


def batch_file(batch: Path, value: str) -> Path:
    relative = Path(value)
    path = (batch / relative).resolve()
    if relative.is_absolute() or not path.is_relative_to(batch.resolve()) or not path.is_file():
        raise ValueError('method review file must exist inside its batch')
    return path


def load_reviews(root: Path, visible_at: datetime) -> tuple[list[dict], list[str]]:
    base = root / 'local_archive/skill_optimization'
    reviews, issues = [], []
    for meta in sorted(base.glob('*/review.json')):
        try:
            batch = meta.parent
            if not batch.resolve().is_relative_to(base.resolve()):
                raise ValueError('batch outside archive')
            obj = json.loads(batch_file(batch, 'review.json').read_text())
            if obj['batch_id'] != batch.name:
                raise ValueError('batch identity mismatch')
            revisions = [r for r in obj['revisions'] if timestamp(r['available_at']) <= visible_at]
            if not revisions:
                continue
            r = max(revisions, key=lambda r: timestamp(r['available_at']))
            for key in ('start_action_date','end_action_date','outcome_through_date'):
                date.fromisoformat(r[key])
            if (not isinstance(r['changes'],list) or not isinstance(r['verification'],str)
                    or any(not isinstance(c,dict) or any(not isinstance(c.get(k),str)
                           for k in ('before','after','cost','check')) for c in r['changes'])):
                raise ValueError('invalid method change description')
            if r['status'] not in {'preliminary', 'complete'}:
                raise ValueError('unknown review status')
            if not r['start_action_date'] <= r['end_action_date'] <= r['outcome_through_date']:
                raise ValueError('invalid review dates')
            if r['outcome_through_date'] > timestamp(r['available_at']).date().isoformat():
                raise ValueError('future outcomes')
            documents = [dict(title=label, text=batch_file(batch, r[key]).read_text())
                         for key,label in [('scope_file','问题与范围'),('report_file','研究结论与后续验证')]]
            with batch_file(batch,r['samples_file']).open(encoding='utf-8-sig',newline='') as f:
                reader = csv.DictReader(f)
                samples = list(reader)
                columns = list(reader.fieldnames or [])
            reviews.append({key:r[key] for key in ('available_at','status','title','start_action_date',
                'end_action_date','outcome_through_date','changes','verification')}
                | dict(batch_id=batch.name,documents=documents,samples=samples,columns=columns,
                       source=f'local_archive/skill_optimization/{batch.name}/'))
        except (KeyError, TypeError, ValueError, OSError):
            # Do not expose exception paths or replace a broken report with invented content.
            issues.append(f'{meta.parent.name}：资料缺失或合同不完整，未展示该报告。')
    return sorted(reviews,key=lambda r:timestamp(r['available_at']),reverse=True), issues


def batch_readiness(root: Path, through: str, visible_at: datetime, reviews: list[dict]) -> dict:
    try:
        from tools import export_skill_optimization_dataset as exporter
    except ModuleNotFoundError:
        import export_skill_optimization_dataset as exporter
    selection = root/'local_archive/forward_selection'
    traces = exporter.discover_frozen_traces(selection,'0001-01-01',through)
    traces = [(name,t) for name,t in traces if not t.get('as_of') or timestamp(t['as_of']) <= visible_at]
    if not traces:
        return {'state':'尚无可核对研究批次','through':through}
    complete = {(r['start_action_date'],r['end_action_date']) for r in reviews if r['status']=='complete'}
    batch = next((traces[i:i+5] for i in range(0,len(traces),5)
                  if (traces[i][1]['action_date'],traces[min(i+4,len(traces)-1)][1]['action_date']) not in complete),[])
    if not batch:
        return {'state':'已有批次均已研究，等待新的连续研究日','through':through}
    start,end = batch[0][1]['action_date'],batch[-1][1]['action_date']
    logs=exporter._read_selection_log(selection/'forward-selection-log.csv',start,end)
    mismatches=[]
    formal=exporter.build_formal_selections(batch,logs,mismatches)
    warehouse=root/'local_warehouse'
    dates=exporter.load_trading_dates(warehouse,start,through)
    if not dates:
        return {'state':'交易日历缺失，成熟程度未知','start':start,'end':end,'through':through}
    prices=exporter.build_daily_price_volume_records(warehouse,formal,through,dates)
    exporter.enrich_selections_with_outcomes(formal,prices,through,dates)
    counts=Counter(r['fixed_d20_status'] for r in formal)
    candidates=[c for name,t in batch for c in exporter.extract_candidate_records(t,exporter._trace_version(name,t))]
    conditional=sum(c.get('final_fate')=='selected' and (c.get('research_thesis') or {}).get('engine_status')=='conditional' for c in candidates)
    calendar_mature = sum(sum(d >= t['action_date'] for d in dates) >= 20 for _,t in batch)
    ready=len(batch)==calendar_mature==5 and all(r['fixed_d20_status']=='complete' for r in formal)
    state='数据已齐，待人工整批研究' if ready else (
        '观察期已满，存在数据缺口；待人工研究并说明限制' if len(batch)==calendar_mature==5
        else '批次尚未齐备；可做初步诊断')
    return dict(state=state,start=start,end=end,through=through,research_days=len(batch),
                formal=len(formal),unique_stocks=len({r['ts_code'] for r in formal}),
                conditional=conditional,candidates=len(candidates),counts=dict(counts),
                legacy=sum(r['trace_version']!='daily-research-trace-v4' for r in formal),
                text_mismatches=len(mismatches),
                request=f'请按 ops/selection-method-review-prompt.md，以 diagnose 模式复盘行动日 {start} 至 {end} 的连续研究批次，行情截止 {through}。检查入选是否偏晚，保留全部候选、反例与缺失，分开旧版、V4和条件事件；未成熟时只作初步诊断。把实际研究存到 local_archive/skill_optimization/ 的新批次或不可变新修订，并刷新本地 WEB“选股方法复盘”。提出改动及代价，未经我批准不再改规则。')


def build_method_page(root: Path, *, visible_at: datetime, through: str, live: bool=False) -> dict:
    reviews,issues=load_reviews(root,visible_at)
    readiness=None
    if live:
        try:
            readiness=batch_readiness(root,through,visible_at,reviews)
        except (ValueError, OSError, KeyError, TypeError):
            readiness={'state':'准备状态读取失败；不能当作零样本或已完成','through':through}
    return dict(visible_at=visible_at.astimezone(ZoneInfo('Asia/Shanghai')).isoformat(timespec='seconds'),through=through,
                clock='最新入口的事后研究时钟' if live else '历史报告截止时钟',
                readiness=readiness,reviews=reviews,issues=issues)
