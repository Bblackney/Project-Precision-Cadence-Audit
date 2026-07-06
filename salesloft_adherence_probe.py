#!/usr/bin/env python3
"""
salesloft_adherence_probe.py  — READ-ONLY API probe for the adherence dashboard build.

Purpose: confirm the exact Salesloft v2 field shapes the adherence scorer will depend on,
BEFORE writing the production scorer. Makes only GET requests. Writes nothing to Salesloft.

It checks:
  1. Users -> the group field used for rep->team mapping (lists distinct groups).
  2. Active, team, BDR/SDR cadences (reusing the scorecard's filters) -> picks samples.
  3. cadence_memberships -> current_state values, added_at, user (assignee), counts.
  4. steps -> step type distribution (email/phone/integration/other); flags any text steps.
  5. actions (queried via step_id, per Salesloft best practice) -> due_on, user, status.
  6. activities (calls + emails) -> completion timestamps and cadence/step linkage.

Output prints to the console AND to salesloft_adherence_probe_output.txt (PII masked).
Paste that file back so the scorer is built against real shapes.

Run:
    cd "<project folder>"
    python3 salesloft_adherence_probe.py
"""

import os, sys, json, time, re, urllib.parse, urllib.request, urllib.error
from collections import Counter

BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
CREDS_FILE = os.path.join(BASE_DIR, "salesloft_credentials.json")
OUT_FILE   = os.path.join(BASE_DIR, "salesloft_adherence_probe_output.txt")
SL_BASE_URL   = "https://api.salesloft.com/v2"
REQUEST_DELAY = 0.5
SAMPLE_CADENCES = 2          # how many in-scope cadences to inspect in depth
EXCLUDED_REGION_RE = re.compile(r"\b(EMEA|CAN|APAC)\b", re.IGNORECASE)
CAD_PREFIX_RE      = re.compile(r"^\s*CAD\b", re.IGNORECASE)
PII_KEYS = {"name","first_name","last_name","full_name","display_name","email",
            "email_address","phone","phone_number","mobile_phone","home_phone",
            "person_company_name","company_name","title"}

_out_fh = None
def out(*a):
    line = " ".join(str(x) for x in a)
    print(line)
    if _out_fh:
        _out_fh.write(line + "\n")

def redact(obj):
    """Recursively mask PII values so the pasted output is safe to share."""
    if isinstance(obj, dict):
        return {k: ("***" if k.lower() in PII_KEYS and v not in (None, "") else redact(v))
                for k, v in obj.items()}
    if isinstance(obj, list):
        return [redact(x) for x in obj]
    return obj

def show(label, rec):
    out(f"\n  {label} — fields: {sorted(rec.keys())}")
    out("  sample (PII masked):")
    out("  " + json.dumps(redact(rec), indent=2)[:1800].replace("\n", "\n  "))

# ── auth + GET (mirrors salesloft_cadence_scorer.py) ───────────────────────────
def load_token():
    tok = os.environ.get("SALESLOFT_API_TOKEN", "")
    if not tok and os.path.exists(CREDS_FILE):
        with open(CREDS_FILE, encoding="utf-8") as f:
            tok = json.load(f).get("api_token", "")
    if not tok or tok.startswith("YOUR_"):
        out("[ERR] No API token. Set SALESLOFT_API_TOKEN or salesloft_credentials.json.")
        sys.exit(1)
    return tok

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
            out(f"    [429] waiting {wait}s…"); time.sleep(wait)
            return _get(token, path, params, _retry + 1)
        out(f"    [HTTP {e.code}] {path}: {e.read().decode('utf-8','replace')[:200]}")
        return None
    except Exception as e:
        out(f"    [ERR] {path}: {e}")
        return None

def first_page(token, path, params=None):
    d = _get(token, path, params); time.sleep(REQUEST_DELAY)
    return (d or {}).get("data", []) or []

