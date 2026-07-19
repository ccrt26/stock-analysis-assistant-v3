# V3 Forward Explanations and V02 Selection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (- [ ]) syntax for tracking.

**Goal:** Add strict-as-of immutable decision cards for action-confirmed stocks and a separately versioned V02 formation path that prevents one hotspot from monopolizing recall and confines Pareto dominance to comparable routes.

**Architecture:** Keep every V01 source named in its frozen rule manifest unchanged. Extend the existing strict formation snapshot with explanation facts, persist cards as independent immutable bundles, and implement V02 in new route, selection, and service modules. Expose only explicit manual explain and form-v2 commands.

**Tech Stack:** Python 3.12, pandas, PyArrow parquet, pytest, pathlib, existing ResearchQuery and ForwardLedger.

## Global Constraints

- Preserve the 2026-07-17 V01 formation bundle byte-for-byte.
- Do not modify rules.py, v3_layered_validation.py, v3_compression_revalidation.py, v3_selection_accuracy_pareto.py, or v3_next_day_entry_validation.py.
- v3-forward-baseline-02 rejects formation dates on or before 2026-07-17.
- V02 keeps at most ten unranked stocks, no padding, no sector quota, and the exact three confirmations.
- Announcement titles prove only that an announcement exists; they do not prove economic effects.
- Real artifacts go only to the frozen U-disk root.
- Do not activate scheduling, production, Supabase, Cloudflare, publishing, broker, order, position, sell, or lifecycle behavior.
- Every production behavior is implemented test-first and committed at an independently reviewable checkpoint.

---

## File Map

- Modify src/stock_analyzer/evaluation/v3_forward/inputs.py: expose strict profile, announcement, and sector-catalog frames.
- Modify src/stock_analyzer/evaluation/v3_forward/ledger.py: persist immutable decision-card bundles.
- Create src/stock_analyzer/evaluation/v3_forward/explanations.py: pure card construction and Chinese rendering.
- Create src/stock_analyzer/evaluation/v3_forward/explanation_service.py: verify an existing formation and write cards.
- Create src/stock_analyzer/evaluation/v3_forward/v2_routes.py: group round-robin, overlap audit, and V02 evidence.
- Create src/stock_analyzer/evaluation/v3_forward/v2_selection.py: route-local Pareto compression, industry audit, and V02 manifest.
- Create src/stock_analyzer/evaluation/v3_forward/v2_service.py: V02 formation orchestration and report.
- Modify src/stock_analyzer/evaluation/v3_forward/__main__.py: manual explain and form-v2 commands.
- Add tests/test_v3_forward_explanations.py, test_v3_forward_v2_routes.py, test_v3_forward_v2_selection.py, and test_v3_forward_v2_service.py.
- Modify tests/test_v3_forward_service.py only for the extended FormationInputs fixture.

---

### Task 1: Expose Strict-As-Of Explanation Facts

**Files:**
- Modify: src/stock_analyzer/evaluation/v3_forward/inputs.py
- Modify: tests/test_v3_forward_service.py
- Create: tests/test_v3_forward_explanations.py

**Interfaces:**
- FormationInputs gains sector_catalogs, company_profiles, and announcements DataFrames.
- form_attention_list remains behaviorally identical for V01.

- [ ] **Step 1: Write the failing input test**

~~~python
inputs = FormationInputs(
    formation_date=FORMATION_DATE,
    cutoff=CUTOFF,
    market=pd.DataFrame(),
    stocks=pd.DataFrame(),
    hotspots=pd.DataFrame(),
    memberships=pd.DataFrame(),
    company_facts=pd.DataFrame(),
    names={},
    health_report={},
    input_manifest={},
    sector_catalogs=pd.DataFrame(),
    company_profiles=pd.DataFrame(),
    announcements=pd.DataFrame(),
)
assert inputs.company_profiles.empty
~~~

Also load the real strict snapshot and assert every non-empty profile or announcement available_at is no later than the UTC formation cutoff.

- [ ] **Step 2: Run RED**

~~~bash
PYTHONPATH=src .venv/bin/python -m pytest tests/test_v3_forward_explanations.py tests/test_v3_forward_service.py -q
~~~

Expected: FAIL because FormationInputs does not accept the new fields.

- [ ] **Step 3: Implement the fields**

Preserve the catalog returned by _as_of_sector_inputs and the already materialized COMPANY_PROFILE and ANNOUNCEMENT snapshot frames. Do not add their columns to V01 candidates.

- [ ] **Step 4: Run GREEN**

Run the same command. Expected: PASS.

- [ ] **Step 5: Commit**

