#!/usr/bin/env python3
"""
Standalone ReelShield database seeder — no Docker required.
Calls TMDB and Gemini directly and writes to the SQLite database.

Usage:
    python3 backend/seed_direct.py               # seed all MOVIES not yet cached
    python3 backend/seed_direct.py --dry-run     # show what would be seeded, no API calls
    python3 backend/seed_direct.py --limit 20    # stop after 20 new movies
    python3 backend/seed_direct.py --fix-missing # only generate warnings for movies already
                                                 # in the DB that are missing warnings
    python3 backend/seed_direct.py --fix-ghosts  # re-seed films whose existing warnings
                                                 # have avg confidence < 0.4 (Gemini default
                                                 # when it didn't recognize the film)

Cases handled automatically:
    - Already in content_warnings  → skipped (except --fix-ghosts re-checks confidence)
    - In movies but no warnings    → generates warnings only (no TMDB re-fetch)
    - Not in DB at all             → full fetch + warnings
"""

import argparse
import json
import os
import re
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path

import requests as req

# ── Load .env ─────────────────────────────────────────────────
def _load_dotenv(path: str = ".env") -> None:
    p = Path(path)
    if not p.exists():
        return
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip())

_load_dotenv()

TMDB_API_KEY   = os.environ.get("TMDB_API_KEY", "")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")

if not TMDB_API_KEY or not GEMINI_API_KEY:
    sys.exit("ERROR: TMDB_API_KEY and GEMINI_API_KEY must be set in .env")

TMDB_BASE  = "https://api.themoviedb.org/3"
GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    f"gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}"
)
DB_PATH = os.environ.get("DB_PATH", "./data/movie_cache.db")

WARNING_CATEGORIES = [
    "violence_gore", "self_harm_suicide",
    "miscarriage_pregnancy_loss", "sexual_content_nudity",
    "animal_abuse", "substances", "language",
    "horror_intensity", "flashing_lights",
]

PROMPT = """\
You are a film content expert with encyclopedic knowledge of movies.
Use your ACTUAL TRAINING KNOWLEDGE of this specific film to generate precise content warnings.

Movie: "{title}" ({year})
MPAA Rating: {rating}
Genres: {genres}
TMDB Overview: {overview}
TMDB Keywords: {keywords}

INSTRUCTIONS:
- Use what you KNOW about this film. Do not just guess from the overview.
- If a content category DEFINITELY occurs, set confidence to 1.0 (confirmed).
- If a category DEFINITELY does NOT occur, set severity to 0 and confidence to 1.0.
- Only use confidence < 1.0 when you genuinely do not know (obscure/unfamiliar film).
- severity scale: 0=absent, 1=mild/brief, 2=moderate, 3=severe or graphic
- notes: concise, SPOILER-FREE explanation
- flashing_lights: strobe effects, rapid cuts, or flashing visuals that could trigger epilepsy?

Return ONLY valid JSON, no markdown fences, no commentary:
{{
  "disclaimer": "Gemini knowledge-based",
  "spoiler_free": {{
    "violence_gore": {{"severity": 0, "confidence": 1.0, "notes": ""}},
    "self_harm_suicide": {{"severity": 0, "confidence": 1.0, "notes": ""}},
    "miscarriage_pregnancy_loss": {{"severity": 0, "confidence": 1.0, "notes": ""}},
    "sexual_content_nudity": {{"severity": 0, "confidence": 1.0, "notes": ""}},
    "animal_abuse": {{"severity": 0, "confidence": 1.0, "notes": ""}},
    "substances": {{"severity": 0, "confidence": 1.0, "notes": ""}},
    "language": {{"severity": 0, "confidence": 1.0, "notes": ""}},
    "horror_intensity": {{"severity": 0, "confidence": 1.0, "notes": ""}},
    "flashing_lights": {{"severity": 0, "confidence": 1.0, "notes": ""}}
  }}
}}"""


# ── Database ──────────────────────────────────────────────────
def _conn() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(os.path.abspath(DB_PATH)), exist_ok=True)
    return sqlite3.connect(DB_PATH)

def _has_warnings(tmdb_id: int) -> bool:
    c = _conn()
    row = c.execute("SELECT 1 FROM content_warnings WHERE tmdb_id=?", (tmdb_id,)).fetchone()
    c.close()
    return row is not None

def _get_cached_metadata(tmdb_id: int) -> dict | None:
    c = _conn()
    row = c.execute("SELECT metadata_json FROM movies WHERE tmdb_id=?", (tmdb_id,)).fetchone()
    c.close()
    return json.loads(row[0]) if row else None

