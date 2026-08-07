#!/usr/bin/env python3
"""
build_period_metrics.py — date-bounded (month/quarter) performance snapshots
for the Pilot Comparison tab's period-vs-period picker (e.g. "Q2 2026 vs
Q2 2025", "July 2026 vs July 2025"), written to pilot_period_metrics.json.

WHY THIS NEEDS A FRESH PULL (can't reuse existing data):
  pilot_legacy_snapshot.json and the live weekly cadence_stats are both
  ALL-TIME CUMULATIVE totals — a single running number like "742 emails
  opened, ever." There is no way to slice "how many of those happened in
  July 2025 specifically" out of that after the fact; Salesloft never gave
  us that breakdown, so it doesn't exist anywhere in our current caches.
  Getting it requires going back to Salesloft and asking for activity
  records bounded to that exact calendar window, then counting ourselves.

  The upside: once a period is pulled, it's just as immutable as the legacy
  snapshot (history doesn't change) — a true one-time cost per period, not
  a recurring pull. Re-run this script later to add more periods; it skips
  any (cadence, month) already in the file unless you pass --force.

SCOPE: both sides (new_id AND legacy_id) of all 15 pairs in
PILOT_LEGACY_PAIRS (salesloft_cadence_scorer.py) — matches Brett's answer
when asked "all 15 pairs" for the initial backfill.

GRANULARITY: pulls at MONTH resolution only, then derives quarters by
summing the 3 constituent months and recomputing rates from the summed
totals. This means a quarter's numbers are always exactly consistent with
its 3 months (no separate API cost, no risk of drift) — 3x less API work
than pulling months and quarters independently. MONTHS_BACK_DEFAULT (18)
covers back to ~Feb 2025 from "today", enough for both stated examples
(Q2 2026 vs Q2 2025, July 2026 vs July 2025) with a couple months of buffer.

DATA SOURCES (all confirmed against the live Salesloft API docs, 2026-08-06):
  • /v2/activities/emails?cadence_id[]=X&sent_at[gte]=..&sent_at[lt]=..
      → sent / opened (counts.views>0) / clicked (counts.clicks>0) /
        replied (counts.replies>0) — same confirmed schema as
        build_step_stats_cache.py's email pull.
  • /v2/meetings?cadence_id=X&start_time[gte]=..&start_time[lt]=..
      &counted_towards_meetings_booked_metric=true
      → meetings booked, matching the same metric definition cadence_stats
        uses for meetings_booked_count.
  • /v2/activities/calls?person_id[]=..&created_at[gte]=..&created_at[lt]=..
      → calls_made / calls_connected (the 'connected' boolean), scoped via
        /v2/cadence_memberships?cadence_id=X for person_ids — calls has NO
        cadence filter at all, same workaround as build_step_stats_cache.py.
        Person roster is pulled ONCE per cadence (not once per period) since
        it only grows over time and doesn't need re-fetching per month.

RATES use the exact same formulas as the main scorer (meeting_rate and
reply_rate/open_rate are "/ emails_sent", not "/ people" — connect_rate is
calls_connected/calls_made) — see score_cadence()'s callers in
salesloft_cadence_scorer.py for the canonical definitions this mirrors.

Run from the project folder, on Brett's Mac (this sandbox has no Salesloft
API access):

    python3 build_period_metrics.py             # backfill default months, skip already-pulled
    python3 build_period_metrics.py --force     # re-pull months already in the file too
    python3 build_period_metrics.py --months 24 # pull further back than the 18-month default

Safe to Ctrl+C at any point — writes whatever's completed so far.
"""
import json
import os
import sys
import time
import urllib.parse
from datetime import datetime, timezone

import salesloft_cadence_scorer as s
import build_step_stats_cache as bsc   # reuses fetch_person_ids_for_cadences

MONTHS_BACK_DEFAULT = 18
QUARTERS_TO_DERIVE = 7   # how many trailing quarters to derive from the pulled months