# ── probe ──────────────────────────────────────────────────────────────────────
def main():
    global _out_fh
    _out_fh = open(OUT_FILE, "w", encoding="utf-8")
    token = load_token()
    out("="*78)
    out("SALESLOFT ADHERENCE PROBE  (read-only)")
    out("="*78)

    # 1) USERS / GROUPS — rep -> team mapping
    out("\n### 1. USERS / GROUPS (rep -> team mapping) ###")
    users = first_page(token, "/users", {"per_page": 100})
    out(f"users on page 1: {len(users)}")
    if users:
        u = users[0]
        out(f"  user fields: {sorted(u.keys())}")
        has_group = "group" in u or "group_id" in u
        out(f"  has group field: {has_group}  (group={json.dumps(u.get('group'))}, group_id={u.get('group_id')})")
        groups = Counter()
        for x in users:
            g = x.get("group") or {}
            gname = g.get("name") if isinstance(g, dict) else None
            groups[gname or f"group_id={x.get('group_id')}"] += 1
        out("  distinct groups seen on page 1 (name -> #users):")
        for g, n in groups.most_common():
            out(f"    {g}: {n}")
        out("  >>> CONFIRM: do these group names map cleanly to SDR / BDR-S / BDR-V / BDR-MM / BDR-CS?")

    # 2) ACTIVE, TEAM, BDR/SDR CADENCES (scorecard filters)
    out("\n### 2. IN-SCOPE CADENCES (active + team + BDR/SDR, region excluded) ###")
    raw = first_page(token, "/cadences", {"status[]": "active", "per_page": 100})
    out(f"active cadences on page 1: {len(raw)}")
    if raw:
        out(f"  cadence fields: {sorted(raw[0].keys())}")
    in_scope = []
    for c in raw:
        nm = (c.get("name") or "")
        low = nm.lower()
        if not c.get("team_cadence"):              continue
        if not ("bdr" in low or "sdr" in low):     continue
        if EXCLUDED_REGION_RE.search(nm) or CAD_PREFIX_RE.search(nm): continue
        in_scope.append(c)
    out(f"in-scope after filters: {len(in_scope)}")
    for c in in_scope[:6]:
        out(f"    id={c.get('id')}  team_cadence={c.get('team_cadence')}  name={c.get('name')!r}")
    samples = in_scope[:SAMPLE_CADENCES]
    if not samples:
        out("  [!] No in-scope cadences found on page 1 — widen the filter or check team_cadence.")
        _out_fh.close(); return

    # 3-6) per sample cadence
    for c in samples:
        cid = c.get("id")
        out("\n" + "-"*78)
        out(f"SAMPLE CADENCE id={cid}  name={c.get('name')!r}")
        out("-"*78)

        # 3) memberships
        out("\n### 3. CADENCE_MEMBERSHIPS ###")
        mem = first_page(token, "/cadence_memberships", {"cadence_id[]": cid, "per_page": 5})
        out(f"  memberships fetched: {len(mem)}")
        if mem:
            show("cadence_membership", mem[0])
            states = Counter(m.get("current_state") for m in mem)
            out(f"  current_state values seen: {dict(states)}")
            out(f"  added_at present: {'added_at' in mem[0]}   user(assignee) present: {'user' in mem[0]}")
            out(f"  counts object: {json.dumps(mem[0].get('counts'))}")
            out("  >>> CONFIRM: which current_state values mean completed vs removed-early (premature removal)?")

        # 4) steps
        out("\n### 4. STEPS ###")
        steps = first_page(token, "/steps", {"cadence_id": cid, "per_page": 100})
        out(f"  steps fetched: {len(steps)}")
        if steps:
            out(f"  step fields: {sorted(steps[0].keys())}")
            types = Counter(s.get("type") for s in steps)
            out(f"  step type distribution: {dict(types)}")
            txt = [s for s in steps if s.get("type") in ("integration", "other")]
            out(f"  potential TEXT/SMS steps (type integration/other): {len(txt)}"
                + (f"  e.g. {[s.get('name') for s in txt[:3]]}" if txt else "  -> none (SMS column would be empty)"))
            for s in steps[:8]:
                out(f"    day {s.get('day')} step {s.get('step_number')}: type={s.get('type')} name={s.get('name')!r}")

        # 5) actions (via step_id, per docs best practice)
        out("\n### 5. ACTIONS (via step_id) ###")
        step_id = steps[0].get("id") if steps else None
        if step_id:
            acts = first_page(token, "/actions", {"step_id": step_id, "per_page": 5})
            out(f"  actions fetched for step {step_id}: {len(acts)}")
            if acts:
                show("action", acts[0])
                out(f"  due_on present: {'due_on' in acts[0]}   user present: {'user' in acts[0]}   "
                    f"type={acts[0].get('type')}  status fields: "
                    f"{[k for k in acts[0] if 'status' in k or 'due' in k]}")
            else:
                out("  (no open actions on this step right now — try another step/cadence)")

    # 6) activities calls + emails
    out("\n### 6. ACTIVITIES (calls + emails) — completion timestamps + cadence/step linkage ###")
    for kind in ("calls", "emails"):
        recs = first_page(token, f"/activities/{kind}", {"per_page": 2})
        out(f"\n  /activities/{kind}: {len(recs)} fetched")
        if recs:
            r = recs[0]
            out(f"  fields: {sorted(r.keys())}")
            link = [k for k in r if k in ("cadence","step","cadence_id","step_id","action","action_id")]
            tstamps = [k for k in r if any(t in k for t in ("created_at","updated_at","completed","sent_at","dialed"))]
            out(f"  cadence/step linkage fields present: {link}")
            out(f"  timestamp fields present: {tstamps}")
            show(f"activity/{kind}", r)
    out("  >>> CONFIRM: can a completed activity be tied to its step/cadence (for on-time vs step due_on)?")

    out("\n" + "="*78)
    out("DONE. Review above, then paste salesloft_adherence_probe_output.txt back.")
    out("="*78)
    _out_fh.close()

if __name__ == "__main__":
    main()
