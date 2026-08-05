# Cadence Performance Scorecard — Workflow (current)

_Last updated: 2026-06-11. Supersedes the SFDC + CSV-upload workflow, `SKILL_cadence_scoring_updated.md`, and the Cowork scheduled task `cadence-api-weekly-scoring`._

## What it does

Every **Friday 5:00 PM**, a launchd job on Brett's Mac:

1. Pulls live data from the **Salesloft API (v2)**
2. Scores every **active, team** BDR/SDR cadence (model v2.1)
3. Appends a dated snapshot to `cadence_scores_master.csv` (historical, append-only)
4. Regenerates `index.html` (dashboard — all runs, filterable by date)
5. Regenerates `pilot_comparison.html` (new pilot cadence vs. its retired legacy predecessor — see "Pilot Comparison tab" below)
6. `git commit` + `push` the outputs to GitHub

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

## Pilot Comparison tab (added 2026-08-05)

A third nav link/page, `pilot_comparison.html`, sits alongside `index.html` and
`adherence.html`. For each Pilot cadence that replaced an older, now-retired
cadence, it shows the **New** cadence's live metrics (recomputed every Friday,
same scoring model as the main scorecard) with the **Legacy** cadence's metrics
directly below it, plus ▲/▼ delta annotations next to the New row's numbers
(New − Legacy: percentage points for rates, points for Score, % relative change
for People). Filters: Run Date (New side only), Team (BDR Strategic / SDR),
Search.

- The pilot↔legacy pair mapping lives in `PILOT_LEGACY_PAIRS` in
  `salesloft_cadence_scorer.py` — edit there if pilot/legacy IDs change. One pair
  (`Webinar Demo`) has `legacy_id: None` — it's a brand-new cadence with no
  predecessor, so the tab shows it with no legacy row/delta.
