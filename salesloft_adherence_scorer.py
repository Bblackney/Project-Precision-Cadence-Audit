#!/usr/bin/env python3
"""
salesloft_adherence_scorer.py — DAILY rep-level cadence adherence pull (Salesloft API v2).

Companion to salesloft_cadence_scorer.py (cadence QUALITY, weekly). Measures cadence
ADHERENCE by rep x cadence, DAILY, on Brett's Mac via launchd.

SCOPE IS USAGE-BASED (not name-filtered): we take the cadences the mapped XDRs are
actually working, discovered from their OPEN ACTIONS, then pull memberships for just
those cadences. A cadence is in scope because a rep has live work in it, regardless of
its name. (Team comes from the rep's Salesloft group, never the cadence name.)

Each run:
  1. user -> team map from /v2/users + GROUP_TEAM_MAP (captures each user's guid).
  2. /v2/actions filtered by user_guid[] (admin token, team-wide) -> every OPEN action for
     our XDRs. Gives: overdue snapshot (due_on < now) + days-late, the cadence universe,
     and the daily actions-ledger (for On-Time over time).
  3. For each cadence in that universe: /v2/cadence_memberships?cadence_id -> active
     (currently_on_cadence), added (this_week/last_week/last_30 by added_at), completed,
     removed (removed + removed_no_action).
  4. Append dated rows to adherence_scores_master.csv; write adherence_data.json.

Reliable day one: active, added, overdue, days-late, cadence-completion, premature-removal.
On-Time fills in once the ledger has history. READS ONLY from Salesloft.

NOTE: /actions team-wide + user_guid requires an ADMIN token (same token the weekly scorer
uses). Non-admin tokens only see their own actions.
"""

import os, sys, json, time, csv, urllib.parse, urllib.request, urllib.error
from datetime import datetime, timezone, timedelta

# ── Paths ───────────────────────────────────────────────────────────────────
BASE_DIR    = os.path.dirname(os.path.abspath(__file__))
CREDS_FILE  = os.path.join(BASE_DIR, "salesloft_credentials.json")
MASTER_CSV  = os.path.join(BASE_DIR, "adherence_scores_master.csv")
DATA_JSON   = os.path.join(BASE_DIR, "adherence_data.json")
LEDGER_FILE = os.path.join(BASE_DIR, "actions_ledger.json")

# ── Constants ─────────────────────────────────────────────────────────────────
SL_BASE_URL   = "https://api.salesloft.com/v2"
REQUEST_DELAY = 0.5
LEDGER_RETENTION_DAYS = 60
GUID_BATCH = 25                 # user_guids per /actions request (URL length safe)

# ── Rep -> team mapping (Salesloft group_id -> team). Confirmed with Brett 2026-06-24. ──
# Team = the rep's Salesloft GROUP (the only attribute with squad granularity; `team` is the
# org-level team and `job_role` is only xDR/AE). Edit this dict when pods are added/renamed.
GROUP_TEAM_MAP = {
    6558: "SDR", 16916: "SDR", 29779: "SDR", 29778: "SDR", 29777: "SDR",
    6559: "BDR-S", 33159: "BDR-S", 30761: "BDR-S", 30760: "BDR-S", 30759: "BDR-S",   # Strategic
    10818: "BDR-V", 26221: "BDR-V", 22492: "BDR-V", 22491: "BDR-V",                   # Velocity
    10588: "BDR-MM", 30807: "BDR-MM", 30808: "BDR-MM",                                # Mid-Market
    15583: "BDR-CS", 29529: "BDR-CS", 30366: "BDR-CS",                                # Customer Sales
    33206: "BDR-Ent",                                                                 # Enterprise
    # Excluded (unmapped -> dropped): 32948 XDR-Canada, 28639 BDR-EMEA, 16917 SDR-EMEA,
    # 12175 BDR, 30765 BDR Draft, 12176 Business Development.
}
TEAM_ORDER = ["SDR", "BDR-S", "BDR-V", "BDR-MM", "BDR-CS", "BDR-Ent"]

CSV_COLUMNS = [
    "run_date", "team", "group_name", "user_id", "rep_name", "cadence_id", "cadence_name",
    "active_people", "scheduled_people",
    "added_this_week", "added_last_week", "added_last_30",
    "completed_memberships", "removed_memberships",
    "open_actions", "overdue_actions", "days_overdue_sum",
]

# ── API helpers (mirror salesloft_cadence_scorer.py) ───────────────────────────
def _get(token, path, params=None, _retry=0):
    url = f"{SL_BASE_URL}{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params, doseq=True)
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}",
                                               "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 429 and _retry < 4:
            wait = 30 * (2 ** _retry)
            print(f"    [429] rate limited — waiting {wait}s (retry {_retry+1}/4)…", flush=True)
            time.sleep(wait); return _get(token, path, params, _retry + 1)
        print(f"    [HTTP {e.code}] {path}: {e.read().decode('utf-8','replace')[:200]}")
        return None
    except Exception as e:
        if _retry < 4:
            wait = 5 * (2 ** _retry)
            print(f"    [retry] {path}: {type(e).__name__} — waiting {wait}s…", flush=True)
            time.sleep(wait); return _get(token, path, params, _retry + 1)
        print(f"    [ERR] {path}: {e} (gave up)"); return None

