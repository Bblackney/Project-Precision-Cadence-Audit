#!/usr/bin/env python3
"""build_connected_cache.py — ONE-TIME, resumable backfill of all-time
'Call - Connected' calls into connected_calls_cache.json (per-cadence counts).

Run from the project folder, on stable wifi:
    python3 -u build_connected_cache.py

~1.4M records ≈ a couple of hours. Progress is saved after every page, so if it
stops (network drop, lid close), just run it again — it resumes from the cursor
with no double-counting. When it finishes it sets backfill_complete; the weekly
scorer then only fetches the small delta since the last run.
"""
import json
import sys

import salesloft_cadence_scorer as s


def main():
    token = json.load(open(s.CREDS_FILE, encoding="utf-8"))["api_token"]
    cache = s._load_cache()

    if cache.get("backfill_complete"):
        print(f"Backfill already complete — cache covers {len(cache.get('counts', {}))} cadences.")
        print("Nothing to do. The weekly scorer keeps it current with deltas.")
        return 0

    print("Backfilling all-time 'Call - Connected' calls into the cache (resumable)…", flush=True)
    print(f"Resuming from cursor: {cache.get('cursor')}", flush=True)

    counts, new_n, pages, caught_up = s._update_connected_cache(token, cache)

    if caught_up:
        cache["backfill_complete"] = True
        s._save_cache(cache)
        print(f"\n✓ Backfill COMPLETE — {new_n:,} calls this run over {pages} pages; "
              f"cache covers {len(counts)} cadences.")
        print("The weekly scorer will now keep it current with small deltas.")
        return 0

    print(f"\n⚠ Stopped early (network) after {new_n:,} calls / {pages} pages. "
          "Progress is saved — just run this again to resume.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
