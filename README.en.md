# AI Policy Tracker

> Do mainstream AI products train their models on your data? A pure front-end tracker comparing the training-data policies of 47 AI products.

[![CI](https://github.com/838860610/ai-policy-tracker/actions/workflows/ci.yml/badge.svg)](https://github.com/838860610/ai-policy-tracker/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)

[English](README.en.md) | [简体中文](README.md)

## Live Demo

**<https://838860610.github.io/ai-policy-tracker/>** — no backend, no build step, works out of the box.

## What is this?

AI products increasingly reserve the right to use your chats, files, and generated content to train their models — sometimes by default, sometimes behind buried settings, sometimes with no way out at all. This project tracks and compares those policies in a single matrix so you can make informed choices.

The full comparison table (in Chinese) lives in [README.md](README.md); the interactive version with per-product detail pages is on the live site.

- **Coverage**: 47 products (43 Chinese + 4 global: ChatGPT, Claude, Gemini, Z.ai), 63 policy entries across consumer (ToC) and enterprise (ToB) tiers
- **Risk rating**: 🟢 low / 🟡 medium / 🔴 high, derived from four explicit criteria — default training opt-in, de-identification, retention period (≤30 days for green), and content copyright — with per-criterion evidence shown on each detail page
- **Evidence-based**: every conclusion cites the exact clause, with the source document/section and verification date

## Features

- **Comparison matrix**: grouped by vendor, filter by region / training usage / risk, searchable; consumer and enterprise versions are shown side by side
- **Detail pages**: key clauses quoted verbatim, opt-out instructions, data retention, an optional change timeline, and an auto-derived "green criteria" checklist
- **Update monitoring**: a Python script re-checks policy sources weekly (HTML/PDF text extraction, normalized text comparison, and conditional requests), covering product terms, version links, and registered supplementary sources. `requests` is the default; only targets configured with `fetch_method: "browser"` use Playwright, so browser rendering is not an automatic fallback and does not guarantee zero missed changes. On change, snapshots are archived under `site/generated/snapshots/`, `pending_verification.json` is updated, and the homepage warning comes from `update_status.json`
- **Fetch health, kept separate from policy changes**: every monitored target carries two orthogonal signals — `status` (did the policy text change?) and `health` (can this run's text be trusted?). A short body or a failed fetch never overwrites the stored snapshot; it only marks the target `degraded` / `no_baseline` / `blocked` in a dedicated queue (`site/generated/monitor_health.json`), which the homepage expands into a "degraded fetches" breakdown with reason, consecutive-run count and a suggested action. A target-level `changed` always has `health=ok`; `rebaselined` only accompanies `ok` or `suspicious`, never `changed`. Different targets of one product can require both content verification and fetch repair. Retrying a single target is cheap (`--only <pid>:<key>`), and fetch method / CSS selector / render wait / body threshold can be configured per target in `targets.main`, `versions.*` or `sources[]`
- **Accessibility**: keyboard navigation (Tab + Enter), ARIA labels
- **Pure front-end**: no backend, no build tools

## Run locally

```bash
git clone https://github.com/838860610/ai-policy-tracker.git
cd ai-policy-tracker

# One-shot: creates .venv, installs deps, opens your browser
./start.sh

# Or serve manually — note `--directory site`: the site lives in site/
python3 -m http.server 8080 --directory site

# For policy monitoring with browser-rendered pages:
.venv/bin/pip install -r requirements-browser.txt
.venv/bin/playwright install chromium
```

> Opening `index.html` directly from disk won't work — browsers block `fetch` on the `file://` protocol. Serve over HTTP.

## How it works

- **Data model**: `site/data/policies/{id}.json` is the single source of truth per product (name, company, per-version policies, `training_status`, registered `sources[]`, timeline, cited clauses). `site/data/products.json` only defines display order.
- **Scripts**: `scripts/validate_data.py` (schema checks), `scripts/gen_readme_table.py` (README table), `scripts/gen_data_bundle.py` (homepage bundle), `scripts/gen_docs.py` (documentation pages), `scripts/gen_product_pages.py` (product pages + sitemap), `scripts/gen_feed.py` (Atom feed), `scripts/gen_api.py` (read-only `/api/v1`), and `scripts/check_updates.py` (policy monitoring).
- **CI / automation**: `.github/workflows/ci.yml` runs on pull requests, main pushes, and manual dispatches. It runs the full regression suite, schema validation, and five `--check` commands (README / docs / product pages / feed / API). A green main push first syncs the latest main, then generates and revalidates those five artifact groups before committing only final differences; it never rebases stale generated files onto newer source data. `.github/workflows/monitor.yml` runs weekly (Mondays 09:00 Beijing time), generates `feed.xml`, optionally sends a webhook notification only for status written by the current run (silent when unconfigured; failures do not block commits), then rebases and commits status, snapshots, queues and feed. `.github/workflows/deploy.yml` publishes `site/` afterwards.
- **Front-end data**: the homepage reads `bundle.json` (falling back to the index and per-product JSON), `update_status.json` and `monitor_health.json`; it does not read the pending queue. Detail pages additionally read `data/policies/{id}.json`, `generated/pending_verification.json` and `generated/monitor_health.json` (falling back to status) for the policy body, pending-change diff card and fetch-health warning.
- **Local and partial runs**: CI skips `monitor_scope=local` targets but preserves their previous target state, adding only `skipped_this_run`; local runs preserve non-local targets in the same way. `--products` / `--only` merge previous state for unchecked targets and skip orphan-snapshot pruning. `--no-browser` preserves skipped browser targets while checking requests targets in mixed products; if every target needs a browser, previous target state is preserved and the product is `skipped` only when no previous state exists. None of these is a complete monitoring pass.
- **Layout**: everything that gets published lives under `site/` (that directory *is* the site root — `site/index.html` → `/`). Data sources and generated artifacts are split: `site/data/` (hand-maintained) vs `site/generated/` (produced by scripts, never edit by hand). `site/generated/` holds `bundle.json`, `update_status.json`, `pending_verification.json`, `monitor_health.json`, `snapshots/`, `api/v1/` and `og-card.png`; `site/feed.xml` is also generated.
- **Deployment**: GitHub Pages via Actions — set *Settings → Pages → Source* to **GitHub Actions** once. "Deploy from a branch" can only publish `/(root)` or `/docs`, so a custom `site/` directory requires the Actions route.

## Contributing

Policy updates and new products are very welcome! The full guide ([CONTRIBUTING.md](CONTRIBUTING.md)) is in Chinese, but it contains an **English quick start** section — in short: policy claims need an official source URL and a verification date; non-policy status claims must be labeled when they rely on media sources. Run the validators before submitting a PR. Found a mistake? [Open an issue](https://github.com/838860610/ai-policy-tracker/issues/new?template=data-correction.yml) with the official policy link.

Everyone participating in this project is expected to follow the [Code of Conduct](CODE_OF_CONDUCT.md). To report a security issue, please use a private channel as described in [SECURITY.md](SECURITY.md). Release history lives in [CHANGELOG.md](CHANGELOG.md).

## License

[MIT](LICENSE) © 2025-2026

## Disclaimer

This project is for reference only and does not constitute legal advice. Policies change frequently — always defer to the latest official terms. Verification dates are shown on each product's detail page.