def paginate(token, path, params=None):
    page = 1
    base = dict(params or {})
    while True:
        data = _get(token, path, {**base, "page": page})
        time.sleep(REQUEST_DELAY)
        if data is None:
            break
        yield from data.get("data", [])
        if not data.get("metadata", {}).get("paging", {}).get("next_page"):
            break
        page += 1

# ── utils ───────────────────────────────────────────────────────────────────
def load_token():
    tok = os.environ.get("SALESLOFT_API_TOKEN", "")
    if not tok and os.path.exists(CREDS_FILE):
        with open(CREDS_FILE, encoding="utf-8") as f:
            tok = json.load(f).get("api_token", "")
    if not tok or tok.startswith("YOUR_"):
        sys.exit("[ERR] No API token (SALESLOFT_API_TOKEN env or salesloft_credentials.json).")
    return tok

def parse_dt(s):
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc)
    except Exception:
        return None

def windows_now(now):
    monday = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    return {"this_week": (monday, now),
            "last_week": (monday - timedelta(days=7), monday),
            "last_30":   (now - timedelta(days=30), now)}

def in_window(dt, win):
    return dt is not None and win[0] <= dt < win[1]

def rid(obj):
    return obj.get("id") if isinstance(obj, dict) else obj

def chunked(seq, n):
    for i in range(0, len(seq), n):
        yield seq[i:i+n]

# ── 1) user -> team map (with guid) ────────────────────────────────────────────
def build_user_team_map(token):
    # resolve Salesloft group ids -> names (the pod/sub-group, e.g. 'BDRV Daniel')
    gnames = {}
    for g in paginate(token, "/groups", {"per_page": 100}):
        gnames[g.get("id")] = g.get("name")
    users, n = {}, 0
    for u in paginate(token, "/users", {"per_page": 100}):
        n += 1
        gid = rid(u.get("group")) or u.get("group_id")
        team = GROUP_TEAM_MAP.get(gid)
        if not team:
            continue
        uid = u.get("id")
        users[uid] = {
            "name": (u.get("name") or f"{u.get('first_name','')} {u.get('last_name','')}".strip()
                     or u.get("email", "") or f"user {uid}"),
            "team": team,
            "group_name": gnames.get(gid) or f"group {gid}",
            "guid": u.get("guid"),
        }
    print(f"  groups: {len(gnames)}; users scanned: {n}; XDRs mapped to a team: {len(users)}", flush=True)
    return users

# ── 2) open actions for our XDRs -> overdue + cadence universe + ledger ─────────
def collect_open_actions(token, users, now, ledger):
    guids = [u["guid"] for u in users.values() if u.get("guid")]
    overdue = {}                  # (uid, cid) -> {"n":x, "days":y}  (past-due open actions)
    openc = {}                    # (uid, cid) -> count of ALL open actions (queued steps)
    universe = set()              # cadence_ids the XDRs have open work in
    today = now.date().isoformat()
    n_actions = 0
    total_batches = (len(guids) + GUID_BATCH - 1) // GUID_BATCH
    print(f"  pulling open actions for {len(guids)} XDRs in {total_batches} batches…", flush=True)
    for bi, batch in enumerate(chunked(guids, GUID_BATCH), 1):
        before = n_actions
        for a in paginate(token, "/actions", {"user_guid[]": batch, "per_page": 100}):
            n_actions += 1
            if n_actions % 2000 == 0:
                print(f"    …{n_actions} actions scanned, {len(universe)} cadences so far", flush=True)
            au = rid(a.get("user"))   # actions echo user{id}; map by id
            if au not in users:
                continue
            cid = rid(a.get("cadence"))
            if cid is None:
                continue
            universe.add(cid)
            openc[(au, cid)] = openc.get((au, cid), 0) + 1   # every open action = a queued step
            aid = a.get("id")
            if aid is not None:
                e = ledger["actions"].get(str(aid))
                if e:
                    e["last_seen"] = today
                else:
                    ledger["actions"][str(aid)] = {
                        "cadence": cid, "user": au, "person": rid(a.get("person")),
                        "step": rid(a.get("step")), "due_on": a.get("due_on"),
                        "type": a.get("type"), "first_seen": today, "last_seen": today}
            due_on = parse_dt(a.get("due_on"))
            if due_on and due_on < now:
                d = overdue.setdefault((au, cid), {"n": 0, "days": 0})
                d["n"] += 1
                d["days"] += max(0, (now - due_on).days)
        print(f"    batch {bi}/{total_batches}: {n_actions} actions total "
              f"({n_actions - before} this batch), {len(universe)} cadences so far", flush=True)
    print(f"  open XDR actions: {n_actions}; cadences in use (universe): {len(universe)}", flush=True)
    return overdue, openc, universe

