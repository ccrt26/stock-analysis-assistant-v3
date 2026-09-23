#!/usr/bin/env bash
# One historical author/check session. No production imports, automatic retry,
# model fallback, or repository test invocation. Run preparation is done separately.
set -eu

if [ "$#" -ne 2 ]; then
  printf 'Usage: RUN_ROOT=/absolute/prepared/run bash %s <300398.SZ|001378.SZ> <author|check>\n' "$0" >&2
  exit 2
fi
: "${RUN_ROOT:?Set RUN_ROOT to the prepared, non-production absolute run directory}"
case "$RUN_ROOT" in /*) ;; *) echo 'RUN_ROOT must be absolute' >&2; exit 2;; esac
case "$1" in 300398.SZ|001378.SZ) ;; *) echo 'Only the two fixed cases are allowed' >&2; exit 2;; esac
case "$2" in author|check) ;; *) echo 'Stage must be author or check' >&2; exit 2;; esac
command -v codex >/dev/null 2>&1 || { echo 'Codex CLI is not available; no model request made' >&2; exit 2; }

stage_dir="$RUN_ROOT/$1/$2"
[ -d "$stage_dir" ] || { echo 'Prepared stage directory missing' >&2; exit 2; }
stage_dir="$(cd "$stage_dir" && pwd -P)"
for required in prompt.md input/source-map.md input/research.json; do
  [ -s "$stage_dir/$required" ] || { printf 'Missing input: %s\n' "$required" >&2; exit 2; }
done
if [ "$2" = check ]; then
  [ -s "$stage_dir/input/article.md" ] || { echo 'Actual author output missing' >&2; exit 2; }
fi

# Existing directory, even from a failure, is intentionally not overwritten.
run_dir="$stage_dir/run"
mkdir "$run_dir" || { echo 'This stage was already started; do not resample automatically' >&2; exit 2; }
start="$(date +%s)"
printf 'model=gpt-6-sol\neffort=xhigh\nauth=chatgpt\n' > "$run_dir/requested-settings.txt"
printf 'configured settings are not independent proof of the served model\n' >> "$run_dir/requested-settings.txt"

if codex exec \
    --ignore-user-config \
    --model gpt-6-sol \
    -c 'model_provider="openai"' \
    -c 'forced_login_method="chatgpt"' \
    -c 'model_reasoning_effort="xhigh"' \
    -c 'project_doc_max_bytes=0' \
    -c 'web_search="disabled"' \
    --sandbox read-only \
    --cd "$stage_dir" \
    --skip-git-repo-check \
    --json \
    --output-last-message "$run_dir/result.md" \
    - < "$stage_dir/prompt.md" > "$run_dir/events.jsonl" 2> "$run_dir/stderr.log"; then
  status=0
else
  status=$?
fi
end="$(date +%s)"
elapsed=$((end - start))
printf '%s\n' "$status" > "$run_dir/exit-code.txt"
printf '%s\n' "$elapsed" > "$run_dir/elapsed-seconds.txt"
printf '%s\t%s\t%s\t%s\t%s\n' "$1" "$2" "$start" "$elapsed" "$status" >> "$RUN_ROOT/stages.tsv"
printf '%s %s: exit=%s elapsed=%ss output=%s\n' "$1" "$2" "$status" "$elapsed" "$run_dir/result.md"
if [ "$status" -ne 0 ]; then
  exit "$status"
fi
[ -s "$run_dir/result.md" ] || { echo 'CLI completed without a non-empty final delivery' >&2; exit 3; }
# Content validity and served-model evidence are checked by the coordinator,
# never inferred here from exit 0, a filename, or the requested settings.
