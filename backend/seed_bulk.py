#!/usr/bin/env python3
"""Bulk-seed the ReelShield cache via the running backend.

Runs a small pool of worker threads that each call /api/load_movie
sequentially with a fixed inter-call delay, so many films cache in
parallel without bursting Gemini.

Usage:
    python backend/seed_bulk.py

Paste TMDB IDs into the SEED_IDS list at the top of this file. The
backend must be running locally (default http://localhost:7860) — set
REELSHIELD_BASE if it lives elsewhere.
"""

import os
import sqlite3
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

import requests


# ─── Configuration ─────────────────────────────────────────────────────
# Paste TMDB IDs to seed here. Order is preserved; duplicates are ignored.
SEED_IDS = [
    # 1930s
    28001,   # It's a Gift (1934)
    770,     # Gone with the Wind (1939)

    # 1950s
    28000,   # Somebody Up There Likes Me (1956)

    # 1980s
    11953,   # Kagemusha (1980)

    # 1990s
    45325,   # Tom and Huck (1995)

    # 2000s
    107,     # Snatch (2000)
    11375,   # Hollywood Homicide (2003)
    28344,   # Bloody Mary (2007)
    22291,   # Baabarr (2009)

    # 2010s
    65759,   # Happy Feet Two (2011)
]

NUM_WORKERS = 2
PER_WORKER_DELAY_SECONDS = 4  # delay between each worker's own /api/load_movie calls

BASE = os.environ.get("REELSHIELD_BASE", "http://localhost:7860")
DEFAULT_DB = os.path.join(os.path.dirname(__file__), "..", "data", "movie_cache.db")
DB_PATH = os.environ.get("DB_PATH", DEFAULT_DB)

ERROR_LOG = os.path.join(os.path.dirname(__file__), "..", "seed_bulk_errors.txt")


# ─── TMDB title preview ────────────────────────────────────────────────
def _load_tmdb_key():
    env_path = os.path.join(os.path.dirname(__file__), "..", ".env")
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line.startswith("TMDB_API_KEY="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    return os.environ.get("TMDB_API_KEY")


TMDB_KEY = _load_tmdb_key()


def fetch_tmdb_title(tmdb_id):
    if not TMDB_KEY:
        return None, None
    try:
        r = requests.get(
            f"https://api.themoviedb.org/3/movie/{tmdb_id}",
            params={"api_key": TMDB_KEY},
            timeout=15,
        )
        if r.ok:
            d = r.json()
            return d.get("title"), (d.get("release_date") or "")[:4]
    except requests.RequestException:
        pass
    return None, None


# ─── Cache check ───────────────────────────────────────────────────────
def already_cached_ids(ids):
    if not ids or not os.path.exists(DB_PATH):
        return set()
    conn = sqlite3.connect(DB_PATH)
    try:
        c = conn.cursor()
        placeholders = ",".join("?" for _ in ids)
        rows = c.execute(
            f"SELECT tmdb_id FROM content_warnings WHERE tmdb_id IN ({placeholders})",
            ids,
        ).fetchall()
        return {r[0] for r in rows}
    except sqlite3.OperationalError:
        # content_warnings table not yet created — treat as empty cache
        return set()
    finally:
        conn.close()


# ─── Concurrency primitives ────────────────────────────────────────────
print_lock = threading.Lock()
error_lock = threading.Lock()
counter_lock = threading.Lock()


def _say(msg):
    with print_lock:
        print(msg, flush=True)


def _record_failure(tmdb_id, reason):
    ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with error_lock:
        with open(ERROR_LOG, "a", encoding="utf-8") as f:
            f.write(f"{ts}\t{tmdb_id}\t{reason}\n")


# ─── Per-ID work ───────────────────────────────────────────────────────
def load_one(tmdb_id, index, total):
    title, year = fetch_tmdb_title(tmdb_id)
    label = f"'{title}' ({year})" if title else "(title lookup failed)"
    _say(f"[{index}/{total}] tmdb={tmdb_id}  {label}  → loading…")
    try:
        r = requests.post(
            f"{BASE}/api/load_movie",
            json={"tmdb_id": tmdb_id},
            timeout=120,
        )
        r.raise_for_status()
        data = r.json()
        cached_title = (data.get("movie") or {}).get("title", title or "?")
        _say(f"[{index}/{total}] tmdb={tmdb_id}  ✓ cached ({cached_title})")
        return ("ok", tmdb_id, cached_title)
    except requests.RequestException as e:
        _say(f"[{index}/{total}] tmdb={tmdb_id}  ✗ ERROR: {e}")
        _record_failure(tmdb_id, repr(e))
        return ("fail", tmdb_id, str(e))


def worker_loop(bucket, counter, total):
    """A single worker processes its slice of IDs, sleeping between calls."""
    results = []
    for local_idx, tid in enumerate(bucket):
        with counter_lock:
            counter[0] += 1
            index = counter[0]
        results.append(load_one(tid, index, total))
        if local_idx < len(bucket) - 1:
            time.sleep(PER_WORKER_DELAY_SECONDS)
    return results


# ─── Driver ────────────────────────────────────────────────────────────
def main():
    if not SEED_IDS:
        print(
            "SEED_IDS is empty. Paste TMDB IDs into the SEED_IDS list at "
            "the top of backend/seed_bulk.py and re-run."
        )
        return 1

    unique_ids = list(dict.fromkeys(SEED_IDS))  # preserve order, drop duplicates
    cached_before = already_cached_ids(unique_ids)
    to_load = [i for i in unique_ids if i not in cached_before]

    print(f"Backend:             {BASE}")
    print(f"DB path:             {DB_PATH}")
    print(f"Total IDs (deduped): {len(unique_ids)}")
    print(f"Already cached:      {len(cached_before)}")
    print(f"To load:             {len(to_load)}")
    print(f"Workers:             {NUM_WORKERS}, per-worker delay: {PER_WORKER_DELAY_SECONDS}s")
    print()

    if not to_load:
        print("Nothing to do — every requested ID is already in the cache.")
        return 0

    # Reset the error log so it only contains this run's failures.
    if os.path.exists(ERROR_LOG):
        os.remove(ERROR_LOG)

    # Round-robin partition so workers progress through the list in parallel
    # instead of one worker burning through its whole block before the next
    # one starts.
    buckets = [[] for _ in range(NUM_WORKERS)]
    for i, tid in enumerate(to_load):
        buckets[i % NUM_WORKERS].append(tid)

    counter = [0]
    total = len(to_load)
    started = time.time()

    results = []
    with ThreadPoolExecutor(max_workers=NUM_WORKERS) as ex:
        futures = [ex.submit(worker_loop, b, counter, total) for b in buckets if b]
        for fut in as_completed(futures):
            results.extend(fut.result())

    ok = [r for r in results if r[0] == "ok"]
    fail = [r for r in results if r[0] == "fail"]
    elapsed = time.time() - started

    print()
    print("─" * 60)
    print(f"Cached this run:  {len(ok)}")
    print(f"Skipped (in DB):  {len(cached_before)}")
    print(f"Failed:           {len(fail)}")
    if elapsed > 0 and ok:
        print(f"Elapsed:          {elapsed:.1f}s ({len(ok) / elapsed * 60:.1f} cached/min)")
    else:
        print(f"Elapsed:          {elapsed:.1f}s")

    if fail:
        print(f"\nFailure details: {ERROR_LOG}")
        print("Re-run the script to retry — completed IDs will be skipped automatically.")

    return 0 if not fail else 2


if __name__ == "__main__":
    sys.exit(main())
