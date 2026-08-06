#!/usr/bin/env python3
"""
build_step_stats_cache.py — per-step (email/call) metric breakdown for the
Cadence Scorecard's click-through "▸ steps" popup, written to
step_stats_cache.json (read by generate_html() in salesloft_cadence_scorer.py).

NOW RUNS AUTOMATICALLY EVERY FRIDAY as a step in run_weekly.sh (added
2026-08-06), right after the main scorer. It's still fine to also run
manually any time between Fridays if you want a fresher view mid-week.

HOW CALL-STEP METRICS ARE FETCHED (rewritten 2026-08-06 — v1 was too slow):
  /v2/activities/calls has NO cadence_id or step_id filter. v1 of this script
  tried to work around that by streaming ALL org call activity (bounded to a
  120-day window) and filtering client-side — confirmed against a real run
  to be ~2.5 HOURS for one 120-day window (org-wide call volume is ~7,000/day).
  Way too slow to re-run periodically.

  Fix (v2): /v2/activities/calls DOES support a person_id[] filter (confirmed
  against the live API docs), and /v2/cadence_memberships?cadence_id=X gives
  the person_id of everyone ever on a given cadence. So instead of scanning
  every call in the org, this pulls the (small) roster of people who were
  ever on one of our ~36 in-scope cadences, then queries calls scoped to just
  those person_ids. Confirmed against a real all-time run: 31 minutes for
  13,176 people (vs. 2.5+ hours org-wide) — much better, but still too slow
  to redo in full every single Friday forever as rosters keep growing.

  Fix (v3, this version): INCREMENTAL, same cursor pattern already used by
  connected_calls_cache.json elsewhere in this project — backfill the full
  all-time history ONCE, then every subsequent run only fetches calls
  created since the last run's cursor and adds them to a persistent running
  total. State lives in step_call_metrics_cache.json (gitignored — it's an
  internal bookkeeping cache, not a publishable artifact; step_stats_cache.json
  remains the one that's committed and read by the dashboard). This makes
  weekly runs fast and roughly constant-time regardless of how large the
  all-time roster grows. `--days N` only affects the FIRST-EVER backfill
  (narrower/faster initial pull, sacrificing older history); once a cursor
  exists it's ignored — every run after that is just "since last time".
  `--days 0` skips call metrics entirely for this run (doesn't touch the
  cursor either way).

SCOPE: exactly the cadences salesloft_cadence_scorer.in_step_detail_scope()
matches — the 15 named Pilot cadences plus anything with "CNV" in the name
(Project Precision). Pulled from the LATEST run already sitting in
cadence_scores_master.csv (no need to re-fetch/re-filter the active-cadence
list — the weekly scorer already did that work).

Run from the project folder, on Brett's Mac (this sandbox has no Salesloft
API access):

    python3 build_step_stats_cache.py             # backfill once, then delta every run after
    python3 build_step_stats_cache.py --days 30   # first backfill only: last 30 days (faster)
    python3 build_step_stats_cache.py --days 0    # skip call metrics entirely this run

Safe to Ctrl+C at any point — a partial result (whatever's completed so far)
is still written to step_stats_cache.json rather than losing everything (the
incremental cursor in step_call_metrics_cache.json only advances after a
batch of calls fully completes, so an interrupted run never loses progress
or double-counts on the next run).
Safe to re-run any time.
"""
import json
import os
import sys
import time
import urllib.parse
from datetime import datetime, timedelta, timezone

import salesloft_cadence_scorer as s

PERSON_BATCH_SIZE = 100   # person_id[] values per /activities/calls request
STEP_CALL_CACHE_FILE = os.path.join(s.BASE_DIR, "step_call_metrics_cache.json")

# Printed once (not per-record) so the raw API shape is visible in the log
# without flooding it — mirrors the existing [debug] pattern in main() Phase 1.
_debug_printed = {"email": False, "call": False}


