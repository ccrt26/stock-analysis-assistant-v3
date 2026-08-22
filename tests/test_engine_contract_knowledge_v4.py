from pathlib import Path
import yaml
def _payload(): return yaml.safe_load(Path("src/stock_analyzer/knowledge/research_registry.yaml").read_text(encoding="utf-8"))
def test_v4_knowledge_entries_exist():
 ids={x["knowledge_id"] for x in _payload()["entries"]}; assert {"src_cn_disclosure_novelty_chain","src_cn_market_propagation_modes","src_cn_sector_leader_cluster","src_cn_attention_proxy_boundary"} <= ids
def test_v4_sources_have_no_duplicate_id_or_doi():
 sources=_payload()["sources"]; ids=[x["source_id"] for x in sources]; assert len(ids)==len(set(ids)); dois=[str(x.get("doi","")).lower() for x in sources if x.get("doi")]; assert len(dois)==len(set(dois))
def test_v4_daily_prompt_and_contract_use_exact_taxonomy():
 prompt=Path("ops/forward-selection-prompt.md").read_text(encoding="utf-8"); contract=Path("docs/architecture/a-share-short-horizon-engine-contract-v4.md").read_text(encoding="utf-8")
 for term in ("daily-research-trace-v4","fresh_event_pending","event_repricing_confirmed","sector_broad_diffusion","sector_leader_cluster","independent_demand_acceleration","one_day_repair","sector_rotation","concentrated_speculation"): assert term in prompt+contract