~~~bash
git add src/stock_analyzer/evaluation/v3_forward/inputs.py tests/test_v3_forward_service.py tests/test_v3_forward_explanations.py
git commit -m "feat: expose strict V3 explanation facts"
~~~

---

### Task 2: Build Human-Readable Decision Cards

**Files:**
- Create: src/stock_analyzer/evaluation/v3_forward/explanations.py
- Modify: tests/test_v3_forward_explanations.py

**Interfaces:**
- build_decision_cards(payload, candidates, inputs) -> pd.DataFrame
- render_decision_cards(payload, cards) -> str
- recent_announcements_json contains canonical JSON, not an object column.

- [ ] **Step 1: Write failing card tests**

Create confirmed price-route and hotspot-route stocks plus one unconfirmed control.

~~~python
cards = build_decision_cards(payload, candidates, inputs)
assert cards["ts_code"].tolist() == ["301257.SZ", "002603.SZ"]
assert cards.loc[cards.ts_code.eq("301257.SZ"), "main_business"].item()
assert "shareholder_reduction" in cards.loc[
    cards.ts_code.eq("301257.SZ"), "recent_announcements_json"
].item()
~~~

Assert the report includes: 这是什么公司、为什么进入关注名单、为什么现在被动作确认、经营与财务、估值与交易阶段、正式公告、反对证据与不确定性、还缺什么确认、结论边界.

- [ ] **Step 2: Run RED**

~~~bash
PYTHONPATH=src .venv/bin/python -m pytest tests/test_v3_forward_explanations.py -q
~~~

Expected: module import failure.

- [ ] **Step 3: Implement minimal pure helpers**

Implement _industry_map, _latest_profiles, _relevant_announcements, build_decision_cards, and render_decision_cards. The announcement selector must:

- reject any input row after cutoff;
- consider only the trailing 120 calendar days;
- prioritize non-empty candidate_event_types, then the frozen business/risk keyword list, then recency;
- retain at most five title/URL/time/type records;
- never infer revenue, profit, approval success, or price impact from the title.

Normalize company introduction whitespace and cap display at 600 Unicode characters without inventing a summary.

- [ ] **Step 4: Test missing facts and no catalyst**

Assert missing profiles render 本地严格时点数据缺失. Assert a price-only stock without a relevant announcement says confirmation is mainly price/volume driven and lacks a fresh company driver.

- [ ] **Step 5: Run GREEN and commit**

~~~bash
PYTHONPATH=src .venv/bin/python -m pytest tests/test_v3_forward_explanations.py -q
git add src/stock_analyzer/evaluation/v3_forward/explanations.py tests/test_v3_forward_explanations.py
git commit -m "feat: explain V3 action-confirmed stocks"
~~~

---

### Task 3: Persist Immutable Decision Cards

**Files:**
- Modify: src/stock_analyzer/evaluation/v3_forward/ledger.py
- Create: src/stock_analyzer/evaluation/v3_forward/explanation_service.py
- Modify: src/stock_analyzer/evaluation/v3_forward/__main__.py
- Modify: tests/test_v3_forward_explanations.py

**Interfaces:**
- ForwardLedger.write_decision_card_bundle(formation_date, rule_version, payload, cards, report)
- explain_observation(...) -> DecisionCardRunResult
- CLI command explain --formation-date YYYY-MM-DD

- [ ] **Step 1: Write failing immutable-service tests**

Create an existing formation bundle, call explain_observation, and assert:

~~~python
assert result.bundle.path == (
    output / "decision-cards" / "formation_date=2026-07-17"
    / "rule_version=v3-forward-baseline-01"
)
assert rerun.bundle.idempotent is True
~~~

Mutating a card field under the same identity must raise ImmutableEvidenceConflict.

- [ ] **Step 2: Run RED**

Expected: missing ledger/service methods.

- [ ] **Step 3: Implement service flow**

1. Load and hash-verify the existing formation.
2. Reload strict formation inputs.
3. Require the recomputed input_manifest hash to equal the formation payload.
4. Build and render cards.
5. Write cards.json, cards.parquet, report.md, and manifest.json atomically.
6. Write immutable report and audit projections.
7. Never invoke write_formation_bundle.

- [ ] **Step 4: Add CLI parsing test and run GREEN**

~~~bash
PYTHONPATH=src .venv/bin/python -m pytest tests/test_v3_forward_explanations.py tests/test_v3_forward_service.py -q
~~~

- [ ] **Step 5: Commit**

~~~bash
git add src/stock_analyzer/evaluation/v3_forward/ledger.py src/stock_analyzer/evaluation/v3_forward/explanation_service.py src/stock_analyzer/evaluation/v3_forward/__main__.py tests/test_v3_forward_explanations.py
git commit -m "feat: persist immutable V3 decision cards"
~~~

