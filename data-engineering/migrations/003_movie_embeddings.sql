-- ReelShield Database Schema (SQLite)
-- Migration: 003_movie_embeddings.sql
--
-- Caches sentence-transformer embeddings (384-dim, all-MiniLM-L6-v2) per movie
-- so /api/recommendations and /api/discover can rank by semantic similarity
-- without re-running the transformer for every query.

CREATE TABLE IF NOT EXISTS movie_embeddings (
    tmdb_id    INTEGER PRIMARY KEY,
    embedding  BLOB    NOT NULL,    -- 384 float32 values = 1536 bytes
    model_name TEXT    NOT NULL,    -- e.g. 'sentence-transformers/all-MiniLM-L6-v2'
    text_hash  TEXT    NOT NULL,    -- sha1[:16] of the source text; re-embed when it changes
    created_at TEXT    NOT NULL,    -- ISO 8601 datetime
    FOREIGN KEY (tmdb_id) REFERENCES movies(tmdb_id) ON DELETE CASCADE
);

-- The model_name index supports future multi-model A/B experiments
-- without scanning the whole table.
CREATE INDEX IF NOT EXISTS idx_movie_embeddings_model
    ON movie_embeddings(model_name);
