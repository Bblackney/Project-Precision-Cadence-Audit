#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# run_adherence.sh — Cadence Adherence DAILY run
# Invoked by launchd every day 6:00 AM (see com.clio.cadence-adherence.plist).
# Runs on this Mac (which has Salesloft API access), then commits + pushes the
# refreshed outputs. All output is appended to adherence_scheduler.log.
#
# PRIVACY: adherence_data.json / adherence_scores_master.csv contain REP-LEVEL
# performance data. Make sure the GitHub repo / Pages site is access-restricted
# before enabling the push below.
# ─────────────────────────────────────────────────────────────────────────────
set -uo pipefail

PROJECT_DIR="/Users/brettblackney/Documents/Claude/Project Precision/Cadence Performance Scorecard — Weekly Scoring"
LOG="$PROJECT_DIR/adherence_scheduler.log"
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"

cd "$PROJECT_DIR" || { echo "$(date '+%F %T') [ERR] cannot cd to project dir" >> "$LOG"; exit 1; }

echo "=================================================================" >> "$LOG"
echo "$(date '+%F %T') >> Starting daily adherence run" >> "$LOG"

# 1) Pull Salesloft, compute adherence, append CSV + JSON, update the actions ledger
python3 -u salesloft_adherence_scorer.py >> "$LOG" 2>&1
RC=$?
if [ "$RC" -ne 0 ]; then
  echo "$(date '+%F %T') [ERR] adherence scorer exited $RC — skipping git push" >> "$LOG"
  exit "$RC"
fi

# 1b) Render adherence.html from the fresh data (inlines adherence_data.json into the template)
python3 -u build_adherence_html.py >> "$LOG" 2>&1

# 2) Commit + push refreshed outputs (push failure is non-fatal).
#    Only stage files that exist (adherence.html + index.html are added once the
#    dashboard viewer / tab bar land).
find .git -name '*.lock' -delete 2>/dev/null
for f in adherence_scores_master.csv adherence_data.json adherence.html index.html; do
  [ -f "$f" ] && git add "$f" >> "$LOG" 2>&1
done
if git diff --cached --quiet; then
  echo "$(date '+%F %T') no output changes to commit" >> "$LOG"
else
  git commit -m "Cadence adherence update $(date +%Y-%m-%d)" >> "$LOG" 2>&1
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
