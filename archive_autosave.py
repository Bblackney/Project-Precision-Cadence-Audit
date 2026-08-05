#!/usr/bin/env python3
"""
archive_autosave.py — Friday 2:00 PM autosave of Archive-Confirmed checkboxes.

Runs on Brett's Mac only (needs Chrome + AppleScript). Drives Chrome via
AppleScript to open the live dashboard and read the confirmed-cadence state
straight out of the page's DOM + localStorage, then merges it into
archive_confirmed.csv on disk using the same append-merge semantics as the
manual "Save Archive-Confirmed CSV" button (existing rows preserved
verbatim; only new cadence_ids get appended; un-confirming a box never
deletes an existing row).

IMPORTANT: the injected JS below only uses `document` (DOM) and
`localStorage` — NOT the page's own JS functions/variables (loadLS(),
confirmedCids(), archiveLineFor(), CSV_FIELDS, ALL_ROWS, etc). Chrome's
"execute javascript" via AppleScript runs in an isolated world that shares
the DOM and localStorage with the page but NOT its top-level `var`/`function`
declarations — reaching for those raises "X is not defined". Don't
"simplify" this by calling back into the page's own helpers.

Fires at 2:00 PM Friday, three hours before the 5:00 PM com.clio.cadence-scorer
run, so run_weekly.sh's own `git add archive_confirmed.csv` sweeps up
whatever this wrote. run_archive_autosave.sh also commits+pushes it
directly as a backup in case the 5pm run doesn't happen that week.

ON FAILURE: posts to a Slack webhook (see slack_webhook.json / WORKFLOW.md)
so Brett knows to click the manual Save button himself that week. Silently
skips the Slack step (just logs a note) if slack_webhook.json isn't set up.

ONE-TIME SETUP REQUIRED (see WORKFLOW.md):
  1. Chrome: View/Chrome menu -> Developer -> "Allow JavaScript from Apple
     Events" must be checked EVERY TIME CHROME RESTARTS — it does not
     persist across a Chrome quit/relaunch/update. This is the single most
     likely cause of a failure here.
  2. Run this once manually (`python3 archive_autosave.py` or
     `launchctl start com.clio.cadence-archive-autosave`) so macOS's
     Automation permission prompt ("Terminal wants to control Google
     Chrome") can actually be approved by a logged-in human. It cannot be
     approved by the unattended Friday run.
  3. (Optional but recommended) create slack_webhook.json — see WORKFLOW.md
     — so failures actually notify Brett instead of failing silently.
"""
import csv
import io
import json
import os
import subprocess
import sys
import urllib.request
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ARCHIVE_CSV = os.path.join(BASE_DIR, "archive_confirmed.csv")
LOG_PATH = os.path.join(BASE_DIR, "archive_autosave.log")
SLACK_WEBHOOK_FILE = os.path.join(BASE_DIR, "slack_webhook.json")  # gitignored
DASHBOARD_URL = "https://bblackney.github.io/Project-Precision-Cadence-Audit/index.html"

