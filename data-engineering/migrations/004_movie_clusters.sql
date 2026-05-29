-- ReelShield Database Schema (SQLite)
-- Migration: 004_movie_clusters.sql
--
-- K-Means cluster assignment per film. Populated offline by
-- backend/train_cluster_model.py and self-healed on the HF Space at
-- container cold start when missing (backend/app.py:
-- _populate_movie_clusters_if_empty). Used by /api/content_twins/<tmdb_id>
-- to surface films in the same warning-profile cluster, ranked by
-- Euclidean distance to the source film in 9-dim severity space.

CREATE TABLE IF NOT EXISTS movie_clusters (
    tmdb_id              INTEGER PRIMARY KEY,
    cluster_id           INTEGER NOT NULL,    -- 0..K-1; human label lives in the .pkl
    distance_to_centroid REAL,                -- Euclidean distance in 9-dim warning space
    model_version        TEXT    NOT NULL,    -- e.g. 'kmeans_k5_seed42' — bumps on retrain
    created_at           TEXT    NOT NULL,    -- ISO 8601 datetime
    FOREIGN KEY (tmdb_id) REFERENCES movies(tmdb_id) ON DELETE CASCADE
);

-- Index on cluster_id supports the content-twins lookup
-- (WHERE mc.cluster_id = ? AND mc.tmdb_id != ?). Cheap at MVP scale,
-- pays off as the cache grows past a few thousand films.
CREATE INDEX IF NOT EXISTS idx_movie_clusters_cluster_id
    ON movie_clusters(cluster_id);

-- Index on model_version lets us delete only the rows from a previous
-- model when retraining, without touching rows we've already migrated.
CREATE INDEX IF NOT EXISTS idx_movie_clusters_model_version
    ON movie_clusters(model_version);
