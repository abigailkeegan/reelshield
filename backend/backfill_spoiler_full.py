#!/usr/bin/env python3
"""
Backfill spoiler-full warning notes for cached films that only have a
spoiler-free assessment.

Most films in the cache were seeded under an older prompt that produced only
the spoiler_free block, so Spoiler Mode in the UI has nothing extra to show
for them (frontend/static/js/app.js falls back to spoiler_free). This script
fills in the spoiler_full block additively:

  - It keeps each film's existing spoiler_free block exactly as is.
  - It asks Gemini only for spoiler-full *notes* per category.
  - Severity and confidence for spoiler_full are copied from spoiler_free, so
    the trained models (which read spoiler_free severities) and the displayed
    severities are unchanged. Only the descriptive notes differ.

Only films that have a populated spoiler_free block but no populated
spoiler_full block are touched. Films without a usable spoiler_free
assessment (e.g. low-confidence "ghost" rows) are skipped and reported.

Usage:
    python backend/backfill_spoiler_full.py                 # backfill all eligible films
    python backend/backfill_spoiler_full.py --dry-run       # list eligible films, no Gemini, no writes
    python backend/backfill_spoiler_full.py --limit 10      # stop after 10 films
    python backend/backfill_spoiler_full.py --delay 3       # seconds between Gemini calls (default 5)

Requires GEMINI_API_KEY in the environment.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import sqlite3  # noqa: E402

from backend.cluster_engine import WARNING_CATEGORIES  # noqa: E402

DEFAULT_DB = os.environ.get("DB_PATH", "./data/movie_cache.db")
GEMINI_MODEL = "models/gemini-2.5-flash"


# ── Pure helpers (no Gemini, no DB) ──────────────────────────────────────────

def _block_is_populated(block: dict | None) -> bool:
    """A warning block counts as populated if any category has a non-empty
    note or a severity above zero."""
    if not block:
        return False
    for cat in WARNING_CATEGORIES:
        d = block.get(cat) or {}
        if (d.get("notes") or "").strip() or float(d.get("severity") or 0) > 0:
            return True
    return False


def needs_backfill(warnings: dict) -> bool:
    """True when the film has a usable spoiler_free block but no populated
    spoiler_full block, i.e. it is a candidate for additive backfill."""
    return (
        _block_is_populated(warnings.get("spoiler_free"))
        and not _block_is_populated(warnings.get("spoiler_full"))
    )


def build_spoiler_full(spoiler_free: dict, gemini_notes: dict) -> dict:
    """Construct the spoiler_full block from the existing spoiler_free block
    and Gemini's per-category spoiler-full notes.

    Severity and confidence are copied verbatim from spoiler_free (the prompt
    contract says they must match). Notes come from Gemini; if Gemini omits a
    category, we fall back to the existing spoiler_free note so we never
    downgrade the data."""
    out: dict = {}
    for cat in WARNING_CATEGORIES:
        sf = spoiler_free.get(cat) or {}
        note = gemini_notes.get(cat)
        # Fall back to the spoiler_free note whenever Gemini gives nothing
        # usable (missing key, null, or empty/whitespace). This guarantees
        # spoiler_full is never blanker than spoiler_free, which matters when
        # Gemini returns an all-empty object (e.g. safety-filtered films).
        if not (note or "").strip():
            note = sf.get("notes", "")
        out[cat] = {
            "severity":   sf.get("severity", 0),
            "confidence": sf.get("confidence", 0.0),
            "notes":      note,
        }
    return out


def _build_prompt(title, year, genres, spoiler_free: dict) -> str:
    lines = []
    for cat in WARNING_CATEGORIES:
        sf = spoiler_free.get(cat) or {}
        sev = sf.get("severity", 0)
        note = (sf.get("notes") or "").strip() or "(none)"
        lines.append(f"- {cat}: severity {sev} — {note}")
    existing = "\n".join(lines)
    cats = ", ".join(WARNING_CATEGORIES)
    return (
        "You are a film content expert with encyclopedic knowledge of movies.\n\n"
        f'For the film "{title}" ({year}), genres: {genres}, a spoiler-free '
        "content-warning assessment already exists. Write the SPOILER-FULL version "
        "of the notes for each category. Spoiler-full notes MAY reference specific "
        "scenes, character names, plot twists, and the ending. Do not change the "
        "severity of any category; only expand the descriptive detail.\n\n"
        f"Existing spoiler-free assessment:\n{existing}\n\n"
        "Return ONLY a JSON object mapping each category to its spoiler-full note "
        "string. For categories that are absent from the film (severity 0), return "
        'an empty string "". Do not include any keys other than these categories:\n'
        f"{cats}\n"
    )


def parse_gemini_json(text: str) -> dict:
    """Extract the JSON object from a Gemini response, tolerating code fences."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```")[1].replace("json", "", 1).strip()
    if text.endswith("```"):
        text = text.rsplit("```", 1)[0].strip()
    start = text.find("{")
    end = text.rfind("}") + 1
    if start >= 0 and end > start:
        text = text[start:end]
    return json.loads(text)


