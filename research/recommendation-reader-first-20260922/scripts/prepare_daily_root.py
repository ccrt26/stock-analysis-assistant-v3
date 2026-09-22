"""Prepare an independent bounded historical data root, never an entire warehouse copy."""
import argparse,json,sys,shutil,hashlib,csv
from pathlib import Path
import pandas as pd,duckdb
p=argparse.ArgumentParser();p.add_argument('--production',type=Path,required=True);p.add_argument('--sources',type=Path,required=True);p.add_argument('--root',type=Path,required=True);a=p.parse_args()
P=a.production.resolve();R=a.root.resolve();S=a.sources.resolve();assert R!=P and not R.exists();R.mkdir(parents=True)
CODE=Path(__file__).resolve().parents[3];sys.path[:0]=[str(CODE/'src'),str(CODE/'tools')]
import recommendation_pipeline as pipe
from stock_analyzer.storage.research_warehouse import ResearchWarehouse
from stock_analyzer.storage.research_schema import connect_research_warehouse
from stock_analyzer.storage.research_parquet import sha256_file
old=pipe.read_json(S/'H3/upstream/accepted-recommendation.json');trace=old['trace'];formation,action,cutoff=pipe.identity(trace)
# Includes only historical episode stocks, selected and actually compared candidates.
codes={e['ts_code'] for e in old['monitor_draft']['snapshot']['episodes']}
codes.update(c['ts_code'] for c in trace['candidate_ledger'])
warehouse=ResearchWarehouse(R/'local_warehouse');source=duckdb.connect(str(P/'local_warehouse/research.duckdb'),read_only=True)
meta=source.execute('select * from research_fact_partitions').fetchdf()
calendar=pd.read_parquet(P/'local_warehouse/facts/trade_calendar/cal_year=2026/data.parquet')
days=sorted(set(str(x)[:10] for x in calendar.loc[calendar['is_open'].astype(str).isin(['True','1','1.0']),'cal_date'] if str(x)[:10]<=formation))[-83:]
allparts={'trade_calendar','security_master','industry_member','company_profile','main_business','announcement','income_statement','balance_sheet','cash_flow','financial_indicator'}
dailies={'equity_daily','adj_factor','index_daily','daily_basic'}
meta=meta.loc[meta['dataset_id'].isin(allparts)|(meta['dataset_id'].isin(dailies)&meta['partition_value'].isin(days))].copy()
meta=meta.loc[(meta.dataset_id!='trade_calendar')|meta.partition_value.isin(['2025','2026'])]
inventory=[]
with connect_research_warehouse(warehouse.duckdb_path) as dest:
 for idx,row in meta.iterrows():
    src=P/'local_warehouse'/row.relative_path;dst=R/'local_warehouse'/row.relative_path;dst.parent.mkdir(parents=True,exist_ok=True)
    frame=pd.read_parquet(src)
    if 'ts_code' in frame and row.dataset_id!='security_master':frame=frame.loc[frame.ts_code.isin(codes)].copy()
    frame.to_parquet(dst,index=False)
    meta.loc[idx,'row_count']=len(frame);meta.loc[idx,'file_sha256']=sha256_file(dst)
    # Subset content is explicitly separate; original metadata stays in provenance below.
    meta.loc[idx,'content_hash']=sha256_file(dst)
    inventory.append(dict(path=str(row.relative_path),source_sha256=row.file_sha256,subset_sha256=sha256_file(dst),rows=len(frame),bytes=dst.stat().st_size))
 dest.register('scoped_metadata',meta);dest.execute('insert into research_fact_partitions select * from scoped_metadata')
 revisions=source.execute("select * from research_fact_revisions where json_extract_string(row_payload,'$.ts_code') in (select unnest(?))",[sorted(codes)]).fetchdf()
 revisions=revisions.loc[revisions.dataset_id.isin(set(meta.dataset_id))]
 dest.register('scoped_revisions',revisions);dest.execute('insert into research_fact_revisions select * from scoped_revisions')
 derived=source.execute("select * from research_derived_partitions where analysis_date between ? and ? and feature_set in ('market_context','sector_hotspot','price_analysis_context','stock_trading_context')",[days[-22],formation]).fetchdf()
 for _,row in derived.iterrows():
    src=P/'local_warehouse'/row.relative_path;dst=R/'local_warehouse'/row.relative_path
    if not src.exists():raise FileNotFoundError(src)
    dst.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(src,dst)
    assert sha256_file(dst)==row.file_sha256
 dest.register('original_derived_metadata',derived);dest.execute('insert into research_derived_partitions select * from original_derived_metadata')
# Copy only formal pre-formation lineage plus target upstream pending, no state/completed adoption.
for category,patterns in [('forward_selection',['research-trace-*.json','daily-research-*.md']),('forward_monitor',['snapshot-*.json','daily-formal-reviews-*.json','monitor-report-*.json','monitor-report-*.md'])]:
 for pattern in patterns:
  for f in (P/'local_archive'/category).glob(pattern):
   import re
   match=re.search(r'\d{4}-\d{2}-\d{2}',f.name)
   if match and match.group()<formation:
    dst=R/'local_archive'/category/f.name;dst.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(f,dst)
log=P/'local_archive/forward_selection/forward-selection-log.csv'
with log.open() as f:reader=csv.DictReader(f);fields=reader.fieldnames;rows=[r for r in reader if r['formation_date']<formation]
dst=R/'local_archive/forward_selection/forward-selection-log.csv';dst.parent.mkdir(parents=True,exist_ok=True)
with dst.open('w') as f:w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rows)
for name in ['registered-episodes.json']:
 src=P/'local_archive/forward_monitor'/name
 if src.exists():shutil.copy2(src,R/'local_archive/forward_monitor'/name)
health=R/'local_archive/data_health'/f'{formation}.json';health.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(P/'local_archive/data_health'/health.name,health)
directory=R/'local_archive/ai_tasks/nightly/replay/recommendation';directory.mkdir(parents=True)
pipe.save_json(R/f'local_archive/forward_selection/pending-trace-{formation}.json',trace)
for key,name in [('snapshot','snapshot'),('ledger','pending-daily-formal-reviews'),('report','pending-report')]:pipe.save_json(R/f'local_archive/forward_monitor/{name}-{formation}.json',old['monitor_draft'][key])
for name in ('research-reply.md','selection-handoff.json'):shutil.copy2(S/'H3/upstream'/name,directory/name)
# Same approved examples; independent content, no writable pointer to production vault.
material=pipe.read_json(S/'H3/materials.json');vault=R/'temporary-vault/10_方法与范文/推荐说明范文';vault.mkdir(parents=True)
for i,example in enumerate(material['examples']):(vault/f'{i+1}.md').write_text(example['text'])
(R/'local_archive/knowledge-vault-path.txt').write_text(str(R/'temporary-vault'))
# Interpreter symlink is the only shared path; archives/facts/code are independent files.
(R/'.venv').symlink_to(P/'.venv',target_is_directory=True)
pipe.save_json(R/'input-copy-provenance.json',dict(formation=formation,as_of=cutoff,scope_codes=sorted(codes),fact_partitions=inventory,derived_count=len(derived),source_database_read_only=True,independent_files=True,subset_not_original_bytes=True))
print(json.dumps(dict(fact_files=len(meta),derived_files=len(derived),bytes=sum(x['bytes'] for x in inventory),codes=len(codes))))
