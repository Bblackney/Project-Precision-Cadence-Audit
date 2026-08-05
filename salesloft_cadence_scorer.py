#!/usr/bin/env python3
"""
salesloft_cadence_scorer.py
Cadence Performance Scorer — Salesloft API Edition v3.0

Replaces sfdc_cadence_scorer.py + attribution cache entirely.
Pulls all metrics directly from the Salesloft API — no SFDC dependency.

Data sources:
  /v2/cadences          → cadence list, owner info
  /v2/cadence_stats/:id → emails sent, opens, replies, calls, meetings booked
  /v2/activities/calls  → connected call count (paginated, only for call cadences)

SCORING MODEL v2.1 — both BDR and SDR max 100 pts, no skip rate

  BDR (100 pts max):
    Meeting Rate  ≥15% →35 | ≥5% →20 | <5% →0
    Reply Rate    ≥10% →30 | ≥5% →22 | ≥2% →13 | <2% →0
    Connect Rate  ≥15% →20 | ≥7% →13 | ≥3% →6  | <3% →0
    Open Rate     ≥50% →15 | ≥35% →10 | ≥20% →5 | <20% →0

  SDR (100 pts max):
    Meeting Rate  ≥10% →35 | ≥5% →20 | ≥2% →13 | <2% →0
    Reply Rate    ≥3%  →30 | ≥1%  →22 | <1% →0
    Connect Rate  ≥15% →20 | ≥7%  →13 | ≥3% →6  | <3% →0
    Open Rate     ≥35% →15 | ≥25% →10 | ≥15% →5 | <15% →0

Verdict buckets: people_acted_on_count == 0 → NO DATA; 1–99 → LOW SAMPLE (scored & shown,
             not bucketed); ≥100 → KEEP/REVIEW/ARCHIVE by score (≥75 / 50–74 / <50).

Credentials: salesloft_credentials.json  {"api_token": "v2_ak_..."}
Outputs:     cadence_scores_master.csv (appended), index.html (regenerated)
"""

import csv
import json
import os
import re
import sys
import time
import urllib.request
import urllib.parse
import urllib.error
from datetime import datetime, timezone
from html import escape

# ── Paths ─────────────────────────────────────────────────────────────────────
BASE_DIR    = os.path.dirname(os.path.abspath(__file__))
CREDS_FILE  = os.path.join(BASE_DIR, "salesloft_credentials.json")
MASTER_CSV  = os.path.join(BASE_DIR, "cadence_scores_master.csv")
MASTER_HTML = os.path.join(BASE_DIR, "index.html")
CACHE_FILE  = os.path.join(BASE_DIR, "connected_calls_cache.json")
ARCHIVE_CSV = os.path.join(BASE_DIR, "archive_confirmed.csv")

# ── Constants ─────────────────────────────────────────────────────────────────
SL_BASE_URL   = "https://api.salesloft.com/v2"
MIN_PEOPLE    = 100    # low-sample threshold: < this → low_sample flag (still scored)
REQUEST_DELAY = 0.5    # seconds between API calls (~2 req/sec, avoids rate limits)
CONNECTED_DISPOSITION = "Call - Connected"   # exact Salesloft disposition for a live connect
# Regions excluded for now. EMEA/CAN/APAC match as whole words anywhere in the name;
# CAD only when the name STARTS with it (so mid-name 'CAD' and the word 'cadence' are safe).
EXCLUDED_REGION_RE = re.compile(r"\b(EMEA|CAN|APAC)\b", re.IGNORECASE)
CAD_PREFIX_RE      = re.compile(r"^\s*CAD\b", re.IGNORECASE)

# ── API helpers ───────────────────────────────────────────────────────────────
def _get(token, path, params=None, _retry=0):
    """Single authenticated GET with 429 backoff. Returns parsed JSON or None on error."""
    url = f"{SL_BASE_URL}{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(
        url, headers={"Authorization": f"Bearer {token}", "Accept": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 429 and _retry < 4:
            wait = 30 * (2 ** _retry)   # 30s, 60s, 120s, 240s
            print(f"    [429] Rate limited — waiting {wait}s before retry {_retry + 1}/4…")
            time.sleep(wait)
            return _get(token, path, params, _retry + 1)
        body = e.read().decode("utf-8", errors="replace")
        print(f"    [HTTP {e.code}] {path}: {body[:200]}")
        return None
    except Exception as e:
        # Transient read/connection errors (IncompleteRead, timeouts, dropped
        # sockets) — retry with backoff instead of giving up, so a single network
        # hiccup can't truncate the connected-calls stream (Phase 3) mid-run.
        if _retry < 4:
            wait = 5 * (2 ** _retry)   # 5s, 10s, 20s, 40s
            print(f"    [retry] {path}: {type(e).__name__} — waiting {wait}s "
                  f"before retry {_retry + 1}/4…")
            time.sleep(wait)
            return _get(token, path, params, _retry + 1)
        print(f"    [ERR] {path}: {e} (gave up after 4 retries)")
        return None


def paginate(token, path, params=None):
    """Yield every record across all pages. Handles next_page pagination."""
    page = 1
    base = dict(params or {})
    while True:
        data = _get(token, path, {**base, "page": page})
        time.sleep(REQUEST_DELAY)
        if data is None:
            break
        records = data.get("data", [])
        yield from records
        if not data.get("metadata", {}).get("paging", {}).get("next_page"):
            break
        page += 1


# ── Connected-calls cache (all-time per-cadence count: built once + weekly delta) ─
def _load_cache():
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"counts": {}, "cursor": None, "backfill_complete": False, "updated_at": None}


def _save_cache(cache):
    cache["updated_at"] = datetime.now(timezone.utc).isoformat()
    tmp = CACHE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cache, f)
    os.replace(tmp, CACHE_FILE)   # atomic write — never leaves a half-written cache


def _update_connected_cache(token, cache):
    """Fetch 'Call - Connected' calls created since cache['cursor'], add to the
    per-cadence counts, advance the cursor, and save after EVERY page (crash-safe).
    Cursor-based (always page=1, created_at[gt]=cursor, sorted ASC) so it resumes
    cleanly with no overlap. With an empty cursor this walks all history (backfill);
    with a populated cursor it pulls only the delta. Returns
    (counts_by_int_id, new_count, pages, caught_up)."""
    counts  = cache.setdefault("counts", {})
    cursor  = cache.get("cursor")
    disp    = urllib.parse.quote(CONNECTED_DISPOSITION)
    new_n = pages = 0
    caught_up = False
    while True:
        q = (f"/activities/calls?disposition[]={disp}"
             "&sort_by=created_at&sort_direction=ASC&per_page=100&page=1")
        if cursor:
            q += "&created_at[gt]=" + urllib.parse.quote(cursor)
        data = _get(token, q)
        time.sleep(REQUEST_DELAY)
        if data is None:
            break                      # error after retries — not caught up
        recs = data.get("data", [])
        if not recs:
            caught_up = True
            break
        for rec in recs:
            cid = rec.get("cadence_id") or (rec.get("cadence") or {}).get("id")
            if cid is not None:
                k = str(cid)
                counts[k] = counts.get(k, 0) + 1
        new_n += len(recs)
        pages += 1
        cursor = recs[-1].get("created_at") or cursor
        cache["cursor"] = cursor
        _save_cache(cache)
        if pages % 50 == 0:
            print(f"    …{new_n:,} connected calls, {len(counts)} cadences, "
                  f"cursor {str(cursor)[:10]}", flush=True)
        if len(recs) < 100:
            caught_up = True
            break
    return {int(k): v for k, v in counts.items()}, new_n, pages, caught_up