def _iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _month_bounds(year, month):
    start = datetime(year, month, 1, tzinfo=timezone.utc)
    if month == 12:
        end = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        end = datetime(year, month + 1, 1, tzinfo=timezone.utc)
    return start, end


def month_keys_back(n, from_dt=None):
    """['2026-08', '2026-07', ...] — n months, most recent (current, partial)
    month first."""
    now = from_dt or datetime.now(timezone.utc)
    y, m = now.year, now.month
    out = []
    for _ in range(n):
        out.append(f"{y}-{m:02d}")
        m -= 1
        if m == 0:
            m, y = 12, y - 1
    return out


def quarter_key_and_months(qkey):
    """'2026-Q3' -> ('2026-Q3', ['2026-07','2026-08','2026-09'])."""
    year, q = qkey.split("-Q")
    year = int(year)
    q = int(q)
    start_month = (q - 1) * 3 + 1
    months = [f"{year}-{m:02d}" for m in range(start_month, start_month + 3)]
    return qkey, months


def trailing_quarter_keys(n, from_dt=None):
    now = from_dt or datetime.now(timezone.utc)
    y, q = now.year, (now.month - 1) // 3 + 1
    out = []
    for _ in range(n):
        out.append(f"{y}-Q{q}")
        q -= 1
        if q == 0:
            q, y = 4, y - 1
    return out


def _extract_email_flags(rec):
    counts = rec.get("counts") if isinstance(rec.get("counts"), dict) else {}

    def pos(k):
        v = counts.get(k)
        return isinstance(v, (int, float)) and v > 0

    return pos("views"), pos("clicks"), pos("replies")


def pull_email_metrics(token, cid, start, end):
    """(sent, opened, clicked, replied, person_ids) for one cadence, bounded
    to [start, end) by sent_at."""
    sent = opened = clicked = replied = 0
    person_ids = set()
    params = {
        "cadence_id[]": cid, "per_page": 100,
        "sent_at[gte]": _iso(start), "sent_at[lt]": _iso(end),
    }
    for rec in s.paginate(token, "/activities/emails", params):
        sent += 1
        o, c, r = _extract_email_flags(rec)
        opened += int(o)
        clicked += int(c)
        replied += int(r)
        pid = (rec.get("recipient") or {}).get("id")
        if pid is not None:
            person_ids.add(pid)
    return sent, opened, clicked, replied, person_ids


def pull_meeting_metrics(token, cid, start, end):
    """meetings_booked count for one cadence, bounded to [start, end) by
    start_time, matching the same 'counted towards Meetings Booked metric'
    definition cadence_stats uses."""
    booked = 0
    params = {
        "cadence_id": cid, "per_page": 100,
        "start_time[gte]": _iso(start), "start_time[lt]": _iso(end),
        "counted_towards_meetings_booked_metric": "true",
    }
    for _rec in s.paginate(token, "/meetings", params):
        booked += 1
    return booked


def pull_call_metrics(token, cid, person_ids, start, end):
    """(calls_made, calls_connected, person_ids_called) for one cadence,
    bounded to [start, end) by created_at. person_ids is that cadence's full
    (all-time) roster — cheap to over-query since the date filter does the
    real narrowing; batches of 100 person_id[] values per request (calls has
    no cadence filter at all, so we filter client-side by embedded cadence.id)."""
    calls_made = calls_connected = 0
    called_people = set()
    if not person_ids:
        return 0, 0, called_people
    since_q = (f"&created_at[gte]={urllib.parse.quote(_iso(start))}"
               f"&created_at[lt]={urllib.parse.quote(_iso(end))}")
    ids = sorted(person_ids)
    for i in range(0, len(ids), 100):
        batch = ids[i:i + 100]
        person_q = "&".join(f"person_id[]={pid}" for pid in batch)
        page = 1
        while True:
            q = f"/activities/calls?{person_q}&per_page=100&page={page}{since_q}"
            data = s._get(token, q)
            time.sleep(s.REQUEST_DELAY)
            if data is None:
                break
            recs = data.get("data", [])
            if not recs:
                break
            for rec in recs:
                cad = rec.get("cadence") or {}
                rcid = rec.get("cadence_id") or cad.get("id")
                if rcid is None or int(rcid) != int(cid):
                    continue
                calls_made += 1
                pid = (rec.get("called_person") or {}).get("id")
                if pid is not None:
                    called_people.add(pid)
                if rec.get("connected") is True:
                    calls_connected += 1
            if len(recs) < 100:
                break
            page += 1
    return calls_made, calls_connected, called_people


