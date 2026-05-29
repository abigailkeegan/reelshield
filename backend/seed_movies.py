#!/usr/bin/env python3
"""Seed the ReelShield database with movies via the running Docker container."""

import os
import time
import sqlite3
import sys
import requests

BASE = os.environ.get("REELSHIELD_BASE", "http://localhost:7860")

DEFAULT_DB = os.path.join(os.path.dirname(__file__), "..", "data", "movie_cache.db")
DB_PATH = os.environ.get("DB_PATH", DEFAULT_DB)

GEMINI_DELAY_SECONDS = 5

TMDB_IDS = [
    10193, 862, 129, 12477, 808, 585, 9487, 10515, 11886, 13053,
    44214, 70074, 264644, 274479, 522931, 11517, 13580, 207703, 9918, 197,
    11873, 753342, 346364, 475557, 603, 297761, 74643, 118340, 284054, 11056,
    1701, 10090, 508965, 399174, 290098, 14836, 15121, 11216, 637,
    77338, 11362, 11689, 11688, 22683, 11798, 289, 11202, 15067, 807,
    539, 240832, 15371, 11360, 11778, 240, 11884, 11, 11324, 578,
    11036, 10010, 14976, 862, 11517, 11574, 11908, 11232, 580489, 634649,
    766507, 361743, 792307,
    11536, 426, 745, 744, 11798, 4375, 11618, 2300, 11232,
    1586, 3035, 11234, 11975, 8012, 11236, 1673, 11822, 11694,
    11610, 15372, 11388, 11367, 11377, 11420, 13352, 11286, 11423, 10739,
    10268, 11389, 9377, 9603, 11017, 812, 11853, 11415,
    10869, 2109, 769, 9806, 10494, 10529, 10632, 10770, 4922, 13183,
    13393, 10929, 9693, 10674, 1724, 1422, 760104, 667538, 385687,
    882569, 940551, 725201, 897087,
    872, 975, 78, 562, 5915,
]


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


def already_cached_ids(ids):
    if not os.path.exists(DB_PATH):
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
    finally:
        conn.close()


def load(tmdb_id):
    r = requests.post(
        f"{BASE}/api/load_movie",
        json={"tmdb_id": tmdb_id},
        timeout=90,
    )
    r.raise_for_status()
    return r.json()


def main():
    ids = TMDB_IDS
    cached = already_cached_ids(ids)
    to_load = [i for i in ids if i not in cached]

    print(f"Total IDs:       {len(ids)}")
    print(f"Already cached:  {len(cached)}")
    print(f"To load:         {len(to_load)}\n")

    if cached:
        print("Skipped (already cached):")
        for i in ids:
            if i in cached:
                print(f"  - {i}")
        print()

    newly_cached = []
    failed = []

    for idx, tid in enumerate(to_load, 1):
        preview_title, preview_year = fetch_tmdb_title(tid)
        preview = f"'{preview_title}' ({preview_year})" if preview_title else "(title lookup failed)"
        print(f"[{idx}/{len(to_load)}] tmdb={tid} → {preview} … loading…", flush=True)
        try:
            result = load(tid)
            title = (result.get("movie") or {}).get("title", "?")
            print(f"    cached OK ({title})")
            newly_cached.append((tid, title))
        except requests.RequestException as e:
            print(f"    ERROR: {e}")
            failed.append(tid)
        if idx < len(to_load):
            time.sleep(GEMINI_DELAY_SECONDS)

    print(f"\nNewly cached ({len(newly_cached)}):")
    for tid, title in newly_cached:
        print(f"  - {tid}  {title}")

    if failed:
        print(f"\nFailed ({len(failed)}):")
        for tid in failed:
            print(f"  - {tid}")


if __name__ == "__main__":
    main()
