from copy import deepcopy
from pathlib import Path
import socket

import httpx
import pytest
import yaml
from pydantic import ValidationError

from stock_analyzer.knowledge.registry import (
    load_knowledge_registry,
    load_legacy_migration,
)


REAL_REGISTRY_PATH = Path(
    "src/stock_analyzer/knowledge/research_registry.yaml"
)
MANDATORY_S_SOURCE_IDS = {
    "official-csrc-program-trading-2024",
    "official-sse-program-trading-2025",
    "official-csrc-disclosure-2025",
    "official-sse-trading-rules-2026",
    "official-szse-trading-rules-2026",
    "official-bse-trading-rules-2026",
    "official-csrc-delisting-enforcement-2024",
    "official-csrc-share-reduction-2024",
    "official-csrc-buyback-2023",
    "official-csrc-restructuring-2023",
    "official-csrc-restructuring-amendment-2025",
}


def source_payload(*, source_id: str = "official-program-trading") -> dict:
    return {
        "source_id": source_id,
        "grade": "S",
        "kind": "official_rule",
        "title": "证券市场程序化交易管理规定（试行）",
        "publisher": "中国证券监督管理委员会",
        "url": "https://www.csrc.gov.cn/csrc/c100028/c7480577/content.shtml",
        "publication_date": "2024-05-15",
        "effective_from": "2024-10-08",
        "last_verified_on": "2026-07-15",
        "jurisdiction": "中国大陆",
        "market_scope": ["A股"],
        "method_summary": "规定程序化交易报告、监测和风险管理边界。",
        "limitations": ["规则不能识别具体成交账户身份。"],
    }


def entry_payload(
    *,
    knowledge_id: str = "src-cn-program-trading-rules-2025",
    primary_source_id: str = "official-program-trading",
) -> dict:
    return {
        "knowledge_id": knowledge_id,
        "title": "程序化交易表达边界",
        "primary_source_id": primary_source_id,
        "source_grade": "S",
        "version_status": "current",
        "effective_from": "2024-10-08",
        "effect": "hard_boundary",
        "modules": ["price_trading", "risk"],
        "opportunity_types": ["general"],
        "topics": ["trader_identity_boundary"],
        "horizon_min_sessions": 10,
        "horizon_center_sessions": 20,
        "horizon_max_sessions": 30,
        "claim_summary": "日线和分钟线不能识别成交账户身份。",
        "allowed_uses": ["描述可观察的价量结果。"],
        "forbidden_uses": ["根据行情柱推断机构或主力身份。"],
        "prerequisites": ["只使用分析时点已公开的市场事实。"],
        "counter_evidence": ["带账户标签的订单级证据。"],
        "data_requirements": [
            {
                "kind": "fact",
                "name": "equity_daily",
                "required_fields": [
                    "trade_date",
                    "ts_code",
                    "close",
                    "available_at",
                ],
            }
        ],
        "local_validation": {
            "status": "not_required",
            "reason": "这是官方表达边界，不是经验阈值。",
        },
    }


def registry_payload() -> dict:
    return {
        "schema_version": "v3-knowledge-governance-v1",
        "generated_on": "2026-07-15",
        "sources": [source_payload()],
        "entries": [entry_payload()],
    }


