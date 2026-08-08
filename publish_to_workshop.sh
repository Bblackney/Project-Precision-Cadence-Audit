#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# publish_to_workshop.sh — publish freshly-scored dashboards to the Clio Workshop
# app (clio-internal/cadence-dashboards) so Workshop redeploys.
#
# The scoring stays on this Mac (the daily adherence run is ~5h; the weekly full
# scoring runs Friday). This script only PUBLISHES the resulting HTML: it copies
# the given files into the Workshop repo's public/ (nginx doc root), then lands
# them on main via an AUTO-MERGING PR — main is PR-gated by an org ruleset, so a
# direct push is rejected. It runs as you (a human token), so the required
# validate.yml check triggers normally and the PR merges unattended
# (required_approving_review_count=0, no CODEOWNERS). The merge redeploys the app.
#
# Usage:  publish_to_workshop.sh index.html adherence.html ...
#         (each arg is a file in PROJECT_DIR to copy into the repo's public/)
#
# Auth: uses gh (GitHub CLI). Interactively gh uses the macOS keyring. Under
# launchd there may be no keychain access — in that case put a token in
# github_token.json ({"token":"gh?_..."}) in PROJECT_DIR (gitignored) and this
# script exports it as GH_TOKEN so gh + git work without the keyring.
# ─────────────────────────────────────────────────────────────────────────────
set -uo pipefail

PROJECT_DIR="/Users/brettblackney/Documents/Claude/Project Precision/Cadence Performance Scorecard — Weekly Scoring"
CLONE="$HOME/clio-workshop/cadence-dashboards"
REPO="clio-internal/cadence-dashboards"
LOG="$PROJECT_DIR/publish_workshop.log"

# gh lives in ~/.local/bin; launchd starts with a minimal PATH.
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"

log(){ echo "$(date '+%F %T') $*" | tee -a "$LOG"; }

# Token fallback for launchd (no keychain access).
if [ -z "${GH_TOKEN:-}" ] && [ -f "$PROJECT_DIR/github_token.json" ]; then
  GH_TOKEN="$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1])).get("token",""))' "$PROJECT_DIR/github_token.json" 2>/dev/null)"
  export GH_TOKEN
fi

[ "$#" -ge 1 ] || { log "[ERR] no files given to publish"; exit 2; }
command -v gh >/dev/null 2>&1 || { log "[ERR] gh not found on PATH"; exit 1; }
[ -d "$CLONE/.git" ] || { log "[ERR] clone missing at $CLONE — run: gh repo clone $REPO \"$CLONE\""; exit 1; }

# Refresh the clone to a clean main and prune any stale auto/ branches.
git -C "$CLONE" fetch --quiet origin || { log "[ERR] git fetch failed (auth?)"; exit 1; }
git -C "$CLONE" checkout --quiet -B main origin/main || { log "[ERR] checkout main failed"; exit 1; }
git -C "$CLONE" reset --hard --quiet origin/main
for b in $(git -C "$CLONE" branch --format='%(refname:short)' | grep '^auto/publish-' 2>/dev/null); do
  git -C "$CLONE" branch -D "$b" >/dev/null 2>&1 || true
done

# Stage the requested files into public/.
mkdir -p "$CLONE/public"
for f in "$@"; do
  src="$PROJECT_DIR/$f"
  if [ ! -f "$src" ]; then log "[WARN] $f not found in project — skipping"; continue; fi
  cp "$src" "$CLONE/public/$f"
done

# A publish marker at repo root gives an audit trail (and guarantees a diff so a
# refresh always lands even if the HTML bytes happen to be identical).
date '+%F %T %Z' > "$CLONE/LAST_PUBLISHED.txt"

cd "$CLONE" || { log "[ERR] cannot cd $CLONE"; exit 1; }
git add public/ LAST_PUBLISHED.txt >/dev/null 2>&1
if git diff --cached --quiet; then
  log "no changes to publish (nothing staged)"; exit 0
fi

STAMP="$(date +%Y%m%d-%H%M%S)"
BR="auto/publish-$STAMP"
DATE="$(date +%F)"
git checkout -q -b "$BR"
git -c user.name="Brett Blackney" -c user.email="brett.blackney@clio.com" \
    commit -q -m "Publish dashboards $DATE"
git push -q origin "$BR" || { log "[ERR] git push failed (auth?)"; exit 1; }

gh pr create --repo "$REPO" --base main --head "$BR" \
  --title "Publish dashboards $DATE" \
  --body "Automated publish from the scoring host ($(hostname -s)). Auto-merges once the required validation check passes." \
  >>"$LOG" 2>&1 || { log "[ERR] gh pr create failed"; git push -q origin --delete "$BR" >/dev/null 2>&1 || true; exit 1; }

log "opened PR from $BR — waiting for required check to pass…"
MSS=""
for i in $(seq 1 40); do
  sleep 15
  STATES=$(gh pr view "$BR" --repo "$REPO" --json statusCheckRollup --jq '[.statusCheckRollup[]?|(.conclusion // .status)]|join(",")' 2>/dev/null)
  MSS=$(gh pr view "$BR" --repo "$REPO" --json mergeStateStatus --jq .mergeStateStatus 2>/dev/null)
  log "  checks=[${STATES:-none}] mergeState=$MSS"
  case "$STATES" in *FAILURE*|*CANCELLED*|*TIMED_OUT*|*ERROR*|*STALE*) log "[ERR] required check failed"; exit 1;; esac
  [ "$MSS" = "CLEAN" ] && break
done
if [ "$MSS" != "CLEAN" ]; then
  log "[ERR] PR not mergeable in time (mergeState=$MSS)"; exit 1
fi

gh pr merge "$BR" --repo "$REPO" --squash --delete-branch >>"$LOG" 2>&1 \
  && log "OK published — merged to main; Workshop will redeploy." \
  || { log "[ERR] merge failed"; exit 1; }
