import json
from datetime import date

from stock_analyzer.storage.local_archive import LocalArchive


def test_local_archive_copies_report_tree_and_writes_manifest(tmp_path):
    reports_dir = tmp_path / "reports"
    data_dir = reports_dir / "data"
    daily_dir = reports_dir / "daily" / "2026-07-08"
    data_dir.mkdir(parents=True)
    daily_dir.mkdir(parents=True)
    (reports_dir / "index.html").write_text("<html>latest</html>", encoding="utf-8")
    (data_dir / "latest.json").write_text("{}", encoding="utf-8")
    (data_dir / ".DS_Store").write_text("system", encoding="utf-8")
    (data_dir / ".hidden.json").write_text("hidden", encoding="utf-8")
    (daily_dir / "index.html").write_text("<html>daily</html>", encoding="utf-8")
    (daily_dir / ".DS_Store").write_text("system", encoding="utf-8")

    archive = LocalArchive(tmp_path / "local_archive")
    manifest_path = archive.archive_report_tree(reports_dir, date(2026, 7, 8))

    assert (
        tmp_path / "local_archive" / "reports" / "2026-07-08" / "index.html"
    ).exists()
    assert (
        tmp_path
        / "local_archive"
        / "reports"
        / "2026-07-08"
        / "data"
        / "latest.json"
    ).exists()
    assert not (
        tmp_path
        / "local_archive"
        / "reports"
        / "2026-07-08"
        / "data"
        / ".DS_Store"
    ).exists()
    assert not (
        tmp_path
        / "local_archive"
        / "reports"
        / "2026-07-08"
        / "data"
        / ".hidden.json"
    ).exists()
    assert manifest_path.exists()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["trade_date"] == "2026-07-08"
    assert manifest["file_count"] == 3
    assert all("sha256" in item for item in manifest["files"])
    manifest_paths = [item["path"] for item in manifest["files"]]
    assert set(manifest_paths) == {
        "data/latest.json",
        "daily/2026-07-08/index.html",
        "index.html",
    }
    assert all(not path.startswith(str(tmp_path)) for path in manifest_paths)
