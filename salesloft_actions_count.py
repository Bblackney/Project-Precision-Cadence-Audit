#!/usr/bin/env python3
"""
salesloft_actions_count.py — READ-ONLY 5-second check.
Confirms (a) how many OPEN actions exist org-wide, and (b) how many a single batch of
25 XDR guids returns. If the batch is a small fraction of org-wide, the user_guid filter
is working and the scorer's slowness is just volume. If they're equal, the filter isn't
narrowing (token not admin / param shape) and we fix the scorer instead of waiting.
"""
import importlib.util, os

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("scorer", os.path.join(HERE, "salesloft_adherence_scorer.py"))
s = importlib.util.module_from_spec(spec); spec.loader.exec_module(s)

tok = s.load_token()

def total(params):
    d = s._get(tok, "/actions", {**params, "per_page": 1,
                                 "include_paging_counts": "true", "limit_paging_counts": "false"})
    return (d or {}).get("metadata", {}).get("paging", {}).get("total_count")

org = total({})
print(f"\norg-wide OPEN actions (no user filter): {org}")

users = s.build_user_team_map(tok)
guids = [u["guid"] for u in users.values() if u.get("guid")][:s.GUID_BATCH]
batch = total({"user_guid[]": guids})
n_batches = (len([u for u in users.values() if u.get('guid')]) + s.GUID_BATCH - 1) // s.GUID_BATCH
print(f"one batch of {len(guids)} XDR guids:        {batch}")
print(f"\n-> ~{n_batches} batches total. If the batch number is a small slice of org-wide,")
print("   the filter works and it's just volume (let it run). If batch ≈ org-wide, the")
print("   filter isn't applying — stop and we fix it.")
