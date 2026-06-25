#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# install_adherence_scheduler.sh — one-time installer for the DAILY adherence run.
# Run ONCE in Terminal:
#   bash "/Users/brettblackney/Documents/Claude/Project Precision/Cadence Performance Scorecard — Weekly Scoring/install_adherence_scheduler.sh"
# After this, the job runs automatically every day 6:00 AM. No further action.
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

PROJECT_DIR="/Users/brettblackney/Documents/Claude/Project Precision/Cadence Performance Scorecard — Weekly Scoring"
PLIST_SRC="$PROJECT_DIR/com.clio.cadence-adherence.plist"
PLIST_DEST="$HOME/Library/LaunchAgents/com.clio.cadence-adherence.plist"

chmod +x "$PROJECT_DIR/run_adherence.sh"
mkdir -p "$HOME/Library/LaunchAgents"
cp "$PLIST_SRC" "$PLIST_DEST"

launchctl unload "$PLIST_DEST" 2>/dev/null || true
launchctl load -w "$PLIST_DEST"

echo "✓ Installed: com.clio.cadence-adherence — runs every day 6:00 AM."
echo ""
echo "  Verify it's loaded:   launchctl list | grep com.clio.cadence-adherence"
echo "  Run a test now:       launchctl start com.clio.cadence-adherence"
echo "                        tail -f \"$PROJECT_DIR/adherence_scheduler.log\""
echo "  Uninstall:            launchctl unload -w \"$PLIST_DEST\" && rm \"$PLIST_DEST\""