def write_yaml(path: Path, payload: dict) -> Path:
    path.write_text(
        yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return path


def test_registry_rejects_duplicate_ids_and_unknown_sources(tmp_path):
    payload = registry_payload()
    payload["sources"].append(deepcopy(payload["sources"][0]))
    with pytest.raises(ValueError, match="official-program-trading"):
        load_knowledge_registry(write_yaml(tmp_path / "duplicate-source.yaml", payload))

    payload = registry_payload()
    payload["entries"].append(deepcopy(payload["entries"][0]))
    with pytest.raises(ValueError, match="src-cn-program-trading-rules-2025"):
        load_knowledge_registry(write_yaml(tmp_path / "duplicate-entry.yaml", payload))

    payload = registry_payload()
    payload["entries"][0]["primary_source_id"] = "missing-source"
    with pytest.raises(ValueError, match="missing-source"):
        load_knowledge_registry(write_yaml(tmp_path / "unknown-source.yaml", payload))


def test_primary_source_grade_must_equal_entry_grade(tmp_path):
    payload = registry_payload()
    payload["entries"][0]["source_grade"] = "A"
    payload["entries"][0]["effect"] = "method_only"
    with pytest.raises(ValueError, match="source grade mismatch"):
        load_knowledge_registry(write_yaml(tmp_path / "grade-mismatch.yaml", payload))


def test_current_rule_versions_cannot_overlap(tmp_path):
    payload = registry_payload()
    old_entry = entry_payload(knowledge_id="rule-v1")
    old_entry["effective_from"] = "2024-10-08"
    old_entry["effective_to"] = "2026-12-31"
    new_entry = entry_payload(knowledge_id="rule-v2")
    new_entry["effective_from"] = "2026-01-01"
    new_entry["supersedes"] = ["rule-v1"]
    payload["entries"] = [old_entry, new_entry]

    with pytest.raises(ValueError, match="overlapping effective intervals"):
        load_knowledge_registry(write_yaml(tmp_path / "overlap.yaml", payload))


def test_supersedes_graph_rejects_cycles(tmp_path):
    payload = registry_payload()
    rule_a = entry_payload(knowledge_id="rule-a")
    rule_a["supersedes"] = ["rule-b"]
    rule_b = entry_payload(knowledge_id="rule-b")
    rule_b["supersedes"] = ["rule-a"]
    payload["entries"] = [rule_a, rule_b]

    with pytest.raises(ValueError, match="version cycle"):
        load_knowledge_registry(write_yaml(tmp_path / "cycle.yaml", payload))


def test_registry_hash_is_order_independent_and_deterministic(tmp_path):
    payload = registry_payload()
    payload["sources"].append(source_payload(source_id="official-program-trading-2"))
    payload["entries"].append(
        entry_payload(
            knowledge_id="src-cn-program-trading-rules-copy",
            primary_source_id="official-program-trading-2",
        )
    )
    first = load_knowledge_registry(write_yaml(tmp_path / "first.yaml", payload))

    reversed_payload = deepcopy(payload)
    reversed_payload["sources"].reverse()
    reversed_payload["entries"].reverse()
    second = load_knowledge_registry(
        write_yaml(tmp_path / "second.yaml", reversed_payload)
    )

    assert first.registry_hash == second.registry_hash
    assert len(first.registry_hash) == 64
    assert first.registry_hash == first.registry_hash.lower()


@pytest.mark.parametrize("legacy_field", ["data_exists", "next_action"])
def test_loader_rejects_legacy_data_exists_and_next_action_fields(
    tmp_path, legacy_field
):
    payload = registry_payload()
    payload["entries"][0][legacy_field] = True
    with pytest.raises(ValidationError, match="extra_forbidden"):
        load_knowledge_registry(write_yaml(tmp_path / f"{legacy_field}.yaml", payload))


def test_registry_loader_never_accesses_network(tmp_path, monkeypatch):
    def fail_network(*args, **kwargs):
        raise AssertionError("registry loading attempted network access")

    monkeypatch.setattr(httpx, "get", fail_network)
    monkeypatch.setattr(httpx.Client, "send", fail_network)
    monkeypatch.setattr(socket, "create_connection", fail_network)

    registry = load_knowledge_registry(
        write_yaml(tmp_path / "offline.yaml", registry_payload())
    )
    assert registry.registry_hash


def test_legacy_migration_loader_validates_fixed_schema(tmp_path):
    payload = {
        "schema_version": "v3-legacy-migration-v1",
        "entries": [
            {
                "legacy_knowledge_id": "legacy-rule",
                "action": "retire",
                "target_knowledge_ids": [],
                "source_verified": False,
                "current_a_share_applicability": "unsupported",
                "data_gate": "not_applicable",
                "local_validation_required": False,
                "reason": "No verified current A-share applicability.",
            }
        ],
    }
    migration = load_legacy_migration(
        write_yaml(tmp_path / "migration.yaml", payload)
    )
    assert migration.entries[0].legacy_knowledge_id == "legacy-rule"


def test_real_registry_contains_exact_mandatory_official_source_floor():
    registry = load_knowledge_registry(REAL_REGISTRY_PATH)
    sources = {source.source_id: source for source in registry.sources}

    assert MANDATORY_S_SOURCE_IDS <= set(sources)
    for source_id in sorted(MANDATORY_S_SOURCE_IDS):
        source = sources[source_id]
        assert source.grade.value == "S"
        assert source.effective_from is not None
        assert source.last_verified_on.isoformat() == "2026-07-15"
        assert source.url.host in {
            "www.csrc.gov.cn",
            "www.sse.com.cn",
            "docs.static.szse.cn",
            "www.bse.cn",
        }


def test_official_entries_never_claim_automatic_price_rise():
    registry = load_knowledge_registry(REAL_REGISTRY_PATH)
    forbidden_claims = ("必然上涨", "自动上涨", "保证上涨", "必涨")

    for entry in registry.entries:
        if entry.source_grade.value != "S":
            continue
        searchable = " ".join((entry.claim_summary, *entry.allowed_uses))
        assert not any(claim in searchable for claim in forbidden_claims)