def _load_call_cache():
    """{"cursor": iso-str|None, "counts": {"cid:sid": {"calls_made","calls_connected"}},
    "backfill_complete": bool, "updated_at": iso-str|None}. Missing/corrupt file
    → fresh empty cache (triggers a full backfill on this run)."""
    if os.path.exists(STEP_CALL_CACHE_FILE):
        try:
            with open(STEP_CALL_CACHE_FILE, encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"  [WARN] could not read {os.path.basename(STEP_CALL_CACHE_FILE)}: {e} "
                  "— starting a fresh backfill.")
    return {"cursor": None, "counts": {}, "backfill_complete": False, "updated_at": None}


def _save_call_cache(cache):
    cache["updated_at"] = datetime.now(timezone.utc).isoformat()
    tmp = STEP_CALL_CACHE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cache, f)
    os.replace(tmp, STEP_CALL_CACHE_FILE)


def _seed_call_cache_from_existing_snapshot():
    """One-time migration: if step_stats_cache.json already has real call
    counts from a prior all-time pull (pre-dating this incremental version),
    seed the new persistent cache from those numbers instead of re-running
    an expensive full backfill that's already effectively been done. Sets
    cursor = now, so the next run only fetches the delta from this point
    forward. Returns the seeded cache, or None if there's nothing to seed
    (step_stats_cache.json missing, or no phone steps with real counts)."""
    if not os.path.exists(s.STEP_STATS_FILE):
        return None
    try:
        with open(s.STEP_STATS_FILE, encoding="utf-8") as f:
            existing = json.load(f)
    except Exception:
        return None
    counts = {}
    any_calls = False
    for v in existing.values():
        for st in v.get("steps", []):
            if st.get("type") != "phone":
                continue
            cm = int(st.get("calls_made") or 0)
            cc = int(st.get("calls_connected") or 0)
            if cm or cc:
                any_calls = True
            sid = st.get("step_id")
            if sid is None:
                continue
            key = f"{v['cadence_id']}:{sid}"
            counts[key] = {"calls_made": cm, "calls_connected": cc}
    if not any_calls:
        return None
    now = datetime.now(timezone.utc).isoformat()
    print(f"  [migrate] seeding {os.path.basename(STEP_CALL_CACHE_FILE)} from the call counts "
          f"already in {os.path.basename(s.STEP_STATS_FILE)} (from a prior all-time pull) — "
          "skipping a redundant backfill. Future runs will only fetch the delta.")
    return {"cursor": now, "counts": counts, "backfill_complete": True, "updated_at": now}


def _extract_email_flags(rec):
    """Read of an /v2/activities/emails record's per-email counts. Confirmed
    2026-08-06 against a real API response: rec['counts'] is
    {attachments, clicks, replies, unique_devices, unique_locations, views}
    — plain integer counts, plural, no '_count' suffix (an earlier version of
    this function guessed wrong field names — 'view_count', 'clicked_at',
    etc. — none of which exist, so opened/clicked/replied always came back
    0/False). 'views'/'clicks'/'replies' are the real, confirmed fields; the
    extra any_positive() keys below are just harmless fallbacks in case the
    schema ever varies by API version. Returns (opened, clicked, replied)
    booleans for this single email."""
    if not _debug_printed["email"]:
        print(f"    [debug] sample email activity fields: {sorted(rec.keys())}")
        if isinstance(rec.get("counts"), dict):
            print(f"    [debug] sample email 'counts' fields: {sorted(rec['counts'].keys())}")
        _debug_printed["email"] = True

    counts = rec.get("counts") if isinstance(rec.get("counts"), dict) else {}

    def any_positive(*keys, source=rec):
        for k in keys:
            v = source.get(k)
            if isinstance(v, (int, float)) and v > 0:
                return True
            if isinstance(v, bool) and v:
                return True
        return False

    opened = (
        any_positive("views", "view_count", "views_count", "open_count", "opens_count", source=counts)
        or any_positive("viewed_at", "opened_at")
        or bool(rec.get("viewed"))
    )
    clicked = (
        any_positive("clicks", "click_count", "clicks_count", source=counts)
        or any_positive("clicked_at")
        or bool(rec.get("clicked"))
    )
    replied = (
        any_positive("replies", "reply_count", "replies_count", source=counts)
        or any_positive("replied_at")
        or bool(rec.get("replied"))
    )
    return opened, clicked, replied