- **Legacy side is a locked, one-time snapshot** — those cadences are retired
  and get no new activity, so there's no reason to ever refetch them. Pulled by
  `build_pilot_legacy_snapshot.py` (needs Salesloft API access — run on Brett's
  Mac, same as the weekly job; the Cowork sandbox can't reach the API) into
  `pilot_legacy_snapshot.json`. **Run this once** before the tab shows any
  legacy rows/deltas:
  ```
  cd <project> && python3 build_pilot_legacy_snapshot.py
  ```
  It's safe to rerun (idempotent overwrite) but should never need to be, since
  the legacy cadences don't change. `pilot_legacy_snapshot.json` is **not**
  gitignored — it's the permanent baseline, committed like `archive_confirmed.csv`.
- The weekly scorer reads that snapshot (if present) and regenerates
  `pilot_comparison.html` on every run — no separate schedule needed. If the
  snapshot file is missing, the page still renders (New rows only, with a
  banner explaining the missing legacy baseline) instead of failing the run.
- `run_weekly.sh` now also `git add`s `pilot_comparison.html` and
  `pilot_legacy_snapshot.json`.

## Archive-Confirmed autosave (Friday 2:00 PM, Brett's machine only)

The dashboard's "Archive Confirmed" checkboxes are per-cadence, browser-local by default
(`localStorage`) and only become durable/shared once written to `archive_confirmed.csv`
(read back by the scorer on every run so ticked boxes survive the regen for everyone).
Brett is the only person who can write that file directly, since it lives in this git repo
on his Mac — anyone else's "Save" click writes to a disconnected local file on *their* own
machine instead (see the red button's tooltip, and it's now positioned at the far right of
the toolbar since it's only relevant to him). A 2:00 PM Friday job — three hours before the
5:00 PM scorer run — automates Brett's own save so he doesn't have to remember to click it:

- Agent label: `com.clio.cadence-archive-autosave`
- Schedule: Friday 2:00 PM (plist `Weekday 5`, `Hour 14`) — deliberately well before the 5pm
  scorer run, so this week's confirmations are baked into that run's regenerated `index.html`
  and swept into its own `git add`.
- Files: `archive_autosave.py` (drives Chrome via AppleScript to read the live dashboard's
  confirmed state and merge it into `archive_confirmed.csv`), `run_archive_autosave.sh`
  (wrapper: run the script, then commit+push `archive_confirmed.csv` directly as a backup
  in case that week's 5pm run doesn't happen), `com.clio.cadence-archive-autosave.plist`,
  `install_archive_autosave_scheduler.sh`.
- Logs: `archive_autosave.log` (script output), `archive_autosave.launchd.out.log` /
  `.err.log` (launchd-level).

**Important implementation detail:** the JS injected via AppleScript's `execute javascript`
runs in an isolated world that shares the page's `document` (DOM) and `localStorage` but
NOT its top-level `var`/`function` declarations. So it can't call the page's own
`loadLS()`/`confirmedCids()`/`archiveLineFor()`/`CSV_FIELDS`/`ALL_ROWS` — it re-derives
everything from `document.querySelectorAll` + `localStorage` directly instead. If this script
ever needs editing, don't "simplify" it back to calling the page's helpers — that's exactly
what caused `ReferenceError: loadLS is not defined` the first time this was built.

**One-time setup (do this before installing):**
1. In Chrome: View menu (or Chrome menu) → Developer → check **"Allow JavaScript from Apple
   Events"**. Without this, `execute javascript` from AppleScript is refused. **This setting
   does NOT persist across a Chrome restart** — it resets to off every time Chrome fully
   quits and relaunches (crash, auto-update, manual quit). Re-check it any time
   `archive_autosave.log` shows "Executing JavaScript through AppleScript is turned off."
2. (Optional but recommended) Slack failure alerts: create a Slack Incoming Webhook
   (api.slack.com/apps → your app → Incoming Webhooks → Add New Webhook to Workspace → pick a
   channel/DM) and save the URL into a new file `slack_webhook.json` in this folder:
   `{"webhook_url": "https://hooks.slack.com/services/…"}`. This file is gitignored — never
   commit it. Without it, failures still log to `archive_autosave.log` but nothing pings
   Brett, so he won't find out unless he checks manually.
3. Install: `bash install_archive_autosave_scheduler.sh`
4. Test manually while logged in and watching: `launchctl start com.clio.cadence-archive-autosave`
   then `tail -f archive_autosave.log`. The first run needs a human to approve macOS's
   "Terminal wants to control Google Chrome" Automation prompt (System Settings → Privacy &
   Security → Automation) — it cannot be approved unattended, so don't trust the Friday
   schedule until one manual run has succeeded end-to-end.

Reliability note: this has the same fragility as the 5pm scorer job — it needs Brett's Mac
awake (not asleep/off) at 2pm Friday, and Chrome installed with a normal (non-Incognito)
window with the "Allow JavaScript from Apple Events" box freshly re-checked since its last
restart. If the Mac was off/asleep, or that Chrome setting reset itself, this simply doesn't
fire/succeed that week; nothing catches up retroactively (see [[cadence-scorecard-ops]]
memory on the missed 7/24 and 7/31 scorer runs for the same underlying limitation on the
Mac-asleep case). The Slack alert (if configured) is the safety net for this — on failure,
Brett gets pinged to click the manual Save button himself that week. Brett accepted the
Mac-awake/Chrome-setting tradeoff over the more robust "auto-save-on-every-checkbox-click"
alternative because the archive-confirm workflow is single-curator (his machine only)
regardless of mechanism, so a once-a-week sweep on his own machine is simpler.

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
Also excluded: archived cadences, non-team (personal) cadences, and region cadences (for now): name contains **EMEA / CAN / APAC** (whole word) or **starts with CAD**.

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
- **`archive_autosave.log` shows "Executing JavaScript through AppleScript is turned off":**
  Chrome's "Allow JavaScript from Apple Events" setting (View/Chrome menu → Developer) isn't
  checked right now. Re-check it — remember it resets every time Chrome restarts, so this is
  the most common failure. A Slack alert should have pinged Brett if `slack_webhook.json` is
  configured; if not, this can fail silently for weeks.
- **`archive_autosave.log` shows some other "osascript failed" error:** macOS's Automation
  permission for Terminal→Chrome was never granted or was revoked. Run
  `launchctl start com.clio.cadence-archive-autosave` manually while logged in to re-trigger
  the permission prompt.
- **`archive_autosave.log` shows "X is not defined" (e.g. `loadLS is not defined`):** someone
  edited `JS_SNIPPET` in `archive_autosave.py` to call the page's own JS functions again. See
  the "Important implementation detail" note above — the isolated-world JS can only use
  `document` and `localStorage`, not the page's `var`/`function` globals.
- **Archive autosave silently does nothing on Fridays:** check the Mac wasn't asleep/off at
  2pm — same as the scorer job, this can't run if nobody's logged in / the machine is off.

## Deprecated — do not use

- Cowork scheduled task `cadence-api-weekly-scoring` — **DISABLED** (sandbox can't reach the API).
- `sfdc_cadence_scorer.py`, `run_sfdc_score_*.py`, `attribution_cache/`, `build_attribution_cache.py`, `update_attribution_cache.py` — old SFDC pipeline.
- `SKILL_cadence_scoring_updated.md`, `sfdc_project_instructions.md` — old docs.