---

### Task 4: Implement V02 Hotspot Recall

**Files:**
- Create: src/stock_analyzer/evaluation/v3_forward/v2_routes.py
- Create: tests/test_v3_forward_v2_routes.py

**Interfaces:**
- round_robin_hotspot_codes(group_lists, limit) -> tuple[str, ...]
- hotspot_overlap_audit(groups, memberships) -> pd.DataFrame
- build_v2_route_evidence(...) -> V2RouteEvidence

- [ ] **Step 1: Write the monopoly reproduction test**

~~~python
codes = round_robin_hotspot_codes(
    {"g1": [f"A{i}" for i in range(40)], "g2": ["B1", "B2", "B3"]},
    limit=6,
)
assert any(code.startswith("B") for code in codes)
assert len(codes) == len(set(codes)) == 6
~~~

- [ ] **Step 2: Run RED**

Expected: module import failure.

- [ ] **Step 3: Implement group round-robin**

Reuse read-only V01 helpers by import. Copy only the evidence-building body whose behavior must differ, so frozen V01 sources remain untouched. Within each group sort by relative_return_20d then current_amount_ratio_20d, and use round_robin_union across ordered group keys.

- [ ] **Step 4: Test overlap math and duplicate stocks**

For membership sets {A,B} and {B,C}, assert Jaccard equals 1/3. A stock in two groups occurs once in hotspot recall. Overlap rows are audit-only.

- [ ] **Step 5: Test complete synthetic route evidence**

Assert hotspot, earnings, and price routes exist, required evidence fields exist, and stock-date identities are unique.

- [ ] **Step 6: Run GREEN and commit**

~~~bash
PYTHONPATH=src .venv/bin/python -m pytest tests/test_v3_forward_v2_routes.py -q
git add src/stock_analyzer/evaluation/v3_forward/v2_routes.py tests/test_v3_forward_v2_routes.py
git commit -m "feat: balance V02 hotspot recall"
~~~

---

### Task 5: Implement Route-Local V02 Compression

**Files:**
- Create: src/stock_analyzer/evaluation/v3_forward/v2_selection.py
- Create: tests/test_v3_forward_v2_selection.py

**Interfaces:**
- compress_v2_attention(evidence, candidate_cap=10) -> tuple[decisions, route_audit]
- form_attention_list_v2(inputs) -> V2FormationEvidence
- v2_rule_manifest() and v2_rule_manifest_hash()

- [ ] **Step 1: Write cross-route RED test**

Create equal earnings and hotspot candidates where only hotspot_support differs.

~~~python
decisions, audit = compress_v2_attention(evidence)
assert set(decisions.loc[decisions.user_layer.eq("关注"), "ts_code"]) == {
    "EARNINGS", "HOTSPOT"
}
~~~

- [ ] **Step 2: Run RED**

Expected: module import failure.

- [ ] **Step 3: Implement route × lane fronts**

For each route named in routes:

1. exclude hard-invalid rows;
2. derive the existing internal lane;
3. compute the first non-dominated front within route and lane only;
4. union lane fronts in deterministic evidence order;
5. round-robin hotspot, earnings, and price route lists;
6. remove duplicates and stop at ten;
7. do not fill from lower fronts.

- [ ] **Step 4: Test comparable dominance and capacity**

A strictly dominated same-route row is excluded. Eleven incomparable front rows yield at most ten. Four front rows yield exactly four.

- [ ] **Step 5: Add audits and manifest**

Map active official L1 industries, add industry_l1_name, and return recalled/frontier/selected counts per route. Industry counts never delete a row.

Assert:

~~~python
assert V2_RULE_VERSION == "v3-forward-baseline-02"
assert v2_rule_manifest()["minimum_formation_date"] == "2026-07-20"
assert len(v2_rule_manifest_hash()) == 64
~~~

- [ ] **Step 6: Run GREEN and commit**

~~~bash
PYTHONPATH=src .venv/bin/python -m pytest tests/test_v3_forward_v2_routes.py tests/test_v3_forward_v2_selection.py -q
git add src/stock_analyzer/evaluation/v3_forward/v2_selection.py tests/test_v3_forward_v2_selection.py
git commit -m "feat: isolate V02 route comparisons"
~~~

---

### Task 6: Orchestrate V02 Formation

**Files:**
- Create: src/stock_analyzer/evaluation/v3_forward/v2_service.py
- Modify: src/stock_analyzer/evaluation/v3_forward/__main__.py
- Create: tests/test_v3_forward_v2_service.py

**Interfaces:**
- form_observation_v2(...) -> V2FormationRunResult
- render_v2_formation_report(...) -> str
- CLI command form-v2 --formation-date YYYY-MM-DD

