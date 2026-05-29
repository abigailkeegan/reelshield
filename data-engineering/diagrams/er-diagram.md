# ReelShield — Entity Relationship Diagram

## Database: SQLite

```
╔══════════════════════════════════════════════════════╗
║                      movies                          ║
╠══════════════════════════════════════════════════════╣
║ PK  tmdb_id        INTEGER   TMDB unique film ID     ║
║     title          TEXT NN   Film title              ║
║     year           TEXT      4-digit release year    ║
║     imdb_id        TEXT      IMDb ID (future use)    ║
║     runtime_min    INTEGER   Runtime in minutes      ║
║     metadata_json  TEXT NN   Full TMDB+computed JSON ║
║     last_updated   TEXT NN   ISO 8601 timestamp      ║
╚══════════════════════════════╦═══════════════════════╝
                               ║ 1
                               ║ (one movie has one
                               ║  cached warning set)
                               ║ 1
╔══════════════════════════════╩═══════════════════════╗
║                  content_warnings                    ║
╠══════════════════════════════════════════════════════╣
║ PK  tmdb_id        INTEGER   FK → movies.tmdb_id     ║
║     warnings_json  TEXT NN   Gemini output JSON      ║
║     last_updated   TEXT NN   ISO 8601 timestamp      ║
╚══════════════════════════════════════════════════════╝
```

## Derived-Data Tables

Per-film data computed from `content_warnings.warnings_json` and the cached
metadata, written by an offline batch step. Each row is keyed on `tmdb_id`
and cascades on delete from `movies`. Note: `movie_embeddings` stores
pretrained sentence-transformer output (deep-learning representations used
off-the-shelf for retrieval, not classic ML); `movie_clusters` stores the
output of a K-Means model trained on this project's warning vectors (classic
ML).

```
╔══════════════════════════════════════════════════════╗
║                 movie_embeddings                     ║
╠══════════════════════════════════════════════════════╣
║ PK  tmdb_id        INTEGER   FK → movies.tmdb_id     ║
║     embedding      BLOB  NN  384-dim float32 vector  ║
║     model_name     TEXT  NN  e.g. all-MiniLM-L6-v2   ║
║     text_hash      TEXT  NN  SHA1 of source string   ║
║     created_at     TEXT  NN  ISO 8601 timestamp      ║
╚══════════════════════════════════════════════════════╝
  Source: backend/embed_all_movies.py
  Use:    recommendations re-ranking, mood matching (Discover)

╔══════════════════════════════════════════════════════╗
║                  movie_clusters                      ║
╠══════════════════════════════════════════════════════╣
║ PK  tmdb_id              INTEGER  FK → movies        ║
║     cluster_id           INTEGER NN  0..K-1          ║
║     distance_to_centroid REAL        Euclidean in    ║
║                                       9-dim warning  ║
║                                       space          ║
║     model_version        TEXT NN     e.g.            ║
║                                       kmeans_k5_seed42║
║     created_at           TEXT NN     ISO 8601        ║
╚══════════════════════════════════════════════════════╝
  Source: backend/train_cluster_model.py (offline trainer)
          backend/app.py:_populate_movie_clusters_if_empty
            (cold-start self-heal on HF Space)
  Use:    /api/content_twins/<tmdb_id> — K-Means neighbors
```

## User & Social Tables

```
╔══════════════════════════════════════════════════════╗
║                       users                          ║
╠══════════════════════════════════════════════════════╣
║ PK  id              INTEGER   AUTOINCREMENT          ║
║     username        TEXT NN   UNIQUE                 ║
║     password_hash   TEXT NN   werkzeug pbkdf2        ║
║     created_at      TEXT NN   ISO 8601 timestamp     ║
╚════╦═════════════════════════════════════════════════╝
     ║ 1                       1 ║                    1 ║
     ║                           ║                      ║
     ║ many                  one ║                 many ║
     ▼                           ▼                      ▼
╔══════════════╗  ╔════════════════════════╗  ╔══════════════════╗
║  watchlist   ║  ║   user_sensitivities   ║  ║     reviews      ║
╠══════════════╣  ╠════════════════════════╣  ╠══════════════════╣
║PK id         ║  ║PK user_id  FK→users.id ║  ║PK id             ║
║FK user_id    ║  ║   sensitivities_json   ║  ║FK user_id        ║
║FK tmdb_id    ║  ║   updated_at           ║  ║FK tmdb_id        ║
║   added_at   ║  ╚════════════════════════╝  ║   username       ║
║UNIQUE        ║                              ║   rating (1-5)   ║
║(user,movie)  ║                              ║   review_text    ║
╚══════════════╝                              ║   created_at     ║
                                              ╚══════════════════╝

(watchlist.tmdb_id and reviews.tmdb_id both FK → movies.tmdb_id)
```

