# Cadence Performance Scorecard — Workflow (current)

_Last updated: 2026-06-11. Supersedes the SFDC + CSV-upload workflow, `SKILL_cadence_scoring_updated.md`, and the Cowork scheduled task `cadence-api-weekly-scoring`._

## What it does

Every **Friday 5:00 PM**, a launchd job on Brett's Mac:

1. Pulls live data from the **Salesloft API (v2)**
2. Scores every **active, team** BDR/SDR cadence (model v2.1)
3. Appends a dated snapshot to `cadence_scores_master.csv` (historical, append-only)
4. Regenerates `index.html` (dashboard — all runs, filterable by date)
5. `git commit` + `push` both files to GitHub

No CSV upload, no SFDC, no manual steps. Runs unattended.

## Scheduler (launchd — local, not Cowork)

- Agent label: `com.clio.cadence-scorer`
- Schedule: Friday 5:00 PM (plist `Weekday 5`, `Hour 17`)
- Plist (active): `~/Library/LaunchAgents/com.clio.cadence-scorer.plist`
- Files in the project folder:
  - `run_weekly.sh` — wrapper launchd runs: score → commit → push
  - `salesloft_cadence_scorer.py` — the scorer
  - `build_connected_cache.py` — ONE-TIME resumable backfill of the connected-calls cache
  - `connected_calls_cache.json` — all-time per-cadence connected counts + cursor (gitignored)
  - `com.clio.cadence-scorer.plist` — source plist (installer copies it into LaunchAgents)
  - `install_scheduler.sh` — one-time installer
- Logs: `scheduler.log` (run output), `launchd.out.log` / `launchd.err.log` (launchd-level)

### Manual run / test
```
launchctl start com.clio.cadence-scorer
tail -f scheduler.log
```
Or directly: `cd <project> && bash run_weekly.sh`

### Reinstall / change schedule
Edit `com.clio.cadence-scorer.plist`, then run `bash install_scheduler.sh`.

## Data source — Salesloft API v2

- Cadences: `/v2/cadences?status[]=active` (active only)
- Filter: `team_cadence == true` (personal copies excluded)
- Per-cadence stats: `/v2/cadence_stats/:id` (emails, opens, replies, calls, meetings, people_acted_on)
- Connected calls: `disposition[]=Call - Connected` from `/v2/activities/calls`, accumulated in `connected_calls_cache.json` (all-time per-cadence counts). Backfilled ONCE via `build_connected_cache.py` (~1.4M records, resumable, cursor-based); each weekly run adds only the delta since the saved cursor. `connect_rate = cached connected ÷ lifetime calls_count` (both all-time, so the denominator matches).
- Credentials: `salesloft_credentials.json` (gitignored — never commit)

Rates:
- `open_rate    = viewed_count    / sent_emails_count × 100`
- `reply_rate   = replied_count   / sent_emails_count × 100`
- `meeting_rate = meetings_booked / sent_emails_count × 100`
- `connect_rate = connected_calls / calls_count × 100`

## Model detection & exclusion

`cadence_name` (case-insensitive): contains BDR → BDR; contains SDR → SDR; neither → excluded.
Also excluded: archived cadences, non-team (personal) cadences, and any cadence whose name contains **EMEA / CAN / APAC** (region exclusion, for now — whole-word match).

## Scoring model v2.1 (both models max 100 pts; no skip rate)

Sample handling: `people_acted_on_count == 0` → **NO DATA**. `1–99` → **LOW SAMPLE** (scored & shown, not bucketed). `≥100` → bucketed KEEP/REVIEW/ARCHIVE by score. (`low_sample` column still written: `True` when <100.)

**BDR:** Meeting ≥15→35, ≥5→20, <5→0 | Reply ≥10→30, ≥5→22, ≥2→13, <2→0 | Connect ≥15→20, ≥7→13, ≥3→6, <3→0 | Open ≥50→15, ≥35→10, ≥20→5, <20→0

**SDR:** Meeting ≥10→35, ≥5→20, ≥2→13, <2→0 | Reply ≥3→30, ≥1→22, <1→0 | Connect ≥15→20, ≥7→13, ≥3→6, <3→0 | Open ≥35→15, ≥25→10, ≥15→5, <15→0

Verdicts (≥100 people only): ≥75 KEEP | 50–74 REVIEW | <50 ARCHIVE. Cadences with <100 people → LOW SAMPLE; 0 people → NO DATA (neither is bucketed).

## Master CSV schema (append-only — never overwrite)

```
run_date, period_label, cadence_id, cadence_name, score, verdict, model_applied,
meeting_rate, reply_rate, connect_rate, open_rate, skip_rate (always 0.0),
steps_completed (= people_acted_on_count), emails_sent, owner,
pts_meeting_rate, pts_reply_rate, pts_connect_rate, pts_open_rate,
pts_skip_rate (always 0), low_sample, created_at
```

## Baseline reset (2026-06-10)

The master CSV was reset to a clean Salesloft-era baseline. Pre-2026-06-10 data (old SFDC
scorer runs, partly malformed) is preserved in `*.BACKUP_*.csv` / `*.BACKUP_*.html` in the
project folder (gitignored). The historical trend builds forward from the first clean Salesloft run.

## Troubleshooting

- **`scheduler.log` not created / "Operation not permitted":** macOS Full Disk Access. The project
  lives under `~/Documents` (a protected folder) and launchd jobs don't inherit Terminal's access.
  Grant FDA to `/bin/bash` (System Settings → Privacy & Security → Full Disk Access → + → ⌘⇧G →
  `/bin/bash`), then reload: `launchctl unload …plist && launchctl load -w …plist`.
- **`git push` fails:** the remote uses an embedded GitHub token (rotate to a credential helper when
  convenient). `run_weekly.sh` treats push failure as non-fatal — outputs still commit locally.
- **Stale git locks** (`index.lock` / `HEAD.lock`): `rm -f .git/*.lock` then retry.

## Deprecated — do not use

- Cowork scheduled task `cadence-api-weekly-scoring` — **DISABLED** (sandbox can't reach the API).
- `sfdc_cadence_scorer.py`, `run_sfdc_score_*.py`, `attribution_cache/`, `build_attribution_cache.py`, `update_attribution_cache.py` — old SFDC pipeline.
- `SKILL_cadence_scoring_updated.md`, `sfdc_project_instructions.md` — old docs.