def _extract_call_flags(rec):
    """Best-effort read of an /v2/activities/calls record's connected flag."""
    if "connected" in rec:
        return bool(rec.get("connected"))
    disposition = str(rec.get("disposition") or "").strip()
    return disposition == s.CONNECTED_DISPOSITION


def fetch_steps(token, cid):
    """All steps for one cadence, via /v2/steps?cadence_id=X (paginated)."""
    out = []
    for st in s.paginate(token, "/steps", {"cadence_id": cid, "per_page": 100}):
        out.append(st)
    return out


def fetch_email_metrics(token, cid, step_id):
    """(sent, opened, clicked, replied) for one cadence+step, all-time."""
    sent = opened = clicked = replied = 0
    params = {"cadence_id[]": cid, "step_id[]": step_id, "per_page": 100}
    for rec in s.paginate(token, "/activities/emails", params):
        sent += 1
        o, c, r = _extract_email_flags(rec)
        opened += int(o)
        clicked += int(c)
        replied += int(r)
    return sent, opened, clicked, replied


def fetch_person_ids_for_cadences(token, cadence_ids):
    """Every person_id ever on any of `cadence_ids`, via
    /v2/cadence_memberships?cadence_id=X (one request per cadence — that
    endpoint only takes a single cadence_id, not an array). No
    currently_on_cadence filter, so this includes people who completed or
    were removed too — call history from before they left still counts."""
    person_ids = set()
    for i, cid in enumerate(cadence_ids, 1):
        n_before = len(person_ids)
        for rec in s.paginate(token, "/cadence_memberships", {"cadence_id": cid, "per_page": 100}):
            pid = (rec.get("person") or {}).get("id")
            if pid is not None:
                person_ids.add(pid)
        print(f"    [{i}/{len(cadence_ids)}] cadence #{cid}: "
              f"+{len(person_ids) - n_before} person(s) (running total {len(person_ids)})")
    return person_ids