## Analytics Tables

```
╔════════════════════════════════════╗
║            movie_loads             ║   One row per /api/load_movie call.
╠════════════════════════════════════╣   Used to measure cache hit rate,
║PK load_id           INTEGER        ║   load time distribution, and
║   tmdb_id           INTEGER NN     ║   warnings produced per request.
║   title, year, genre, mpaa_rating  ║
║   was_cached        INTEGER (0/1)  ║
║   load_time_ms      INTEGER        ║
║   warnings_generated TEXT  (JSON)  ║
║   confidence_scores  TEXT  (JSON)  ║
║   spoiler_mode_on   INTEGER (0/1)  ║
║   timestamp         TEXT NN        ║
╚════════════╦═══════════════════════╝
             ║ 1
             ║
             ║ many
             ▼
╔════════════════════════════════════╗
║         warning_analytics          ║   One row per (load, category).
╠════════════════════════════════════╣   Used to compute per-category
║PK warning_id          INTEGER      ║   trigger and confidence stats.
║FK load_id  → movie_loads.load_id   ║
║   tmdb_id             INTEGER NN   ║
║   category            TEXT NN      ║
║   was_triggered       INTEGER (0/1)║
║   confidence_score    REAL         ║
║   severity_level      INTEGER (0-3)║
║   user_flagged_inaccurate (reserved)║
║   flag_reason          (reserved)  ║
║   timestamp           TEXT NN      ║
╚════════════════════════════════════╝

╔════════════════════════════════════╗
║         warning_feedback           ║   Thumbs up / down on a warning
╠════════════════════════════════════╣   category or a chat reply.
║PK id                  INTEGER      ║   user_id is nullable so anonymous
║   user_id             INTEGER      ║   sessions can still leave feedback.
║   movie_id            INTEGER NN   ║
║   category            TEXT         ║
║   feedback_type       TEXT NN      ║   'warning' | 'chat'
║   rating              TEXT NN      ║   'up' | 'down'
║   chat_message_text   TEXT         ║
║   created_at          TEXT NN      ║
╚════════════════════════════════════╝
```

## External Data Sources (not stored in DB)

```
┌─────────────────┐     ┌──────────────────────┐
│   TMDB API      │────▶│  movies table         │
│  (REST)         │     │  (cached metadata)    │
└─────────────────┘     └──────────────────────┘

┌─────────────────┐     ┌──────────────────────┐
│  Gemini API     │────▶│  content_warnings     │
│  (AI)           │     │  (cached warnings)    │
└─────────────────┘     └──────────────────────┘

┌──────────────────────────┐    ┌────────────────────────────┐
│ HF Dataset               │──▶ │ /data on cold start:        │
│ abigailkeegan/           │    │ · movie_cache.db (DB hydrate)│
│ reelshield-cache         │    │ · cluster_model.pkl          │
│                          │    │ · mpa_classifier.pkl         │
└──────────────────────────┘    └────────────────────────────┘
```

## Normalization Notes

The schema is in **2NF**. The `metadata_json` and `warnings_json` columns intentionally
store denormalized JSON blobs for the following reasons:

1. **Schema flexibility** — TMDB fields and warning categories can expand without
   requiring ALTER TABLE migrations
2. **Read performance** — Single row lookup by primary key is O(1); no JOINs needed
3. **Appropriate scale** — At MVP scale (<100k movies), JSON blobs are practical;
   a fully normalized schema would be premature optimization

For a production system at scale, the JSON blobs would be decomposed into:
- `movie_genres` (many-to-many)
- `movie_keywords` (many-to-many)
- `warning_categories` (one row per category per movie)