- [ ] **Step 1: Write boundary and bundle RED tests**

Assert 2026-07-17 raises ValueError. A later synthetic date writes a V02 payload containing route, overlap, and industry audits, then writes decision cards.

- [ ] **Step 2: Run RED**

Expected: missing module/function.

- [ ] **Step 3: Implement the V02 report**

It must include market/hotspot summary, full attention list, all three confirmation details, route counts, L1 industry counts, maximum concentration, highest hotspot overlaps, a concentration warning when one industry exceeds half, detailed action-confirmed cards, strict cutoff, and non-advice language.

- [ ] **Step 4: Implement immutable V02 orchestration**

Use only V02 route/selection/manifest functions. Audit future fields, duplicates, counts, route distribution, overlaps, and industry concentration. Then write cards using the exact same FormationInputs snapshot.

- [ ] **Step 5: Add CLI and idempotence tests**

form-v2 must be explicit; form must never silently switch versions. Exact reruns preserve hashes.

- [ ] **Step 6: Run all forward tests and commit**

~~~bash
PYTHONPATH=src .venv/bin/python -m pytest tests/test_v3_forward_rules.py tests/test_v3_forward_ledger.py tests/test_v3_forward_inputs.py tests/test_v3_forward_service.py tests/test_v3_forward_explanations.py tests/test_v3_forward_v2_routes.py tests/test_v3_forward_v2_selection.py tests/test_v3_forward_v2_service.py -q
git add src/stock_analyzer/evaluation/v3_forward/v2_service.py src/stock_analyzer/evaluation/v3_forward/__main__.py tests/test_v3_forward_v2_service.py
git commit -m "feat: form audited V02 forward observations"
~~~

---

### Task 7: Produce the Real 2026-07-17 Cards

**Runtime:** frozen U-disk root only.

- [ ] **Step 1: Capture V01 authority hashes**

Hash formation.json, candidates.parquet, report.md, and manifest.json.

- [ ] **Step 2: Run explain**

~~~bash
PYTHONPATH=src .venv/bin/python -m stock_analyzer.evaluation.v3_forward explain   --formation-date 2026-07-17   --warehouse-root /Users/ccrt/Documents/股票分析助手/local_warehouse   --archive-root /Users/ccrt/Documents/股票分析助手/local_archive   --output-root /Volumes/ZHUTONG/股票分析助手-V3回测/2026-07-19-v3-forward-observation
~~~

Expected: exactly 301257.SZ and 002603.SZ.

- [ ] **Step 3: Audit factual completeness**

Verify identity, business, industry, confirmations, financials, valuation, price stage, announcements, counter-evidence, missing confirmation, non-advice language, and all available times at or before cutoff.

- [ ] **Step 4: Rerun and verify idempotence**

Expected: idempotent status and identical card bundle hashes.

- [ ] **Step 5: Recheck V01 authority hashes**

Expected: exact match with Step 1.

- [ ] **Step 6: Run an in-memory V02 mechanical diagnostic**

Call pure form_attention_list_v2 on 2026-07-17 inputs. Do not invoke form-v2, write a V02 authority bundle, or claim performance improvement. Record route distribution and verify earnings candidates are no longer removed solely by cross-route hotspot support.

---

### Task 8: Final Verification

- [ ] **Step 1: Run the full related suite**

~~~bash
PYTHONPATH=src .venv/bin/python -m pytest   tests/test_v3_forward_rules.py   tests/test_v3_forward_ledger.py   tests/test_v3_forward_inputs.py   tests/test_v3_forward_service.py   tests/test_v3_forward_explanations.py   tests/test_v3_forward_v2_routes.py   tests/test_v3_forward_v2_selection.py   tests/test_v3_forward_v2_service.py   tests/test_v3_layered_validation.py   tests/test_v3_compression_revalidation.py   tests/test_v3_next_day_entry_validation.py   tests/test_v3_selection_accuracy_pareto.py -q
~~~

Expected: all pass.

- [ ] **Step 2: Run boundary scans**

~~~bash
git diff --check
rg -n "supabase|cloudflare|launchctl|broker|place_order|position_size"   src/stock_analyzer/evaluation/v3_forward tests/test_v3_forward_*.py
~~~

Classify benign text matches; no external-write or trading implementation is allowed.

- [ ] **Step 3: Verify repository and U-disk state**

Require clean git status, unchanged V01 authority hashes, passed real card audit, no V02 authority formation for 2026-07-17, and no runtime artifact outside the frozen U-disk root.

- [ ] **Step 4: Report**

Report exact tests, commits, card path, V01 hash result, the two company summaries, V02 mechanical route distribution, and the next eligible V02 formation date. State that no scheduler or trading action was activated.

