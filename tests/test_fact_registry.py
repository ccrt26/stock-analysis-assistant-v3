"""Technical registry regressions; no research model or private facts."""
import fcntl
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from stock_analyzer.ops import selection_parallel_compact as compact


def test_public_fact_transaction_locks_real_directory_before_read(tmp_path, monkeypatch):
    root = tmp_path / 'parts'
    root.mkdir()
    alias = tmp_path / 'alias'
    alias.symlink_to(root, target_is_directory=True)
    start = threading.Barrier(2)  # before entering the production lock

    def transaction(catalog_path, *, codes, parts_dir, **kwargs):
        assert parts_dir == root.resolve()
        with (parts_dir / '.facts-delivery.lock').open('a+b') as probe:
            with pytest.raises(BlockingIOError):
                fcntl.flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)
        path = parts_dir / 'parts-registry.json'
        registry = json.loads(path.read_text()) if path.exists() else {'parts': {}}
        registry['parts'][codes[0]] = {'scope': codes[0]}
        compact._write_registry_atomic(path, registry)
        return codes[0]

    monkeypatch.setattr(compact, '_facts_compact_locked', transaction)

    def request(code, directory):
        start.wait(timeout=5)
        return compact.facts_compact(tmp_path / 'catalog.json', codes=[code],
                                     categories=['price'], parts_dir=directory)

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(request, code, directory)
                   for code, directory in [('A', root), ('B', alias)]]
        assert {future.result(timeout=5) for future in futures} == {'A', 'B'}
    assert set(json.loads((root / 'parts-registry.json').read_text())['parts']) == {'A', 'B'}
    inode = (root / '.facts-delivery.lock').stat().st_ino
    compact.facts_compact(tmp_path / 'catalog.json', codes=['C'], categories=['price'], parts_dir=root)
    assert (root / '.facts-delivery.lock').stat().st_ino == inode


def test_atomic_registry_reader_and_failed_publication(tmp_path, monkeypatch):
    path = tmp_path / 'parts-registry.json'
    old = {'parts': {'old': {'scope': 'old', 'data': '中' * 40000}}}
    new = {'parts': {**old['parts'], 'new': {'scope': 'new', 'data': '文' * 40000}}}
    compact._write_registry_atomic(path, old)
    initial = path.read_bytes()
    # Observe while a complete temp file exists but publication is still pending.
    replace = compact.os.replace
    seen = []

    def observe_then_replace(source, destination):
        assert Path(source).parent == destination.parent
        assert json.loads(Path(source).read_text()) == new
        seen.append(json.loads(destination.read_text()))
        replace(source, destination)
        seen.append(json.loads(destination.read_text()))

    monkeypatch.setattr(compact.os, 'replace', observe_then_replace)
    compact._write_registry_atomic(path, new)
    assert seen == [old, new]
    saved = path.read_bytes()
    unrelated = tmp_path / '.parts-registry.json.unrelated.tmp'
    unrelated.write_text('other writer')

    def fail_replace(source, destination):
        assert Path(source).is_file()
        raise OSError('publication failed')

    monkeypatch.setattr(compact.os, 'replace', fail_replace)
    with pytest.raises(OSError, match='publication failed'):
        compact._write_registry_atomic(path, old)
    assert path.read_bytes() == saved and saved != initial
    assert list(tmp_path.glob('.parts-registry.json.*.tmp')) == [unrelated]


def test_fact_lock_exception_releases_and_directories_are_independent(tmp_path):
    first, second = tmp_path / 'first', tmp_path / 'second'
    first.mkdir()
    second.mkdir()
    with pytest.raises(RuntimeError, match='transaction failed'):
        with compact._facts_directory_lock(first):
            with compact._facts_directory_lock(second):
                assert (second / '.facts-delivery.lock').is_file()
            raise RuntimeError('transaction failed')
    inode = (first / '.facts-delivery.lock').stat().st_ino
    with (first / '.facts-delivery.lock').open('a+b') as probe:
        fcntl.flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(probe, fcntl.LOCK_UN)
    with compact._facts_directory_lock(first):
        assert (first / '.facts-delivery.lock').stat().st_ino == inode
