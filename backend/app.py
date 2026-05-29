import re
import json
import sqlite3
import time
import os
from werkzeug.security import generate_password_hash, check_password_hash
import secrets
from datetime import datetime
from typing import Optional, Dict, List
import numpy as np
import requests as req
from flask import Flask, render_template, request, jsonify, session
import google.generativeai as genai
from backend.comfort_distance_recommender import comfort_find_movies, comfort_group_movies
from backend.embeddings import (
    MODEL_NAME as EMBED_MODEL_NAME,
    bytes_to_vec,
    cosine_top_k,
    embed_text,
)
from backend.cluster_engine import find_twins as cluster_find_twins, get_cluster_name
from backend.mpa_classifier import (
    load_model as load_mpa_model,
    predict_one as predict_mpa,
    CERT_TO_LABEL as MPA_CERT_TO_LABEL,
)

# ─── CONFIG FROM ENVIRONMENT ─────────────────────────────────
TMDB_API_KEY   = os.environ.get("TMDB_API_KEY", "")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")

if not TMDB_API_KEY or not GEMINI_API_KEY:
    raise RuntimeError(
        "Missing API keys. Set TMDB_API_KEY and GEMINI_API_KEY "
        "in your .env file or environment variables."
    )

genai.configure(api_key=GEMINI_API_KEY)
gemini_model = genai.GenerativeModel(
    model_name="models/gemini-2.5-flash",
    generation_config={"temperature": 0.1, "top_p": 0.9, "max_output_tokens": 8000}
)

TMDB_BASE = "https://api.themoviedb.org/3"
DB_PATH   = os.environ.get("DB_PATH", "/data/movie_cache.db")
OMDB_API_KEY = os.environ.get("OMDB_API_KEY", "")
OMDB_BASE    = "http://www.omdbapi.com"


def _hydrate_cache_from_hf():
    """If DB_PATH is missing or empty, pull a pre-warmed copy from the
    HF Dataset on first boot so the Space starts with cached warnings
    instead of cold-building. Failures are non-fatal — the app falls
    back to lazily building the cache as users search."""
    try:
        if DB_PATH == ":memory:":
            return
        if os.path.exists(DB_PATH) and os.path.getsize(DB_PATH) > 0:
            return
        repo = os.environ.get("REELSHIELD_CACHE_REPO", "abigailkeegan/reelshield-cache")
        from huggingface_hub import hf_hub_download
        import shutil
        parent = os.path.dirname(DB_PATH)
        if parent:
            os.makedirs(parent, exist_ok=True)
        downloaded = hf_hub_download(
            repo_id=repo,
            repo_type="dataset",
            filename="movie_cache.db",
        )
        shutil.copy(downloaded, DB_PATH)
        size_mb = os.path.getsize(DB_PATH) / 1_000_000
        print(f"Hydrated cache from {repo} -> {DB_PATH} ({size_mb:.1f} MB)")
    except Exception as e:
        print(f"Cache hydration skipped: {type(e).__name__}: {e}")


_hydrate_cache_from_hf()


def _hydrate_models_from_hf():
    """Pull the trained .pkl artifacts from the HF Dataset on cold start
    so the two classic-ML features (K-Means content twins, MPA-rating
    classifier) work without retraining. Each file is downloaded
    independently; missing files are non-fatal — the feature that needs
    them will simply skip until a .pkl is present."""
    try:
        repo = os.environ.get("REELSHIELD_CACHE_REPO", "abigailkeegan/reelshield-cache")
        from huggingface_hub import hf_hub_download
        import shutil
        targets = [
            ("cluster_model.pkl",   "/data/cluster_model.pkl"),
            ("mpa_classifier.pkl",  "/data/mpa_classifier.pkl"),
        ]
        for filename, dest in targets:
            if os.path.exists(dest) and os.path.getsize(dest) > 0:
                continue
            parent = os.path.dirname(dest)
            if parent:
                os.makedirs(parent, exist_ok=True)
            try:
                downloaded = hf_hub_download(
                    repo_id=repo,
                    repo_type="dataset",
                    filename=filename,
                )
                shutil.copy(downloaded, dest)
                print(f"Hydrated model {filename} -> {dest}")
            except Exception as e:
                print(f"Model {filename} hydration skipped: {type(e).__name__}: {e}")
    except Exception as e:
        print(f"Model hydration skipped: {type(e).__name__}: {e}")


_hydrate_models_from_hf()


def _populate_movie_clusters_if_empty():
    """Self-heal the movie_clusters table on cold start: if the K-Means
    model is present but no per-film assignments exist (e.g. the cache DB
    was hydrated from an older snapshot that pre-dates clustering), load
    the model and write assignments derived from the cached warning
    vectors. Idempotent — exits immediately when the table already has
    rows. Non-fatal on any error."""
    try:
        if DB_PATH == ":memory:":
            return
        if not os.path.exists(DB_PATH) or os.path.getsize(DB_PATH) == 0:
            return
        from backend.cluster_engine import load_model, extract_features, assign_clusters
        model = load_model()
        if model is None:
            return
        conn = sqlite3.connect(DB_PATH)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS movie_clusters (
                tmdb_id INTEGER PRIMARY KEY,
                cluster_id INTEGER NOT NULL,
                distance_to_centroid REAL,
                model_version TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (tmdb_id) REFERENCES movies(tmdb_id) ON DELETE CASCADE
            )
        """)
        conn.commit()
        existing = conn.execute("SELECT COUNT(*) FROM movie_clusters").fetchone()[0]
        if existing > 0:
            conn.close()
            return
        X, ids = extract_features(DB_PATH)
        cluster_ids, dists = assign_clusters(model, X)
        model_version = f"kmeans_k{model.n_clusters}_hydrated"
        now = datetime.now().isoformat()
        conn.executemany(
            "INSERT OR REPLACE INTO movie_clusters VALUES (?,?,?,?,?)",
            [
                (int(tid), int(cid), float(d), model_version, now)
                for tid, cid, d in zip(ids, cluster_ids, dists)
            ],
        )
        conn.commit()
        conn.close()
        print(f"Populated movie_clusters with {len(ids)} rows (model_version={model_version})")
    except Exception as e:
        print(f"Cluster assignment skipped: {type(e).__name__}: {e}")


_populate_movie_clusters_if_empty()

WARNING_CATEGORIES = [
    "violence_gore", "self_harm_suicide",
    "miscarriage_pregnancy_loss", "sexual_content_nudity",
    "animal_abuse", "substances", "language",
    "horror_intensity", "flashing_lights"
]

# ─── DEFAULT PROMPT ───────────────────────────────────────────
DEFAULT_PROMPT_TEMPLATE = """You are a film content expert with encyclopedic knowledge of movies.
Use your ACTUAL TRAINING KNOWLEDGE of this specific film to generate precise content warnings.

Movie: "{title}" ({year})
MPA Rating: {rating}
Genres: {genres}
TMDB Overview: {overview}
TMDB Keywords: {keywords}

INSTRUCTIONS:
- Use what you KNOW about this film. Do not just guess from the overview.
- Each category's "confidence" must be scored INDEPENDENTLY for THAT category. Do not reuse a single overall confidence across categories.
- For each category, ask yourself: "How specifically and confidently do I recall this aspect of this film?"
  * 1.0 = I can recall specific scenes / details supporting my severity rating for THIS category
  * 0.7-0.9 = I recall the film generally and am reasonably sure about this category but lack specific scenes
  * 0.4-0.6 = I am inferring this category from genre / overview / era rather than direct recall
  * 0.1-0.3 = I do not really remember this aspect of the film; this is a guess
- It is EXPECTED that confidence will vary across categories for the same film. A film where you remember the action scenes vividly but can't recall language use should have high violence_gore confidence and low language confidence.
- severity scale: 0=absent, 1=mild/brief, 2=moderate, 3=severe or graphic
- notes: produce TWO versions per category:
  * spoiler_free notes: brief, generic description with NO plot reveals, character names, or specific scenes (e.g. "Multiple intense fight scenes with blood")
  * spoiler_full notes: may reference specific scenes, characters, twists, or endings (e.g. "Vincent shoots Marvin in the face during the car ride after the diner robbery")
