#!/usr/bin/env bash
# Actual commands, environment paths mechanically replaced. Do not resample
# terminal trials. The plan and its code SHA must already match the checkout.
set -o pipefail
"$PYTHON" research/recommendation-reader-first-20260922/scripts/prepare_samples.py --production "$PRODUCTION_ROOT" --output "$WORK_ROOT/sources"
PYTHONPATH=src:tools "$PYTHON" research/recommendation-reader-first-20260922/scripts/prepare_daily_root.py --production "$PRODUCTION_ROOT" --sources "$WORK_ROOT/sources" --root "$WORK_ROOT/daily-root"
PYTHONPATH=src:tools "$PYTHON" -u research/recommendation-reader-first-20260922/scripts/run_trials.py --work "$WORK_ROOT" --code "$CODE_ROOT"
# The first process was deliberately interrupted during request 2 for the
# documented authority-wiring fix; exact completed deliveries were retained.
PYTHONPATH=src:tools "$PYTHON" -u research/recommendation-reader-first-20260922/scripts/run_trials.py --work "$WORK_ROOT" --code "$CODE_ROOT" --continue-interrupted
# Request 7 completed with a negative reading judgment, but the old parser
# miscounted a CLI warning. Request 8 was interrupted to stop that fault.
PYTHONPATH=src:tools "$PYTHON" research/recommendation-reader-first-20260922/scripts/recover_reader_receipt.py --work "$WORK_ROOT" --code "$CODE_ROOT"
PYTHONPATH=src:tools "$PYTHON" -u research/recommendation-reader-first-20260922/scripts/run_trials.py --continue-interrupted --work "$WORK_ROOT" --code "$CODE_ROOT"

# No model call: carry the original unresolved H3 issue into normal handling.
"$PYTHON" research/recommendation-reader-first-20260922/scripts/prepare_unresolved_daily_handoff.py --work "$WORK_ROOT" --code "$CODE_ROOT"
# Request 24 stopped for quota with no review delivery; user requested recovery.
"$PYTHON" research/recommendation-reader-first-20260922/scripts/prepare_quota_resume.py --work "$WORK_ROOT" --code "$CODE_ROOT"
# Candidate 066129e, same writing prompts/samples, original SID; ledger starts at 25.
PYTHONPATH=src:tools "$PYTHON" -u research/recommendation-reader-first-20260922/scripts/run_trials.py --work "$WORK_ROOT" --code "$CODE_ROOT"

# Final checks, after 53 requests and all trials terminal. H3 failed before adoption.
"$PYTHON" research/recommendation-reader-first-20260922/scripts/check_daily_meaning.py --work "$WORK_ROOT" --code "$CODE_ROOT" --output "$EVIDENCE_ROOT/integration"
"$PYTHON" research/recommendation-reader-first-20260922/scripts/check_daily_page.py --root "$WORK_ROOT/daily-root" --output "$EVIDENCE_ROOT/integration"
# Production query ran twice: original disabled-text parser receipt preserved.
"$PYTHON" research/recommendation-reader-first-20260922/scripts/check_production.py --production "$PRODUCTION_ROOT" --evidence "$EVIDENCE_ROOT/integration"
"$PYTHON" research/recommendation-reader-first-20260922/scripts/check_production.py --production "$PRODUCTION_ROOT" --evidence "$EVIDENCE_ROOT/integration"
"$PYTHON" research/recommendation-reader-first-20260922/scripts/export_evidence.py --work "$WORK_ROOT" --production "$PRODUCTION_ROOT" --output "$EVIDENCE_ROOT"
"$PYTHON" research/recommendation-reader-first-20260922/scripts/summarize_requests.py --work "$WORK_ROOT" --output "$EVIDENCE_ROOT/run-statistics.json"
"$PYTHON" research/recommendation-reader-first-20260922/scripts/audit_actual_stages.py --work "$WORK_ROOT" --output "$EVIDENCE_ROOT/integration"
