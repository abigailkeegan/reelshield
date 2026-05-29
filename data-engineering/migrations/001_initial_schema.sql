-- ReelShield Database Schema (SQLite)
-- Migration: 001_initial_schema.sql

-- ─── MOVIES TABLE ────────────────────────────────────────────
-- Caches TMDB metadata to avoid repeated API calls.
-- metadata_json stores the full bundle (genres, keywords, poster, etc.)
-- so we never need to re-fetch from TMDB for the same film.
CREATE TABLE IF NOT EXISTS movies (
    tmdb_id       INTEGER PRIMARY KEY,
    title         TEXT    NOT NULL,
    year          TEXT,
    imdb_id       TEXT,
    runtime_min   INTEGER,
    metadata_json TEXT    NOT NULL,   -- JSON blob: full movie bundle
    last_updated  TEXT    NOT NULL    -- ISO 8601 datetime
);

-- Index on title for future text search support
CREATE INDEX IF NOT EXISTS idx_movies_title ON movies(title);

-- Index on last_updated for cache invalidation queries
CREATE INDEX IF NOT EXISTS idx_movies_updated ON movies(last_updated);


-- ─── CONTENT WARNINGS TABLE ──────────────────────────────────
-- Caches Gemini-generated warnings keyed to tmdb_id.
-- 1:1 with movies — each film has at most one cached warning set.
-- warnings_json structure:
-- {
--   "disclaimer": "Gemini knowledge-based",
--   "spoiler_free": {
--     "violence_gore":              {"severity": 0-3, "confidence": 0-1, "notes": ""},
--     "self_harm_suicide":          {"severity": 0-3, "confidence": 0-1, "notes": ""},
--     "miscarriage_pregnancy_loss": {"severity": 0-3, "confidence": 0-1, "notes": ""},
--     "sexual_content_nudity":      {"severity": 0-3, "confidence": 0-1, "notes": ""},
--     "animal_abuse":               {"severity": 0-3, "confidence": 0-1, "notes": ""},
--     "substances":                 {"severity": 0-3, "confidence": 0-1, "notes": ""},
--     "language":                   {"severity": 0-3, "confidence": 0-1, "notes": ""},
--     "horror_intensity":           {"severity": 0-3, "confidence": 0-1, "notes": ""},
--     "flashing_lights":            {"severity": 0-3, "confidence": 0-1, "notes": ""}
--   }
-- }
CREATE TABLE IF NOT EXISTS content_warnings (
    tmdb_id       INTEGER PRIMARY KEY,
    warnings_json TEXT    NOT NULL,   -- JSON blob: all 9 warning categories
    last_updated  TEXT    NOT NULL,   -- ISO 8601 datetime
    FOREIGN KEY (tmdb_id) REFERENCES movies(tmdb_id) ON DELETE CASCADE
);

-- Index on last_updated for identifying stale warnings
CREATE INDEX IF NOT EXISTS idx_warnings_updated ON content_warnings(last_updated);