def fetch_user_map(token):
    """Return {user_id: 'Full Name'} for all Salesloft users — used to resolve a
    cadence's creator ID into the 'Created by' name."""
    users = {}
    for u in paginate(token, "/users", {"per_page": 100}):
        uid = u.get("id")
        if uid is None:
            continue
        users[uid] = (u.get("name")
                      or f"{u.get('first_name','')} {u.get('last_name','')}".strip()
                      or u.get("email", ""))
    return users


# ── Model detection ───────────────────────────────────────────────────────────
def detect_model(name):
    """Returns 'BDR', 'SDR', or None (exclude)."""
    n = name.lower()
    if "bdr" in n:
        return "BDR"
    if "sdr" in n:
        return "SDR"
    return None


# ── Scoring ───────────────────────────────────────────────────────────────────
def _score_bdr(meeting_rate, reply_rate, connect_rate, open_rate):
    m = 35 if meeting_rate >= 15 else (20 if meeting_rate >= 5 else 0)
    r = 30 if reply_rate >= 10 else (22 if reply_rate >= 5 else (13 if reply_rate >= 2 else 0))
    c = 20 if connect_rate >= 15 else (13 if connect_rate >= 7 else (6 if connect_rate >= 3 else 0))
    o = 15 if open_rate >= 50 else (10 if open_rate >= 35 else (5 if open_rate >= 20 else 0))
    return m, r, c, o


def _score_sdr(meeting_rate, reply_rate, connect_rate, open_rate):
    m = 35 if meeting_rate >= 10 else (20 if meeting_rate >= 5 else (13 if meeting_rate >= 2 else 0))
    r = 30 if reply_rate >= 3 else (22 if reply_rate >= 1 else 0)
    c = 20 if connect_rate >= 15 else (13 if connect_rate >= 7 else (6 if connect_rate >= 3 else 0))
    o = 15 if open_rate >= 35 else (10 if open_rate >= 25 else (5 if open_rate >= 15 else 0))
    return m, r, c, o


def score_cadence(model, meeting_rate, reply_rate, connect_rate, open_rate):
    """Returns (pts_m, pts_r, pts_c, pts_o, total_score)."""
    fn = _score_bdr if model == "BDR" else _score_sdr
    pts = fn(meeting_rate, reply_rate, connect_rate, open_rate)
    return pts + (sum(pts),)


def get_verdict(score):
    return "KEEP" if score >= 75 else ("REVIEW" if score >= 50 else "ARCHIVE")


# ── CSV ───────────────────────────────────────────────────────────────────────
# Schema matches existing cadence_scores_master.csv for clean appending.
# skip_rate / pts_skip_rate are carried as zeros (removed from model in v2.1).
# steps_completed is populated with people_acted_on_count (nearest equivalent).
CSV_FIELDS = [
    "run_date", "period_label", "cadence_id", "cadence_name",
    "score", "verdict", "model_applied",
    "meeting_rate", "reply_rate", "connect_rate", "open_rate",
    "skip_rate",         # legacy column — always 0.0
    "steps_completed",   # populated with people_acted_on_count
    "emails_sent", "created_by",
    "pts_meeting_rate", "pts_reply_rate", "pts_connect_rate", "pts_open_rate",
    "pts_skip_rate",     # legacy column — always 0
    "low_sample", "created_at",
]