def fetch_call_metrics_by_step(token, cadence_step_ids, person_ids, days, cache):
    """Query /v2/activities/calls?person_id[]=... in batches of
    PERSON_BATCH_SIZE, filtered client-side to the (cadence_id, step_id)
    pairs in `cadence_step_ids`. INCREMENTAL: if `cache["cursor"]` is already
    set (a prior backfill completed), only fetches calls created since that
    cursor — `days` is ignored in that case, every run is just "since last
    time". If there's no cursor yet, this is the first-ever backfill:
    `days` optionally bounds it (None = all-time).

    Returns the merged {(cadence_id, step_id): {"calls_made", "calls_connected"}}
    dict (cache's prior totals + this run's delta). Only mutates/saves `cache`
    (advances the cursor, merges counts) on a FULLY successful run — if
    Ctrl+C'd partway through, `cache` is left untouched and this returns the
    cache's prior totals unchanged, so nothing is lost or double-counted on
    the next run (which will just retry the same not-yet-committed window)."""
    prior = {
        tuple(int(x) for x in k.split(":")): v
        for k, v in cache.get("counts", {}).items()
    }
    if days is not None and days <= 0:
        print("  [skip] --days 0 — call metrics disabled this run, using prior totals as-is.")
        return prior
    if not cadence_step_ids or not person_ids:
        print("  [skip] no phone-type steps or no people found — nothing to query.")
        return prior

    cursor = cache.get("cursor")
    since_q = ""
    if cursor:
        since_q = f"&created_at[gt]={urllib.parse.quote(cursor)}"
        mode_desc = f"delta since {cursor[:19]}"
    elif days is not None:
        since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        since_q = f"&created_at[gt]={urllib.parse.quote(since)}"
        mode_desc = f"first backfill, last {days}d"
    else:
        mode_desc = "first backfill, all-time"

    batches = [sorted(person_ids)[i:i + PERSON_BATCH_SIZE]
               for i in range(0, len(person_ids), PERSON_BATCH_SIZE)]
    print(f"  Querying calls for {len(person_ids)} person(s) across "
          f"{len(cadence_step_ids)} phone-step slot(s), in {len(batches)} batch(es) of "
          f"up to {PERSON_BATCH_SIZE} ({mode_desc})…")

    run_start = datetime.now(timezone.utc).isoformat()
    result = {}   # this run's delta only — merged into `cache` at the end
    scanned = matched = 0
    debug_shown = False
    t0 = time.time()
    try:
        for bi, batch in enumerate(batches, 1):
            person_q = "&".join(f"person_id[]={pid}" for pid in batch)
            page = 1
            while True:
                q = f"/activities/calls?{person_q}&per_page=100&page={page}{since_q}"
                data = s._get(token, q)
                time.sleep(s.REQUEST_DELAY)
                if data is None:
                    print(f"    [WARN] calls fetch failed for batch {bi}/{len(batches)} page {page} "
                          "— skipping this batch, continuing with the rest.")
                    break
                recs = data.get("data", [])
                if not recs:
                    break
                for rec in recs:
                    scanned += 1
                    if not debug_shown:
                        cad_dbg = rec.get("cadence") or {}
                        step_dbg = rec.get("step") or {}
                        print(f"    [debug] sample call activity fields: {sorted(rec.keys())}")
                        if cad_dbg:
                            print(f"    [debug] sample call 'cadence' sub-fields: {sorted(cad_dbg.keys())}")
                        if step_dbg:
                            print(f"    [debug] sample call 'step' sub-fields: {sorted(step_dbg.keys())}")
                        print(f"    [debug] extracted cadence_id={rec.get('cadence_id') or cad_dbg.get('id')!r} "
                              f"step_id={rec.get('step_id') or step_dbg.get('id')!r} from that record")
                        debug_shown = True
                    cad = rec.get("cadence") or {}
                    step = rec.get("step") or {}
                    cid = rec.get("cadence_id") or cad.get("id")
                    sid = rec.get("step_id") or step.get("id")
                    if cid is None or sid is None:
                        continue
                    key = (int(cid), int(sid))
                    if key not in cadence_step_ids:
                        continue
                    matched += 1
                    bucket = result.setdefault(key, {"calls_made": 0, "calls_connected": 0})
                    bucket["calls_made"] += 1
                    if _extract_call_flags(rec):
                        bucket["calls_connected"] += 1
                if len(recs) < 100:
                    break
                page += 1
            if bi % 10 == 0 or bi == len(batches):
                elapsed = time.time() - t0
                print(f"    …batch {bi}/{len(batches)}, {elapsed:,.0f}s elapsed, "
                      f"{scanned:,} calls seen, {matched} matched an in-scope cadence+step", flush=True)
    except KeyboardInterrupt:
        print(f"\n    [interrupted] stopping calls fetch after {scanned:,} seen, "
              f"{matched} matched this run. NOT committing the cursor — cache stays exactly "
              "as it was, so the next run retries this same window cleanly (no lost or "
              "double-counted calls). Using prior totals for this write.")
        return prior
    print(f"    → calls done: {scanned:,} seen, {matched} matched an in-scope cadence+step this run.")

    # Merge this run's delta into the persistent totals and commit the cursor —
    # only reached on a fully successful run (no KeyboardInterrupt above).
    merged = {k: dict(v) for k, v in prior.items()}
    for key, delta in result.items():
        bucket = merged.setdefault(key, {"calls_made": 0, "calls_connected": 0})
        bucket["calls_made"] += delta["calls_made"]
        bucket["calls_connected"] += delta["calls_connected"]
    cache["counts"] = {f"{cid}:{sid}": v for (cid, sid), v in merged.items()}
    cache["cursor"] = run_start
    cache["backfill_complete"] = True
    _save_call_cache(cache)
    print(f"    → committed to {os.path.basename(STEP_CALL_CACHE_FILE)}, cursor now {run_start[:19]}.")
    return merged


