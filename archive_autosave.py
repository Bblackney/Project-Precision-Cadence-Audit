#!/usr/bin/env python3
"""
archive_autosave.py — Friday 4:00 PM autosave of Archive-Confirmed checkboxes.

Runs on Brett's Mac only (needs Chrome + AppleScript). Drives Chrome via
AppleScript to open the live dashboard, reads the confirmed-cadence state
straight out of the page's own JS (localStorage + already-server-rendered
state — the exact same data the manual "Save Archive-Confirmed CSV" button
would write), then merges it into archive_confirmed.csv on disk using the
same append-merge semantics as that button (existing rows preserved
verbatim; only new cadence_ids get appended; un-confirming a box never
deletes an existing row).

Fires at 4:00 PM Friday, before the 5:00 PM com.clio.cadence-scorer run, so
run_weekly.sh's own `git add archive_confirmed.csv` sweeps up whatever this
wrote. run_archive_autosave.sh also commits+pushes it directly as a backup
in case the 5pm run doesn't happen that week.

ONE-TIME SETUP REQUIRED (see WORKFLOW.md):
  1. Chrome: View/Chrome menu -> Developer -> "Allow JavaScript from Apple
     Events" must be checked.
  2. Run this once manually (`python3 archive_autosave.py` or
     `launchctl start com.clio.cadence-archive-autosave`) so macOS's
     Automation permission prompt ("Terminal wants to control Google
     Chrome") can actually be approved by a logged-in human. It cannot be
     approved by the unattended Friday run.
"""
import csv
import io
import json
import os
import subprocess
import sys
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ARCHIVE_CSV = os.path.join(BASE_DIR, "archive_confirmed.csv")
LOG_PATH = os.path.join(BASE_DIR, "archive_autosave.log")
DASHBOARD_URL = "https://bblackney.github.io/Project-Precision-Cadence-Audit/index.html"

# Runs inside the live page's own JS context (same functions the manual Save
# button already uses) — so this is exactly what a human clicking Save would
# produce, just headless.
JS_SNIPPET = (
    "(function(){try{"
    "var m=loadLS();"
    "var cids=Array.from(confirmedCids());"
    "var lines=cids.map(function(cid){return archiveLineFor(cid,m);});"
    "return JSON.stringify({ok:true,"
    "header:CSV_FIELDS.concat(['archive_confirmed','confirmed_at']).join(','),"
    "lines:lines});"
    "}catch(e){return JSON.stringify({ok:false,error:String(e)});}})();"
)

APPLESCRIPT_TEMPLATE = '''
tell application "Google Chrome"
    activate
    if (count of windows) = 0 then
        make new window
    end if
    set targetTab to make new tab at end of tabs of front window with properties {{URL:"{url}"}}
    delay 10
    set jsResult to execute targetTab javascript "{js}"
    close targetTab
    return jsResult
end tell
'''


def log(msg: str) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"{ts} {msg}"
    print(line)
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def run_applescript(script: str):
    proc = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    return proc.returncode, proc.stdout.strip(), proc.stderr.strip()


def read_existing_archive():
    """Returns (header:str, order:list[cid], by_id:dict[cid,raw_line])."""
    if not os.path.exists(ARCHIVE_CSV):
        return None, [], {}
    with open(ARCHIVE_CSV, newline="", encoding="utf-8") as f:
        raw_lines = [ln for ln in f.read().splitlines() if ln != ""]
    if not raw_lines:
        return None, [], {}
    header = raw_lines[0]
    header_fields = next(csv.reader([header]))
    if "cadence_id" not in header_fields:
        return header, [], {}
    cid_idx = header_fields.index("cadence_id")
    order, by_id = [], {}
    for raw in raw_lines[1:]:
        fields = next(csv.reader([raw]))
        if cid_idx >= len(fields):
            continue
        cid = fields[cid_idx].strip()
        if cid and cid not in by_id:
            by_id[cid] = raw
            order.append(cid)
    return header, order, by_id


def main() -> int:
    log("=" * 60)
    log(">> Archive-confirmed autosave starting")

    script = APPLESCRIPT_TEMPLATE.format(url=DASHBOARD_URL, js=JS_SNIPPET)
    rc, out, err = run_applescript(script)
    if rc != 0:
        log(f"[ERR] osascript failed (rc={rc}): {err or out}")
        log("      Likely cause: Chrome Automation permission not granted yet, or")
        log("      'Allow JavaScript from Apple Events' not enabled. See WORKFLOW.md.")
        return 1

    try:
        payload = json.loads(out)
    except json.JSONDecodeError:
        log(f"[ERR] could not parse JS result as JSON: {out[:300]!r}")
        return 1

    if not payload.get("ok"):
        log(f"[ERR] page-side JS error: {payload.get('error')}")
        return 1

    lines = payload.get("lines", [])
    header_from_page = payload.get("header", "")
    log(f"  -> {len(lines)} confirmed cadence(s) currently checked on the live dashboard")

    existing_header, order, by_id = read_existing_archive()
    header = existing_header or header_from_page
    header_fields = next(csv.reader([header])) if header else []
    if "cadence_id" not in header_fields:
        log(f"[ERR] unexpected CSV header, refusing to write: {header!r}")
        return 1
    cid_idx = header_fields.index("cadence_id")

    added = 0
    for raw in lines:
        fields = next(csv.reader([raw]))
        if cid_idx >= len(fields):
            continue
        cid = fields[cid_idx].strip()
        if cid and cid not in by_id:
            by_id[cid] = raw
            order.append(cid)
            added += 1

    out_buf = io.StringIO()
    writer = csv.writer(out_buf, lineterminator="\n")
    out_buf.write(header + "\n")
    for cid in order:
        out_buf.write(by_id[cid] + "\n")

    with open(ARCHIVE_CSV, "w", encoding="utf-8") as f:
        f.write(out_buf.getvalue())

    log(f"  -> wrote {len(order)} total confirmed cadence(s) ({added} new) to "
        f"{os.path.basename(ARCHIVE_CSV)}")
    log("✓ Done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