- severity and confidence values MUST be identical between spoiler_free and spoiler_full for the same category — they describe the film's content itself, not the description style. Only the notes text changes.
- self_harm_suicide: does the film depict self-harm, suicide attempts, or suicidal ideation in any form?
- flashing_lights: does the film contain strobe effects, rapid cuts, or flashing visuals that could trigger photosensitive epilepsy? Be specific.

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
  }},
  "spoiler_full": {{
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

# ─── WATCHLIST RANK PROMPT ────────────────────────────────────
WATCHLIST_RANK_PROMPT = """You are screening a watchlist of movies for a user with specific sensitivities.

User sensitivity profile: {user_sensitivities}
Watchlist movies with cached warnings: {watchlist_json}

For each movie, return a ranked watchlist — safest to most triggering FOR THIS SPECIFIC USER.

Return ONLY a JSON array:
[
  {{
    "tmdb_id": 123,
    "title": "Movie Title",
    "rank": 1,
    "safe_for_user": true,
    "match_reason": "No triggers match your profile",
    "watchlist_badge": "🟢 Safe"
  }}
]

Ranking rules:
- Rank 1 = safest for this user's specific sensitivities
- Ignore categories the user hasn't flagged as sensitive
- Consider severity, not just presence of a warning
- watchlist_badge must be exactly one of: "🟢 Safe", "🟡 Mild Triggers", "🔴 Strong Triggers"
- Return ONLY valid JSON"""

# ─── GROUP PROFILE MERGE PROMPT ───────────────────────────────
GROUP_PROFILE_PROMPT = """You are helping a group of people find movies safe for everyone.

Group members and their sensitivity profiles:
{group_profiles_json}

Task - Generate a MERGED group profile:
- Combine ALL individual sensitivities (union, not intersection)
- Flag categories where 2+ members share a sensitivity as "high priority"
- Identify if any sensitivities conflict with popular genres

Return ONLY JSON:
{{
  "merged_sensitivities": ["category1", "category2"],
  "high_priority": ["category1"],
  "avoid_genres": ["Horror", "War"],
  "group_summary": "One sentence describing group's collective needs",
  "recommended_genres": ["Comedy", "Animation"]
}}"""

# ─── GROUP MOVIE RECOMMENDER PROMPT ───────────────────────────
GROUP_RECOMMENDER_PROMPT = """You are a movie recommender for a group with the following combined sensitivity profile.

Group profile: {merged_group_profile}
Candidate movies with warnings: {candidate_movies_json}
Mood preference: {mood}
Streaming availability (optional): {platform}

Score each movie on its suitability for the ENTIRE group.
A movie only passes if it is safe for ALL members.

Return ONLY a JSON array of recommended movies, sorted by group score:
[
  {{
    "tmdb_id": 123,
    "title": "Movie Title",
    "group_score": 94,
    "why_safe": "No warnings match any member's sensitivities",
    "one_concern": "Mild language — lowest risk item",
    "vibe": "Feel-good comedy, light and fun",
    "confidence": "high"
  }}
]

Rules:
- Exclude ANY movie that triggers even ONE member's HIGH priority sensitivity
- group_score is 0-100 (100 = perfect for everyone)
- why_safe must reference the group, not individuals (preserve privacy)
- Limit to top 5 recommendations
- confidence must be exactly one of: "high", "medium", "low"
- Return ONLY valid JSON"""

# ─── MOOD INTERPRETER PROMPT ──────────────────────────────────
MOOD_INTERPRETER_PROMPT = """You are an emotional readiness interpreter for a movie recommendation engine.

The user has selected the following mood state:
Mood input: "{mood_input}"

Mood options the user chose from:
- "I need something light and easy"
- "I'm okay with some emotion but nothing heavy"
- "I can handle something intense tonight"
- "I want to feel something deep — bring it on"
- "I need comfort and familiarity"

Also consider:
User's permanent sensitivity profile: {user_sensitivities}
Time of day: {time_of_day}
Day of week: {day_of_week}

Return ONLY JSON:
{{
  "emotional_ceiling": "low",
  "recommended_tones": ["heartwarming", "comedic", "thrilling"],
  "avoid_tones": ["bleak", "traumatic", "nihilistic"],
  "warning_threshold": "mild_ok",
  "genre_suggestions": ["Animation", "Rom-Com", "Adventure"],
  "mood_summary": "You're in the mood for something fun and low-stakes tonight."
}}

Rules:
- emotional_ceiling must be exactly one of: "low", "medium", "high", "intense"
- warning_threshold must be exactly one of: "exclude_all", "mild_ok", "moderate_ok", "all_ok"
- Permanent sensitivities ALWAYS override mood (mood never unlocks blocked content)
- Be empathetic in mood_summary — this user may be in a vulnerable state
- warning_threshold reflects mood, not permanent profile
- Return ONLY valid JSON"""

FRONTEND_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend")
TEMPLATE_DIR = os.path.join(FRONTEND_DIR, "templates")
STATIC_DIR = os.path.join(FRONTEND_DIR, "static")
app = Flask(
    __name__,
    template_folder=TEMPLATE_DIR,
    static_folder=STATIC_DIR,
    static_url_path="/static",
)
app.secret_key = os.environ.get("SECRET_KEY", secrets.token_hex(32))

app_state = {
    "current_movie": None,
    "conversation_history": [],
    "prompt_template": DEFAULT_PROMPT_TEMPLATE
}


# ─── HELPERS ──────────────────────────────────────────────────
def hash_password(password: str) -> str:
    return generate_password_hash(password)

def call_gemini(prompt: str, retries: int = 4) -> str:
    for attempt in range(retries):
        try:
            return gemini_model.generate_content(prompt).text.strip()
        except Exception as e:
            msg = str(e)
            if "429" in msg or "Resource exhausted" in msg or "RESOURCE_EXHAUSTED" in msg:
                wait = 5 * (attempt + 1)
                print(f"Rate limited. Waiting {wait}s (retry {attempt+1}/{retries})...")
                time.sleep(wait)
            else:
                return f"Error: {msg}"
    return "Error: Rate limit exceeded. Please wait a minute and try again."


# ─── DATABASE ─────────────────────────────────────────────────
class MovieDatabase:
    def __init__(self, db_path=DB_PATH):
        self.db_path = db_path
        dir_path = os.path.dirname(db_path)
        if dir_path:
            os.makedirs(dir_path, exist_ok=True)
        conn = sqlite3.connect(db_path)
        c = conn.cursor()

        c.execute("""CREATE TABLE IF NOT EXISTS movies
            (tmdb_id INTEGER PRIMARY KEY, title TEXT, year TEXT,
             imdb_id TEXT, runtime_min INTEGER, metadata_json TEXT, last_updated TEXT)""")

        c.execute("""CREATE TABLE IF NOT EXISTS content_warnings
            (tmdb_id INTEGER PRIMARY KEY, warnings_json TEXT, last_updated TEXT,
             FOREIGN KEY (tmdb_id) REFERENCES movies(tmdb_id))""")

        c.execute("""CREATE TABLE IF NOT EXISTS users
            (id INTEGER PRIMARY KEY AUTOINCREMENT,
             username TEXT UNIQUE NOT NULL,
             password_hash TEXT NOT NULL,
             created_at TEXT NOT NULL)""")

        c.execute("""CREATE TABLE IF NOT EXISTS reviews
            (id INTEGER PRIMARY KEY AUTOINCREMENT,
             tmdb_id INTEGER NOT NULL,
             user_id INTEGER NOT NULL,
             username TEXT NOT NULL,
             rating INTEGER,
             review_text TEXT NOT NULL,
             created_at TEXT NOT NULL,
             FOREIGN KEY (tmdb_id) REFERENCES movies(tmdb_id),
             FOREIGN KEY (user_id) REFERENCES users(id))""")

        c.execute("""CREATE TABLE IF NOT EXISTS watchlist
            (id INTEGER PRIMARY KEY AUTOINCREMENT,
             user_id INTEGER NOT NULL,
             tmdb_id INTEGER NOT NULL,
             added_at TEXT NOT NULL,
             UNIQUE(user_id, tmdb_id),
             FOREIGN KEY (user_id) REFERENCES users(id))""")

        c.execute("""CREATE TABLE IF NOT EXISTS user_sensitivities
            (user_id INTEGER PRIMARY KEY,
             sensitivities_json TEXT NOT NULL,
             updated_at TEXT NOT NULL,
             FOREIGN KEY (user_id) REFERENCES users(id))""")

        c.execute("""CREATE TABLE IF NOT EXISTS movie_loads
            (load_id INTEGER PRIMARY KEY AUTOINCREMENT,
             tmdb_id INTEGER NOT NULL,
             title TEXT,
             year TEXT,
             genre TEXT,
             mpaa_rating TEXT,
             was_cached INTEGER NOT NULL DEFAULT 0,
             load_time_ms INTEGER,
             warnings_generated TEXT,
             confidence_scores TEXT,
             spoiler_mode_on INTEGER NOT NULL DEFAULT 0,
             timestamp TEXT NOT NULL)""")

        c.execute("""CREATE TABLE IF NOT EXISTS warning_analytics
            (warning_id INTEGER PRIMARY KEY AUTOINCREMENT,
             load_id INTEGER,
             tmdb_id INTEGER NOT NULL,
             category TEXT NOT NULL,
             was_triggered INTEGER NOT NULL DEFAULT 0,
             confidence_score REAL,
             severity_level INTEGER,
             user_flagged_inaccurate INTEGER NOT NULL DEFAULT 0,
             flag_reason TEXT,
             timestamp TEXT NOT NULL,
             FOREIGN KEY (load_id) REFERENCES movie_loads(load_id))""")

        c.execute("""CREATE TABLE IF NOT EXISTS warning_feedback
            (id INTEGER PRIMARY KEY AUTOINCREMENT,
             user_id INTEGER,
             movie_id INTEGER NOT NULL,
             category TEXT,
             feedback_type TEXT NOT NULL,
             rating TEXT NOT NULL,
             chat_message_text TEXT,
             created_at TEXT NOT NULL)""")

        c.execute("""CREATE TABLE IF NOT EXISTS movie_embeddings
            (tmdb_id INTEGER PRIMARY KEY,
             embedding BLOB NOT NULL,
             model_name TEXT NOT NULL,
             text_hash TEXT NOT NULL,
             created_at TEXT NOT NULL,
             FOREIGN KEY (tmdb_id) REFERENCES movies(tmdb_id) ON DELETE CASCADE)""")

        c.execute("""CREATE TABLE IF NOT EXISTS movie_clusters
            (tmdb_id INTEGER PRIMARY KEY,
             cluster_id INTEGER NOT NULL,
             distance_to_centroid REAL,
             model_version TEXT NOT NULL,
             created_at TEXT NOT NULL,
             FOREIGN KEY (tmdb_id) REFERENCES movies(tmdb_id) ON DELETE CASCADE)""")

        conn.commit()
        conn.close()

    def _conn(self):
        return sqlite3.connect(self.db_path)

    # ── Movies / Warnings ──
    def save_movie(self, tmdb_id, data):
        conn = self._conn()
        conn.cursor().execute(
            "INSERT OR REPLACE INTO movies VALUES (?,?,?,?,?,?,?)",
            (tmdb_id, data.get("title"), data.get("year"), data.get("imdb_id"),
             data.get("runtime_min"), json.dumps(data), datetime.now().isoformat())
        )
        conn.commit(); conn.close()

    def get_movie(self, tmdb_id):
        conn = self._conn()
        row = conn.cursor().execute(
            "SELECT metadata_json FROM movies WHERE tmdb_id=?", (tmdb_id,)
        ).fetchone()
        conn.close()
        return json.loads(row[0]) if row else None

    def save_warnings(self, tmdb_id, data):
        conn = self._conn()
        conn.cursor().execute(
            "INSERT OR REPLACE INTO content_warnings VALUES (?,?,?)",
            (tmdb_id, json.dumps(data), datetime.now().isoformat())
        )
        conn.commit(); conn.close()

    def get_warnings(self, tmdb_id):
        conn = self._conn()
        row = conn.cursor().execute(
            "SELECT warnings_json FROM content_warnings WHERE tmdb_id=?", (tmdb_id,)
        ).fetchone()
        conn.close()
        return json.loads(row[0]) if row else None

    # ── Embeddings ──
    def save_embedding(self, tmdb_id, embedding_bytes, model_name, text_hash):
        conn = self._conn()
        conn.cursor().execute(
            "INSERT OR REPLACE INTO movie_embeddings VALUES (?,?,?,?,?)",
            (tmdb_id, embedding_bytes, model_name, text_hash, datetime.now().isoformat())
        )
        conn.commit(); conn.close()

    def get_embedding(self, tmdb_id):
        """Returns (embedding_bytes, text_hash) or None."""
        conn = self._conn()
        row = conn.cursor().execute(
            "SELECT embedding, text_hash FROM movie_embeddings WHERE tmdb_id=?", (tmdb_id,)
        ).fetchone()
        conn.close()
        return (row[0], row[1]) if row else None

    def get_all_embeddings(self, model_name=None):
        """Returns [(tmdb_id, embedding_bytes), ...] for the given model (or all if None)."""
        conn = self._conn()
        if model_name:
            rows = conn.cursor().execute(
                "SELECT tmdb_id, embedding FROM movie_embeddings WHERE model_name=?",
                (model_name,)
            ).fetchall()
        else:
            rows = conn.cursor().execute(
                "SELECT tmdb_id, embedding FROM movie_embeddings"
            ).fetchall()
        conn.close()
        return rows

    def get_all_movies_with_warnings(self):
        conn = self._conn()
        rows = conn.cursor().execute(
            "SELECT m.tmdb_id, m.metadata_json, cw.warnings_json "
            "FROM movies m JOIN content_warnings cw ON m.tmdb_id = cw.tmdb_id"
        ).fetchall()
        conn.close()
        return [(r[0], json.loads(r[1]), json.loads(r[2])) for r in rows]

    def get_well_assessed_movies(self, min_categories: int = 5, min_avg_confidence: float = 0.4) -> list:
        """Return movies where at least min_categories of the 9 warning categories
        have an explicit severity value AND the average confidence across the
        populated categories is at least min_avg_confidence.

        The confidence floor is critical for safety: Gemini will produce a
        "default" all-zero response with confidence 0.3 when it doesn't
        recognize a film, which used to let NC-17 / R titles through the
        comfort filter as if they were content-free. Anything below the floor
        is treated as un-assessed and excluded from the recommendation pool."""
        conn = self._conn()
        rows = conn.cursor().execute(
            "SELECT m.tmdb_id, m.metadata_json, cw.warnings_json "
            "FROM movies m JOIN content_warnings cw ON m.tmdb_id = cw.tmdb_id"
        ).fetchall()
        conn.close()
        result = []
        for tmdb_id, metadata_json, warnings_json in rows:
            movie    = json.loads(metadata_json)
            warnings = json.loads(warnings_json)
            wf       = warnings.get("spoiler_free") or {}
            confidences = [
                (wf.get(cat) or {}).get("confidence")
                for cat in WARNING_CATEGORIES
                if (wf.get(cat) or {}).get("severity") is not None
            ]
            if len(confidences) < min_categories:
                continue
            # Treat missing confidence as 0 — safer than treating it as certain
            avg_conf = sum(c or 0.0 for c in confidences) / len(confidences)
            if avg_conf < min_avg_confidence:
                continue
            result.append({
                "tmdb_id": tmdb_id,
                "title":   movie.get("title", "Unknown"),
                "year":    movie.get("year", ""),
                "poster":  (
                    f"https://image.tmdb.org/t/p/w200{movie['poster_path']}"
                    if movie.get("poster_path") else None
                ),
                "warnings": wf,
            })
        return result

    # ── Users ──
    def create_user(self, username, password):
        try:
            conn = self._conn()
            conn.cursor().execute(
                "INSERT INTO users (username, password_hash, created_at) VALUES (?,?,?)",
                (username, hash_password(password), datetime.now().isoformat())
            )
            conn.commit(); conn.close()
            return True, "Account created successfully."
        except sqlite3.IntegrityError:
            return False, "Username already taken."

    def get_user(self, username):
        conn = self._conn()
        row = conn.cursor().execute(
            "SELECT id, username, password_hash FROM users WHERE username=?", (username,)
        ).fetchone()
        conn.close()
        if not row:
            return None
        return {"id": row[0], "username": row[1], "password_hash": row[2]}

    def verify_user(self, username, password):
        user = self.get_user(username)
        if user and check_password_hash(user["password_hash"], password):
            return user
        return None

    # ── Reviews ──
    def save_review(self, tmdb_id, user_id, username, rating, review_text):
        conn = self._conn()
        conn.cursor().execute(
            "INSERT INTO reviews (tmdb_id, user_id, username, rating, review_text, created_at) VALUES (?,?,?,?,?,?)",
            (tmdb_id, user_id, username, rating, review_text, datetime.now().isoformat())
        )
        conn.commit(); conn.close()

    def get_reviews(self, tmdb_id):
        conn = self._conn()
        rows = conn.cursor().execute(
            "SELECT username, rating, review_text, created_at FROM reviews "
            "WHERE tmdb_id=? ORDER BY created_at DESC", (tmdb_id,)
        ).fetchall()
        conn.close()
        return [{"username": r[0], "rating": r[1], "review_text": r[2], "created_at": r[3]} for r in rows]

    def user_has_reviewed(self, tmdb_id, user_id):
        conn = self._conn()
        row = conn.cursor().execute(
            "SELECT id FROM reviews WHERE tmdb_id=? AND user_id=?", (tmdb_id, user_id)
        ).fetchone()
        conn.close()
        return row is not None

    # ── Watchlist ──
    def add_to_watchlist(self, user_id, tmdb_id):
        try:
            conn = self._conn()
            conn.cursor().execute(
                "INSERT OR IGNORE INTO watchlist (user_id, tmdb_id, added_at) VALUES (?,?,?)",
                (user_id, tmdb_id, datetime.now().isoformat())
            )
            conn.commit(); conn.close()
            return True
        except Exception:
            return False

    def remove_from_watchlist(self, user_id, tmdb_id):
        conn = self._conn()
        conn.cursor().execute(
            "DELETE FROM watchlist WHERE user_id=? AND tmdb_id=?", (user_id, tmdb_id)
        )
        conn.commit(); conn.close()

    def get_watchlist(self, user_id):
        conn = self._conn()
        rows = conn.cursor().execute(
            "SELECT tmdb_id FROM watchlist WHERE user_id=? ORDER BY added_at DESC", (user_id,)
        ).fetchall()
        conn.close()
        return [r[0] for r in rows]

    # ── Analytics ──
    def log_movie_load(self, tmdb_id, title, year, genres, mpaa_rating,
                       was_cached, load_time_ms, warnings_generated,
                       confidence_scores, spoiler_mode_on):
        conn = self._conn()
        c    = conn.cursor()
        c.execute(
            """INSERT INTO movie_loads
               (tmdb_id, title, year, genre, mpaa_rating, was_cached,
                load_time_ms, warnings_generated, confidence_scores,
                spoiler_mode_on, timestamp)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (tmdb_id, title, year, json.dumps(genres), mpaa_rating,
             int(was_cached), load_time_ms,
             json.dumps(warnings_generated), json.dumps(confidence_scores),
             int(spoiler_mode_on), datetime.now().isoformat())
        )
        load_id = c.lastrowid
        conn.commit(); conn.close()
        return load_id

    def log_warning_analytics(self, load_id, tmdb_id, category,
                               was_triggered, confidence_score, severity_level):
        conn = self._conn()
        conn.cursor().execute(
            """INSERT INTO warning_analytics
               (load_id, tmdb_id, category, was_triggered, confidence_score,
                severity_level, user_flagged_inaccurate, flag_reason, timestamp)
               VALUES (?,?,?,?,?,?,0,NULL,?)""",
            (load_id, tmdb_id, category, int(was_triggered),
             confidence_score, severity_level, datetime.now().isoformat())
        )
        conn.commit(); conn.close()

    def save_feedback(self, user_id, movie_id, category, feedback_type, rating, chat_message_text):
        conn = self._conn()
        conn.cursor().execute(
            """INSERT INTO warning_feedback
               (user_id, movie_id, category, feedback_type, rating, chat_message_text, created_at)
               VALUES (?,?,?,?,?,?,?)""",
            (user_id, movie_id, category, feedback_type, rating, chat_message_text, datetime.now().isoformat())
        )
        conn.commit(); conn.close()

    def is_in_watchlist(self, user_id, tmdb_id):
        conn = self._conn()
        row = conn.cursor().execute(
            "SELECT id FROM watchlist WHERE user_id=? AND tmdb_id=?", (user_id, tmdb_id)
        ).fetchone()
        conn.close()
        return row is not None

    # ── Sensitivities ──
    def save_sensitivities(self, user_id, sensitivities):
        conn = self._conn()
        conn.cursor().execute(
            "INSERT OR REPLACE INTO user_sensitivities (user_id, sensitivities_json, updated_at) VALUES (?,?,?)",
            (user_id, json.dumps(sensitivities), datetime.now().isoformat())
        )
        conn.commit(); conn.close()

    def get_sensitivities(self, user_id):
        conn = self._conn()
        row = conn.cursor().execute(
            "SELECT sensitivities_json FROM user_sensitivities WHERE user_id=?", (user_id,)
        ).fetchone()
        conn.close()
        return json.loads(row[0]) if row else []


# ─── DATA FETCHER ─────────────────────────────────────────────
class MovieDataFetcher:
    @staticmethod
    def _get(url, params=None):
        r = req.get(url, params=params, timeout=30)
        r.raise_for_status()
        return r.json()

    @staticmethod
    def search_movie(query, max_results=5):
        data = MovieDataFetcher._get(
            f"{TMDB_BASE}/search/movie",
            {"api_key": TMDB_API_KEY, "query": query, "include_adult": False}
        )
        return (data.get("results") or [])[:max_results]

    @staticmethod
    def build_bundle(tmdb_id):
        d       = MovieDataFetcher._get(f"{TMDB_BASE}/movie/{tmdb_id}", {"api_key": TMDB_API_KEY})
        kw_data = MovieDataFetcher._get(f"{TMDB_BASE}/movie/{tmdb_id}/keywords", {"api_key": TMDB_API_KEY})
        rd_data = MovieDataFetcher._get(f"{TMDB_BASE}/movie/{tmdb_id}/release_dates", {"api_key": TMDB_API_KEY})

        cert = None
        for c in rd_data.get("results", []):
            if c.get("iso_3166_1") == "US":
                for rd in c.get("release_dates", []):
                    cert = (rd.get("certification") or "").strip() or None
                    if cert: break

        overview = d.get("overview", "")
        if overview:
            overview = re.sub(r"\s+", " ", overview).strip()

        release = d.get("release_date", "")
        return {
            "tmdb_id": tmdb_id,
            "title": d.get("title"),
            "year": release[:4] if release else None,
            "imdb_id": d.get("imdb_id"),
            "runtime_min": d.get("runtime"),
            "overview": overview or None,
            "genres": [g["name"] for g in (d.get("genres") or [])],
            "keywords": [k["name"] for k in kw_data.get("keywords", []) if k.get("name")],
            "us_certification": cert,
            "poster_path": d.get("poster_path"),
        }

    @staticmethod
    def get_similar(tmdb_id, max_results=10):
        data = MovieDataFetcher._get(
            f"{TMDB_BASE}/movie/{tmdb_id}/similar",
            {"api_key": TMDB_API_KEY}
        )
        results = (data.get("results") or [])[:max_results]
        return [{
            "tmdb_id": r["id"],
            "title":   r.get("title"),
            "year":    (r.get("release_date") or "")[:4] or None,
            "poster":  f"https://image.tmdb.org/t/p/w200{r['poster_path']}" if r.get("poster_path") else None,
            "overview": (r.get("overview") or "")[:200],
        } for r in results]


# ─── WARNING GENERATOR ────────────────────────────────────────
class ContentWarningGenerator:
    @staticmethod
    def generate_warnings(movie_data: Dict, prompt_template: str) -> Dict:
        prompt = prompt_template.format(
            title    = movie_data.get("title", "Unknown"),
            year     = movie_data.get("year", ""),
            rating   = movie_data.get("us_certification", "Unknown"),
            overview = (movie_data.get("overview") or "")[:300],
            keywords = ", ".join((movie_data.get("keywords") or [])[:20]),
            genres   = ", ".join((movie_data.get("genres") or []))
        )
        try:
            text = call_gemini(prompt).strip()
            print(f"Gemini raw response (first 200 chars): {text[:200]}")
            if text.startswith("```"):
                text = text.split("```")[1].replace("json", "", 1).strip()
            if text.endswith("```"):
                text = text.rsplit("```", 1)[0].strip()
            start = text.find("{")
            end   = text.rfind("}") + 1
            if start >= 0 and end > start:
                text = text[start:end]
            return json.loads(text)
        except Exception as e:
            print(f"WARNING GENERATION ERROR: {e}")
            return {
                "disclaimer": "Fallback",
                "spoiler_free": {
                    cat: {"severity": 0, "confidence": 0.3, "notes": ""}
                    for cat in WARNING_CATEGORIES
                }
            }

    @staticmethod
    def quick_check(movie_data: Dict, category: str) -> int:
        """Single-category severity check. Returns 0-3."""
        prompt = (
            f'Does the movie "{movie_data.get("title")} ({movie_data.get("year")})" '
            f'contain {category.replace("_", " ")}? '
            f'Reply with ONLY a single digit: 0 (absent), 1 (mild), 2 (moderate), or 3 (severe). No other text.'
        )
        try:
            result = call_gemini(prompt).strip()
            digit  = int(re.search(r"[0-3]", result).group())
            return digit
        except Exception:
            return 0


def _fetch_omdb_enrichment(imdb_id: str) -> dict:
    """
    Fetch extended OMDb fields for a movie.
    Returns a dict of enrichment data, or {} on failure.
    Fields: director, writers, actors, plot, language, country, awards,
            box_office, imdb_rating, imdb_votes, metascore, rated, ratings.
    """
    if not imdb_id or not OMDB_API_KEY:
        return {}
    try:
        data = MovieDataFetcher._get(
            OMDB_BASE,
            {"apikey": OMDB_API_KEY, "i": imdb_id, "tomatoes": "true", "plot": "full"}
        )
        if data.get("Response") != "True":
            return {}
        def _clean(v):
            return v if v and v != "N/A" else None
        return {
            "director":    _clean(data.get("Director")),
            "writers":     _clean(data.get("Writer")),
            "actors":      _clean(data.get("Actors")),
            "plot_full":   _clean(data.get("Plot")),
            "language":    _clean(data.get("Language")),
            "country":     _clean(data.get("Country")),
            "awards":      _clean(data.get("Awards")),
            "box_office":  _clean(data.get("BoxOffice")),
            "imdb_rating": _clean(data.get("imdbRating")),
            "imdb_votes":  _clean(data.get("imdbVotes")),
            "metascore":   _clean(data.get("Metascore")),
            "rated":       _clean(data.get("Rated")),
            "ratings":     data.get("Ratings") or [],
        }
    except Exception as e:
        print(f"OMDb enrichment error: {e}")
        return {}


db          = MovieDatabase()
fetcher     = MovieDataFetcher()
warning_gen = ContentWarningGenerator()


# ─── EMBEDDING CACHE (in-process) ────────────────────────────
# 384 float32s × ~400 films ≈ 600 KB. We reload on demand if the DB
# row count grew (new movies embedded via the backfill script).
_embedding_cache: dict[int, "np.ndarray"] = {}
_embedding_cache_size = 0


def _load_embedding_cache():
    global _embedding_cache, _embedding_cache_size
    rows = db.get_all_embeddings(model_name=EMBED_MODEL_NAME)
    if len(rows) == _embedding_cache_size and _embedding_cache:
        return _embedding_cache
    _embedding_cache = {tmdb_id: bytes_to_vec(blob) for tmdb_id, blob in rows}
    _embedding_cache_size = len(rows)
    return _embedding_cache


_mpa_model = None
_mpa_model_loaded = False


def _get_mpa_model():
    """Lazy-load the MPA classifier; cache None if no model on disk."""
    global _mpa_model, _mpa_model_loaded
    if not _mpa_model_loaded:
        bundle = load_mpa_model()
        _mpa_model = bundle[0] if bundle else None
        _mpa_model_loaded = True
    return _mpa_model


# ─── AUTH ROUTES ──────────────────────────────────────────────
@app.route("/api/register", methods=["POST"])
def register():
    data     = request.json or {}
    username = (data.get("username") or "").strip()
    password = (data.get("password") or "").strip()
    if not username or not password:
        return jsonify({"ok": False, "error": "Username and password are required."}), 400
    if len(username) < 3:
        return jsonify({"ok": False, "error": "Username must be at least 3 characters."}), 400
    if len(password) < 8:
        return jsonify({"ok": False, "error": "Password must be at least 8 characters."}), 400
    ok, msg = db.create_user(username, password)
    if ok:
        user = db.get_user(username)
        session["user_id"]  = user["id"]
        session["username"] = user["username"]
        return jsonify({"ok": True, "username": username})
    return jsonify({"ok": False, "error": msg}), 409

@app.route("/api/login", methods=["POST"])
def login():
    data     = request.json or {}
    username = (data.get("username") or "").strip()
    password = (data.get("password") or "").strip()
    user     = db.verify_user(username, password)
    if not user:
        return jsonify({"ok": False, "error": "Invalid username or password."}), 401
    session["user_id"]  = user["id"]
    session["username"] = user["username"]
    return jsonify({"ok": True, "username": user["username"]})

@app.route("/api/logout", methods=["POST"])
def logout():
    session.clear()
    return jsonify({"ok": True})

@app.route("/api/me")
def me():
    if "user_id" in session:
        return jsonify({"logged_in": True, "username": session["username"]})
    return jsonify({"logged_in": False})


# ─── REVIEW ROUTES ────────────────────────────────────────────
@app.route("/api/reviews/<int:tmdb_id>", methods=["GET"])
def get_reviews(tmdb_id):
    return jsonify(db.get_reviews(tmdb_id))

@app.route("/api/reviews/<int:tmdb_id>", methods=["POST"])
def post_review(tmdb_id):
    if "user_id" not in session:
        return jsonify({"ok": False, "error": "You must be logged in to post a review."}), 401
    data        = request.json or {}
    review_text = (data.get("review_text") or "").strip()
    rating      = data.get("rating")
    if not review_text:
        return jsonify({"ok": False, "error": "Review text cannot be empty."}), 400
    if rating is not None:
        try:
            rating = int(rating)
            if not 1 <= rating <= 5:
                raise ValueError
        except ValueError:
            return jsonify({"ok": False, "error": "Rating must be between 1 and 5."}), 400
    if db.user_has_reviewed(tmdb_id, session["user_id"]):
        return jsonify({"ok": False, "error": "You have already reviewed this movie."}), 409
    db.save_review(tmdb_id, session["user_id"], session["username"], rating, review_text)
    return jsonify({"ok": True})


# ─── RECOMMENDATION ROUTE ─────────────────────────────────────
@app.route("/api/recommendations/<int:tmdb_id>", methods=["POST"])
def get_recommendations(tmdb_id):
    """
    Body: { "avoid_category": "violence_gore" }

    Candidate pool = TMDB's /similar (thematic similarity from genres +
    keywords) UNION the source film's K-Means cluster (content-profile
    similarity from warning severities). Filter to candidates with
    severity == 0 for the avoided category. Re-rank survivors by
    sentence-transformer cosine similarity to the source.

    Why the union: TMDB /similar caps at ~10 thematic neighbors, of
    which often only 0–3 survive the severity filter. Adding the cluster
    members (typically 40–120 films) gives the filter room to find safe
    matches that share a content profile even when TMDB's metadata-only
    similarity missed them.
    """
    avoid = (request.json or {}).get("avoid_category", "").strip()
    if avoid not in WARNING_CATEGORIES:
        return jsonify({"ok": False, "error": "Invalid category."}), 400

    # ── Source 1: TMDB thematic neighbors ─────────────────────────
    candidates: dict[int, dict] = {}
    for m in fetcher.get_similar(tmdb_id, max_results=10):
        if m["tmdb_id"] == tmdb_id:
            continue
        candidates[m["tmdb_id"]] = m

    # ── Source 2: K-Means content-profile neighbors ───────────────
    # Pull every film in the same cluster (top_k high enough to cover
    # the largest cluster). Cluster neighbors arrive already enriched
    # with title/year/poster, matching the TMDB shape.
    try:
        cluster_neighbors = cluster_find_twins(DB_PATH, tmdb_id, top_k=200)
    except Exception as e:
        print(f"Cluster expansion skipped: {type(e).__name__}: {e}")
        cluster_neighbors = []
    for m in cluster_neighbors:
        # Don't overwrite TMDB entries — they may have extra fields the
        # frontend uses; cluster neighbors only fill the gap.
        if m["tmdb_id"] not in candidates:
            candidates[m["tmdb_id"]] = m

    # ── Filter: severity == 0 for the avoided category ────────────
    safe: list[dict] = []
    for movie in candidates.values():
        cached_warnings = db.get_warnings(movie["tmdb_id"])
        if cached_warnings:
            severity = (cached_warnings.get("spoiler_free") or {}).get(avoid, {}).get("severity", 0)
        else:
            movie_data = db.get_movie(movie["tmdb_id"]) or {"title": movie.get("title"), "year": movie.get("year")}
            severity   = warning_gen.quick_check(movie_data, avoid)
        if severity == 0:
            safe.append(movie)

    # ── Re-rank by embedding cosine similarity to the source ──────
    embed_cache = _load_embedding_cache()
    src_vec = embed_cache.get(tmdb_id)
    if src_vec is not None and safe:
        scored = []
        for m in safe:
            cand_vec = embed_cache.get(m["tmdb_id"])
            sim = float(np.dot(src_vec, cand_vec)) if cand_vec is not None else -1.0
            m["semantic_similarity"] = round(sim, 3) if sim > -1.0 else None
            scored.append((sim, m))
        scored.sort(key=lambda t: t[0], reverse=True)
        safe = [m for _, m in scored]

    return jsonify({"ok": True, "recommendations": safe[:5]})


# ─── CONTENT TWINS ROUTE (K-Means cluster neighbors) ─────────
@app.route("/api/content_twins/<int:tmdb_id>", methods=["GET"])
def content_twins(tmdb_id):
    """Return films in the same K-Means content cluster as the source film,
    ranked by Euclidean distance in warning-vector space. Distinct from
    semantic similarity — clusters by *what's in the film* (severity profile)
    rather than *what the film is about*."""
    twins = cluster_find_twins(db.db_path, tmdb_id, top_k=8)
    cluster = get_cluster_name(db.db_path, tmdb_id)
    return jsonify({
        "ok": True,
        "cluster_id":   cluster[0] if cluster else None,
        "cluster_name": cluster[1] if cluster else None,
        "twins":        twins,
    })


# ─── EXTERNAL REVIEWS ROUTE ──────────────────────────────────
@app.route("/api/external_reviews/<int:tmdb_id>")
def external_reviews(tmdb_id):
    """
    Returns:
    - Ratings from OMDb (IMDb, Rotten Tomatoes, Metacritic)
    - Written reviews from TMDB
    """
    result = {"ratings": [], "reviews": [], "enrichment": {}}

    # ── OMDb data (use cached enrichment if available) ──
    try:
        movie = db.get_movie(tmdb_id)
        omdb  = (movie or {}).get("omdb") or {}

        # Fall back to a live OMDb call if enrichment not yet cached
        if not omdb:
            imdb_id = (movie or {}).get("imdb_id")
            if not imdb_id:
                d = MovieDataFetcher._get(
                    f"{TMDB_BASE}/movie/{tmdb_id}/external_ids",
                    {"api_key": TMDB_API_KEY}
                )
                imdb_id = d.get("imdb_id")
            omdb = _fetch_omdb_enrichment(imdb_id)

        for r in omdb.get("ratings") or []:
            result["ratings"].append({"source": r["Source"], "value": r["Value"]})

        result["enrichment"] = {
            "director":    omdb.get("director"),
            "actors":      omdb.get("actors"),
            "writers":     omdb.get("writers"),
            "awards":      omdb.get("awards"),
            "box_office":  omdb.get("box_office"),
            "language":    omdb.get("language"),
            "country":     omdb.get("country"),
            "imdb_rating": omdb.get("imdb_rating"),
            "imdb_votes":  omdb.get("imdb_votes"),
            "metascore":   omdb.get("metascore"),
        }
    except Exception as e:
        print(f"OMDb error: {e}")

    # ── TMDB written reviews ──
    try:
        data    = MovieDataFetcher._get(
            f"{TMDB_BASE}/movie/{tmdb_id}/reviews",
            {"api_key": TMDB_API_KEY, "language": "en-US", "page": 1}
        )
        for r in (data.get("results") or [])[:5]:
            content = (r.get("content") or "").strip()
            if not content:
                continue
            result["reviews"].append({
                "author":  r.get("author", "Anonymous"),
                "source":  "TMDB",
                "url":     (r.get("url") or ""),
                "excerpt": content[:400] + ("..." if len(content) > 400 else ""),
                "rating":  r.get("author_details", {}).get("rating")
            })
    except Exception as e:
        print(f"TMDB reviews error: {e}")

    return jsonify(result)


# ─── EXISTING ROUTES ──────────────────────────────────────────
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/search", methods=["POST"])
def search():
    data     = request.json or {}
    query    = data.get("query", "").strip()
    genre_id = data.get("genre_id")

    if genre_id:
        # Browse popular movies by genre
        results_data = MovieDataFetcher._get(
            f"{TMDB_BASE}/discover/movie",
            {"api_key": TMDB_API_KEY, "with_genres": genre_id,
             "sort_by": "popularity.desc", "include_adult": False}
        )
        results = (results_data.get("results") or [])[:10]
    elif query:
        results = fetcher.search_movie(query, max_results=8)
    else:
        return jsonify([])

    return jsonify([{
        "tmdb_id": r["id"],
        "title":   r.get("title"),
        "year":    (r.get("release_date") or "")[:4] or None,
        "poster":  f"https://image.tmdb.org/t/p/w200{r['poster_path']}" if r.get("poster_path") else None,
    } for r in results])

@app.route("/api/load_movie", methods=["POST"])
def load_movie():
    data         = request.json or {}
    tmdb_id      = data.get("tmdb_id")
    spoiler_mode = data.get("spoiler_mode", False)

    t0     = time.time()
    cached = db.get_movie(tmdb_id)
    if cached:
        # Backfill OMDb enrichment if not yet stored
        if not cached.get("omdb"):
            enrichment = _fetch_omdb_enrichment(cached.get("imdb_id"))
            if enrichment:
                cached["omdb"] = enrichment
                db.save_movie(tmdb_id, cached)
        app_state["current_movie"] = cached
        warn = db.get_warnings(tmdb_id) or warning_gen.generate_warnings(cached, app_state["prompt_template"])
        if not db.get_warnings(tmdb_id):
            db.save_warnings(tmdb_id, warn)
    else:
        movie_data = fetcher.build_bundle(tmdb_id)
        enrichment = _fetch_omdb_enrichment(movie_data.get("imdb_id"))
        if enrichment:
            movie_data["omdb"] = enrichment
        db.save_movie(tmdb_id, movie_data)
        app_state["current_movie"] = movie_data
        warn = warning_gen.generate_warnings(movie_data, app_state["prompt_template"])
        db.save_warnings(tmdb_id, warn)

    load_time_ms = int((time.time() - t0) * 1000)
    movie        = app_state["current_movie"]
    sf           = (warn.get("spoiler_free") or {})

    confidence_scores = {cat: (sf.get(cat) or {}).get("confidence", 0) for cat in WARNING_CATEGORIES}

    # ── Log movie_loads ──
    load_id = db.log_movie_load(
        tmdb_id          = tmdb_id,
        title            = movie.get("title"),
        year             = movie.get("year"),
        genres           = movie.get("genres", []),
        mpaa_rating      = movie.get("us_certification"),
        was_cached       = cached is not None,
        load_time_ms     = load_time_ms,
        warnings_generated = warn,
        confidence_scores  = confidence_scores,
        spoiler_mode_on  = spoiler_mode
    )

    # ── Log warning_analytics (one row per category) ──
    for cat in WARNING_CATEGORIES:
        w = sf.get(cat) or {}
        db.log_warning_analytics(
            load_id         = load_id,
            tmdb_id         = tmdb_id,
            category        = cat,
            was_triggered   = w.get("severity", 0) > 0,
            confidence_score= w.get("confidence", 0),
            severity_level  = w.get("severity", 0)
        )

    app_state["conversation_history"] = []

    # MPA classifier: predict family/teen/adult bucket from the warning vector.
    # Surface the prediction when (a) it disagrees with the stored TMDB cert,
    # or (b) no TMDB cert is available. When it agrees, omit to avoid clutter.
    mpa_prediction = None
    mm = _get_mpa_model()
    if mm is not None:
        try:
            pred = predict_mpa(mm, warn, movie.get("year"))
            cert = (movie.get("us_certification") or "").strip().upper()
            actual_idx = MPA_CERT_TO_LABEL.get(cert)
            conf = pred["probabilities"][pred["label"]]
            disagrees = actual_idx is not None and pred["label_idx"] != actual_idx
            # Only surface confident disagreements; the classifier is ~70%
            # accurate so low-confidence flags add more noise than signal.
            if conf >= 0.70 and (disagrees or actual_idx is None):
                mpa_prediction = {
                    "label":      pred["label"],
                    "confidence": conf,
                    "disagrees":  disagrees,
                }
        except Exception as e:
            print(f"MPA classifier error: {e}")

    return jsonify({
        "movie":            movie,
        "warnings":         warn,
        "load_id":          load_id,
        "mpa_prediction":   mpa_prediction,
    })

@app.route("/api/chat", methods=["POST"])
def chat():
    message      = request.json.get("message", "")
    spoiler_mode = request.json.get("spoiler_mode", False)
    if not app_state["current_movie"]:
        return jsonify({"error": "No movie loaded"}), 400
    movie     = app_state["current_movie"]
    mode_note = "Do NOT reveal plot twists or endings." if not spoiler_mode else "You may discuss all plot details."
    ctx  = f'You are a helpful movie content advisor. Movie: {movie["title"]} ({movie.get("year","")})\n{mode_note}\nAnswer in 2-3 sentences.'
    hist = ctx + "\n\n"
    for m in app_state["conversation_history"][-6:]:
        hist += f"{m['role']}: {m['content']}\n\n"
    hist += f"User: {message}\n\nAssistant:"
    response = call_gemini(hist)
    app_state["conversation_history"] += [
        {"role": "User",      "content": message},
        {"role": "Assistant", "content": response}
    ]
    return jsonify({"response": response})

@app.route("/api/prompt", methods=["GET"])
def get_prompt():
    return jsonify({"prompt": app_state["prompt_template"]})

@app.route("/api/prompt", methods=["POST"])
def set_prompt():
    new_prompt = request.json.get("prompt", "").strip()
    if not new_prompt:
        return jsonify({"error": "Prompt cannot be empty"}), 400
    required = ["{title}", "{year}", "{rating}", "{genres}", "{overview}", "{keywords}"]
    missing  = [p for p in required if p not in new_prompt]
    if missing:
        return jsonify({"error": f"Prompt is missing required placeholders: {', '.join(missing)}"}), 400
    app_state["prompt_template"] = new_prompt
    return jsonify({"ok": True, "message": "Prompt updated. New searches will use this prompt."})

@app.route("/api/prompt/reset", methods=["POST"])
def reset_prompt():
    app_state["prompt_template"] = DEFAULT_PROMPT_TEMPLATE
    return jsonify({"ok": True, "prompt": DEFAULT_PROMPT_TEMPLATE})

@app.route("/health")
def health():
    return jsonify({"status": "ok"})


# ─── FEEDBACK ROUTE ──────────────────────────────────────────
@app.route("/api/feedback", methods=["POST"])
def submit_feedback():
    data              = request.json or {}
    movie_id          = data.get("movie_id")
    category          = data.get("category")
    feedback_type     = (data.get("feedback_type") or "").strip()
    rating            = (data.get("rating") or "").strip()
    chat_message_text = data.get("chat_message_text")
    if not movie_id:
        return jsonify({"ok": False, "error": "movie_id required."}), 400
    if feedback_type not in ("warning", "chat"):
        return jsonify({"ok": False, "error": "feedback_type must be 'warning' or 'chat'."}), 400
    if rating not in ("up", "down"):
        return jsonify({"ok": False, "error": "rating must be 'up' or 'down'."}), 400
    db.save_feedback(session.get("user_id"), movie_id, category, feedback_type, rating, chat_message_text)
    return jsonify({"ok": True})


# ─── WATCHLIST ROUTES ────────────────────────────────────────
@app.route("/api/watchlist", methods=["GET"])
def get_watchlist():
    if "user_id" not in session:
        return jsonify({"ok": False, "error": "Login required."}), 401
    tmdb_ids = db.get_watchlist(session["user_id"])
    movies = []
    for tid in tmdb_ids:
        movie = db.get_movie(tid)
        if movie:
            movies.append({
                "tmdb_id": tid,
                "title":   movie.get("title"),
                "year":    movie.get("year"),
                "poster":  f"https://image.tmdb.org/t/p/w200{movie['poster_path']}" if movie.get("poster_path") else None,
            })
    return jsonify({"ok": True, "watchlist": movies})

@app.route("/api/watchlist/<int:tmdb_id>", methods=["POST"])
def add_watchlist(tmdb_id):
    if "user_id" not in session:
        return jsonify({"ok": False, "error": "Login required."}), 401
    db.add_to_watchlist(session["user_id"], tmdb_id)
    return jsonify({"ok": True})

@app.route("/api/watchlist/<int:tmdb_id>", methods=["DELETE"])
def remove_watchlist(tmdb_id):
    if "user_id" not in session:
        return jsonify({"ok": False, "error": "Login required."}), 401
    db.remove_from_watchlist(session["user_id"], tmdb_id)
    return jsonify({"ok": True})

@app.route("/api/watchlist/check/<int:tmdb_id>")
def check_watchlist(tmdb_id):
    if "user_id" not in session:
        return jsonify({"in_watchlist": False})
    return jsonify({"in_watchlist": db.is_in_watchlist(session["user_id"], tmdb_id)})


# ─── SENSITIVITY PROFILE ROUTES ───────────────────────────────
@app.route("/api/profile/sensitivities", methods=["GET"])
def get_sensitivities_route():
    if "user_id" not in session:
        return jsonify({"ok": False, "error": "Login required."}), 401
    return jsonify({"ok": True, "sensitivities": db.get_sensitivities(session["user_id"])})

@app.route("/api/profile/sensitivities", methods=["POST"])
def save_sensitivities_route():
    if "user_id" not in session:
        return jsonify({"ok": False, "error": "Login required."}), 401
    data = request.json or {}
    sensitivities = [s for s in (data.get("sensitivities") or []) if s in WARNING_CATEGORIES]
    db.save_sensitivities(session["user_id"], sensitivities)
    return jsonify({"ok": True})


# ─── WATCHLIST RANK ROUTE ────────────────────────────────────
@app.route("/api/watchlist/rank", methods=["POST"])
def watchlist_rank():
    if "user_id" not in session:
        return jsonify({"ok": False, "error": "Login required."}), 401

    user_sensitivities = db.get_sensitivities(session["user_id"])
    tmdb_ids = db.get_watchlist(session["user_id"])
    if not tmdb_ids:
        return jsonify({"ok": True, "ranked": []})

    watchlist_data = []
    for tid in tmdb_ids:
        movie    = db.get_movie(tid)
        warnings = db.get_warnings(tid)
        if movie:
            watchlist_data.append({
                "tmdb_id":  tid,
                "title":    movie.get("title"),
                "year":     movie.get("year"),
                "warnings": warnings.get("spoiler_free", {}) if warnings else {}
            })

    prompt = WATCHLIST_RANK_PROMPT.format(
        user_sensitivities = json.dumps(user_sensitivities),
        watchlist_json     = json.dumps(watchlist_data)
    )
    try:
        text = call_gemini(prompt).strip()
        if text.startswith("```"):
            text = text.split("```")[1].replace("json", "", 1).strip()
        if text.endswith("```"):
            text = text.rsplit("```", 1)[0].strip()
        start = text.find("["); end = text.rfind("]") + 1
        if start >= 0 and end > start:
            text = text[start:end]
        ranked = json.loads(text)

        # Attach poster from DB
        movie_map = {m["tmdb_id"]: m for m in watchlist_data}
        for item in ranked:
            tid = item.get("tmdb_id")
            movie = db.get_movie(tid) if tid else None
            item["poster"] = (
                f"https://image.tmdb.org/t/p/w200{movie['poster_path']}"
                if movie and movie.get("poster_path") else None
            )

        return jsonify({"ok": True, "ranked": ranked})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# ─── GROUP WATCH ROUTES ───────────────────────────────────────
MOOD_GENRE_MAP = {
    "comedy":      35,
    "feel-good":   35,
    "adventure":   12,
    "family":   10751,
    "drama":       18,
    "thriller":    53,
    "sci-fi":     878,
    "romance":  10749,
    "animation":   16,
    "documentary": 99,
}

@app.route("/api/group/merge", methods=["POST"])
def group_merge():
    """Merge individual sensitivity profiles into a group profile via Gemini."""
    data    = request.json or {}
    members = data.get("members", [])
    if not members:
        return jsonify({"ok": False, "error": "No members provided."}), 400
    prompt = GROUP_PROFILE_PROMPT.format(group_profiles_json=json.dumps(members))
    try:
        text = call_gemini(prompt).strip()
        if text.startswith("Error:"):
            return jsonify({"ok": False, "error": text}), 502
        if text.startswith("```"):
            text = text.split("```")[1].replace("json", "", 1).strip()
        if text.endswith("```"):
            text = text.rsplit("```", 1)[0].strip()
        start = text.find("{"); end = text.rfind("}") + 1
        if start < 0 or end <= start:
            return jsonify({"ok": False, "error": "No JSON found in Gemini response."}), 502
        merged = json.loads(text[start:end])
        return jsonify({"ok": True, "merged": merged})
    except json.JSONDecodeError as e:
        return jsonify({"ok": False, "error": f"Failed to parse Gemini response: {e}"}), 502
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/group/recommend", methods=["POST"])
def group_recommend():
    """Score candidate movies for a group using merged sensitivity profile."""
    data           = request.json or {}
    merged_profile = data.get("merged_profile", {})
    mood           = (data.get("mood") or "").strip().lower()
    platform       = (data.get("platform") or "Any").strip()

    if not merged_profile:
        return jsonify({"ok": False, "error": "No group profile provided."}), 400

    # Build candidate list from local database
    all_movies = db.get_all_movies_with_warnings()
    import random
    random.shuffle(all_movies)
    candidates = []
    for tid, movie, warnings in all_movies:
        wf = warnings.get("spoiler_free", {})
        if all((wf.get(cat) or {}).get("notes", "") == "" for cat in WARNING_CATEGORIES):
            continue
        candidates.append({
            "tmdb_id":  tid,
            "title":    movie.get("title", "Unknown"),
            "year":     movie.get("year", ""),
            "poster":   (f"https://image.tmdb.org/t/p/w200{movie['poster_path']}" if movie.get("poster_path") else None),
            "warnings": wf
        })
        if len(candidates) >= 20:
            break

    if not candidates:
        return jsonify({"ok": False, "error": "No cached movies found. Load some movies first to build the cache."}), 404

    logged_in_sens  = db.get_sensitivities(session["user_id"]) if "user_id" in session else []
    members_ordered = data.get("members") or []
    recs = comfort_group_movies(
        candidates              = candidates,
        logged_in_sensitivities = logged_in_sens,
        members_ordered         = members_ordered,
        top_n                   = 5,
    )
    return jsonify({"ok": True, "recommendations": recs})


# ─── DISCOVER ROUTE (unified mood + warning avoidance) ───────
@app.route("/api/discover", methods=["POST"])
def discover():
    data          = request.json or {}
    mood_input    = (data.get("mood_input") or "").strip()
    avoid_cats    = [c for c in (data.get("avoid_categories") or [])[:3] if c in WARNING_CATEGORIES]

    if "user_id" in session:
        user_sensitivities = db.get_sensitivities(session["user_id"])
    else:
        user_sensitivities = data.get("sensitivities", [])

    # Step 1: Interpret mood if provided
    mood_profile = None
    if mood_input:
        mp_prompt = MOOD_INTERPRETER_PROMPT.format(
            mood_input         = mood_input,
            user_sensitivities = json.dumps(user_sensitivities),
            time_of_day        = "evening",
            day_of_week        = "today"
        )
        try:
            text = call_gemini(mp_prompt).strip()
            if text.startswith("```"):
                text = text.split("```")[1].replace("json", "", 1).strip()
            if text.endswith("```"):
                text = text.rsplit("```", 1)[0].strip()
            s = text.find("{"); e = text.rfind("}") + 1
            if s >= 0 and e > s:
                mood_profile = json.loads(text[s:e])
        except Exception as ex:
            print(f"Mood interpret error: {ex}")

    # Step 2: Fetch well-assessed movies from local DB (>=5 of 9 warning categories populated)
    pool = db.get_well_assessed_movies()

    # Step 3: Filter to movies that pass avoided categories
    candidates = [
        c for c in pool
        if not any((c["warnings"].get(cat) or {}).get("severity", 0) > 0 for cat in avoid_cats)
    ]

    if not candidates:
        return jsonify({"ok": False, "error": "No cached movies passed your filters. Load some movies via search first."}), 404

    # Step 4: Rank by comfort distance — hard-exclude sensitive cats, score engagement within comfort space.
    # When the user provides a mood, score the entire candidate pool so the mood
    # signal can promote films from anywhere in the comfort distribution. Without
    # a mood, we just take the comfort top 5 directly.
    combined_sens = list({*user_sensitivities, *avoid_cats})
    if mood_input:
        # Get every safe candidate with a comfort score, no MMR cap, so the
        # mood blend below operates over the full pool.
        recs = comfort_find_movies(
            candidates=candidates, user_sensitivities=combined_sens,
            top_n=len(candidates), apply_mmr=False,
        )
    else:
        recs = comfort_find_movies(candidates=candidates, user_sensitivities=combined_sens, top_n=5)

    # Step 5: If the user typed a mood phrase, blend contrastive mood-cosine
    # into the score. The positive anchor is the user's phrase plus Gemini's
    # recommended_tones; the negative anchor is Gemini's avoid_tones (e.g.
    # ["bleak", "violent"] for a "gentle family" query). The per-film mood
    # signal is `pos_cosine - neg_cosine`, then per-query normalized to
    # [0, 100] across the candidate pool and blended 50/50 with comfort.
    # Full subtraction (alpha=1.0) is critical — horror films whose overviews
    # mention "family" score high on positive but also score very high on
    # avoid_tones like "bleak/traumatic", so they cancel out.
    if mood_input:
        embed_cache = _load_embedding_cache()
        if embed_cache:
            rec_tones    = (mood_profile or {}).get("recommended_tones") or []
            avoid_tones  = (mood_profile or {}).get("avoid_tones") or []
            positive_txt = mood_input + (". Tones: " + ", ".join(rec_tones) if rec_tones else "")
            negative_txt = ", ".join(avoid_tones) if avoid_tones else ""
            pos_vec      = embed_text(positive_txt)
            neg_vec      = embed_text(negative_txt) if negative_txt else None

            raw_scores: list[float] = []
            for r in recs:
                cand_vec = embed_cache.get(r["tmdb_id"])
                if cand_vec is None:
                    r["_raw"] = None
                    continue
                pos_sim = float(np.dot(pos_vec, cand_vec))
                neg_sim = float(np.dot(neg_vec, cand_vec)) if neg_vec is not None else 0.0
                contrast = pos_sim - 1.0 * neg_sim
                r["_raw"]    = contrast
                r["_pos"]    = pos_sim
                r["_neg"]    = neg_sim
                raw_scores.append(contrast)

            if raw_scores:
                lo, hi = min(raw_scores), max(raw_scores)
                span   = max(hi - lo, 1e-6)
                for r in recs:
                    raw = r.pop("_raw", None)
                    pos = r.pop("_pos", None)
                    neg = r.pop("_neg", None)
                    if raw is None:
                        r["mood_similarity"] = None
                        r["mood_score"]      = None
                        continue
                    r["mood_similarity"] = round(pos, 3)
                    r["mood_avoid_similarity"] = round(neg, 3) if neg_vec is not None else None
                    mood_score_0_100     = ((raw - lo) / span) * 100.0
                    r["mood_score"]      = round(mood_score_0_100)
                    r["final_score"]     = round(0.5 * r["final_score"] + 0.5 * mood_score_0_100, 1)
                recs.sort(key=lambda r: r["final_score"], reverse=True)

    return jsonify({"ok": True, "mood_profile": mood_profile, "recommendations": recs[:5]})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=7860, debug=False)
