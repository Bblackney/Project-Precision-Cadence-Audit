#!/usr/bin/env python3
"""
add_rep_groups.py — ONE-OFF backfill. Adds each rep's Salesloft sub-group (pod) name to
adherence_data.json + adherence_scores_master.csv, then regenerates adherence.html, so the
dashboard's By Team view can break a selected team into its pods. Avoids re-running the full
scorer: pulls only /groups + /users (~10s). Read-only on Salesloft.

    python3 add_rep_groups.py

(After this runs once, the daily scorer captures group_name natively, so it isn't needed again.)
"""
import json, csv, os
import salesloft_adherence_scorer as s
import build_adherence_html

tok = s.load_token()
users = s.build_user_team_map(tok)          # uid -> {team, group_name, guid, name}
data = json.load(open(s.DATA_JSON, encoding="utf-8"))
rows = data["rows"]
miss = 0
for r in rows:
    info = users.get(r["user_id"])
    r["group_name"] = (info or {}).get("group_name") or r.get("team")
    if not info:
        miss += 1
json.dump(data, open(s.DATA_JSON, "w"))
with open(s.MASTER_CSV, "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=s.CSV_COLUMNS); w.writeheader()
    for r in rows:
        w.writerow({k: r.get(k, "") for k in s.CSV_COLUMNS})
print(f"  added group_name to {len(rows)} rows ({miss} reps not in current /users)")
build_adherence_html.main()
