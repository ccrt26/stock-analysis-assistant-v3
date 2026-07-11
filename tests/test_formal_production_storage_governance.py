from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC = PROJECT_ROOT / "src" / "stock_analyzer"


def test_production_source_does_not_reference_legacy_json_evidence_store():
    violations = []
    for path in SRC.rglob("*.py"):
        relative = path.relative_to(SRC).as_posix()
        if relative == "storage/evidence_store.py":
            continue
        text = path.read_text(encoding="utf-8")
        if "LocalEvidenceStore" in text:
            violations.append(relative)
    assert violations == []


def test_production_source_does_not_construct_wide_formal_json_paths():
    violations = []
    for path in SRC.rglob("*.py"):
        relative = path.relative_to(SRC).as_posix()
        if relative == "storage/evidence_store.py":
            continue
        text = path.read_text(encoding="utf-8")
        if '"formal_evidence"' in text or "'formal_evidence'" in text:
            violations.append(relative)
    assert violations == []
