# Scheduled scoring — GitHub Actions

These workflows move the weekly/daily scoring off Brett's Mac (launchd) and into
GitHub Actions, so the app hosted on **Clio Workshop** stays fresh on its own.
On Workshop, a push to `main` auto-redeploys — so each run's commit re-publishes.

| Workflow | Replaces | Schedule (local intent) | Regenerates |
|---|---|---|---|
| `weekly-scorecard.yml` | `run_weekly.sh` / com.clio.cadence-scorer | **Fri 17:00** America/Vancouver | `index.html` **and** `pilot_comparison.html` (+ CSV/JSON caches) |
| `daily-adherence.yml` | `run_adherence.sh` / com.clio.cadence-adherence | **Daily 06:00** America/Vancouver | `adherence.html` (+ CSV/JSON) |

Pure Python stdlib — no `requirements.txt`. Runs on Python 3.11 (matches local).

## 1. Required secret — do this once in the deployed repo
Both workflows read the SalesLoft token from `${{ secrets.SALESLOFT_API_TOKEN }}`
(the scorers already prefer the `SALESLOFT_API_TOKEN` env var over the local
`salesloft_credentials.json`, which stays gitignored and never ships).

In the `clio-internal` repo GitHub UI:
`Settings → Secrets and variables → Actions → New repository secret`
- **Name:** `SALESLOFT_API_TOKEN`
- **Value:** your `v2_ak_...` token

> Enter it in GitHub's UI yourself — don't paste the token into chat or commit it.

## 2. Data files must be committed to the deployed repo
The scorers **append** to history files, so these must exist in the repo for the
Actions to build on (they travel with the migration to `clio-internal`):
`cadence_scores_master.csv`, `adherence_scores_master.csv`, `adherence_data.json`,
`pilot_legacy_snapshot.json`, `pilot_period_metrics.json`, `step_stats_cache.json`,
`archive_confirmed.csv`, `actions_ledger.json`, and the templates
(`adherence_template.html`). Note: `connected_calls_cache.json` /
`step_call_metrics_cache.json` are gitignored, so `build_step_stats_cache.py`
starts cold in CI and does a fuller fetch — non-fatal, just slower.

## 3. DST caveat (GitHub cron is UTC, no DST)
The crons are set to match Pacific during **PDT (summer)**:
- Weekly `0 0 * * 6` → Sat 00:00 UTC = Fri 17:00 PDT / 16:00 PST
- Daily `0 13 * * *` → 13:00 UTC = 06:00 PDT / 05:00 PST

In winter each run lands one hour earlier local. If you need an exact local hour
year-round, schedule BOTH candidate UTC times and gate with a guard step, e.g.:

```yaml
on:
  schedule:
    - cron: "0 13 * * *"   # 06:00 PDT
    - cron: "0 14 * * *"   # 06:00 PST
jobs:
  adherence:
    steps:
      - name: Only continue at 06:00 America/Vancouver
        run: |
          H=$(TZ=America/Vancouver date +%H)
          [ "$H" = "06" ] || { echo "Not 06:00 local ($H) — skipping."; exit 0; }
```

## 4. Not portable: the Friday 2pm archive autosave
`run_archive_autosave.sh` / `archive_autosave.py` drive **Chrome via AppleScript**
on the Mac to scrape whatever's ticked on the live dashboard. That can't run on a
headless Linux runner. Options:
- **Leave it local** (keep just that one launchd job on the Mac), or
- **Rework it** so "archive confirmed" writes server-side in the Workshop app
  instead of being scraped from the browser (better long-term; removes the Mac
  dependency entirely).

## 5. No feedback loop
Both workflows trigger on `schedule` + manual `workflow_dispatch` only — never on
`push` — so the bot's own commits don't retrigger them. Each also has a
`concurrency` group so overlapping runs can't collide on the git push.

## Turning off the Mac
Once these Actions are verified green in the deployed repo, unload the local
launchd jobs so you're not double-writing:
```bash
launchctl unload ~/Library/LaunchAgents/com.clio.cadence-scorer.plist
launchctl unload ~/Library/LaunchAgents/com.clio.cadence-adherence.plist
# (keep com.clio.cadence-archive-autosave loaded if you go with "leave it local")
```