# Self-contained: only touches `document` and `localStorage` (shared across
# Chrome's isolated-world AppleScript execution and the page's own JS world).
# Deliberately does NOT call the page's loadLS()/confirmedCids()/
# archiveLineFor()/CSV_FIELDS/ALL_ROWS — those live in the page's own JS
# world and are invisible here, which is exactly what broke the first
# version of this script ("ReferenceError: loadLS is not defined").
JS_SNIPPET = r"""
(function(){
  try{
    var FIELDS=["run_date","period_label","cadence_id","cadence_name","score",
      "verdict","model_applied","meeting_rate","reply_rate","connect_rate",
      "open_rate","skip_rate","steps_completed","emails_sent","created_by",
      "pts_meeting_rate","pts_reply_rate","pts_connect_rate","pts_open_rate",
      "pts_skip_rate","low_sample","created_at"];
    function csvCell(v){
      v=(v===null||v===undefined)?'':String(v);
      return /[",\n]/.test(v)?'"'+v.replace(/"/g,'""')+'"':v;
    }
    var rows=Array.from(document.querySelectorAll('#tbody tr'));
    var latestByCid={};
    rows.forEach(function(r){
      var cid=r.dataset.cid;
      if(!cid) return;
      var d=r.dataset.date||'';
      if(!latestByCid[cid]||d>latestByCid[cid].dataset.date) latestByCid[cid]=r;
    });
    var confirmedSet={};
    document.querySelectorAll('input.archChk:checked').forEach(function(b){
      if(b.dataset.cid) confirmedSet[b.dataset.cid]=true;
    });
    var ls={};
    try{ ls=JSON.parse(localStorage.getItem('cadenceArchiveConfirmed'))||{}; }catch(e){}
    var today=new Date().toISOString().slice(0,10);
    var lines=Object.keys(confirmedSet).map(function(cid){
      var r=latestByCid[cid];
      var when=(ls[cid]&&ls[cid].t)||today;
      var vals={cadence_id:cid};
      if(r){
        vals.run_date=r.dataset.date||'';
        vals.verdict=r.dataset.verdict||'';
        vals.model_applied=r.dataset.model||'';
        vals.cadence_name=(r.cells[1]&&r.cells[1].getAttribute('title'))
          ||(r.cells[1]&&r.cells[1].textContent)||'';
        vals.score=r.cells[5]?r.cells[5].textContent.trim():'';
        vals.meeting_rate=r.cells[6]?r.cells[6].textContent.replace('%','').trim():'';
        vals.reply_rate=r.cells[7]?r.cells[7].textContent.replace('%','').trim():'';
        vals.connect_rate=r.cells[8]?r.cells[8].textContent.replace('%','').trim():'';
        vals.open_rate=r.cells[9]?r.cells[9].textContent.replace('%','').trim():'';
        vals.steps_completed=r.cells[10]?r.cells[10].textContent.replace(/,/g,'').trim():'';
        vals.created_by=r.cells[12]?r.cells[12].textContent.trim():'';
        vals.created_at=r.cells[13]?r.cells[13].textContent.trim():'';
      }
      var line=FIELDS.map(function(f){return csvCell(vals[f]!==undefined?vals[f]:'');});
      line.push('TRUE');
      line.push(csvCell(when));
      return line.join(',');
    });
    return JSON.stringify({ok:true,
      header:FIELDS.concat(['archive_confirmed','confirmed_at']).join(','),
      lines:lines});
  }catch(e){
    return JSON.stringify({ok:false,error:String(e)});
  }
})();
"""

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


def notify_slack_failure(reason: str) -> None:
    """Best-effort Slack alert so a silent failure doesn't sit unnoticed for
    a week. No-ops quietly if slack_webhook.json isn't set up yet."""
    if not os.path.exists(SLACK_WEBHOOK_FILE):
        log("  (no slack_webhook.json configured — skipping Slack alert; see WORKFLOW.md)")
        return
    try:
        with open(SLACK_WEBHOOK_FILE, encoding="utf-8") as f:
            cfg = json.load(f)
        url = (cfg.get("webhook_url") or "").strip()
        if not url:
            log("  [WARN] slack_webhook.json has no webhook_url — skipping Slack alert")
            return
        text = (
            ":warning: *Cadence Scorecard — Archive-Confirmed autosave failed*\n"
            f"{reason}\n"
            "Anything checked since the last successful save is only in your browser's "
            "localStorage right now — click *:arrow_down: Save Archive-Confirmed CSV* on "
            "the dashboard to save it manually. Details in `archive_autosave.log`."
        )
        body = json.dumps({"text": text}).encode("utf-8")
        req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            resp.read()
        log("  -> Slack failure alert sent")
    except Exception as e:  # never let a notification problem mask the real error
        log(f"  [WARN] Slack alert failed to send: {e}")


def fail(reason: str) -> int:
    log(f"[ERR] {reason}")
    notify_slack_failure(reason)
    return 1


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

    script = APPLESCRIPT_TEMPLATE.format(url=DASHBOARD_URL, js=JS_SNIPPET.strip())
    rc, out, err = run_applescript(script)
    if rc != 0:
        detail = err or out
        log(f"      osascript detail: {detail}")
        return fail(
            "Chrome automation failed (osascript). Check: Chrome's 'Allow JavaScript "
            "from Apple Events' setting (resets every Chrome restart) and macOS's "
            "Automation permission for Terminal -> Google Chrome."
        )

    try:
        payload = json.loads(out)
    except json.JSONDecodeError:
        log(f"      raw output: {out[:300]!r}")
        return fail("Could not parse the page's JS result as JSON.")

    if not payload.get("ok"):
        return fail(f"Page-side JS error: {payload.get('error')}")

    lines = payload.get("lines", [])
    header_from_page = payload.get("header", "")
    log(f"  -> {len(lines)} confirmed cadence(s) currently checked on the live dashboard")

    existing_header, order, by_id = read_existing_archive()
    header = existing_header or header_from_page
    header_fields = next(csv.reader([header])) if header else []
    if "cadence_id" not in header_fields:
        return fail(f"Unexpected CSV header, refusing to write: {header!r}")
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
