# Cadence Performance Scorecard — Clio Workshop deploy bundle

This folder is the **static site** to deploy to the Clio Internal Workshop.
It is self-contained: no CDN, no external scripts, no runtime `fetch()` — all
data is baked into the HTML by the project's Python build scripts.

## What's here (the entire app)
- `index.html` — **entry point** (Cadence Scorecard). ~19 MB (data embedded).
- `adherence.html` — Cadence Adherence dashboard.
- `pilot_comparison.html` — Pilot Comparison dashboard.

The three pages cross-link via a top nav (`index` / `adherence` / `pilot_comparison`),
and every link resolves inside this folder — nothing else is required to render.

## Deploy — GitHub / Claude Code path (chosen)
In an **interactive** Claude Code terminal (`claude` in Terminal.app):
1. `/plugin marketplace add clio/claude-plugins`
2. Install the `clio-workshop` plugin (`/plugin`).
3. Run `/deploy` and point it at this folder as the static site (entry `index.html`).
   Apps live in the `clio-internal` GitHub org; access is Okta-gated.

## Deploy — static upload path (fallback, no plugin)
Go to https://create.clio.app/, name the app, upload the 3 files in this folder,
click Deploy. Home page must be `index.html` (it is).

## Data classification (Workshop rule) — OK
Content is Clio's own sales/cadence metrics = **corporate/customer data (allowed)**.
No **client data** (info about customers' clients) is present. Do not add any.

## Important: this is a SNAPSHOT
Data is current as of **2026-08-07**. The weekly re-scoring runs from local
Python scripts + launchd on Brett's Mac (`run_weekly.sh`, `run_adherence.sh`, the
`com.clio.*.plist` jobs) — that pipeline is **not** part of this bundle and does
**not** run on Workshop. To keep the hosted copy fresh you must either
re-deploy after each local run, or move the pipeline into the app as a scheduled
GitHub Action. Nothing in this bundle contains secrets (SalesLoft/Slack
credentials load from gitignored files / env vars, never committed).