def _save_movie(tmdb_id: int, data: dict) -> None:
    c = _conn()
    c.execute(
        "INSERT OR REPLACE INTO movies VALUES (?,?,?,?,?,?,?)",
        (tmdb_id, data.get("title"), data.get("year"), data.get("imdb_id"),
         data.get("runtime_min"), json.dumps(data), datetime.now().isoformat())
    )
    c.commit(); c.close()

def _save_warnings(tmdb_id: int, data: dict) -> None:
    c = _conn()
    c.execute(
        "INSERT OR REPLACE INTO content_warnings VALUES (?,?,?)",
        (tmdb_id, json.dumps(data), datetime.now().isoformat())
    )
    c.commit(); c.close()

def _count_warnings() -> int:
    c = _conn()
    n = c.execute("SELECT COUNT(*) FROM content_warnings").fetchone()[0]
    c.close()
    return n

def _movies_missing_warnings() -> list[tuple[int, str]]:
    c = _conn()
    rows = c.execute(
        "SELECT m.tmdb_id, m.title FROM movies m "
        "LEFT JOIN content_warnings cw ON m.tmdb_id=cw.tmdb_id "
        "WHERE cw.tmdb_id IS NULL ORDER BY m.title"
    ).fetchall()
    c.close()
    return rows


def _ghost_films(min_avg_confidence: float = 0.4) -> list[tuple[int, str]]:
    """Films where Gemini returned warnings but average confidence is below
    the floor — i.e. the model didn't recognize the film and defaulted to
    all-zero severity at 0.3 confidence. These need re-seeding because the
    cached warnings can't be trusted."""
    c = _conn()
    rows = c.execute(
        "SELECT m.tmdb_id, m.title, cw.warnings_json "
        "FROM movies m JOIN content_warnings cw ON m.tmdb_id=cw.tmdb_id"
    ).fetchall()
    c.close()
    ghosts: list[tuple[int, str]] = []
    for tmdb_id, title, wj in rows:
        try:
            sf = (json.loads(wj or "{}").get("spoiler_free") or {})
        except json.JSONDecodeError:
            ghosts.append((tmdb_id, title))
            continue
        confs = [
            (sf.get(cat) or {}).get("confidence")
            for cat in WARNING_CATEGORIES
            if (sf.get(cat) or {}).get("severity") is not None
        ]
        if not confs:
            ghosts.append((tmdb_id, title))
            continue
        avg = sum(c or 0.0 for c in confs) / len(confs)
        if avg < min_avg_confidence:
            ghosts.append((tmdb_id, title))
    ghosts.sort(key=lambda t: t[1])
    return ghosts


# ── TMDB ──────────────────────────────────────────────────────
def _tmdb(path: str, params: dict | None = None) -> dict:
    p = {"api_key": TMDB_API_KEY, **(params or {})}
    r = req.get(f"{TMDB_BASE}{path}", params=p, timeout=30)
    r.raise_for_status()
    return r.json()

def search_tmdb(query: str) -> int | None:
    data    = _tmdb("/search/movie", {"query": query, "include_adult": False})
    results = data.get("results") or []
    return results[0]["id"] if results else None

def build_bundle(tmdb_id: int) -> dict:
    d       = _tmdb(f"/movie/{tmdb_id}")
    kw_data = _tmdb(f"/movie/{tmdb_id}/keywords")
    rd_data = _tmdb(f"/movie/{tmdb_id}/release_dates")

    cert = None
    for entry in rd_data.get("results", []):
        if entry.get("iso_3166_1") == "US":
            for rd in entry.get("release_dates", []):
                cert = (rd.get("certification") or "").strip() or None
                if cert:
                    break

    overview = re.sub(r"\s+", " ", d.get("overview", "") or "").strip()
    release  = d.get("release_date", "")
    return {
        "tmdb_id":          tmdb_id,
        "title":            d.get("title"),
        "year":             release[:4] if release else None,
        "imdb_id":          d.get("imdb_id"),
        "runtime_min":      d.get("runtime"),
        "overview":         overview or None,
        "genres":           [g["name"] for g in (d.get("genres") or [])],
        "keywords":         [k["name"] for k in kw_data.get("keywords", []) if k.get("name")],
        "us_certification": cert,
        "poster_path":      d.get("poster_path"),
    }


