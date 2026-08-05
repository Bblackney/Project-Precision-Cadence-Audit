#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# run_archive_autosave.sh — Friday 4:00 PM Archive-Confirmed autosave.
# Invoked by launchd (see com.clio.cadence-archive-autosave.plist), one hour
# before com.clio.cadence-scorer's 5:00 PM weekly run.
#
# Drives Chrome via AppleScript (archive_autosave.py) to read whatever's
# currently ticked on the live dashboard and merge it into
# archive_confirmed.csv, then commits+pushes that file directly as a backup
# — in case the 5pm run doesn't happen that week (e.g. Mac asleep), this
# week's confirmations are still captured and pushed on their own.
#
# ONE-TIME SETUP REQUIRED — see WORKFLOW.md:
#   1. Chrome: View/Chrome menu -> Developer -> "Allow JavaScript from Apple
#      Events" must be checked.
#   2. Run this once manually first so macOS's Automation permission prompt
#      can be approved by you — it can't be approved unattended.
# ─────────────────────────────────────────────────────────────────────────────
set -uo pipefail

PROJECT_DIR="/Users/brettblackney/Documents/Claude/Project Precision/Cadence Performance Scorecard — Weekly Scoring"
LOG="$PROJECT_DIR/archive_autosave.log"

export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"

cd "$PROJECT_DIR" || { echo "$(date '+%F %T') [ERR] cannot cd to project dir" >> "$LOG"; exit 1; }

python3 -u archive_autosave.py
RC=$?
if [ "$RC" -ne 0 ]; then
  echo "$(date '+%F %T') [ERR] archive_autosave.py exited $RC — skipping git push" >> "$LOG"
  exit "$RC"
fi

# Clear any stale git locks first (same pattern as run_weekly.sh).
find .git -name '*.lock' -delete 2>/dev/null
git add archive_confirmed.csv >> "$LOG" 2>&1
if git diff --cached --quiet; then
  echo "$(date '+%F %T') no archive changes to commit" >> "$LOG"
else
  git commit -m "Archive-confirmed autosave $(date +%Y-%m-%d)" >> "$LOG" 2>&1
  if git push origin main >> "$LOG" 2>&1; then
    echo "$(date '+%F %T') OK pushed to origin/main" >> "$LOG"
  else
    echo "$(date '+%F %T') [WARN] push to origin/main failed (non-fatal — local commit still stands)" >> "$LOG"
  fi
  if git remote get-url origin-old-personal >/dev/null 2>&1; then
    if git push origin-old-personal main >> "$LOG" 2>&1; then
      echo "$(date '+%F %T') OK pushed to origin-old-personal/main" >> "$LOG"
    else
      echo "$(date '+%F %T') [WARN] push to origin-old-personal/main failed (non-fatal)" >> "$LOG"
    fi
  fi
fi
echo "$(date '+%F %T') OK Done" >> "$LOG"
