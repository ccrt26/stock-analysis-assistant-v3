# Cloudflare Pages Manual Publish and Smoke

Phase 1 prepares a Cloudflare Pages artifact at `dist/pages`, but it does not upload it. Manual publish is allowed only after explicit approval and after the local production run has completed successfully.

## Approval Gates

- Do not deploy Cloudflare Pages without explicit approval.
- Do not run a real production job to create a fresh artifact without explicit approval.
- Do not print, copy, commit, or log credential values used for Cloudflare Pages or report authentication.

## Prepare Artifact

After an approved successful production run, `dist/pages` should already be prepared. To prepare it manually after approval:

```bash
PROJECT_ROOT=/Users/ccrt/股票分析助手 PYTHONPATH=src .venv/bin/python -m stock_analyzer ops prepare-deploy --output-dir dist/pages
```

The artifact must include the report files and `functions/_middleware.ts`. It must not include local env files, Git metadata, virtualenvs, local warehouse data, local archive data, logs, raw caches, or `.superpowers`.

## Manual Publish

Run the manual Cloudflare Pages deploy only after approval:

```bash
npx wrangler pages deploy dist/pages --project-name stock-analysis-assistant-v3
```

This command intentionally uses manual `wrangler pages deploy dist/pages`. Phase 2 will make Cloudflare publish automation mandatory, but Phase 1 must not auto-upload.

## Online Smoke

After a manual deployment, run the smoke command from the project root. Provide the report password through the approved local secret source and reference its environment variable name with `--password-env`.

```bash
PROJECT_ROOT=/Users/ccrt/股票分析助手 PYTHONPATH=src .venv/bin/python -m stock_analyzer ops smoke-report-site --url https://YOUR-PAGES-DOMAIN --password-env REPORT_PASSWORD
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