# ── Gemini ────────────────────────────────────────────────────
def call_gemini(prompt: str, retries: int = 4) -> str:
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.1, "topP": 0.9, "maxOutputTokens": 2000},
    }
    for attempt in range(retries):
        try:
            r = req.post(GEMINI_URL, json=body, timeout=60)
            if r.status_code == 429:
                wait = 15 * (attempt + 1)
                print(f"\n    rate-limited — waiting {wait}s", end="", flush=True)
                time.sleep(wait)
                continue
            r.raise_for_status()
            return r.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
        except Exception as e:
            if attempt == retries - 1:
                return f"Error: {e}"
            time.sleep(5)
    return "Error: max retries"

def generate_warnings(movie: dict) -> dict:
    prompt = PROMPT.format(
        title    = movie.get("title", "Unknown"),
        year     = movie.get("year", ""),
        rating   = movie.get("us_certification") or "Unknown",
        overview = (movie.get("overview") or "")[:300],
        keywords = ", ".join((movie.get("keywords") or [])[:20]),
        genres   = ", ".join((movie.get("genres") or [])),
    )
    text = call_gemini(prompt)
    try:
        if text.startswith("```"):
            text = text.split("```")[1].replace("json", "", 1).strip()
        if text.endswith("```"):
            text = text.rsplit("```", 1)[0].strip()
        s = text.find("{"); e = text.rfind("}") + 1
        if s >= 0 and e > s:
            text = text[s:e]
        return json.loads(text)
    except Exception:
        return {
            "disclaimer": "Fallback",
            "spoiler_free": {
                cat: {"severity": 0, "confidence": 0.3, "notes": ""}
                for cat in WARNING_CATEGORIES
            },
        }


