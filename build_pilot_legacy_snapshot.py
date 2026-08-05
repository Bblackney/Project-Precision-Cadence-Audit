#!/usr/bin/env python3
"""
build_pilot_legacy_snapshot.py — ONE-TIME pull of the legacy (pre-pilot) cadence
metrics for every Pilot Comparison pair (see PILOT_LEGACY_PAIRS in
salesloft_cadence_scorer.py), locked into pilot_legacy_snapshot.json.

These legacy cadences are retired — no longer used, no new activity — so their
numbers never change once pulled. Pull once, lock in, done. Re-running it later
is harmless (it just re-pulls and overwrites with the same all-time numbers) but
there's no need to schedule it; unlike the weekly scorer, this never needs to run
again unless the pilot/legacy ID mapping changes.

Run from the project folder, on Brett's Mac (same one that runs the weekly job —
this sandbox has no Salesloft API access):

    python3 build_pilot_legacy_snapshot.py

Uses the existing connected_calls_cache.json for connect_rate (that cache already
covers all-time history for every cadence ever active, including these retired
ones) — no separate backfill needed. If that cache's backfill isn't complete yet,
connect_rate for these legacy cadences may be partial; a [WARN] prints in that case.
"""
import json
import os
import sys
import time
from datetime import datetime, timezone

import salesloft_cadence_scorer as s


def main():
    token = os.environ.get("SALESLOFT_API_TOKEN", "")
    if not token:
        if not os.path.exists(s.CREDS_FILE):
            sys.exit(f"[ERR] Missing credentials: {s.CREDS_FILE}")
        with open(s.CREDS_FILE, encoding="utf-8") as f:
            token = json.load(f).get("api_token", "")
    if not token or token.startswith("YOUR_"):
        sys.exit("[ERR] api_token not configured.")

    cache = s._load_cache()
    connected_calls = {int(k): v for k, v in cache.get("counts", {}).items()}
    if not cache.get("backfill_complete"):
        print("[WARN] connected_calls_cache.json backfill not complete — "
              "connect_rate for legacy cadences may be partial/zero until it finishes.")

    legacy_pairs = [p for p in s.PILOT_LEGACY_PAIRS if p.get("legacy_id")]
    print(f"Pulling {len(legacy_pairs)} legacy cadences "
          f"({len(s.PILOT_LEGACY_PAIRS) - len(legacy_pairs)} pilot pair(s) have no "
          "legacy predecessor and are skipped)…\n")

    snapshot = {}
    for pair in legacy_pairs:
        lid = pair["legacy_id"]
        print(f"  #{lid} — {pair['team']} / {pair['label']}…", end=" ", flush=True)
        cad  = s._get(token, f"/cadences/{lid}")
        stat = s._get(token, f"/cadence_stats/{lid}")
        time.sleep(s.REQUEST_DELAY)

        cad_data  = (cad or {}).get("data", {}) or {}
        stat_data = (stat or {}).get("data", {}) or {}
        if not cad_data and not stat_data:
            print("[ERR] no data returned — check the ID / API access. Skipped.")
            continue

        emails_sent     = int(stat_data.get("sent_emails_count") or 0)
        people_acted_on = int(stat_data.get("people_acted_on_count") or 0)
        viewed_count    = int(stat_data.get("viewed_count") or 0)
        replied_count   = int(stat_data.get("replied_count") or 0)
        calls_count     = int(stat_data.get("calls_count") or 0)
        meetings_count  = int(stat_data.get("meetings_booked_count") or 0)
        connects        = connected_calls.get(lid, 0)

        open_rate    = (viewed_count   / emails_sent * 100) if emails_sent > 0 else 0.0
        reply_rate   = (replied_count  / emails_sent * 100) if emails_sent > 0 else 0.0
        meeting_rate = (meetings_count / emails_sent * 100) if emails_sent > 0 else 0.0
        connect_rate = (connects       / calls_count * 100) if calls_count > 0 else 0.0

        pts_m, pts_r, pts_c, pts_o, total_score = s.score_cadence(
            pair["model"], meeting_rate, reply_rate, connect_rate, open_rate
        )
        verdict = s.get_verdict(total_score)
        if people_acted_on == 0:
            verdict, total_score = "NO DATA", 0
        elif people_acted_on < s.MIN_PEOPLE:
            verdict = "LOW SAMPLE"

        snapshot[str(lid)] = {
            "cadence_id":      lid,
            "cadence_name":    cad_data.get("name", "") or f"(legacy #{lid})",
            "team":            pair["team"],
            "model":           pair["model"],
            "pair_label":      pair["label"],
            "score":           total_score,
            "verdict":         verdict,
            "meeting_rate":    round(meeting_rate, 2),
            "reply_rate":      round(reply_rate, 2),
            "connect_rate":    round(connect_rate, 2),
            "open_rate":       round(open_rate, 2),
            "people_acted_on": people_acted_on,
            "emails_sent":     emails_sent,
            "calls_count":     calls_count,
            "connected_calls": connects,
            "pulled_at":       datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        }
        print(f"{snapshot[str(lid)]['cadence_name']!r} — score {total_score} ({verdict})")

    if not snapshot:
        sys.exit("\n[ERR] Nothing pulled successfully — pilot_legacy_snapshot.json NOT written.")

    tmp = s.PILOT_SNAPSHOT_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, indent=2)
    os.replace(tmp, s.PILOT_SNAPSHOT_FILE)

    print(f"\n✓ Wrote {os.path.basename(s.PILOT_SNAPSHOT_FILE)} — "
          f"{len(snapshot)}/{len(legacy_pairs)} legacy cadences locked in.")
    if len(snapshot) < len(legacy_pairs):
        print("  Some IDs failed to pull (see [ERR] lines above) — rerun this script")
        print("  after checking those IDs; it's safe to rerun, it just overwrites.")
    print("\nThis file must be committed to git (it is NOT gitignored — it's the")
    print("permanent baseline for the Pilot Comparison tab). Next weekly run will")
    print("pick it up automatically and render pilot_comparison.html.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
