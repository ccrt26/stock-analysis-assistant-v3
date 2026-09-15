#!/bin/bash
# 沿用已配置的静态发布仓库，只提交固定首页；push 失败可原命令重试。
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SOURCE="${1:-$REPO_ROOT/local_archive/forward_monitor/style-preview/prism-a2.html}"
SITE_DIR="${PRISM_SITE_DIR:-$HOME/prism-site}"
[ -f "$SOURCE" ] || { echo "找不到源页面" >&2; exit 1; }
[ -d "$SITE_DIR/.git" ] || { echo "发布仓库不存在" >&2; exit 1; }
grep -q 'id="snapshot"' "$SOURCE" || { echo "不是 A2 快照页面" >&2; exit 1; }
cd "$SITE_DIR"
[ "$(git branch --show-current)" = "main" ] || { echo "发布仓库不在 main，未推送" >&2; exit 1; }
cp "$SOURCE" public/index.html
if ! git diff --quiet HEAD -- public/index.html; then
  git add -- public/index.html
  git commit -q --only -m "Update research page" -- public/index.html
fi
# 即使页面没有差异，也可能存在上次已提交但推送失败的提交。
git push -q origin main
echo "public=pushed（已推送，公网是否可见需另行核对）"
