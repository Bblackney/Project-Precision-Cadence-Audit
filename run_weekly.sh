#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# run_weekly.sh — Cadence Performance Scorecard weekly run
# Invoked by launchd every Friday 5:00 PM (see com.clio.cadence-scorer.plist).
# Runs on this Mac (which has Salesloft API access), then commits + pushes the
# refreshed outputs. All output is appended to scheduler.log in the project dir.
# ─────────────────────────────────────────────────────────────────────────────
set -uo pipefail

PROJECT_DIR="/Users/brettblackney/Documents/Claude/Project Precision/Cadence Performance Scorecard — Weekly Scoring"
LOG="$PROJECT_DIR/scheduler.log"

# launchd runs with a minimal PATH — add common python3 / git locations.
# If you use pyenv/conda, prepend that python's bin dir here.
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"

cd "$PROJECT_DIR" || { echo "$(date '+%F %T') [ERR] cannot cd to project dir" >> "$LOG"; exit 1; }

echo "=================================================================" >> "$LOG"
echo "$(date '+%F %T') >> Starting weekly cadence run" >> "$LOG"

# 1) Score (fetch Salesloft, score, append CSV, regenerate index.html)
# -u = unbuffered stdout so progress lines stream to scheduler.log live (tail -f).
python3 -u salesloft_cadence_scorer.py >> "$LOG" 2>&1
RC=$?
if [ "$RC" -ne 0 ]; then
  echo "$(date '+%F %T') [ERR] scorer exited $RC — skipping git push" >> "$LOG"
  exit "$RC"
fi

# 2) Commit + push refreshed outputs (push failure is non-fatal)
# Clear any stale git locks first — a crashed/previous git op leaves a *.lock
# that would otherwise block this commit (and thus the weekly push).
find .git -name '*.lock' -delete 2>/dev/null
git add cadence_scores_master.csv index.html archive_confirmed.csv >> "$LOG" 2>&1
if git diff --cached --quiet; then
  echo "$(date '+%F %T') no output changes to commit" >> "$LOG"
else
  git commit -m "Cadence scorecard update $(date +%Y-%m-%d)" >> "$LOG" 2>&1
  if git push origin main >> "$LOG" 2>&1; then
    echo "$(date '+%F %T') OK pushed to origin/main" >> "$LOG"
  else
    echo "$(date '+%F %T') [WARN] git push to origin failed — outputs are committed locally" >> "$LOG"
  fi
  # Also push to the legacy repo (origin-old-personal) that bblackney.github.io/Project-Precision-Cadence-Audit/
  # still serves from, so that published URL doesn't drift out of sync with origin/main.
  if git remote get-url origin-old-personal >> "$LOG" 2>&1; then
    if git push origin-old-personal main >> "$LOG" 2>&1; then
      echo "$(date '+%F %T') OK pushed to origin-old-personal/main" >> "$LOG"
    else
      echo "$(date '+%F %T') [WARN] git push to origin-old-personal failed — outputs are committed locally" >> "$LOG"
    fi
  fi
fi

echo "$(date '+%F %T') OK Done" >> "$LOG"
