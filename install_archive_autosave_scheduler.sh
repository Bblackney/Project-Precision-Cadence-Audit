#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# install_archive_autosave_scheduler.sh — one-time installer for the Friday
# 4pm Archive-Confirmed autosave.
#
# BEFORE running this:
#   1. In Chrome: View menu (or Chrome menu) -> Developer -> check
#      "Allow JavaScript from Apple Events".
#
# Run ONCE in Terminal:
#   bash "/Users/brettblackney/Documents/Claude/Project Precision/Cadence Performance Scorecard — Weekly Scoring/install_archive_autosave_scheduler.sh"
#
# After install, TEST IT MANUALLY before trusting the schedule — the very
# first run needs a human logged in to approve macOS's "Terminal wants to
# control Google Chrome" Automation prompt. It will silently fail if that
# prompt only ever appears unattended on a Friday at 4pm with nobody there
# to click Allow.
#   launchctl start com.clio.cadence-archive-autosave
#   tail -f "archive_autosave.log"
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

PROJECT_DIR="/Users/brettblackney/Documents/Claude/Project Precision/Cadence Performance Scorecard — Weekly Scoring"
PLIST_SRC="$PROJECT_DIR/com.clio.cadence-archive-autosave.plist"
PLIST_DEST="$HOME/Library/LaunchAgents/com.clio.cadence-archive-autosave.plist"

chmod +x "$PROJECT_DIR/run_archive_autosave.sh"
mkdir -p "$HOME/Library/LaunchAgents"
cp "$PLIST_SRC" "$PLIST_DEST"

launchctl unload "$PLIST_DEST" 2>/dev/null || true
launchctl load -w "$PLIST_DEST"

echo "✓ Installed: com.clio.cadence-archive-autosave — runs every Friday 4:00 PM."
echo ""
echo "  Verify it's loaded:   launchctl list | grep com.clio.cadence-archive-autosave"
echo "  Run a test now:       launchctl start com.clio.cadence-archive-autosave"
echo "                        tail -f \"$PROJECT_DIR/archive_autosave.log\""
echo "  Uninstall:            launchctl unload -w \"$PLIST_DEST\" && rm \"$PLIST_DEST\""