def append_to_csv(rows):
    exists = os.path.exists(MASTER_CSV)
    with open(MASTER_CSV, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
        if not exists:
            w.writeheader()
        w.writerows(rows)
    print(f"  → Appended {len(rows)} rows to {os.path.basename(MASTER_CSV)}")


def read_all_csv():
    if not os.path.exists(MASTER_CSV):
        return []
    with open(MASTER_CSV, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


# Extra columns written to archive_confirmed.csv on top of the standard CSV_FIELDS.
ARCHIVE_EXTRA_FIELDS = ["archive_confirmed", "confirmed_at"]


def read_archive_confirmed():
    """Master record of archive decisions, keyed by cadence_id.

    Returns {cadence_id(str): confirmed_at(str)} for every cadence whose
    archive_confirmed flag is truthy in archive_confirmed.csv. The dashboard's
    "Archive Confirmed" checkboxes write this file (one row per confirmed
    cadence, full line-item info); the weekly run reads it back so the boxes
    stay checked across regenerations. Missing file → empty (no-op)."""
    if not os.path.exists(ARCHIVE_CSV):
        return {}
    out = {}
    try:
        with open(ARCHIVE_CSV, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                cid = str(row.get("cadence_id", "")).strip()
                flag = str(row.get("archive_confirmed", "")).strip().upper()
                if cid and flag in ("TRUE", "1", "YES", "Y"):
                    out[cid] = str(row.get("confirmed_at", "")).strip()
    except Exception as e:  # never let a malformed file break the weekly run
        print(f"  [WARN] could not read {os.path.basename(ARCHIVE_CSV)}: {e}")
    return out


# ── HTML dashboard ─────────────────────────────────────────────────────────────
VERDICT_COLOR = {"KEEP": "#16a34a", "REVIEW": "#d97706", "ARCHIVE": "#dc2626", "LOW SAMPLE": "#475569", "NO DATA": "#94a3b8"}
VERDICT_BG    = {"KEEP": "#dcfce7", "REVIEW": "#fef9c3", "ARCHIVE": "#fee2e2", "LOW SAMPLE": "#e2e8f0", "NO DATA": "#f8fafc"}


def _safe_float(v, default=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _row_html(r, confirmed=None):
    confirmed = confirmed or {}
    cid = str(r.get("cadence_id", "")).strip()
    chk = " checked" if cid in confirmed else ""
    v   = r.get("verdict", "ARCHIVE")
    ls  = str(r.get("low_sample", "")).strip().lower() in ("true", "1")
    s   = int(_safe_float(r.get("score")))
    fg  = VERDICT_COLOR.get(v, "#374151")
    bg  = VERDICT_BG.get(v, "#f3f4f6")
    model_badge = (
        '<span style="background:#dbeafe;color:#1e40af;padding:1px 7px;border-radius:9px;'
        'font-size:11px;font-weight:700;">BDR</span>'
        if r.get("model_applied") == "BDR" else
        '<span style="background:#ede9fe;color:#4c1d95;padding:1px 7px;border-radius:9px;'
        'font-size:11px;font-weight:700;">SDR</span>'
    )
    low_flag = (
        '<span title="Low sample — fewer than 100 people acted on" '
        'style="color:#9ca3af;font-size:11px;margin-right:3px;">⚠</span>'
        if ls else ""
    )
    ppl = int(_safe_float(r.get("steps_completed")))
    return f"""      <tr data-date="{escape(r.get('run_date',''))}" data-model="{escape(r.get('model_applied',''))}" data-verdict="{escape(v)}" data-cid="{escape(cid)}">
        <td style="padding:8px 12px;border-bottom:1px solid #f3f4f6;font-size:12px;color:#6b7280;font-variant-numeric:tabular-nums;">{escape(cid)}</td>
        <td style="padding:8px 12px;border-bottom:1px solid #f3f4f6;max-width:300px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="{escape(r.get('cadence_name',''))}">{low_flag}{escape(r.get('cadence_name',''))}</td>
        <td style="padding:8px 12px;border-bottom:1px solid #f3f4f6;text-align:center;">{model_badge}</td>
        <td style="padding:8px 12px;border-bottom:1px solid #f3f4f6;text-align:center;"><span style="display:inline-block;padding:2px 10px;border-radius:12px;font-size:12px;font-weight:700;background:{bg};color:{fg};">{v}</span></td>
        <td style="padding:8px 12px;border-bottom:1px solid #f3f4f6;text-align:center;"><input type="checkbox" class="archChk" data-cid="{escape(cid)}" onchange="onArch(this)"{chk}></td>
        <td style="padding:8px 12px;border-bottom:1px solid #f3f4f6;text-align:right;font-weight:700;color:{fg};">{s}</td>
        <td style="padding:8px 12px;border-bottom:1px solid #f3f4f6;text-align:right;">{_safe_float(r.get('meeting_rate')):.1f}%</td>
        <td style="padding:8px 12px;border-bottom:1px solid #f3f4f6;text-align:right;">{_safe_float(r.get('reply_rate')):.1f}%</td>
        <td style="padding:8px 12px;border-bottom:1px solid #f3f4f6;text-align:right;">{_safe_float(r.get('connect_rate')):.1f}%</td>
        <td style="padding:8px 12px;border-bottom:1px solid #f3f4f6;text-align:right;">{_safe_float(r.get('open_rate')):.1f}%</td>
        <td style="padding:8px 12px;border-bottom:1px solid #f3f4f6;text-align:right;">{ppl:,}</td>
        <td style="padding:8px 12px;border-bottom:1px solid #f3f4f6;text-align:right;font-size:12px;color:#6b7280;">{escape(str(r.get('pts_meeting_rate','0')))} / {escape(str(r.get('pts_reply_rate','0')))} / {escape(str(r.get('pts_connect_rate','0')))} / {escape(str(r.get('pts_open_rate','0')))}</td>
        <td style="padding:8px 12px;border-bottom:1px solid #f3f4f6;font-size:12px;color:#6b7280;">{escape(r.get('created_by',''))}</td>
        <td style="padding:8px 12px;border-bottom:1px solid #f3f4f6;text-align:center;font-size:12px;color:#9ca3af;">{escape(r.get('created_at',''))}</td>
        <td style="padding:8px 12px;border-bottom:1px solid #f3f4f6;text-align:center;font-size:12px;color:#9ca3af;">{escape(r.get('run_date',''))}</td>
      </tr>"""


def generate_html(all_rows, run_date):
    dates       = sorted(set(r["run_date"] for r in all_rows if r.get("run_date")), reverse=True)
    latest      = dates[0] if dates else run_date
    latest_rows = [r for r in all_rows if r.get("run_date") == latest]

    # Every cadence in the latest run carries exactly one verdict:
    # KEEP/REVIEW/ARCHIVE (only for ≥100-people cadences), LOW SAMPLE (<100), or NO DATA (0).
    keep_n      = sum(1 for r in latest_rows if r.get("verdict") == "KEEP")
    review_n    = sum(1 for r in latest_rows if r.get("verdict") == "REVIEW")
    archive_n   = sum(1 for r in latest_rows if r.get("verdict") == "ARCHIVE")
    low_n       = sum(1 for r in latest_rows if r.get("verdict") == "LOW SAMPLE")
    nodata_n    = sum(1 for r in latest_rows if r.get("verdict") == "NO DATA")

    confirmed      = read_archive_confirmed()
    all_rows_html  = "\n".join(_row_html(r, confirmed) for r in all_rows)
    rows_json      = json.dumps(all_rows, ensure_ascii=True)
    confirmed_json = json.dumps(confirmed, ensure_ascii=True)
    fields_json    = json.dumps(CSV_FIELDS, ensure_ascii=True)
    date_options  = "\n      ".join(
        f'<option value="{d}"{" selected" if d == latest else ""}>{d}</option>'
        for d in dates
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Cadence Performance Scorecard</title>
  <style>
    *{{box-sizing:border-box;margin:0;padding:0}}
    body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:#f8fafc;color:#1e293b}}
    .hdr{{background:linear-gradient(135deg,#1e3a5f 0%,#2563eb 100%);color:white;padding:24px 32px}}
    .hdr h1{{font-size:20px;font-weight:700;letter-spacing:-.3px}}
    .hdr p{{font-size:12px;opacity:.75;margin-top:4px}}
    .kpi-bar{{background:white;padding:14px 32px;border-bottom:1px solid #e2e8f0;display:flex;gap:28px;flex-wrap:wrap;align-items:center}}
    .kpi{{text-align:center;min-width:70px}}
    .kpi .num{{font-size:26px;font-weight:800;line-height:1}}
    .kpi .lbl{{font-size:10px;font-weight:600;text-transform:uppercase;letter-spacing:.5px;margin-top:2px}}
    .kpi.keep .num{{color:#16a34a}}.kpi.keep .lbl{{color:#166534}}
    .kpi.review .num{{color:#d97706}}.kpi.review .lbl{{color:#92400e}}
    .kpi.archive .num{{color:#dc2626}}.kpi.archive .lbl{{color:#991b1b}}
    .kpi.low .num{{color:#475569}}.kpi.low .lbl{{color:#334155}}
    .kpi.nodata .num{{color:#94a3b8}}.kpi.nodata .lbl{{color:#64748b}}
    .ctrl{{background:white;padding:12px 32px;border-bottom:1px solid #e2e8f0;display:flex;gap:14px;align-items:center;flex-wrap:wrap}}
    .ctrl label{{font-size:12px;font-weight:500;color:#374151;display:flex;flex-direction:column;gap:3px}}
    .ctrl select,.ctrl input{{border:1px solid #d1d5db;border-radius:5px;padding:5px 8px;font-size:12px;outline:none;background:white;min-width:120px}}
    .ctrl input[type=checkbox]{{min-width:auto;width:14px;height:14px;padding:0;margin:0;border-radius:3px;vertical-align:middle}}
    .dd{{position:relative}}
    .dd-btn{{border:1px solid #d1d5db;border-radius:5px;padding:5px 8px;font-size:12px;background:white;cursor:pointer;min-width:120px;text-align:left;font-weight:400;color:#374151}}
    .dd-btn:hover{{border-color:#2563eb}}
    .dd-panel{{display:none;position:absolute;z-index:20;background:white;border:1px solid #d1d5db;border-radius:6px;box-shadow:0 6px 18px rgba(0,0,0,.14);padding:6px 10px;margin-top:3px;min-width:150px}}
    .dd-panel.open{{display:block}}
    .dd-panel label{{display:flex;flex-direction:row;align-items:center;gap:7px;padding:4px 2px;font-size:12px;font-weight:400;color:#374151;white-space:nowrap;cursor:pointer}}
    .ctrl select:focus,.ctrl input:focus{{border-color:#2563eb}}
    .tbl-wrap{{padding:20px 32px;overflow-x:auto}}
    table{{width:100%;border-collapse:collapse;background:white;border-radius:10px;overflow:hidden;box-shadow:0 1px 3px rgba(0,0,0,.07);font-size:13px}}
    thead th{{background:#f8fafc;padding:9px 12px;text-align:left;font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.5px;color:#64748b;border-bottom:2px solid #e2e8f0;cursor:pointer;user-select:none;white-space:nowrap}}
    thead th:hover{{background:#f1f5f9}}
    thead th.asc::after{{content:" ▲"}}
    thead th.desc::after{{content:" ▼"}}
    tbody tr:hover{{background:#f8fafc}}
    .foot{{font-size:11px;color:#6b7280;padding:4px 32px 20px;line-height:1.7}}
    #rowCount{{font-size:11px;color:#9ca3af;margin-left:auto}}
  </style>
</head>
<body>
<nav style="padding:14px 32px 0;display:flex;gap:8px;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif">
  <a href="index.html" style="display:inline-flex;align-items:center;padding:8px 16px;border-radius:999px;border:1px solid #2f5bd0;background:#2f5bd0;color:#fff;font-weight:600;font-size:13px;text-decoration:none">Cadence Performance</a>
  <a href="adherence.html" style="display:inline-flex;align-items:center;padding:8px 16px;border-radius:999px;border:1px solid #e3e7ec;background:#fff;color:#65707d;font-weight:600;font-size:13px;text-decoration:none">Cadence Adherence</a>
</nav>
<div class="hdr">
  <h1>Cadence Performance Scorecard</h1>
  <p>Model v2.1 · Salesloft API · BDR &amp; SDR both max 100 pts · Generated {escape(run_date)}</p>
</div>

<div class="kpi-bar" id="kpiBar">
  <div class="kpi keep">   <div class="num" id="kpiKeep">{keep_n}</div>    <div class="lbl">Keep</div></div>
  <div class="kpi review"> <div class="num" id="kpiReview">{review_n}</div> <div class="lbl">Review</div></div>
  <div class="kpi archive"><div class="num" id="kpiArchive">{archive_n}</div><div class="lbl">Archive</div></div>
  <div class="kpi low">    <div class="num" id="kpiLow">{low_n}</div>       <div class="lbl">Low Sample</div></div>
  <div class="kpi nodata"> <div class="num" id="kpiNoData">{nodata_n}</div> <div class="lbl">No Data</div></div>
</div>

<div class="ctrl">
  <button type="button" id="saveArchBtn" onclick="saveArchiveCSV()" title="Save every Archive-Confirmed cadence (full info) to archive_confirmed.csv" style="border:1px solid #b91c1c;background:#dc2626;color:#fff;border-radius:5px;padding:7px 12px;font-size:12px;font-weight:700;cursor:pointer;white-space:nowrap;">⬇ Save Archive-Confirmed CSV <span id="archCount">(0)</span></button>
  <button type="button" id="cnvBtn" onclick="toggleCnv()" title="Show only cadences whose name contains 'CNV'" style="border:1px solid #2563eb;background:#fff;color:#2563eb;border-radius:5px;padding:7px 12px;font-size:12px;font-weight:700;cursor:pointer;white-space:nowrap;">Project Precision Cadences</button>
  <button type="button" id="pilotBtn" onclick="togglePilot()" title="Show only the 15 Pilot cadences" style="border:1px solid #7c3aed;background:#fff;color:#7c3aed;border-radius:5px;padding:7px 12px;font-size:12px;font-weight:700;cursor:pointer;white-space:nowrap;">Pilot Cadences</button>
  <div style="display:flex;flex-direction:column;gap:3px;font-size:12px;font-weight:500;color:#374151;">Verdict
    <div class="dd">
      <button type="button" class="dd-btn" id="vBtn" onclick="toggleDD('vPanel')">Verdict (3)</button>
      <div class="dd-panel" id="vPanel">
        <label><input type="checkbox" class="fVerdict" value="KEEP" checked onchange="filter()">KEEP</label>
        <label><input type="checkbox" class="fVerdict" value="REVIEW" checked onchange="filter()">REVIEW</label>
        <label><input type="checkbox" class="fVerdict" value="ARCHIVE" checked onchange="filter()">ARCHIVE</label>
        <label><input type="checkbox" class="fVerdict" value="LOW SAMPLE" onchange="filter()">LOW SAMPLE</label>
        <label><input type="checkbox" class="fVerdict" value="NO DATA" onchange="filter()">NO DATA</label>
      </div>
    </div>
  </div>
  <div style="display:flex;flex-direction:column;gap:3px;font-size:12px;font-weight:500;color:#374151;">Team
    <div class="dd">
      <button type="button" class="dd-btn" id="tBtn" onclick="toggleDD('tPanel')">Team (all)</button>
      <div class="dd-panel" id="tPanel">
        <label><input type="checkbox" class="fTeam" value="SDR" onchange="filter()">SDR</label>
        <label><input type="checkbox" class="fTeam" value="BDR-S" onchange="filter()">BDR-S</label>
        <label><input type="checkbox" class="fTeam" value="BDR-V" onchange="filter()">BDR-V</label>
        <label><input type="checkbox" class="fTeam" value="BDR-MM" onchange="filter()">BDR-MM</label>
        <label><input type="checkbox" class="fTeam" value="BDR-CS" onchange="filter()">BDR-CS</label>
      </div>
    </div>
  </div>
  <label>Search
    <input type="text" id="fSearch" placeholder="Cadence name…" oninput="filter()">
  </label>
  <label>Run Date
    <select id="fDate" onchange="filter()">
      <option value="">All dates</option>
      {date_options}
    </select>
  </label>
  <span id="rowCount"></span>
</div>

<div class="tbl-wrap">
  <table id="tbl">
    <thead><tr>
      <th onclick="sort(0)" title="Salesloft cadence ID">Cadence ID</th>
      <th onclick="sort(1)">Cadence Name</th>
      <th onclick="sort(2)" style="text-align:center">Model</th>
      <th onclick="sort(3)" style="text-align:center">Verdict</th>
      <th onclick="sort(4)" style="text-align:center" title="Tick to confirm this cadence for archive — saves to archive_confirmed.csv">Archive Confirmed</th>
      <th onclick="sort(5)" style="text-align:right">Score</th>
      <th onclick="sort(6)" style="text-align:right">Mtg Rate</th>
      <th onclick="sort(7)" style="text-align:right">Reply Rate</th>
      <th onclick="sort(8)" style="text-align:right">Connect Rate</th>
      <th onclick="sort(9)" style="text-align:right">Open Rate</th>
      <th onclick="sort(10)" style="text-align:right" title="people_acted_on_count">People</th>
      <th onclick="sort(11)" style="text-align:right" title="Mtg / Reply / Connect / Open">Pts Breakdown</th>
      <th onclick="sort(12)">Created by</th>
      <th onclick="sort(13)" style="text-align:center" title="When the cadence was created in Salesloft">Created</th>
      <th onclick="sort(14)" style="text-align:center">Run Date</th>
    </tr></thead>
    <tbody id="tbody">
{all_rows_html}
    </tbody>
  </table>
</div>

<div class="foot">
  Both models max 100 pts &nbsp;|&nbsp; KEEP / REVIEW / ARCHIVE apply only to cadences with ≥100 people acted on (≥75 KEEP · 50–74 REVIEW · &lt;50 ARCHIVE) &nbsp;|&nbsp; LOW SAMPLE = &lt;100 people (scored &amp; shown, not bucketed) &nbsp;|&nbsp; NO DATA = no one acted on<br>
  BDR: Mtg ≥15%=35, ≥5%=20 &nbsp;· Reply ≥10%=30, ≥5%=22, ≥2%=13 &nbsp;· Connect ≥15%=20, ≥7%=13, ≥3%=6 &nbsp;· Open ≥50%=15, ≥35%=10, ≥20%=5<br>
  SDR: Mtg ≥10%=35, ≥5%=20, ≥2%=13 &nbsp;· Reply ≥3%=30, ≥1%=22 &nbsp;· Connect ≥15%=20, ≥7%=13, ≥3%=6 &nbsp;· Open ≥35%=15, ≥25%=10, ≥15%=5
</div>

<script id="cadenceData">
// Full per-row data (every column, every run) so the CSV export carries complete
// line-item info — not the rounded text shown in the table.
const ALL_ROWS = {rows_json};
// Cadences already confirmed-for-archive in the committed archive_confirmed.csv.
const SERVER_CONFIRMED = {confirmed_json};
// Column order of cadence_scores_master.csv — export uses this + the 2 archive cols.
const CSV_FIELDS = {fields_json};
</script>
<script>
const tbody=document.getElementById('tbody');
const allRows=Array.from(tbody.querySelectorAll('tr'));
let sc=5,sd=-1;
function normPilot(s){{return s.toUpperCase().replace(/[^A-Z0-9]/g,'');}}
// The 15 Pilot cadences (exact names, whitespace/punctuation-normalized so minor
// spacing drift between weekly runs doesn't break the match).
const PILOT_SET=new Set(["SDRDEMOREQENUSCNVPREDEMO","SDRMANAGETRIALENUSCNVTRIALON","SDRDEMOREQWEBINARENUSCNVPREDEMO","SDRWEBPRICINGENUSCNV","SDRSOFTWAREADVICEENUSCNV","BDRVELOCITYTRANSACTIONALAIENUSCNV","BDRVELOCITYLITIGATIONAIENUSCNV","BDRVELOCITYAQLNMQLENUSCNV","BDRVELOCITYCLOSEDLOSTAIENUSCNV","BDRVELOCITYOUTBOUNDENUSCNV","BDRSTRATEGICWEBSIGHTSINTENTENUSCNV","BDRSTRATEGICAQLSEXCLDRAFTENUSCNV","BDRSTRATEGICNMQLENUSCNV","BDRSTRATEGICOBCLINTENTENUSCNV","BDRSTRATEGICOBNMQLINTENTENUSCNV"]);
function setAllVerdicts(on){{
  document.querySelectorAll('.fVerdict').forEach(cb=>cb.checked=on);
}}
function setDefaultVerdicts(){{
  document.querySelectorAll('.fVerdict').forEach(cb=>{{
    cb.checked=(cb.value==='KEEP'||cb.value==='REVIEW'||cb.value==='ARCHIVE');
  }});
}}
let cnvOnly=false;
function toggleCnv(){{
  cnvOnly=!cnvOnly;
  const b=document.getElementById('cnvBtn');
  b.style.background=cnvOnly?'#2563eb':'#fff';
  b.style.color=cnvOnly?'#fff':'#2563eb';
  if(cnvOnly){{
    // Mutually exclusive with Pilot — turning this on turns Pilot off.
    pilotOnly=false;
    const pb=document.getElementById('pilotBtn');
    pb.style.background='#fff';
    pb.style.color='#7c3aed';
    setAllVerdicts(true); // most CNV cadences are Low Sample/No Data — show them by default
  }}else if(!pilotOnly){{
    setDefaultVerdicts();
  }}
  filter();
}}

let pilotOnly=false;
function togglePilot(){{
  pilotOnly=!pilotOnly;
  const b=document.getElementById('pilotBtn');
  b.style.background=pilotOnly?'#7c3aed':'#fff';
  b.style.color=pilotOnly?'#fff':'#7c3aed';
  if(pilotOnly){{
    // Mutually exclusive with Project Precision — turning this on turns it off.
    cnvOnly=false;
    const cb=document.getElementById('cnvBtn');
    cb.style.background='#fff';
    cb.style.color='#2563eb';
    setAllVerdicts(true);
  }}else if(!cnvOnly){{
    setDefaultVerdicts();
  }}
  filter();
}}

// ── Archive-Confirmed state ─────────────────────────────────────────────────
// localStorage gives instant persistence across reloads AND across the Friday
// regeneration (boxes stay ticked on this browser). The downloaded
// archive_confirmed.csv is the durable, shared master record the scorer reads back.
const LS_KEY='cadenceArchiveConfirmed';            // {{cid:{{c:bool,t:isoDate}}}}
function loadLS(){{ try{{return JSON.parse(localStorage.getItem(LS_KEY))||{{}};}}catch(e){{return {{}};}} }}
function saveLS(m){{ try{{localStorage.setItem(LS_KEY,JSON.stringify(m));}}catch(e){{}} }}
function todayISO(){{ return new Date().toISOString().slice(0,10); }}

// Fired when any checkbox toggles. Treats Archive Confirmed as per-cadence:
// every row for that cadence_id mirrors the new state.
function onArch(box){{
  const cid=box.dataset.cid, on=box.checked;
  const m=loadLS();
  m[cid]={{c:on, t:on?(((m[cid]||{{}}).t)||SERVER_CONFIRMED[cid]||todayISO()):''}};
  saveLS(m);
  document.querySelectorAll('input.archChk[data-cid="'+cid+'"]').forEach(b=>{{b.checked=on;}});
  updateArchCount();
}}

// Apply saved state on load: localStorage override wins; otherwise the
// server-rendered (committed-file) state already set by the generator stands.
function applyArchState(){{
  const m=loadLS();
  document.querySelectorAll('input.archChk').forEach(b=>{{
    const cid=b.dataset.cid;
    if(Object.prototype.hasOwnProperty.call(m,cid)) b.checked=!!m[cid].c;
  }});
  updateArchCount();
}}

// Distinct confirmed cadence_ids (deduped — same cadence can appear across runs).
function confirmedCids(){{
  const s=new Set();
  document.querySelectorAll('input.archChk:checked').forEach(b=>s.add(b.dataset.cid));
  return s;
}}
function updateArchCount(){{
  const n=confirmedCids().size;
  const el=document.getElementById('archCount'); if(el) el.textContent='('+n+')';
}}

function csvCell(v){{
  v=(v===null||v===undefined)?'':String(v);
  return /[",\\n]/.test(v)?'"'+v.replace(/"/g,'""')+'"':v;
}}

// ── Archive CSV builder (APPEND-MERGE — never duplicates, never drops rows) ───
// Existing rows already on disk are preserved verbatim (incl. their original
// confirmed_at); only cadence_ids NOT already in the file are appended.
// Dedupe key = cadence_id. Un-ticking a box does NOT remove an existing row.
function latestRowFor(cid){{
  let best=null;
  ALL_ROWS.forEach(r=>{{ if(String(r.cadence_id||'').trim()!==cid) return;
    if(!best||String(r.run_date||'')>String(best.run_date||'')) best=r; }});
  return best;
}}
function archiveLineFor(cid,m){{
  const r=latestRowFor(cid)||{{}};
  const when=((m[cid]||{{}}).t)||SERVER_CONFIRMED[cid]||todayISO();
  return CSV_FIELDS.map(f=>csvCell(r[f])).concat(['TRUE',csvCell(when)]).join(',');
}}
function parseCSVLine(line){{
  const out=[]; let cur='',q=false;
  for(let i=0;i<line.length;i++){{ const ch=line[i];
    if(q){{ if(ch==='"'){{ if(line[i+1]==='"'){{cur+='"';i++;}} else q=false; }} else cur+=ch; }}
    else {{ if(ch===','){{out.push(cur);cur='';}} else if(ch==='"'){{q=true;}} else cur+=ch; }}
  }}
  out.push(cur); return out;
}}
// Read the file already on disk (via the saved handle) so we can append to it.
async function readExistingArchive(handle){{
  try{{
    let text=await (await handle.getFile()).text();
    text=text.replace(/\\r\\n/g,'\\n').replace(/\\r/g,'\\n');
    const rows=text.split('\\n').filter(l=>l.length);
    if(!rows.length) return {{header:null,order:[],byId:{{}}}};
    const cidIdx=CSV_FIELDS.indexOf('cadence_id');
    const order=[], byId={{}};
    for(let i=1;i<rows.length;i++){{
      const cid=String(parseCSVLine(rows[i])[cidIdx]||'').trim();
      if(!cid||byId[cid]) continue;
      byId[cid]=rows[i]; order.push(cid);
    }}
    return {{header:rows[0],order:order,byId:byId}};
  }}catch(e){{ return null; }}
}}
// Merge: keep every existing row, append only the confirmed cadences that are missing.
function buildMergedCSV(existing){{
  const m=loadLS();
  const header=(existing&&existing.header)?existing.header
              :CSV_FIELDS.concat(['archive_confirmed','confirmed_at']).join(',');
  const lines=[header]; const seen={{}};
  if(existing) existing.order.forEach(cid=>{{ lines.push(existing.byId[cid]); seen[cid]=1; }});
  let added=0;
  Array.from(confirmedCids()).sort().forEach(cid=>{{
    if(!seen[cid]){{ lines.push(archiveLineFor(cid,m)); added++; }}
  }});
  buildMergedCSV._added=added; buildMergedCSV._total=lines.length-1;
  return lines.join('\\n')+'\\n';
}}

function toggleDD(id){{
  const p=document.getElementById(id), wasOpen=p.classList.contains('open');
  document.querySelectorAll('.dd-panel').forEach(x=>x.classList.remove('open'));
  if(!wasOpen) p.classList.add('open');
}}
document.addEventListener('click',e=>{{
  if(!e.target.closest('.dd')) document.querySelectorAll('.dd-panel').forEach(x=>x.classList.remove('open'));
}});

function filter(){{
  const d=document.getElementById('fDate').value;
  const teams=Array.from(document.querySelectorAll('.fTeam:checked')).map(c=>c.value.toUpperCase());
  const verdicts=Array.from(document.querySelectorAll('.fVerdict:checked')).map(c=>c.value);
  const s=document.getElementById('fSearch').value.toLowerCase();
  document.getElementById('tBtn').textContent=teams.length?('Team ('+teams.length+')'):'Team (all)';
  document.getElementById('vBtn').textContent=verdicts.length===5?'Verdict (all)':('Verdict ('+verdicts.length+')');
  let vis=0,k=0,rv=0,ar=0,lo=0,nd=0;
  allRows.forEach(r=>{{
    const dateOk=!d||r.dataset.date===d;
    const nameU=r.cells[1].textContent.toUpperCase();
    const teamOk=teams.length===0||teams.some(tm=>{{
      if(tm==='SDR')    return nameU.includes('SDR')&&!nameU.includes('BDR');
      if(tm==='BDR-S')  return nameU.includes('BDR-S')||nameU.includes('BDR - S')||nameU.includes('STRATEGIC')||nameU.includes('STRAT');
      if(tm==='BDR-V')  return nameU.includes('BDR-V')||nameU.includes('BDR - V')||nameU.includes('BDRV')||nameU.includes('VELOCITY');
      if(tm==='BDR-MM') return nameU.includes('BDR-MM')||nameU.includes('BDR - MM')||nameU.includes('MID-MARKET');
      if(tm==='BDR-CS') return nameU.includes('BDR-CS')||nameU.includes('BDR - CS');
      return nameU.includes(tm);
    }});
    const searchOk=!s||r.cells[1].textContent.toLowerCase().includes(s);
    const cnvOk=!cnvOnly||nameU.includes('CNV');
    const pilotOk=!pilotOnly||PILOT_SET.has(normPilot(r.cells[1].textContent));
    const vd=r.dataset.verdict;
    // KPI cards reflect Date + Team + Search + Project Precision/Pilot scope (not the Verdict
    // picker) — so they update as you filter, but always show every verdict's count for that scope.
    const kpiScope=dateOk&&teamOk&&searchOk&&cnvOk&&pilotOk;
    if(kpiScope){{if(vd==='KEEP')k++;else if(vd==='REVIEW')rv++;else if(vd==='ARCHIVE')ar++;else if(vd==='LOW SAMPLE')lo++;else if(vd==='NO DATA')nd++;}}
    // Verdict picker stays live even inside Project Precision/Pilot scope — those toggles
    // pre-check every Verdict box (see toggleCnv()/togglePilot()) instead of bypassing the
    // picker, so users can still narrow further by verdict while scoped in.
    const show=kpiScope&&verdicts.includes(vd);
    r.style.display=show?'':'none';
    if(show)vis++;
  }});
  document.getElementById('rowCount').textContent=vis+' cadences';
  document.getElementById('kpiKeep').textContent=k;
  document.getElementById('kpiReview').textContent=rv;
  document.getElementById('kpiArchive').textContent=ar;
  document.getElementById('kpiLow').textContent=lo;
  document.getElementById('kpiNoData').textContent=nd;
}}

function sort(col){{
  if(sc===col)sd*=-1;else{{sc=col;sd=-1;}}
  document.querySelectorAll('thead th').forEach((th,i)=>{{th.className=i===col?(sd===1?'asc':'desc'):'';}} );
  const rows=allRows.filter(r=>r.style.display!=='none');
  rows.sort((a,b)=>{{
    const acb=a.cells[col]?.querySelector('input[type=checkbox]');
    const bcb=b.cells[col]?.querySelector('input[type=checkbox]');
    if(acb&&bcb) return ((acb.checked?1:0)-(bcb.checked?1:0))*sd;
    const av=a.cells[col]?.textContent.trim()||'';
    const bv=b.cells[col]?.textContent.trim()||'';
    const an=parseFloat(av.replace(/[^0-9.\-]/g,''));
    const bn=parseFloat(bv.replace(/[^0-9.\-]/g,''));
    if(!isNaN(an)&&!isNaN(bn))return(an-bn)*sd;
    return av.localeCompare(bv)*sd;
  }});
  rows.forEach(r=>tbody.appendChild(r));
}}

// ── One-click save to archive_confirmed.csv (File System Access API) ──────────
// First save: pick/create the file in the project folder (grant once). The handle
// is remembered (IndexedDB) so later saves write in one click. Browsers without the
// API (e.g. Safari) fall back to a normal download you drop into the folder.
const FS_DB='cadenceFS', FS_STORE='handles', FS_KEY='archiveCsv';
function fsOpen(){{return new Promise((res,rej)=>{{const r=indexedDB.open(FS_DB,1);r.onupgradeneeded=()=>r.result.createObjectStore(FS_STORE);r.onsuccess=()=>res(r.result);r.onerror=()=>rej(r.error);}});}}
async function fsPut(h){{const db=await fsOpen();return new Promise((res,rej)=>{{const tx=db.transaction(FS_STORE,'readwrite');tx.objectStore(FS_STORE).put(h,FS_KEY);tx.oncomplete=()=>res();tx.onerror=()=>rej(tx.error);}});}}
async function fsGet(){{const db=await fsOpen();return new Promise(res=>{{const tx=db.transaction(FS_STORE,'readonly');const q=tx.objectStore(FS_STORE).get(FS_KEY);q.onsuccess=()=>res(q.result||null);q.onerror=()=>res(null);}});}}
async function fsPerm(h){{const o={{mode:'readwrite'}};if((await h.queryPermission(o))==='granted')return true;if((await h.requestPermission(o))==='granted')return true;return false;}}

let archHandle=null;
async function saveArchiveCSV(){{
  if(window.showSaveFilePicker){{
    try{{
      if(!archHandle) archHandle=await fsGet();
      if(archHandle && !(await fsPerm(archHandle))) archHandle=null;
      if(!archHandle){{
        archHandle=await window.showSaveFilePicker({{suggestedName:'archive_confirmed.csv',types:[{{description:'CSV file',accept:{{'text/csv':['.csv']}}}}]}});
        await fsPut(archHandle);
      }}
      const existing=await readExistingArchive(archHandle);   // read what's on disk first
      const csv=buildMergedCSV(existing);                     // keep existing rows, append missing
      const w=await archHandle.createWritable();
      await w.write(csv); await w.close();
      const added=buildMergedCSV._added, total=buildMergedCSV._total;
      toast(added>0 ? ('Added '+added+' new — '+total+' total in '+archHandle.name)
                    : ('No new cadences — '+total+' already in '+archHandle.name));
      return;
    }}catch(e){{ if(e&&e.name==='AbortError') return; console.warn('FS save failed; downloading instead:',e); }}
  }}
  // Fallback (no disk access): write the full current confirmed set.
  const csv=buildMergedCSV(null);
  downloadArchiveCSV(csv);
}}
function downloadArchiveCSV(csv){{
  const blob=new Blob([csv],{{type:'text/csv;charset=utf-8'}});
  const a=document.createElement('a');
  a.href=URL.createObjectURL(blob); a.download='archive_confirmed.csv';
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(()=>URL.revokeObjectURL(a.href),1500);
  toast('Downloaded archive_confirmed.csv ('+buildMergedCSV._total+') — merge it into the project folder');
}}
function toast(msg){{
  let t=document.getElementById('archToast');
  if(!t){{t=document.createElement('div');t.id='archToast';t.style.cssText='position:fixed;bottom:20px;left:50%;transform:translateX(-50%);background:#111827;color:#fff;padding:10px 16px;border-radius:8px;font-size:13px;font-weight:600;box-shadow:0 6px 20px rgba(0,0,0,.25);z-index:50;opacity:0;transition:opacity .2s';document.body.appendChild(t);}}
  t.textContent=msg; t.style.opacity='1';
  clearTimeout(t._h); t._h=setTimeout(()=>{{t.style.opacity='0';}},3200);
}}

window.onload=()=>{{
  applyArchState();
  const sel=document.getElementById('fDate');
  if(sel.options.length>1){{sel.selectedIndex=1;filter();sort(5);}}
  else filter();
}};
</script>
</body>
</html>"""


# ── Main ───────────────────────────────────────────────────────────────────────
def main():
    print("=" * 62)
    print("Cadence Performance Scorer — Salesloft API v3.0")
    print(f"Run: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print("=" * 62)

    # ── Load credentials ──────────────────────────────────────────────────────
    token = os.environ.get("SALESLOFT_API_TOKEN", "")
    if not token:
        if not os.path.exists(CREDS_FILE):
            print(f"\n[ERR] Missing credentials: {CREDS_FILE}")
            print('      Create it with: {"api_token": "v2_ak_..."}')
            print("      Or set env var: SALESLOFT_API_TOKEN")
            return 1
        with open(CREDS_FILE, encoding="utf-8") as f:
            creds = json.load(f)
        token = creds.get("api_token", "")
    if not token or token.startswith("YOUR_"):
        print("[ERR] api_token not configured.")
        return 1

    run_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # ── Phase 1: Fetch active TEAM BDR/SDR cadences ──────────────────────────
    # Filters (per RevOps direction, 2026-06-10):
    #   • status[]=active        → archived cadences excluded at the API
    #   • team_cadence == True   → exclude reps' personal / individual cadences
    # Both filters are applied defensively: each only fires when its field is
    # actually present in the payload, so an unexpected field name can never
    # silently drop every cadence. The one-time [debug] line prints the real
    # field names from the live API (this sandbox can't reach Salesloft) so the
    # keys can be confirmed/locked in after the first real run.
    print("\n[1/4] Fetching active team BDR/SDR cadences…")
    cadences = {}   # id → {id, name, model, owner, created_at}
    total_seen    = 0
    excl_personal = 0   # dropped: not a team cadence
    excl_archived = 0   # dropped: archived
    excl_region   = 0   # dropped: EMEA / CAN / APAC (excluded for now)
    page = 1
    while True:
        # Build URL manually — status[] brackets must not be percent-encoded
        data = _get(token, f"/cadences?status[]=active&per_page=100&page={page}")
        time.sleep(REQUEST_DELAY)
        if data is None:
            print("  [WARN] Cadences request failed — retrying once…")
            time.sleep(2)
            data = _get(token, "/cadences", {"per_page": 100, "page": page})
            time.sleep(REQUEST_DELAY)
        if data is None:
            print("  [ERR] Could not fetch cadences. Aborting.")
            return 1
        records = data.get("data", [])
        if page == 1 and records:
            print(f"  [debug] cadence record fields: {sorted(records[0].keys())}")
        total_seen += len(records)
        for c in records:
            name  = c.get("name") or ""
            model = detect_model(name)
            if model is None:
                continue
            # Region exclusion — EMEA/CAN/APAC anywhere, or a name that STARTS with CAD.
            if EXCLUDED_REGION_RE.search(name) or CAD_PREFIX_RE.search(name):
                excl_region += 1
                continue
            # Exclude archived (defensive — the query already requests active)
            if c.get("archived_at") or str(c.get("archived", "")).strip().lower() == "true":
                excl_archived += 1
                continue
            # Team cadences only — exclude personal copies. Applied only when
            # the 'team_cadence' field is present (see [debug] line above).
            if "team_cadence" in c and c.get("team_cadence") is not True:
                excl_personal += 1
                continue
            cid        = c.get("id")
            # owner/creator come back as ID references ({"id":N,"_href":...}) with
            # no name — we resolve the creator ID to a name after Phase 1.
            creator    = c.get("creator") or c.get("owner") or {}
            created    = (c.get("created_at") or "")[:10]
            cadences[cid] = {
                "id": cid, "name": name, "model": model,
                "created_by_id": creator.get("id"), "created_by": "",
                "created_at": created,
            }
        paging = data.get("metadata", {}).get("paging", {})
        if not paging.get("next_page"):
            break
        page += 1

    print(f"  → {len(cadences)} active team BDR/SDR cadences kept "
          f"(from {total_seen} total; excluded {excl_personal} personal, "
          f"{excl_archived} archived, {excl_region} EMEA/CAN/APAC)")
    if not cadences:
        print("  [ERR] No active team BDR/SDR cadences found.")
        print("        If the [debug] field list above has no 'team_cadence' key,")
        print("        the filter field name differs — send that line to fix the script.")
        return 1

    # ── Phase 2: Fetch cadence stats ─────────────────────────────────────────
    # Resolve creator IDs → names for the "Created by" column.
    print("  Resolving creator names from /v2/users…")
    user_map = fetch_user_map(token)
    for cad_row in cadences.values():
        cad_row["created_by"] = user_map.get(cad_row.get("created_by_id"), "")

    print("\n[2/4] Fetching cadence stats…")
    stats = {}  # cadence_id → stats dict
    ids   = list(cadences.keys())
    for i, cid in enumerate(ids, 1):
        resp = _get(token, f"/cadence_stats/{cid}")
        time.sleep(REQUEST_DELAY)
        stats[cid] = resp.get("data", {}) if resp else {}
        if i % 50 == 0 or i == len(ids):
            print(f"  {i}/{len(ids)} stats fetched…")

    # ── Phase 3: Connected calls — cumulative cache + weekly delta ───────────
    # We no longer stream all-time connected calls every run (≈1.4M records,
    # hours). build_connected_cache.py backfills an all-time per-cadence count
    # ONCE into connected_calls_cache.json; here we fetch only the delta (calls
    # created since the saved cursor), add it to the cache, and read cumulative
    # counts. connect_rate = cached all-time connected / lifetime calls_count.
    print("\n[3/4] Connected calls — updating cache (delta since last run)…")
    cache = _load_cache()
    if not cache.get("backfill_complete"):
        print("  [WARN] connected-calls backfill NOT complete — run build_connected_cache.py.")
        print("         Connect rate will be partial/zero until the backfill finishes.")
        connected_calls = {int(k): v for k, v in cache.get("counts", {}).items()}
    else:
        connected_calls, new_n, pages, _ = _update_connected_cache(token, cache)
        print(f"  → delta: +{new_n:,} new connected calls over {pages} page(s); "
              f"cache now covers {len(connected_calls)} cadences.")

    # ── Phase 4: Score ────────────────────────────────────────────────────────
    print("\n[4/4] Scoring…")
    scored_rows = []
    for cid in sorted(cadences, key=lambda x: cadences[x]["name"]):
        c   = cadences[cid]
        s   = stats.get(cid) or {}

        emails_sent      = int(s.get("sent_emails_count")     or 0)
        people_acted_on  = int(s.get("people_acted_on_count") or 0)
        viewed_count     = int(s.get("viewed_count")          or 0)
        replied_count    = int(s.get("replied_count")         or 0)
        calls_count      = int(s.get("calls_count")           or 0)
        meetings_count   = int(s.get("meetings_booked_count") or 0)
        connects         = connected_calls.get(cid, 0)

        open_rate    = (viewed_count   / emails_sent  * 100) if emails_sent  > 0 else 0.0
        reply_rate   = (replied_count  / emails_sent  * 100) if emails_sent  > 0 else 0.0
        meeting_rate = (meetings_count / emails_sent  * 100) if emails_sent  > 0 else 0.0
        connect_rate = (connects       / calls_count  * 100) if calls_count  > 0 else 0.0

        low_sample = people_acted_on < MIN_PEOPLE

        pts_m, pts_r, pts_c, pts_o, total_score = score_cadence(
            c["model"], meeting_rate, reply_rate, connect_rate, open_rate
        )
        cadence_verdict = get_verdict(total_score)
        # Verdict buckets — every cadence gets exactly one:
        #  • Zero activity (nobody acted on) → NO DATA.
        #  • Low sample (<100 people) → LOW SAMPLE — scored and shown, but NOT
        #    bucketed as KEEP/REVIEW/ARCHIVE (too thin to judge).
        #  • Only cadences with ≥100 people acted on get KEEP/REVIEW/ARCHIVE by score.
        if people_acted_on == 0:
            cadence_verdict = "NO DATA"
            total_score = 0
        elif low_sample:
            cadence_verdict = "LOW SAMPLE"

        scored_rows.append({
            "run_date":         run_date,
            "period_label":     "all-time",
            "cadence_id":       cid,
            "cadence_name":     c["name"],
            "score":            total_score,
            "verdict":          cadence_verdict,
            "model_applied":    c["model"],
            "meeting_rate":     round(meeting_rate, 2),
            "reply_rate":       round(reply_rate, 2),
            "connect_rate":     round(connect_rate, 2),
            "open_rate":        round(open_rate, 2),
            "skip_rate":        0.0,
            "steps_completed":  people_acted_on,
            "emails_sent":      emails_sent,
            "created_by":       c["created_by"],
            "pts_meeting_rate": pts_m,
            "pts_reply_rate":   pts_r,
            "pts_connect_rate": pts_c,
            "pts_open_rate":    pts_o,
            "pts_skip_rate":    0,
            "low_sample":       low_sample,
            "created_at":       c["created_at"],
        })

    keep_n    = sum(1 for r in scored_rows if r["verdict"] == "KEEP")
    review_n  = sum(1 for r in scored_rows if r["verdict"] == "REVIEW")
    archive_n = sum(1 for r in scored_rows if r["verdict"] == "ARCHIVE")
    low_n     = sum(1 for r in scored_rows if r["low_sample"])
    print(
        f"  → {len(scored_rows)} scored  |  "
        f"{keep_n} KEEP  {review_n} REVIEW  {archive_n} ARCHIVE  "
        f"({low_n} low sample)"
    )

    # ── Phase 5: Persist ──────────────────────────────────────────────────────
    print("\n[5/5] Writing outputs…")
    append_to_csv(scored_rows)

    all_csv_rows = read_all_csv()
    html = generate_html(all_csv_rows, run_date)
    with open(MASTER_HTML, "w", encoding="utf-8") as f:
        f.write(html)
    print(
        f"  → {os.path.basename(MASTER_HTML)} regenerated  "
        f"({len(all_csv_rows)} total rows across all runs)"
    )

    print(f"\n✓ Done — {len(scored_rows)} cadences scored  |  Run date: {run_date}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
