#!/usr/bin/env python3
"""
Re-assess films whose cached warnings are all-zero severity.

Some cached entries claim a film has zero content in every category, often at
high confidence (e.g. a famously violent film stored as having no violence).
Those defeat the avoid filters and mislabel films as safe. This script finds
every film whose entire spoiler_free severity vector is zero and re-runs the
app's own warning generation against the film's cached metadata, overwriting
the stored warnings. A Gemini failure (fallback result) is never written, so
a bad call can't make the data worse.

Usage:
    python backend/reassess_warnings.py --dry-run     # list targets, no Gemini
    python backend/reassess_warnings.py               # re-assess all all-zero films
    python backend/reassess_warnings.py --limit 5     # stop after 5

Requires TMDB_API_KEY and GEMINI_API_KEY in the environment.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import backend.app as app  # noqa: E402  (imports the app's prompt, generator, db)

CATS = app.WARNING_CATEGORIES


def _all_zero(sf: dict) -> bool:
    return max((float((sf.get(k) or {}).get("severity") or 0) for k in CATS), default=0) == 0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=os.environ.get("DB_PATH", "./data/movie_cache.db"))
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--delay", type=float, default=5.0)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    conn = sqlite3.connect(args.db)
    rows = conn.execute(
        "SELECT m.tmdb_id, m.title, m.year, m.metadata_json, cw.warnings_json "
        "FROM movies m JOIN content_warnings cw USING(tmdb_id)"
    ).fetchall()
    conn.close()

    targets = []
    for tid, title, year, mj, wj in rows:
        sf = (json.loads(wj or "{}")).get("spoiler_free") or {}
        if _all_zero(sf):
            targets.append((tid, title, year, json.loads(mj or "{}")))

    print(f"{len(targets)} films with all-zero severities (re-assessment targets)")
    if args.limit:
        targets = targets[: args.limit]
        print(f"  (limited to {len(targets)} this run)")

    if args.dry_run:
        for tid, t, y, _ in targets:
            print(f"  {tid:<8} {t} ({y})")
        return

    updated = still_zero = failed = 0
    for i, (tid, title, year, meta) in enumerate(targets, 1):
        movie_data = {
            "title":            meta.get("title") or title,
            "year":             meta.get("year") or year,
            "us_certification": meta.get("us_certification"),
            "overview":         meta.get("overview"),
            "keywords":         meta.get("keywords"),
            "genres":           meta.get("genres"),
        }
        try:
            new = app.warning_gen.generate_warnings(movie_data, app.DEFAULT_PROMPT_TEMPLATE)
        except Exception as e:
            failed += 1
            print(f"  [{i}/{len(targets)}] FAIL     {title} ({year}): {e}")
            new = None

        nsf = (new or {}).get("spoiler_free") or {}
        if not new or new.get("disclaimer") == "Fallback" or not nsf:
            if new is not None:
                failed += 1
                print(f"  [{i}/{len(targets)}] FALLBACK {title} ({year}) (kept old data)")
        else:
            app.db.save_warnings(tid, new)
            nz = max((float((nsf.get(k) or {}).get("severity") or 0) for k in CATS), default=0)
            if nz > 0:
                updated += 1
                print(f"  [{i}/{len(targets)}] UPDATED  {title} ({year})")
            else:
                still_zero += 1
                print(f"  [{i}/{len(targets)}] still 0  {title} ({year})")

        if i < len(targets) and args.delay > 0:
            time.sleep(args.delay)

    print(f"\nDone: {updated} now have content warnings, {still_zero} re-confirmed clean, {failed} failed/kept.")


if __name__ == "__main__":
    main()
