#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# install_scheduler.sh — one-time installer for the weekly cadence scorer.
# Run ONCE in Terminal:
#   bash "/Users/brettblackney/Documents/Claude/Project Precision/Cadence Performance Scorecard — Weekly Scoring/install_scheduler.sh"
# After this, the job runs automatically every Friday 5:00 PM. No further action.
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

PROJECT_DIR="/Users/brettblackney/Documents/Claude/Project Precision/Cadence Performance Scorecard — Weekly Scoring"
PLIST_SRC="$PROJECT_DIR/com.clio.cadence-scorer.plist"
PLIST_DEST="$HOME/Library/LaunchAgents/com.clio.cadence-scorer.plist"

chmod +x "$PROJECT_DIR/run_weekly.sh"
mkdir -p "$HOME/Library/LaunchAgents"
cp "$PLIST_SRC" "$PLIST_DEST"

# Reload cleanly if it was already installed.
launchctl unload "$PLIST_DEST" 2>/dev/null || true
launchctl load -w "$PLIST_DEST"

echo "✓ Installed: com.clio.cadence-scorer — runs every Friday 5:00 PM."
echo ""
echo "  Verify it's loaded:   launchctl list | grep com.clio.cadence-scorer"
echo "  Run a test now:       launchctl start com.clio.cadence-scorer"
echo "                        tail -f \"$PROJECT_DIR/scheduler.log\""
echo "  Uninstall:            launchctl unload -w \"$PLIST_DEST\" && rm \"$PLIST_DEST\""
