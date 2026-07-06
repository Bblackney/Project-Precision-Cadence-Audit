#!/usr/bin/env python3
"""
salesloft_adherence_probe2.py  — READ-ONLY follow-up probe. Makes only GET requests.

Resolves the two open questions from probe 1:
  A. TEAM MAPPING: lists Salesloft groups (id -> name) and shows which user attribute
     (group / team / job_role / role) cleanly identifies SDR / BDR-S / BDR-V / BDR-MM / BDR-CS.
  B. ON-TIME FEASIBILITY: tests whether a COMPLETED action is still retrievable by id with
     its due_on. If yes -> On-Time is directly derivable (activity timestamp vs action.due_on).
     If no  -> we accumulate a daily "actions ledger" instead.

Output prints to console AND salesloft_adherence_probe2_output.txt (PII masked).
Run:
    cd "<project folder>"
    python3 salesloft_adherence_probe2.py
"""
import os, sys, json, time, urllib.parse, urllib.request, urllib.error
from collections import Counter

BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
CREDS_FILE = os.path.join(BASE_DIR, "salesloft_credentials.json")
OUT_FILE   = os.path.join(BASE_DIR, "salesloft_adherence_probe2_output.txt")
SL = "https://api.salesloft.com/v2"
DELAY = 0.5
USER_PAGES = 3                 # sample 300 users to see distinct team/job_role values
PII = {"name","first_name","last_name","full_name","email","email_address","phone","phone_number"}

_fh = None
def out(*a):
    s = " ".join(str(x) for x in a); print(s)
    if _fh: _fh.write(s + "\n")

def load_token():
    t = os.environ.get("SALESLOFT_API_TOKEN", "")
    if not t and os.path.exists(CREDS_FILE):
        with open(CREDS_FILE, encoding="utf-8") as f:
            t = json.load(f).get("api_token", "")
    if not t or t.startswith("YOUR_"):
        out("[ERR] no API token"); sys.exit(1)
    return t

def get(tok, path, params=None, _r=0):
    u = f"{SL}{path}" + ("?" + urllib.parse.urlencode(params, doseq=True) if params else "")
    req = urllib.request.Request(u, headers={"Authorization": f"Bearer {tok}", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.getcode(), json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 429 and _r < 4:
            time.sleep(30 * 2 ** _r); return get(tok, path, params, _r + 1)
        return e.code, {"_error": e.read().decode("utf-8", "replace")[:160]}
    except Exception as e:
        return None, {"_error": str(e)}

def page(tok, path, params=None):
    _, d = get(tok, path, params); time.sleep(DELAY)
    return (d or {}).get("data", []) or []

def sval(v):
    if isinstance(v, dict): return v.get("name") or v.get("id") or json.dumps(v)
    return v

def main():
    global _fh
    _fh = open(OUT_FILE, "w", encoding="utf-8")
    tok = load_token()
    out("="*78); out("SALESLOFT ADHERENCE PROBE 2 (read-only)"); out("="*78)

    # ── A. GROUPS + which user attribute = team ──────────────────────────────
    out("\n### A1. GROUPS (id -> name) ###")
    groups = {}
    gp = 1
    while gp <= 6:
        code, d = get(tok, "/groups", {"per_page": 100, "page": gp}); time.sleep(DELAY)
        recs = (d or {}).get("data", []) or []
        for g in recs:
            groups[g.get("id")] = g.get("name")
        if not (d or {}).get("metadata", {}).get("paging", {}).get("next_page"):
            break
        gp += 1
    out(f"  total groups: {len(groups)}")
    for gid, gn in list(groups.items())[:60]:
        out(f"    {gid}: {gn!r}")
    hits = [f"{gid}:{gn}" for gid, gn in groups.items()
            if gn and any(k in gn.upper() for k in ("BDR", "SDR", "XDR"))]
    out(f"  groups whose name has BDR/SDR/XDR: {hits or 'NONE'}")

    out("\n### A2. USER ATTRIBUTES — which one splits the teams? ###")
    users = []
    for p in range(1, USER_PAGES + 1):
        users += page(tok, "/users", {"per_page": 100, "page": p})
    out(f"  sampled users: {len(users)}")
    if users:
        u0 = users[0]
        out(f"  sample: team={json.dumps(u0.get('team'))}  job_role={u0.get('job_role')!r}  "
            f"role={sval(u0.get('role'))!r}  group={json.dumps(u0.get('group'))}  group_id={u0.get('group_id')}")
        def dist(label, fn):
            c = Counter(fn(u) for u in users)
            out(f"\n  distinct {label} (value -> #users), top 30:")
            for v, n in c.most_common(30):
                out(f"    {v!r}: {n}")
        dist("team", lambda u: sval(u.get("team")))
        dist("job_role", lambda u: u.get("job_role"))
        dist("role", lambda u: sval(u.get("role")))
        dist("group name (resolved)", lambda u: groups.get(
            (u.get("group") or {}).get("id") if isinstance(u.get("group"), dict) else u.get("group_id")))
    out("\n  >>> Tell me which attribute cleanly = SDR / BDR-S / BDR-V / BDR-MM / BDR-CS.")

    # ── B. Is a COMPLETED action retrievable with its due_on? ────────────────
    out("\n### B. ON-TIME FEASIBILITY — can we read a completed action's due_on? ###")
    # find a cadence-linked call activity that references an action
    acts = page(tok, "/activities/calls", {"per_page": 25})
    cand = next((a for a in acts if (a.get("action") or {}).get("id") and (a.get("cadence") or {}).get("id")), None)
    if not cand:
        out("  no cadence-linked call activity with an action id on the first page; try emails")
        acts = page(tok, "/activities/emails", {"per_page": 25})
        cand = next((a for a in acts if (a.get("action") or {}).get("id") and (a.get("cadence") or {}).get("id")), None)
    if not cand:
        out("  [!] couldn't find a completed cadence step with an action id to test. Re-run later.")
    else:
        aid = cand["action"]["id"]
        out(f"  testing completed action id={aid} (from a logged cadence step)")
        code, d = get(tok, f"/actions/{aid}"); time.sleep(DELAY)
        out(f"  GET /actions/{aid} -> HTTP {code}")
        if code == 200 and isinstance(d, dict) and d.get("data"):
            rec = d["data"]
            out(f"  RETRIEVABLE. due_on={rec.get('due_on')}  due={rec.get('due')}  status={rec.get('status')}")
            out("  >>> RESULT: completed actions keep due_on -> On-Time is DIRECTLY derivable "
                "(activity created_at vs action.due_on). No ledger needed.")
        else:
            out(f"  NOT retrievable (resp: {json.dumps(d)[:160]}).")
            out("  >>> RESULT: completed actions drop out -> we accumulate a DAILY actions ledger "
                "(snapshot open actions + due_on each run) to compute On-Time over time.")

    out("\n" + "="*78)
    out("DONE. Paste salesloft_adherence_probe2_output.txt back.")
    out("="*78)
    _fh.close()

if __name__ == "__main__":
    main()