# ── Movie list ────────────────────────────────────────────────
MOVIES = [
    # ── Studio Ghibli / Japanese animation ───────────────────
    "My Neighbor Totoro (1988)",
    "Princess Mononoke (1997)",
    "Howl's Moving Castle (2004)",
    "Nausicaä of the Valley of the Wind (1984)",
    "The Tale of Princess Kaguya (2013)",
    "Grave of the Fireflies (1988)",
    "Your Name (2016)",
    "A Silent Voice (2016)",
    "Wolf Children (2012)",
    "Weathering with You (2019)",

    # ── Pixar / Disney animation ──────────────────────────────
    "Toy Story (1995)",
    "Toy Story 3 (2010)",
    "Finding Nemo (2003)",
    "The Incredibles (2004)",
    "WALL-E (2008)",
    "Inside Out (2015)",
    "Inside Out 2 (2024)",
    "Ratatouille (2007)",
    "Soul (2020)",
    "Turning Red (2022)",

    # ── Classic family / adventure ────────────────────────────
    "The Wizard of Oz (1939)",
    "Mary Poppins (1964)",
    "Babe (1995)",
    "The NeverEnding Story (1984)",
    "Labyrinth (1986)",
    "Bambi (1942)",
    "Fantasia (1940)",
    "Willy Wonka and the Chocolate Factory (1971)",
    "The Secret Garden (1993)",
    "Homeward Bound: The Incredible Journey (1993)",

    # ── Romance / Drama ───────────────────────────────────────
    "Before Sunrise (1995)",
    "Before Sunset (2004)",
    "Before Midnight (2013)",
    "Eternal Sunshine of the Spotless Mind (2004)",
    "Lost in Translation (2003)",
    "Carol (2015)",
    "Portrait of a Lady on Fire (2019)",
    "Call Me by Your Name (2017)",
    "Brokeback Mountain (2005)",
    "Blue Valentine (2010)",

    # ── Classic Hollywood drama ───────────────────────────────
    "Casablanca (1942)",
    "All About Eve (1950)",
    "Sunset Boulevard (1950)",
    "12 Angry Men (1957)",
    "To Kill a Mockingbird (1962)",
    "One Flew Over the Cuckoo's Nest (1975)",
    "Kramer vs. Kramer (1979)",
    "Sophie's Choice (1982)",
    "Ordinary People (1980)",
    "Terms of Endearment (1983)",

    # ── Comedy ───────────────────────────────────────────────
    "Some Like It Hot (1959)",
    "Dr. Strangelove (1964)",
    "Annie Hall (1977)",
    "Ferris Bueller's Day Off (1986)",
    "When Harry Met Sally (1989)",
    "Home Alone (1990)",
    "The Truman Show (1998)",
    "School of Rock (2003)",
    "Little Miss Sunshine (2006)",
    "The Favourite (2018)",

    # ── Crime / Neo-noir ──────────────────────────────────────
    "The Godfather (1972)",
    "The Godfather Part II (1974)",
    "Goodfellas (1990)",
    "Pulp Fiction (1994)",
    "Fargo (1996)",
    "L.A. Confidential (1997)",
    "The Silence of the Lambs (1991)",
    "Se7en (1995)",
    "Zodiac (2007)",
    "Nightcrawler (2014)",

    # ── Psychological thriller ────────────────────────────────
    "Rear Window (1954)",
    "Psycho (1960)",
    "The Conversation (1974)",
    "Chinatown (1974)",
    "Misery (1990)",
    "Memento (2000)",
    "Oldboy (2003)",
    "Black Swan (2010)",
    "Gone Girl (2014)",
    "Promising Young Woman (2020)",

    # ── Horror ───────────────────────────────────────────────
    "The Shining (1980)",
    "Halloween (1978)",
    "The Thing (1982)",
    "Alien (1979)",
    "Aliens (1986)",
    "The Exorcist (1973)",
    "Rosemary's Baby (1968)",
    "28 Days Later (2002)",
    "Sinister (2012)",
    "Terrifier 2 (2022)",

    # ── Sci-Fi ────────────────────────────────────────────────
    "2001: A Space Odyssey (1968)",
    "Blade Runner (1982)",
    "The Matrix (1999)",
    "Children of Men (2006)",
    "Gravity (2013)",
    "Coherence (2013)",
    "Primer (2004)",
    "Predestination (2014)",
    "Upgrade (2018)",
    "Prospect (2018)",

    # ── Action / Adventure ────────────────────────────────────
    "Raiders of the Lost Ark (1981)",
    "The Terminator (1984)",
    "Aliens (1986)",
    "Speed (1994)",
    "Mission: Impossible (1996)",
    "Gladiator (2000)",
    "Casino Royale (2006)",
    "The Bourne Identity (2002)",
    "Edge of Tomorrow (2014)",
    "Fury (2014)",

    # ── International / World cinema ──────────────────────────
    "City of God (2002)",
    "Pan's Labyrinth (2006)",
    "The Lives of Others (2006)",
    "Amour (2012)",
    "The Hunt (2012)",
    "Force Majeure (2014)",
    "Son of Saul (2015)",
    "Roma (2018)",
    "Shoplifters (2018)",
    "Capernaum (2018)",

    # ── 2020s ─────────────────────────────────────────────────
    "The Power of the Dog (2021)",
    "Spencer (2021)",
    "Drive My Car (2021)",
    "The Northman (2022)",
    "Babylon (2022)",
    "Women Talking (2022)",
    "All of Us Strangers (2023)",
    "Saltburn (2023)",
    "May December (2023)",
    "Civil War (2024)",

    # ── Documentaries / True story ────────────────────────────
    "American History X (1998)",
    "Hotel Rwanda (2004)",
    "The Social Network (2010)",
    "Argo (2012)",
    "Spotlight (2015)",
    "I, Tonya (2017)",
    "Judas and the Black Messiah (2021)",
    "Summer of Soul (2021)",
    "All the Beauty and the Bloodshed (2022)",
    "20 Days in Mariupol (2023)",

    # ── Substance / mental health / heavy ─────────────────────
    "Trainspotting (1996)",
    "Requiem for a Dream (2000)",
    "A Beautiful Boy (2018)",
    "Beautiful Boy (2018)",
    "Elephant (2003)",
    "We Need to Talk About Kevin (2011)",
    "The Perks of Being a Wallflower (2012)",
    "Short Term 12 (2013)",
    "Silver Linings Playbook (2012)",
    "Cake (2014)",
]


