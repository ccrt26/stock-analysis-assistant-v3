# A-share Skill Optimization Dataset Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan.

**Goal:** Export, validate, document, commit, and push a sanitized A-share research dataset covering action dates 2026-08-20 through 2026-08-31.

**Architecture:** A deterministic Python exporter reads frozen local research artifacts and warehouse slices, normalizes them into public-safe CSV/JSONL files, and emits a manifest with counts and hashes. A separate artifact-tool workbook builder turns those normalized files into a human-readable review workbook. Validation checks boundaries, counts, referential integrity, privacy, parseability, checksums, and workbook rendering.

**Tech Stack:** Python 3.11, DuckDB/PyArrow where needed, CSV/JSONL, Node.js with `@oai/artifact-tool`, pytest.

**Spec:** `docs/superpowers/specs/2026-09-01-a-share-skill-optimization-dataset-design.md`

## Global Constraints

- Treat frozen research artifacts as read-only inputs.
- Do not alter any Skill, selection contract, schema, automation, or existing local archive.
- Do not publish credentials, local absolute paths, raw logs, or the whole ignored fact warehouse.
- Keep formation evidence separate from post-selection outcome data.
- Stop the public sample at `action_date=2026-08-31` and outcome date `2026-08-31`.

---

### Task 1: Implement and test the deterministic exporter

**Files:**
- Create: `tools/export_skill_optimization_dataset.py`
- Create: `tests/test_export_skill_optimization_dataset.py`

**Steps:**
1. Write failing tests for boundary filtering, event-key stability, absolute-path rejection, and JSONL/CSV consistency.
2. Implement source discovery and normalization for selection logs, research traces, registered episodes, monitor reports, and derived market/sector/price context.
3. Export the normalized data files and generated README/manifest/checksums without embedding local source paths.
4. Run the focused pytest file and fix failures.

### Task 2: Generate the normalized dataset

**Files:**
- Create: `research/skill-optimization/selection-sample-2026-08-20-to-2026-08-31/README.md`
- Create: `research/skill-optimization/selection-sample-2026-08-20-to-2026-08-31/manifest.json`
- Create: `research/skill-optimization/selection-sample-2026-08-20-to-2026-08-31/checksums.sha256`
- Create: `research/skill-optimization/selection-sample-2026-08-20-to-2026-08-31/data/*`

**Steps:**
1. Run the exporter against the local read-only artifacts.
2. Cross-check the 25 pre-existing workbook records by action date, code, name, reason, counterevidence, and comparison.
3. Confirm the four 2026-08-31 additions and exclude 2026-09-01 actions.
4. Record explicit missing fields as null/unknown rather than reconstructing them.

### Task 3: Build and visually verify the review workbook

**Files:**
- Create: `tools/build_skill_optimization_workbook.mjs`
- Create: `research/skill-optimization/selection-sample-2026-08-20-to-2026-08-31/A股Skill优化样本_2026-08-20至2026-08-31.xlsx`

**Steps:**
1. Mark the artifact operation once before authoring.
2. Build styled sheets for overview, formal selections, review contracts, decision evidence, candidate ledger, daily paths, monitor reviews, and data inventory.
3. Add filters, frozen headers, appropriate number/date formats, readable widths, and source/limit notes.
4. Inspect workbook ranges, scan for formula errors, render every sheet, and visually review the output.

### Task 4: Validate the complete package

**Files:**
- Create: `tools/validate_skill_optimization_dataset.py`

**Steps:**
1. Validate record counts, dates, unique event keys, code/name mappings, and relationship integrity.
2. Scan all committed text and workbook strings for absolute paths, credentials, and post-boundary action dates.
3. Recompute checksums and compare them with the manifest.
4. Run focused tests and the full repository test suite.

### Task 5: Commit and publish the branch

**Steps:**
1. Review `git diff --check`, repository status, and the staged file list.
2. Commit the generated package, tools, tests, spec, and plan on `codex/skill-optimization-dataset-20260831`.
3. Push the branch to `origin` and report the commit hash and GitHub branch URL.