# ── cadence names for the universe ─────────────────────────────────────────────
def cadence_names(token, ids):
    names = {}
    for cid in ids:
        d = _get(token, f"/cadences/{cid}")
        time.sleep(REQUEST_DELAY)
        rec = (d or {}).get("data", d) or {}
        names[cid] = rec.get("name", f"cadence {cid}")
    return names

# ── 3) memberships per universe cadence ────────────────────────────────────────
def membership_metrics(token, cid, users, windows):
    per_user = {}
    for m in paginate(token, "/cadence_memberships", {"cadence_id": cid, "per_page": 100}):
        uid = rid(m.get("user"))
        if uid not in users:
            continue
        r = per_user.setdefault(uid, {"active_people": 0, "scheduled_people": 0,
                                      "added_this_week": 0, "added_last_week": 0, "added_last_30": 0,
                                      "completed_memberships": 0, "removed_memberships": 0})
        st = (m.get("current_state") or "").lower()
        if m.get("currently_on_cadence"):
            r["active_people"] += 1
        if st == "scheduled":
            r["scheduled_people"] += 1
        if st == "completed":
            r["completed_memberships"] += 1
        if st in ("removed", "removed_no_action"):
            r["removed_memberships"] += 1
        added = parse_dt(m.get("added_at"))
        if in_window(added, windows["this_week"]): r["added_this_week"] += 1
        if in_window(added, windows["last_week"]): r["added_last_week"] += 1
        if in_window(added, windows["last_30"]):   r["added_last_30"]   += 1
    return per_user

# ── ledger ──────────────────────────────────────────────────────────────────
def load_ledger():
    if os.path.exists(LEDGER_FILE):
        try:
            with open(LEDGER_FILE, encoding="utf-8") as f:
                d = json.load(f); d.setdefault("actions", {}); return d
        except Exception:
            pass
    return {"actions": {}, "updated_at": None}

def save_ledger(ledger, now):
    cutoff = (now - timedelta(days=LEDGER_RETENTION_DAYS)).date().isoformat()
    ledger["actions"] = {k: v for k, v in ledger["actions"].items()
                         if v.get("last_seen", "0") >= cutoff}
    ledger["updated_at"] = now.isoformat()
    tmp = LEDGER_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(ledger, f)
    os.replace(tmp, LEDGER_FILE)

# ── outputs ─────────────────────────────────────────────────────────────────
def write_outputs(rows, run_date, now):
    new_file = not os.path.exists(MASTER_CSV)
    with open(MASTER_CSV, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        if new_file:
            w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in CSV_COLUMNS})
    with open(DATA_JSON, "w", encoding="utf-8") as f:
        json.dump({"run_date": run_date, "generated_at": now.isoformat(),
                   "team_order": TEAM_ORDER, "rows": rows}, f)
    print(f"  wrote {len(rows)} rows -> adherence_scores_master.csv + adherence_data.json", flush=True)

# ── main ──────────────────────────────────────────────────────────────────────
def main():
    token = load_token()
    now = datetime.now(timezone.utc)
    run_date = now.date().isoformat()
    windows = windows_now(now)
    print(f"=== Adherence run {run_date} ===", flush=True)

    users = build_user_team_map(token)
    if not users:
        sys.exit("[ERR] no users mapped to a team — check GROUP_TEAM_MAP / group ids.")

    ledger = load_ledger()
    overdue, openc, universe = collect_open_actions(token, users, now, ledger)
    save_ledger(ledger, now)

    names = cadence_names(token, universe)

    # assemble rows from the union of (membership users) + (open/overdue action users) per cadence
    rows_by_key = {}
    def ensure(uid, cid):
        return rows_by_key.setdefault((uid, cid), {
            "active_people": 0, "scheduled_people": 0, "added_this_week": 0,
            "added_last_week": 0, "added_last_30": 0, "completed_memberships": 0,
            "removed_memberships": 0, "open_actions": 0, "overdue_actions": 0, "days_overdue_sum": 0})
    for i, cid in enumerate(sorted(universe), 1):
        if i % 25 == 0:
            print(f"    …memberships {i}/{len(universe)} cadences", flush=True)
        mm = membership_metrics(token, cid, users, windows)
        for uid, r in mm.items():
            ensure(uid, cid).update(r)
    for (uid, cid), n in openc.items():
        ensure(uid, cid)["open_actions"] = n
    for (uid, cid), d in overdue.items():
        row = ensure(uid, cid)
        row["overdue_actions"] = d["n"]
        row["days_overdue_sum"] = d["days"]

    rows = []
    for (uid, cid), r in rows_by_key.items():
        if uid not in users:
            continue
        rows.append({"run_date": run_date, "team": users[uid]["team"],
                     "group_name": users[uid]["group_name"],
                     "user_id": uid, "rep_name": users[uid]["name"],
                     "cadence_id": cid, "cadence_name": names.get(cid, f"cadence {cid}"), **r})

    write_outputs(rows, run_date, now)
    print(f"  ledger now tracking {len(ledger['actions'])} open actions (On-Time history building).", flush=True)
    print("=== done ===", flush=True)

if __name__ == "__main__":
    main()