# ── Main ──────────────────────────────────────────────────────
def main() -> None:
    parser = argparse.ArgumentParser(description="Seed ReelShield DB without Docker.")
    parser.add_argument("--dry-run",     action="store_true", help="Print plan, no API calls")
    parser.add_argument("--limit",       type=int, default=0, help="Max new movies to add (0 = all)")
    parser.add_argument("--fix-missing", action="store_true",
                        help="Only generate warnings for DB movies that are missing them")
    parser.add_argument("--fix-ghosts", action="store_true",
                        help="Re-seed films whose existing warnings have avg confidence < 0.4 "
                             "(Gemini default when it didn't recognize the film)")
    parser.add_argument("--ghost-threshold", type=float, default=0.4,
                        help="Confidence floor for --fix-ghosts (default 0.4)")
    args = parser.parse_args()

    before = _count_warnings()
    print(f"Database: {DB_PATH}")
    print(f"Warnings already cached: {before}\n")

    if args.fix_missing:
        missing = _movies_missing_warnings()
        if not missing:
            print("All DB movies already have warnings.")
            return
        print(f"Fixing {len(missing)} movies with missing warnings:\n")
        ok = fail = 0
        for tmdb_id, title in missing:
            print(f"  {title} (tmdb={tmdb_id}) ...", end=" ", flush=True)
            if args.dry_run:
                print("[dry-run]"); continue
            meta = _get_cached_metadata(tmdb_id)
            if not meta:
                print("ERROR: no metadata in DB"); fail += 1; continue
            warn = generate_warnings(meta)
            _save_warnings(tmdb_id, warn)
            sf   = warn.get("spoiler_free", {})
            hits = [c for c in WARNING_CATEGORIES if (sf.get(c) or {}).get("severity", 0) > 0]
            print(f"OK  ({len(hits)} warnings)")
            ok += 1
            time.sleep(1)
        print(f"\nDone: {ok} fixed, {fail} failed.")
        return

    if args.fix_ghosts:
        ghosts = _ghost_films(min_avg_confidence=args.ghost_threshold)
        if not ghosts:
            print(f"No ghost films found (confidence threshold {args.ghost_threshold}).")
            return
        limit = args.limit or len(ghosts)
        ghosts = ghosts[:limit]
        print(f"Re-seeding {len(ghosts)} ghost films (avg confidence < {args.ghost_threshold}):\n")
        ok = fail = skipped = 0
        for tmdb_id, title in ghosts:
            print(f"  {title} (tmdb={tmdb_id}) ...", end=" ", flush=True)
            if args.dry_run:
                print("[dry-run]"); continue
            meta = _get_cached_metadata(tmdb_id)
            if not meta:
                print("ERROR: no metadata in DB"); fail += 1; continue
            try:
                warn = generate_warnings(meta)
            except Exception as e:
                print(f"ERROR: {e}"); fail += 1; continue
            # Sanity check: if the regenerated warnings are still ghostly,
            # don't overwrite the existing row — record and move on.
            sf = warn.get("spoiler_free", {})
            confs = [(sf.get(c) or {}).get("confidence", 0.0) for c in WARNING_CATEGORIES]
            avg_conf = sum(confs) / max(len(confs), 1)
            if avg_conf < args.ghost_threshold:
                print(f"still ghosty (avg conf {avg_conf:.2f}), skipping")
                skipped += 1
                time.sleep(1)
                continue
            _save_warnings(tmdb_id, warn)
            hits = [c for c in WARNING_CATEGORIES if (sf.get(c) or {}).get("severity", 0) > 0]
            print(f"OK  (avg conf {avg_conf:.2f}, {len(hits)} warnings)")
            ok += 1
            time.sleep(1)
        print(f"\nDone: {ok} re-seeded, {skipped} still ghosty, {fail} failed.")
        return

    # ── Normal seeding from MOVIES list ───────────────────────
    added = skip = fail = 0
    limit = args.limit or len(MOVIES)

    for i, title in enumerate(MOVIES, 1):
        if added >= limit:
            print(f"\nLimit of {limit} reached.")
            break

        query = re.sub(r"\s*\(\d{4}\)\s*$", "", title).strip()
        print(f"[{i:3d}/{len(MOVIES)}] {title}", end=" … ", flush=True)

        if args.dry_run:
            print("[dry-run]"); continue

        try:
            # Search TMDB
            tmdb_id = search_tmdb(query)
            if not tmdb_id:
                print("NOT FOUND"); fail += 1; continue

            # Already fully cached?
            if _has_warnings(tmdb_id):
                print(f"skip (tmdb={tmdb_id})"); skip += 1; continue

            # Metadata already cached?
            meta = _get_cached_metadata(tmdb_id)
            if meta:
                print(f"meta cached (tmdb={tmdb_id}), generating warnings …", end=" ", flush=True)
            else:
                meta = build_bundle(tmdb_id)
                _save_movie(tmdb_id, meta)

            warn = generate_warnings(meta)
            _save_warnings(tmdb_id, warn)

            sf   = warn.get("spoiler_free", {})
            hits = [c for c in WARNING_CATEGORIES if (sf.get(c) or {}).get("severity", 0) > 0]
            print(f"OK  (tmdb={tmdb_id}, {len(hits)} warnings triggered)")
            added += 1

        except Exception as e:
            print(f"ERROR: {e}"); fail += 1

        time.sleep(1)   # gentle rate-limiting between movies

    after = _count_warnings()
    print(f"\n{'─'*55}")
    print(f"Added:   {added}")
    print(f"Skipped: {skip} (already cached)")
    print(f"Failed:  {fail}")
    print(f"Total warnings in DB: {before} → {after}")


if __name__ == "__main__":
    main()