def in_scope_cadences_from_master_csv():
    """(id, name) pairs for the latest run's rows whose name matches
    in_step_detail_scope() — i.e. the exact same scope generate_html() uses."""
    rows = s.read_all_csv()
    if not rows:
        return []
    dates = sorted({r.get("run_date", "") for r in rows if r.get("run_date")}, reverse=True)
    if not dates:
        return []
    latest = dates[0]
    seen, out = set(), []
    for r in rows:
        if r.get("run_date") != latest:
            continue
        name = r.get("cadence_name", "")
        if not s.in_step_detail_scope(name):
            continue
        cid = str(r.get("cadence_id", "")).strip()
        if not cid or cid in seen:
            continue
        seen.add(cid)
        out.append((int(cid), name))
    return out


def _write_snapshot(snapshot, note=""):
    tmp = s.STEP_STATS_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, indent=2)
    os.replace(tmp, s.STEP_STATS_FILE)
    total_steps = sum(len(v["steps"]) for v in snapshot.values())
    print(f"\n✓ Wrote {os.path.basename(s.STEP_STATS_FILE)}{note} — "
          f"{len(snapshot)} cadences, {total_steps} steps.")
    print("This file IS committed to git (not gitignored) so index.html's popup works")
    print("for everyone viewing the published dashboard, not just on this Mac.")
    print("Re-run this script whenever you want fresher step-level numbers, then commit:")
    print("  rm -f .git/*.lock")
    print("  git add step_stats_cache.json salesloft_cadence_scorer.py index.html")
    print('  git commit -m "Refresh step-level detail cache"')
    print("  git push origin main && git push origin-old-personal main")