def compute_rates(counts):
    sent = counts.get("emails_sent", 0)
    calls_made = counts.get("calls_made", 0)
    return {
        **counts,
        "open_rate": round(counts.get("opened", 0) / sent * 100, 2) if sent else 0.0,
        "reply_rate": round(counts.get("replied", 0) / sent * 100, 2) if sent else 0.0,
        "meeting_rate": round(counts.get("meetings_booked", 0) / sent * 100, 2) if sent else 0.0,
        "connect_rate": round(counts.get("calls_connected", 0) / calls_made * 100, 2) if calls_made else 0.0,
    }


def in_scope_cadence_ids():
    """(cadence_id, name-hint) for every distinct cadence in PILOT_LEGACY_PAIRS
    — both new_id and legacy_id sides, deduped. name-hint is just the pair
    label + New/Legacy tag for progress printing; the real cadence_name gets
    filled in from the API response."""
    out = {}
    for p in s.PILOT_LEGACY_PAIRS:
        if p.get("new_id"):
            out[int(p["new_id"])] = f"{p['label']} (New)"
        if p.get("legacy_id"):
            out[int(p["legacy_id"])] = f"{p['label']} (Legacy)"
    return out


def main():
    args = sys.argv[1:]
    force = "--force" in args
    months_back = MONTHS_BACK_DEFAULT
    if "--months" in args:
        i = args.index("--months")
        if i + 1 < len(args):
            try:
                months_back = int(args[i + 1])
            except ValueError:
                sys.exit(f"[ERR] --months needs an integer, got {args[i + 1]!r}")

    token = os.environ.get("SALESLOFT_API_TOKEN", "")
    if not token:
        if not os.path.exists(s.CREDS_FILE):
            sys.exit(f"[ERR] Missing credentials: {s.CREDS_FILE}")
        with open(s.CREDS_FILE, encoding="utf-8") as f:
            token = json.load(f).get("api_token", "")
    if not token or token.startswith("YOUR_"):
        sys.exit("[ERR] api_token not configured.")

    cadence_ids = in_scope_cadence_ids()
    print(f"In scope: {len(cadence_ids)} cadence(s) across all 15 Pilot Comparison pairs "
          f"(New + Legacy sides).")

    months = month_keys_back(months_back)
    print(f"Backfilling {len(months)} month(s): {months[-1]} .. {months[0]}"
          f"{' (--force: re-pulling months already saved)' if force else ''}\n")

    snapshot = {}
    if os.path.exists(s.PERIOD_METRICS_FILE):
        try:
            with open(s.PERIOD_METRICS_FILE, encoding="utf-8") as f:
                snapshot = json.load(f)
        except Exception:
            snapshot = {}

    try:
        for i, (cid, hint) in enumerate(sorted(cadence_ids.items()), 1):
            print(f"[{i}/{len(cadence_ids)}] #{cid} {hint!r}")
            entry = snapshot.setdefault(str(cid), {"cadence_name": "", "months": {}, "quarters": {}})

            months_needed = [m for m in months if force or m not in entry["months"]]
            if not months_needed:
                print("    all months already cached — skipping (use --force to redo)")
                continue

            person_ids = bsc.fetch_person_ids_for_cadences(token, [cid])
            print(f"    {len(person_ids)} person(s) ever on this cadence")
            cadence_name = None

            for mkey in months_needed:
                y, m = (int(x) for x in mkey.split("-"))
                start, end = _month_bounds(y, m)
                sent, opened, clicked, replied, email_people = pull_email_metrics(token, cid, start, end)
                booked = pull_meeting_metrics(token, cid, start, end)
                calls_made, calls_connected, call_people = pull_call_metrics(token, cid, person_ids, start, end)
                people = len(email_people | call_people)
                counts = {
                    "emails_sent": sent, "opened": opened, "clicked": clicked, "replied": replied,
                    "meetings_booked": booked,
                    "calls_made": calls_made, "calls_connected": calls_connected,
                    "people": people,
                }
                entry["months"][mkey] = compute_rates(counts)
                print(f"    {mkey}: {sent} sent, {booked} booked, {calls_made} calls, {people} people")
                if cadence_name is None and sent:
                    pass   # cadence_name resolved separately below if still blank

            snapshot[str(cid)] = entry
            _save(snapshot)
    except KeyboardInterrupt:
        print(f"\n[interrupted] saving {len(snapshot)} cadence(s) worth of progress so far.")
        _save(snapshot)
        return 0

    # Resolve cadence names (once) from cadence_scores_master.csv / cadences API,
    # falling back to the pair label if not found — cosmetic only, doesn't affect numbers.
    _fill_cadence_names(snapshot)

    # Derive quarters from the pulled months (sum counts, recompute rates) —
    # zero extra API cost, always exactly consistent with the monthly numbers.
    qkeys = trailing_quarter_keys(QUARTERS_TO_DERIVE)
    for cid_str, entry in snapshot.items():
        entry["quarters"] = {}
        for qkey in qkeys:
            _, mkeys = quarter_key_and_months(qkey)
            if not all(mk in entry["months"] for mk in mkeys):
                continue   # don't have all 3 months for this quarter yet
            summed = {"emails_sent": 0, "opened": 0, "clicked": 0, "replied": 0,
                      "meetings_booked": 0, "calls_made": 0, "calls_connected": 0, "people": 0}
            for mk in mkeys:
                mrec = entry["months"][mk]
                for k in summed:
                    summed[k] += mrec.get(k, 0)
            entry["quarters"][qkey] = compute_rates(summed)

    _save(snapshot)
    total_months = sum(len(v["months"]) for v in snapshot.values())
    total_quarters = sum(len(v["quarters"]) for v in snapshot.values())
    print(f"\n✓ Wrote {os.path.basename(s.PERIOD_METRICS_FILE)} — "
          f"{len(snapshot)} cadences, {total_months} cadence-months, {total_quarters} cadence-quarters.")
    print("This file IS committed to git (not gitignored) — it's the permanent baseline for")
    print("the Pilot Comparison tab's period picker, same pattern as pilot_legacy_snapshot.json.")
    print("Re-run this script later (safe, skips already-pulled months) to extend the window:")
    print("  rm -f .git/*.lock")
    print("  git add pilot_period_metrics.json")
    print('  git commit -m "Add period-comparison data for Pilot Comparison tab"')
    print("  git push origin main && git push origin-old-personal main")
    return 0


def _save(snapshot):
    tmp = s.PERIOD_METRICS_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, indent=2)
    os.replace(tmp, s.PERIOD_METRICS_FILE)


def _fill_cadence_names(snapshot):
    """Best-effort cadence_name resolution from cadence_scores_master.csv
    (covers New/active cadences) or PILOT_LEGACY_PAIRS labels as a fallback
    (covers Legacy/retired cadences, which won't be in the master CSV)."""
    by_id = {}
    for r in s.read_all_csv():
        cid = str(r.get("cadence_id", "")).strip()
        if cid:
            by_id[cid] = r.get("cadence_name", "")
    for p in s.PILOT_LEGACY_PAIRS:
        if p.get("new_id"):
            by_id.setdefault(str(p["new_id"]), p["label"] + " (New)")
        if p.get("legacy_id"):
            by_id.setdefault(str(p["legacy_id"]), p["label"] + " (Legacy)")
    for cid_str, entry in snapshot.items():
        if not entry.get("cadence_name"):
            entry["cadence_name"] = by_id.get(cid_str, f"#{cid_str}")


if __name__ == "__main__":
    sys.exit(main())
