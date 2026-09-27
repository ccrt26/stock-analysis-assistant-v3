"""Inspect or repair reviewed statement conflicts without touching research outputs."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
import fcntl
import json
from pathlib import Path
import shutil
from zoneinfo import ZoneInfo

import duckdb

from stock_analyzer.config import AppConfig
from stock_analyzer.data.fundamental_backfill import FundamentalBackfillService
from stock_analyzer.data.research_contracts import ResearchDatasetId
from stock_analyzer.data.tushare_research_client import TushareResearchClient
from stock_analyzer.ops.research_data_job import research_job_lock
from stock_analyzer.ops.research_health import build_research_health_report, write_health_report
from stock_analyzer.storage.research_parquet import sha256_file
from stock_analyzer.storage.research_query import ResearchQuery
from stock_analyzer.storage.research_schema import RESEARCH_SCHEMA_VERSION
from stock_analyzer.storage.research_warehouse import ResearchWarehouse

STATEMENTS = ("income_statement", "balance_sheet", "cash_flow")


def _json(value):
    return json.dumps(value, ensure_ascii=False, indent=2, default=str)


def _write(path, value):
    path.write_text(_json(value) + "\n", encoding="utf-8")


def inspect_conflicts(root: Path) -> dict:
    """No directory creation, locks, mutable warehouse constructor or API calls."""
    with duckdb.connect(str(root / "research.duckdb"), read_only=True) as con:
        rows = con.execute(
            "select dataset_id,business_key_hash,business_key_json,row_payload,first_seen_at "
            "from research_fact_conflicts where status='unresolved' "
            "and dataset_id in (?, ?, ?) order by dataset_id,business_key_hash",
            list(STATEMENTS),
        ).fetchall()
    groups = defaultdict(list)
    for dataset, key_hash, key, payload, first_seen in rows:
        groups[(dataset, key_hash)].append((json.loads(key), json.loads(payload), first_seen))
    targets = []
    for (dataset, key_hash), variants in groups.items():
        targets.append({
            "dataset": dataset, "business_key_hash": key_hash,
            "key": variants[0][0], "variants": len(variants),
            "update_flags": [str(row.get("update_flag", row.get("_provider_update_flag"))) for _, row, _ in variants],
            "first_seen_at": min(first for _, _, first in variants).isoformat(),
        })
    return {"inspected_at": datetime.now(timezone.utc).isoformat(),
            "counts": dict(Counter(item["dataset"] for item in targets)), "targets": targets}


def reviewed_targets(current, reviewed):
    allowed = {(v["dataset"], v["business_key_hash"]): v for v in reviewed["targets"]}
    selected = []
    for target in current["targets"]:
        identity = (target["dataset"], target["business_key_hash"])
        if identity not in allowed or allowed[identity]["key"] != target["key"]:
            raise ValueError("unreviewed statement conflict scope; inspect and review before applying")
        selected.append(target)
    return selected


@contextmanager
def _facts_lock(root):
    with (root / ".facts.lock").open("a+b") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def create_backup(root: Path, run_dir: Path, targets: list[dict]) -> dict:
    """Caller holds job lock; retain existing job -> facts lock ordering."""
    with _facts_lock(root):
        database = root / "research.duckdb"
        if database.with_suffix(".duckdb.wal").exists():
            raise ValueError("WAL present: stop before writable warehouse construction")
        if list((root / ".fact-promotions").glob("*.json")) or list((root / "facts").rglob("*.previous")):
            raise ValueError("pending fact recovery: stop before backup or repair")
        pairs = {(v["dataset"], v["key"]["report_period"]) for v in targets}
        with duckdb.connect(str(database), read_only=True) as con:
            version = con.execute("select value from research_metadata where key='research_schema_version'").fetchone()
            if version is None or int(version[0]) != RESEARCH_SCHEMA_VERSION:
                raise ValueError("warehouse schema version differs; repair cannot migrate")
            rows = con.execute("select dataset_id,partition_value,relative_path from research_fact_partitions").fetchall()
        sources = [database]
        sources.extend(root / path for dataset, period, path in rows if (dataset, period) in pairs)
        manifest = {"created_at": datetime.now(timezone.utc).isoformat(), "targets": targets, "files": []}
        for source in sources:
            if root.resolve() not in source.resolve().parents or not source.is_file():
                raise ValueError("invalid backup source")
            relative = source.relative_to(root)
            destination = run_dir / "backup" / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
            digest = sha256_file(destination)
            if digest != sha256_file(source):
                raise ValueError("backup verification failed")
            manifest["files"].append({"path": str(relative), "bytes": destination.stat().st_size, "sha256": digest})
        if database.with_suffix(".duckdb.wal").exists():
            raise ValueError("WAL appeared during backup; stop repair")
        _write(run_dir / "backup-manifest.json", manifest)
    return manifest


def _current_identity(frame):
    return {str(r["business_key_hash"]): [str(r["payload_hash"]), datetime.fromisoformat(str(r["available_at"])).astimezone(timezone.utc).isoformat(), int(r["revision_no"])]
            for r in frame.to_dict(orient="records")}


def snapshot(warehouse, targets, cutoffs):
    query = ResearchQuery(warehouse)
    selected = defaultdict(set)
    periods = defaultdict(set)
    for item in targets:
        selected[item["dataset"]].add(item["business_key_hash"])
        periods[item["dataset"]].add(item["key"]["report_period"])
    result = {"non_target_current": {}, "target_current": {}, "historical": {}, "revisions": {}, "conflicts": {}}
    for dataset, values in periods.items():
        manifest = warehouse.partition_manifest(dataset)
        available = set(manifest["partition_value"].astype(str)) if not manifest.empty else set()
        physical = tuple(sorted(values & available))
        frame = warehouse.read_current_partitions(dataset, physical) if physical else None
        current = _current_identity(frame) if frame is not None else {}
        result["target_current"][dataset] = {k: v for k, v in current.items() if k in selected[dataset]}
        result["non_target_current"][dataset] = {k: v for k, v in current.items() if k not in selected[dataset]}
        result["historical"][dataset] = {}
        for cutoff in cutoffs:
            visible = query.dataset_partitions_as_of(dataset, physical, cutoff) if physical else None
            identities = _current_identity(visible) if visible is not None else {}
            result["historical"][dataset][cutoff.isoformat()] = {k: v for k, v in identities.items() if k in selected[dataset]}
    with duckdb.connect(str(warehouse.duckdb_path), read_only=True) as con:
        # Keep actual persisted revisions and conflict lifecycle identities for comparison.
        for dataset, key_hash, revision, payload in con.execute(
            "select dataset_id,business_key_hash,revision_no,to_json(r)::varchar "
            "from research_fact_revisions r where dataset_id in (?, ?, ?)", list(STATEMENTS)
        ).fetchall():
            result["revisions"][f"{dataset}/{key_hash}/{revision}"] = payload
        for identity, dataset, key_hash, payload in con.execute(
            "select conflict_id,dataset_id,business_key_hash,to_json(c)::varchar "
            "from research_fact_conflicts c"
        ).fetchall():
            result["conflicts"][identity] = [dataset, key_hash, payload]
        pairs = {(v["dataset"], v["key"]["report_period"]) for v in targets}
        result["other_partitions"] = [list(row) for row in con.execute(
            "select dataset_id,partition_value,content_hash,file_sha256,row_count from research_fact_partitions order by 1,2"
        ).fetchall() if (row[0], row[1]) not in pairs]
        result["derived"] = str(con.execute("select feature_set,analysis_date,formula_version,content_hash,run_id from research_derived_partitions order by 1,2,3").fetchall())
        result["stage_runs"] = str(con.execute("select run_id,status,finished_at from research_ingestion_runs order by run_id").fetchall())
    return result


def verify(before, after, targets, started):
    for field in ("non_target_current", "historical", "other_partitions", "derived", "stage_runs"):
        if before[field] != after[field]:
            raise ValueError(f"repair changed protected state: {field}")
    for dataset, current in after["target_current"].items():
        for key, value in current.items():
            if before["target_current"][dataset].get(key) != value and datetime.fromisoformat(value[1]) < started:
                raise ValueError("target financial content was backdated")
    for key, value in before["revisions"].items():
        if after["revisions"].get(key) != value:
            raise ValueError("repair changed existing revision history")
    selected = {(v["dataset"], v["business_key_hash"]) for v in targets}
    for key in set(after["revisions"]) - set(before["revisions"]):
        parts = key.split("/")
        if (parts[0], parts[1]) not in selected:
            raise ValueError("repair added a non-target revision")
    for identity, (dataset, key_hash, payload) in before["conflicts"].items():
        old = json.loads(payload)
        item = after["conflicts"].get(identity)
        if item is None:
            raise ValueError("repair deleted conflict history")
        if (dataset, key_hash) not in selected or old["status"] != "unresolved":
            if item != before["conflicts"][identity]:
                raise ValueError("repair changed unrelated conflict history")
            continue
        new = json.loads(item[2])
        for field in ("first_seen_at", "available_at", "row_payload", "payload_hash"):
            if old[field] != new[field]:
                raise ValueError("repair rewrote conflict evidence")
        if new["status"] == "resolved" and datetime.fromisoformat(new["resolved_at"]) < started:
            raise ValueError("resolution was backdated")


def _formal_files(archive):
    return {str(p.relative_to(archive)): (p.stat().st_size, p.stat().st_mtime_ns)
            for folder in ("forward_selection", "forward_monitor", "data_health")
            for p in (archive / folder).rglob("*") if p.is_file()}


def _live_client(config):
    import tushare as ts
    token = config.resolve_tushare_token()
    if not token:
        raise RuntimeError("Tushare token missing")
    return TushareResearchClient(ts.pro_api(token))


def apply_repair(config, reviewed, output_dir, client_factory=_live_client):
    root = config.local_warehouse_dir
    with research_job_lock(root):
        targets = reviewed_targets(inspect_conflicts(root), reviewed)
        if not targets:
            return {"status": "nothing_to_repair", "remaining": 0}
        started = datetime.now(timezone.utc)
        run_dir = output_dir / started.strftime("run-%Y%m%dT%H%M%S.%fZ")
        run_dir.mkdir(parents=True, exist_ok=False)
        results = {"started_at": started.isoformat(), "target_count": len(targets), "steps": [], "run_dir": str(run_dir), "status": "running"}
        try:
            create_backup(root, run_dir, targets)
            readonly = ResearchWarehouse(root, read_only=True)
            cutoffs = [started - timedelta(microseconds=1), min(datetime.fromisoformat(v["first_seen_at"]) for v in targets) - timedelta(microseconds=1)]
            before = snapshot(readonly, targets, cutoffs)
            _write(run_dir / "before.json", before)
            protected_files = _formal_files(config.local_archive_dir)
            warehouse = ResearchWarehouse(root)
            service = FundamentalBackfillService(client_factory(config), warehouse)
            for dataset in STATEMENTS:
                dataset_targets = [v for v in targets if v["dataset"] == dataset]
                if not dataset_targets:
                    continue
                keys = tuple(tuple(v["key"][field] for field in ("ts_code", "report_period", "report_type", "statement_type")) for v in dataset_targets)
                result = service.backfill_statement_business_keys(
                    dataset=ResearchDatasetId(dataset), business_keys=keys,
                    through=datetime.now(ZoneInfo("Asia/Shanghai")).date(),
                )
                results["steps"].append(result.model_dump(mode="json"))
                _write(run_dir / "result.json", results)
                print(f"{dataset}: committed={result.committed} limited={result.limited} failed={result.failed} waiting={result.waiting_upstream}", flush=True)
            after = snapshot(ResearchWarehouse(root, read_only=True), targets, cutoffs)
            _write(run_dir / "after.json", after)
            verify(before, after, targets, started)
            if protected_files != _formal_files(config.local_archive_dir):
                raise ValueError("formal research or health files changed during repair")
            remaining = inspect_conflicts(root)
            results["remaining"] = len(remaining["targets"])
            results["resolved"] = len(targets) - results["remaining"]
            results["verification"] = "historical_queries_non_targets_revisions_and_formal_outputs_unchanged"
            _write(run_dir / "remaining.json", remaining)
            report = build_research_health_report(ResearchWarehouse(root, read_only=True), datetime.now(ZoneInfo("Asia/Shanghai")).date())
            write_health_report(report, run_dir / "health")
            results["status"] = "completed" if not results["remaining"] else "limited"
        except Exception as exc:
            results["status"] = "failed"
            results["error"] = {"type": type(exc).__name__, "message": str(exc)}
            try:
                results["remaining"] = len(inspect_conflicts(root)["targets"])
                results["resolved"] = len(targets) - results["remaining"]
            except Exception:
                results["remaining"] = None
            _write(run_dir / "result.json", results)
            raise
        results["finished_at"] = datetime.now(timezone.utc).isoformat()
        _write(run_dir / "result.json", results)
        return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--inspect", action="store_true")
    mode.add_argument("--apply", action="store_true")
    parser.add_argument("--targets", type=Path, help="Previously inspected and reviewed target JSON; mandatory for apply")
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    config = AppConfig.load()
    if not args.apply:
        print(_json(inspect_conflicts(config.local_warehouse_dir)))
        return
    if args.targets is None or args.output_dir is None:
        parser.error("--apply requires --targets and --output-dir")
    result = apply_repair(config, json.loads(args.targets.read_text()), args.output_dir)
    print(_json(result))
    if result["status"] not in ("completed", "nothing_to_repair"):
        raise SystemExit(2)


if __name__ == "__main__":
    main()