def main():
    days = None   # None = all-time (default); overridden by --days N below
    args = sys.argv[1:]
    if "--days" in args:
        i = args.index("--days")
        if i + 1 < len(args):
            try:
                days = int(args[i + 1])
            except ValueError:
                sys.exit(f"[ERR] --days needs an integer, got {args[i + 1]!r}")

    token = os.environ.get("SALESLOFT_API_TOKEN", "")
    if not token:
        if not os.path.exists(s.CREDS_FILE):
            sys.exit(f"[ERR] Missing credentials: {s.CREDS_FILE}")
        with open(s.CREDS_FILE, encoding="utf-8") as f:
            token = json.load(f).get("api_token", "")
    if not token or token.startswith("YOUR_"):
        sys.exit("[ERR] api_token not configured.")

    cadences = in_scope_cadences_from_master_csv()
    if not cadences:
        sys.exit("[ERR] No in-scope cadences found in cadence_scores_master.csv — "
                  "run salesloft_cadence_scorer.py at least once first.")

    print(f"In scope: {len(cadences)} cadence(s) (Pilot + Project Precision).\n")

    pulled_at = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    snapshot = {}
    call_step_keys = set()      # {(cid, step_id)} for phone-type steps
    phone_cadence_ids = set()   # cadence_ids that have >=1 phone step

    # ── Phase 1: steps + email metrics (fast, targeted, per-cadence) ─────────
    try:
        for i, (cid, name) in enumerate(cadences, 1):
            print(f"  [{i}/{len(cadences)}] #{cid} {name!r} — fetching steps…", end=" ", flush=True)
            steps = fetch_steps(token, cid)
            print(f"{len(steps)} step(s)")

            step_out = []
            for st in steps:
                sid = st.get("id")
                stype = str(st.get("type", "") or "").lower()
                entry = {
                    "step_id": sid,
                    "name": st.get("name") or "",
                    "display_name": st.get("display_name"),
                    "day": st.get("day"),
                    "step_number": st.get("step_number"),
                    "type": stype,
                    "multitouch_enabled": bool(st.get("multitouch_enabled")),
                    "disabled": (st.get("enabled") is False) or bool(st.get("disabled")),
                }
                if stype == "email" and sid is not None:
                    sent, opened, clicked, replied = fetch_email_metrics(token, cid, sid)
                    entry.update(sent=sent, opened=opened, clicked=clicked, replied=replied)
                elif stype == "phone" and sid is not None:
                    call_step_keys.add((cid, int(sid)))
                    phone_cadence_ids.add(cid)
                    entry.update(calls_made=0, calls_connected=0)   # filled in Phase 2
                step_out.append(entry)

            step_out.sort(key=lambda e: (
                e["day"] if isinstance(e["day"], (int, float)) else 9999,
                e["step_number"] if isinstance(e["step_number"], (int, float)) else 9999,
            ))
            snapshot[str(cid)] = {
                "cadence_id": cid,
                "cadence_name": name,
                "pulled_at": pulled_at,
                "calls_window_days": days,   # None = all-time
                "steps": step_out,
            }
    except KeyboardInterrupt:
        print(f"\n[interrupted] stopping during steps/email phase — writing the "
              f"{len(snapshot)} cadence(s) already completed.")
        _write_snapshot(snapshot, note=" (PARTIAL — interrupted)")
        return 0

    n_email_steps = sum(1 for v in snapshot.values() for st in v["steps"] if st["type"] == "email")
    print(f"\nPhase 1 done: {n_email_steps} email step(s) pulled all-time, "
          f"{len(call_step_keys)} phone step(s) found across {len(phone_cadence_ids)} cadence(s).")

    # ── Phase 2: person-scoped call metrics (targeted, incremental) ──────────
    call_cache = _load_call_cache()
    if call_cache.get("cursor") is None and not call_cache.get("counts"):
        seeded = _seed_call_cache_from_existing_snapshot()
        if seeded is not None:
            call_cache = seeded
            _save_call_cache(call_cache)

    def _prior_call_metrics():
        return {tuple(int(x) for x in k.split(":")): v for k, v in call_cache.get("counts", {}).items()}

    call_metrics = _prior_call_metrics()   # fallback if Phase 2 is skipped/interrupted below
    if days is None or days > 0:
        print("\nPhase 2: resolving cadence membership → person_ids for phone-step cadences…")
        try:
            person_ids = fetch_person_ids_for_cadences(token, sorted(phone_cadence_ids))
        except KeyboardInterrupt:
            print("\n[interrupted] stopping during membership lookup — writing steps/email data "
                  "already completed, using prior call totals (cache untouched).")
            for v in snapshot.values():
                for st in v["steps"]:
                    if st["type"] != "phone":
                        continue
                    cm = call_metrics.get((v["cadence_id"], st["step_id"]), {"calls_made": 0, "calls_connected": 0})
                    st["calls_made"] = cm["calls_made"]
                    st["calls_connected"] = cm["calls_connected"]
            _write_snapshot(snapshot, note=" (PARTIAL — interrupted before calls; using prior call totals)")
            return 0
        call_metrics = fetch_call_metrics_by_step(token, call_step_keys, person_ids, days, call_cache)
    else:
        print("\n  [skip] --days 0 — call metrics disabled this run, using prior totals as-is.")

    for v in snapshot.values():
        for st in v["steps"]:
            if st["type"] != "phone":
                continue
            cm = call_metrics.get((v["cadence_id"], st["step_id"]), {"calls_made": 0, "calls_connected": 0})
            st["calls_made"] = cm["calls_made"]
            st["calls_connected"] = cm["calls_connected"]

    _write_snapshot(snapshot)
    return 0


if __name__ == "__main__":
    sys.exit(main())