# ── Main backfill loop ───────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=DEFAULT_DB)
    parser.add_argument("--limit", type=int, default=0, help="Stop after N films (0 = no limit)")
    parser.add_argument("--delay", type=float, default=5.0, help="Seconds between Gemini calls")
    parser.add_argument("--dry-run", action="store_true", help="List eligible films; no Gemini, no writes")
    args = parser.parse_args()

    conn = sqlite3.connect(args.db)
    rows = conn.execute(
        "SELECT m.tmdb_id, m.title, m.year, m.metadata_json, cw.warnings_json "
        "FROM movies m JOIN content_warnings cw USING(tmdb_id)"
    ).fetchall()

    eligible = []
    skipped_no_sf = 0
    already_full = 0
    for tmdb_id, title, year, mj, wj in rows:
        try:
            warn = json.loads(wj or "{}")
            meta = json.loads(mj or "{}")
        except json.JSONDecodeError:
            continue
        if _block_is_populated(warn.get("spoiler_full")):
            already_full += 1
            continue
        if not _block_is_populated(warn.get("spoiler_free")):
            skipped_no_sf += 1
            continue
        eligible.append((tmdb_id, title, year, meta, warn))

    print(f"Scanned {len(rows)} cached films.")
    print(f"  already have spoiler_full : {already_full}")
    print(f"  no usable spoiler_free    : {skipped_no_sf} (skipped)")
    print(f"  eligible for backfill     : {len(eligible)}")
    if args.limit:
        eligible = eligible[: args.limit]
        print(f"  (limited to {len(eligible)} this run)")

    if args.dry_run:
        print("\n[dry-run] films that would be backfilled:")
        for tmdb_id, title, year, _meta, _warn in eligible:
            print(f"  {tmdb_id:<8} {title} ({year})")
        return

    if not eligible:
        print("\nNothing to do.")
        return

    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        sys.exit("GEMINI_API_KEY is not set. Export it before running a real backfill.")
    import google.generativeai as genai
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(
        model_name=GEMINI_MODEL,
        generation_config={"temperature": 0.1, "top_p": 0.9, "max_output_tokens": 8000},
    )

    done = 0
    fallback = 0
    for i, (tmdb_id, title, year, meta, warn) in enumerate(eligible, 1):
        genres = ", ".join(meta.get("genres") or [])
        prompt = _build_prompt(title, year, genres, warn["spoiler_free"])
        try:
            resp = model.generate_content(prompt)
            notes = parse_gemini_json(resp.text)
            if not isinstance(notes, dict):
                raise ValueError("Gemini did not return a JSON object")
            status = "OK"
        except Exception as e:
            # Don't skip: write a spoiler_free-derived block so the film is
            # never left missing/blank. build_spoiler_full copies the
            # spoiler_free notes when given no Gemini notes.
            notes = {}
            status = f"FALLBACK ({e})"
            fallback += 1

        warn["spoiler_full"] = build_spoiler_full(warn["spoiler_free"], notes)
        conn.execute(
            "INSERT OR REPLACE INTO content_warnings VALUES (?,?,?)",
            (tmdb_id, json.dumps(warn), __import__("datetime").datetime.now().isoformat()),
        )
        conn.commit()
        done += 1
        print(f"  [{i}/{len(eligible)}] {status:<8} {title} ({year})")

        if i < len(eligible) and args.delay > 0:
            time.sleep(args.delay)

    conn.close()
    print(f"\nBackfilled {done} films ({fallback} via spoiler_free fallback).")


if __name__ == "__main__":
    main()
