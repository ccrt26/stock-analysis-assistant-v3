# Cloudflare Pages Publish and Smoke

> **Current availability:** The receipt-scoped 15-file 2026-07-10 report package is live at `https://tl-quant-reports.pages.dev`. The one-command publish and an independent online password/date/content/redaction smoke both passed on 2026-07-11; last-known-good was saved and automatic publication is enabled. This proves publication mechanics, not report readability; the separate `REPORT-004` product Gate remains blocked.

The prepared package contains only the 14 files listed by the activated receipt plus `functions/_middleware.ts`; historical report files are preserved locally but excluded. Manual publish is allowed only after explicit approval and after the local production run has completed successfully.

## Approval Gates

- Do not deploy Cloudflare Pages without explicit approval.
- Do not run a real production job to create a fresh artifact without explicit approval.
- Do not print, copy, commit, or log credential values used for Cloudflare Pages or report authentication.

## Phase 2 One-Command Publish

Phase 2 adds a local one-command publish flow. The first real Cloudflare deployment still requires explicit approval. After the first one-command publish succeeds and online smoke passes, the system automatically enables full auto publish for later successful daily production runs.

第一次发布成功并通过 online smoke 后，后续成功的每日生产运行会自动转为全自动发布。

Use the simple entrypoint:

```bash
stock-analyzer-publish
```

The command publishes the current trading day's successful report when recommendations are greater than zero. It does not publish non-trading days, failed production runs, or zero-recommendation reports.

The command must:

- rebuild `dist/pages` before upload;
- deploy with Wrangler;
- run online smoke;
- save the successful artifact as last known good;
- roll back to last known good if the newly deployed site fails smoke;
- write local publish status and a simple local status page;
- avoid printing or logging credentials.

Do not print, copy, commit, or log Cloudflare token, report password, report session secret, Supabase service-role key, Tushare token, or `.env.local` contents.

不要打印、复制、提交或记录 Cloudflare token、报告密码、报告会话密钥、Supabase service-role key、Tushare token 或 `.env.local` 内容。

## Prepare Artifact

After an approved successful production run, `dist/pages` should already be prepared. To prepare it manually after approval:

```bash
export PROJECT_ROOT="$PWD"
PYTHONPATH=src .venv/bin/python -m stock_analyzer ops prepare-deploy --output-dir dist/pages
```

The artifact must include the report files and `functions/_middleware.ts`. It must not include local env files, Git metadata, virtualenvs, local warehouse data, local archive data, logs, raw caches, or `.superpowers`.

## Manual Publish

Use this lower-level fallback only when the Phase 2 one-command publish flow is unavailable or explicitly bypassed. Run the manual Cloudflare Pages deploy only after approval:

```bash
npx wrangler pages deploy dist/pages --project-name stock-analysis-assistant-v3
```

This command intentionally uses manual `wrangler pages deploy dist/pages`. Phase 2 makes `stock-analyzer-publish` the preferred path, while direct Wrangler deploy remains a fallback for approved operator intervention.

## Online Smoke

After a manual deployment, run the smoke command from the project root. Provide the report password through the approved local secret source and reference its environment variable name with `--password-env`.

```bash
export PROJECT_ROOT="$PWD"
PYTHONPATH=src .venv/bin/python -m stock_analyzer ops smoke-report-site --url https://YOUR-PAGES-DOMAIN --password-env REPORT_PASSWORD --expected-trade-date YYYY-MM-DD
```

The smoke check must verify:

- Anonymous access to `/` redirects to `/login`.
- `/login` is reachable.
- The approved password opens the report.
- The homepage report date is the intended trade date.
- The page does not contain fixture or sample content.
- The page does not expose sensitive variable names or credential-looking values.
- Failures include a redacted fix suggestion.

## Failure Handling

If smoke fails, do not re-deploy blindly. Keep the last known good online report, inspect the failure, fix locally, prepare `dist/pages` again, and request approval before another manual deployment.
