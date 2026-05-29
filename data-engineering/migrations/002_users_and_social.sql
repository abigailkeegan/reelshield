-- ReelShield Database Schema (SQLite)
-- Migration: 002_users_and_social.sql
--
-- Adds the user accounts layer plus the social, profile, and analytics
-- tables that sit on top of the movies / content_warnings cache.

-- ─── USERS TABLE ─────────────────────────────────────────────
-- Account credentials. password_hash uses werkzeug pbkdf2 (sha256, 600k iters).
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT    UNIQUE NOT NULL,
    password_hash TEXT    NOT NULL,
    created_at    TEXT    NOT NULL    -- ISO 8601 datetime
);

CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);


-- ─── REVIEWS TABLE ───────────────────────────────────────────
-- User-written reviews + 1-5 star ratings, scoped to one movie per row.
CREATE TABLE IF NOT EXISTS reviews (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    tmdb_id     INTEGER NOT NULL,
    user_id     INTEGER NOT NULL,
    username    TEXT    NOT NULL,    -- denormalized for fast display
    rating      INTEGER,             -- 1-5 stars, nullable for text-only reviews
    review_text TEXT    NOT NULL,
    created_at  TEXT    NOT NULL,    -- ISO 8601 datetime
    FOREIGN KEY (tmdb_id) REFERENCES movies(tmdb_id),
    FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE INDEX IF NOT EXISTS idx_reviews_tmdb_id ON reviews(tmdb_id);
CREATE INDEX IF NOT EXISTS idx_reviews_user_id ON reviews(user_id);


-- ─── WATCHLIST TABLE ─────────────────────────────────────────
-- Per-user "want to watch" list. Each (user, movie) pair is unique.
CREATE TABLE IF NOT EXISTS watchlist (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id  INTEGER NOT NULL,
    tmdb_id  INTEGER NOT NULL,
    added_at TEXT    NOT NULL,    -- ISO 8601 datetime
    UNIQUE(user_id, tmdb_id),
    FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE INDEX IF NOT EXISTS idx_watchlist_user_id ON watchlist(user_id);


-- ─── USER SENSITIVITIES TABLE ────────────────────────────────
-- A user's permanent "always avoid" warning categories.
-- One row per user; sensitivities_json is a JSON array of category names.
CREATE TABLE IF NOT EXISTS user_sensitivities (
    user_id            INTEGER PRIMARY KEY,
    sensitivities_json TEXT    NOT NULL,   -- JSON array of category strings
    updated_at         TEXT    NOT NULL,   -- ISO 8601 datetime
    FOREIGN KEY (user_id) REFERENCES users(id)
);


-- ─── MOVIE LOADS TABLE ───────────────────────────────────────
-- Instrumentation: one row per /api/load_movie call, used for performance
-- analysis (cache hit rate, load time distribution, warnings produced).
CREATE TABLE IF NOT EXISTS movie_loads (
    load_id             INTEGER PRIMARY KEY AUTOINCREMENT,
    tmdb_id             INTEGER NOT NULL,
    title               TEXT,
    year                TEXT,
    genre               TEXT,
    mpaa_rating         TEXT,
    was_cached          INTEGER NOT NULL DEFAULT 0,    -- 0 / 1 boolean
    load_time_ms        INTEGER,
    warnings_generated  TEXT,                          -- JSON array of triggered categories
    confidence_scores   TEXT,                          -- JSON map of category -> confidence
    spoiler_mode_on     INTEGER NOT NULL DEFAULT 0,    -- 0 / 1 boolean
    timestamp           TEXT    NOT NULL               -- ISO 8601 datetime
);

CREATE INDEX IF NOT EXISTS idx_movie_loads_tmdb_id   ON movie_loads(tmdb_id);
CREATE INDEX IF NOT EXISTS idx_movie_loads_timestamp ON movie_loads(timestamp);


-- ─── WARNING ANALYTICS TABLE ─────────────────────────────────
-- One row per (load_id, category) — the per-category outcome of a single
-- movie load. Used to compute false-positive / false-negative rates.
CREATE TABLE IF NOT EXISTS warning_analytics (
    warning_id              INTEGER PRIMARY KEY AUTOINCREMENT,
    load_id                 INTEGER,
    tmdb_id                 INTEGER NOT NULL,
    category                TEXT    NOT NULL,
    was_triggered           INTEGER NOT NULL DEFAULT 0,   -- 0 / 1 boolean
    confidence_score        REAL,
    severity_level          INTEGER,                      -- 0-3
    user_flagged_inaccurate INTEGER NOT NULL DEFAULT 0,   -- reserved for future flag UI
    flag_reason             TEXT,                         -- reserved for future flag UI
    timestamp               TEXT    NOT NULL,             -- ISO 8601 datetime
    FOREIGN KEY (load_id) REFERENCES movie_loads(load_id)
);

CREATE INDEX IF NOT EXISTS idx_warning_analytics_tmdb_id  ON warning_analytics(tmdb_id);
CREATE INDEX IF NOT EXISTS idx_warning_analytics_category ON warning_analytics(category);


-- ─── WARNING FEEDBACK TABLE ──────────────────────────────────
-- Thumbs up / thumbs down on individual warning categories and chat replies.
-- user_id is nullable so anonymous sessions can still leave feedback.
CREATE TABLE IF NOT EXISTS warning_feedback (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id           INTEGER,                          -- nullable: anonymous feedback allowed
    movie_id          INTEGER NOT NULL,
    category          TEXT,                             -- warning category, or null for chat feedback
    feedback_type     TEXT    NOT NULL,                 -- 'warning' | 'chat'
    rating            TEXT    NOT NULL,                 -- 'up' | 'down'
    chat_message_text TEXT,                             -- the chat reply being rated, if applicable
    created_at        TEXT    NOT NULL                  -- ISO 8601 datetime
);

CREATE INDEX IF NOT EXISTS idx_warning_feedback_movie_id ON warning_feedback(movie_id);
CREATE INDEX IF NOT EXISTS idx_warning_feedback_user_id  ON warning_feedback(user_id);
