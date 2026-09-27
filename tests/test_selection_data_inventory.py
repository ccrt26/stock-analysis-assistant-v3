from __future__ import annotations

import csv
from pathlib import Path

from tools import selection_data_inventory as inv


class FakeCon:
    def __enter__(self): return self
    def __exit__(self,*a): pass
    def execute(self,*a): return self
    def fetchall(self): return []


def setup(tmp_path,monkeypatch):
    source=tmp_path/'source'
    (source/'local_warehouse/facts/equity_daily').mkdir(parents=True)
    (source/'local_archive/forward_selection').mkdir(parents=True)
    (source/'logs').mkdir()
    (source/'local_warehouse/research.duckdb').write_bytes(b'x')
    (source/'local_warehouse/facts/equity_daily/x.parquet').write_bytes(b'fact')
    (source/'local_archive/forward_selection/report.json').write_text('{}')
    (source/'logs/unknown.log').write_text('log')
    out=tmp_path/'archive/selection_trials/confirmation-cost-v3/maintenance'
    monkeypatch.setattr(inv,'connect_research_warehouse',lambda *a,**k:FakeCon())
    return source,out


def test_inventory_is_read_only_and_reports_unknown(tmp_path,monkeypatch):
    source,out=setup(tmp_path,monkeypatch)
    listing,_=inv.inventory(source,out)
    with listing.open(encoding='utf-8-sig') as f: rows=list(csv.DictReader(f))
    assert any(r['category']=='用途待核日志' for r in rows)
    assert (source/'logs/unknown.log').read_text()=='log'


def test_referenced_evidence_is_not_cleanup_candidate(tmp_path,monkeypatch):
    source,out=setup(tmp_path,monkeypatch)
    _,proposal=inv.inventory(source,out)
    with proposal.open(encoding='utf-8-sig') as f: rows=list(csv.DictReader(f))
    assert rows==[] and (source/'local_archive/forward_selection/report.json').exists()


def test_no_delete_option_or_implicit_cleanup(tmp_path,monkeypatch):
    source,out=setup(tmp_path,monkeypatch)
    inv.inventory(source,out)
    assert (source/'local_warehouse/facts/equity_daily/x.parquet').read_bytes()==b'fact'
    assert '--delete' not in inv.__doc__
