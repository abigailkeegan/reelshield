# 📊 Data Engineering - ReelShield

## Overview

ReelShield uses **SQLite** for both local/Docker development and the deployed Hugging Face Space. All schema decisions are documented below.

---

## Entity-Relationship Diagram

```
┌──────────────────────────────────────┐
│              movies                  │
├──────────────────────────────────────┤
│ tmdb_id       INTEGER  PK            │
│ title         TEXT     NOT NULL      │
│ year          TEXT                   │
│ imdb_id       TEXT                   │
│ runtime_min   INTEGER                │
│ metadata_json TEXT     (full blob)   │
│ last_updated  TEXT     (ISO 8601)    │
└──┬─────────────┬─────────────┬───────┘
   │ 1           │ 1           │ 1
   │             │             │
   │ 1           │ 1           │ 1
┌──▼──────────┐ ┌▼─────────────┐ ┌▼──────────────────┐
│content_warn │ │movie_embeddng│ │  movie_clusters   │
│-ings        │ │              │ │                   │
├─────────────┤ ├──────────────┤ ├───────────────────┤
│ tmdb_id  PK │ │ tmdb_id  PK  │ │ tmdb_id  PK       │
│ warnings_j  │ │ embedding    │ │ cluster_id        │
│ last_updated│ │ model_name   │ │ distance_to_cent  │
└─────────────┘ │ text_hash    │ │ model_version     │
                │ created_at   │ │ created_at        │
                └──────────────┘ └───────────────────┘
```

**Relationships:** Each movie has at most one cached warning set, one MiniLM embedding, and one K-Means cluster assignment (all 1:1). Warnings are regenerated only when explicitly refreshed; embeddings are written by `backend/embed_all_movies.py` (a one-pass batch over the cached films using the pretrained `all-MiniLM-L6-v2` model); cluster assignments are written by `backend/train_cluster_model.py` (the K-Means trainer, the only classic-ML model on this side). Both self-heal on the HF Space at container cold start when missing.

---

## Schema Documentation

### Table: `movies`

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `tmdb_id` | INTEGER | PRIMARY KEY | TMDB's unique film identifier |
| `title` | TEXT | NOT NULL | Film title as returned by TMDB |
| `year` | TEXT | | 4-digit release year |
| `imdb_id` | TEXT | | IMDb identifier (for future cross-referencing) |
| `runtime_min` | INTEGER | | Runtime in minutes |
| `metadata_json` | TEXT | | Full JSON blob of TMDB + computed metadata |
| `last_updated` | TEXT | | ISO 8601 timestamp of last cache update |

**Indexes:**
- `tmdb_id` (PRIMARY KEY - automatically indexed)
- Recommended future index: `title` for text search

**Why JSON blob?** The metadata structure evolves as we add new data sources (TMDB keywords, OMDb ratings, etc.). Storing as JSON avoids schema migrations every time a new field is added, while still allowing the app to access structured data at runtime.

---

### Table: `content_warnings`

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `tmdb_id` | INTEGER | PRIMARY KEY, FK | References `movies.tmdb_id` |
| `warnings_json` | TEXT | | Full JSON blob of Gemini-generated warnings |
| `last_updated` | TEXT | | ISO 8601 timestamp |

**Warning JSON structure:**
```json
{
  "disclaimer": "Gemini knowledge-based",
  "spoiler_free": {
    "violence_gore":             {"severity": 0-3, "confidence": 0.0-1.0, "notes": ""},
    "self_harm_suicide":         {"severity": 0-3, "confidence": 0.0-1.0, "notes": ""},
    "miscarriage_pregnancy_loss":{"severity": 0-3, "confidence": 0.0-1.0, "notes": ""},
    "sexual_content_nudity":     {"severity": 0-3, "confidence": 0.0-1.0, "notes": ""},
    "animal_abuse":              {"severity": 0-3, "confidence": 0.0-1.0, "notes": ""},
    "substances":                {"severity": 0-3, "confidence": 0.0-1.0, "notes": ""},
    "language":                  {"severity": 0-3, "confidence": 0.0-1.0, "notes": ""},
    "horror_intensity":          {"severity": 0-3, "confidence": 0.0-1.0, "notes": ""},
    "flashing_lights":           {"severity": 0-3, "confidence": 0.0-1.0, "notes": ""}
  },
  "spoiler_full": {
    "violence_gore":             {"severity": 0-3, "confidence": 0.0-1.0, "notes": ""},
    "self_harm_suicide":         {"severity": 0-3, "confidence": 0.0-1.0, "notes": ""},
    "miscarriage_pregnancy_loss":{"severity": 0-3, "confidence": 0.0-1.0, "notes": ""},
    "sexual_content_nudity":     {"severity": 0-3, "confidence": 0.0-1.0, "notes": ""},
    "animal_abuse":              {"severity": 0-3, "confidence": 0.0-1.0, "notes": ""},
    "substances":                {"severity": 0-3, "confidence": 0.0-1.0, "notes": ""},
    "language":                  {"severity": 0-3, "confidence": 0.0-1.0, "notes": ""},
    "horror_intensity":          {"severity": 0-3, "confidence": 0.0-1.0, "notes": ""},
    "flashing_lights":           {"severity": 0-3, "confidence": 0.0-1.0, "notes": ""}
  }
}
```

**Severity scale:** 0 = absent, 1 = mild/brief, 2 = moderate, 3 = severe/graphic
**Confidence scale:** 1.0 = confirmed by AI knowledge, <1.0 = estimated (obscure film)

**Why two blocks?** `spoiler_free` and `spoiler_full` carry the same `severity` and `confidence` values for each category — only the `notes` text differs. The spoiler-mode toggle in the UI picks which `notes` to render; the underlying numbers describe the film itself, not the description style. Older cached rows may only contain `spoiler_free`; the frontend falls back to it when `spoiler_full` is absent.

---

### Table: `users`

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | INTEGER | PRIMARY KEY, AUTOINCREMENT | Internal user id |
| `username` | TEXT | UNIQUE, NOT NULL | Login name |
| `password_hash` | TEXT | NOT NULL | werkzeug pbkdf2(sha256) hash |
| `created_at` | TEXT | NOT NULL | ISO 8601 timestamp |

**Indexes:** `idx_users_username` on `username`.

---

### Table: `reviews`

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | INTEGER | PRIMARY KEY, AUTOINCREMENT | Review id |
| `tmdb_id` | INTEGER | NOT NULL, FK → `movies.tmdb_id` | Film being reviewed |
| `user_id` | INTEGER | NOT NULL, FK → `users.id` | Author |
| `username` | TEXT | NOT NULL | Denormalized for fast display |
| `rating` | INTEGER | | 1–5 stars; nullable for text-only reviews |
| `review_text` | TEXT | NOT NULL | Body |
| `created_at` | TEXT | NOT NULL | ISO 8601 timestamp |

**Indexes:** `idx_reviews_tmdb_id`, `idx_reviews_user_id`.

---

### Table: `watchlist`

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | INTEGER | PRIMARY KEY, AUTOINCREMENT | Row id |
| `user_id` | INTEGER | NOT NULL, FK → `users.id` | Owner |
| `tmdb_id` | INTEGER | NOT NULL | Film |
| `added_at` | TEXT | NOT NULL | ISO 8601 timestamp |

**Constraints:** `UNIQUE(user_id, tmdb_id)` prevents duplicate entries.  
**Indexes:** `idx_watchlist_user_id`.

---

### Table: `user_sensitivities`

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `user_id` | INTEGER | PRIMARY KEY, FK → `users.id` | One row per user |
| `sensitivities_json` | TEXT | NOT NULL | JSON array of warning-category strings the user always wants to avoid |
| `updated_at` | TEXT | NOT NULL | ISO 8601 timestamp |

---

### Table: `movie_loads`

Instrumentation table. One row per `/api/load_movie` call.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `load_id` | INTEGER | PRIMARY KEY, AUTOINCREMENT | Load id |
| `tmdb_id` | INTEGER | NOT NULL | Film loaded |
| `title`, `year`, `genre`, `mpaa_rating` | TEXT | | Snapshot of movie metadata |
| `was_cached` | INTEGER | NOT NULL DEFAULT 0 | 0/1 boolean - cache hit |
| `load_time_ms` | INTEGER | | End-to-end load latency |
| `warnings_generated` | TEXT | | JSON array of triggered category names |
| `confidence_scores` | TEXT | | JSON map of category → confidence |
| `spoiler_mode_on` | INTEGER | NOT NULL DEFAULT 0 | 0/1 boolean |
| `timestamp` | TEXT | NOT NULL | ISO 8601 timestamp |

**Indexes:** `idx_movie_loads_tmdb_id`, `idx_movie_loads_timestamp`.

---

### Table: `warning_analytics`

One row per `(load_id, category)`. Used to compute per-category trigger rates and average confidence over time.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `warning_id` | INTEGER | PRIMARY KEY, AUTOINCREMENT | Row id |
| `load_id` | INTEGER | FK → `movie_loads.load_id` | The load this row belongs to |
| `tmdb_id` | INTEGER | NOT NULL | Film |
| `category` | TEXT | NOT NULL | Warning category name |
| `was_triggered` | INTEGER | NOT NULL DEFAULT 0 | 0/1 boolean |
| `confidence_score` | REAL | | 0.0–1.0 |
| `severity_level` | INTEGER | | 0–3 |
| `user_flagged_inaccurate` | INTEGER | NOT NULL DEFAULT 0 | Reserved for a future "flag this warning" UI |
| `flag_reason` | TEXT | | Reserved for the same |
| `timestamp` | TEXT | NOT NULL | ISO 8601 timestamp |

**Indexes:** `idx_warning_analytics_tmdb_id`, `idx_warning_analytics_category`.

---

### Table: `movie_embeddings`

Sentence-transformer (`all-MiniLM-L6-v2`) embeddings of each film's title + overview + keywords. Used to re-rank recommendations and match free-text mood queries on the Discover page.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `tmdb_id` | INTEGER | PRIMARY KEY, FK → `movies.tmdb_id` (ON DELETE CASCADE) | One row per film |
| `embedding` | BLOB | NOT NULL | 384-dim float32 vector packed as bytes |
| `model_name` | TEXT | NOT NULL | Embedding model identifier (`all-MiniLM-L6-v2`) |
| `text_hash` | TEXT | NOT NULL | SHA1 of the source text — lets the pipeline re-embed only when the source string changes |
| `created_at` | TEXT | NOT NULL | ISO 8601 timestamp |

Populated by `backend/embed_all_movies.py`; consumed by `backend/embeddings.py:cosine_top_k`.

---

### Table: `movie_clusters`

K-Means cluster assignment per film. Used by the "Content twins" UI section (`/api/content_twins/<tmdb_id>`) and the offline cluster-archetype analysis.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `tmdb_id` | INTEGER | PRIMARY KEY, FK → `movies.tmdb_id` (ON DELETE CASCADE) | One row per film |
| `cluster_id` | INTEGER | NOT NULL | 0..K-1; mapping to a human-readable label lives in the `.pkl` (`cluster_names` dict) |
| `distance_to_centroid` | REAL | | Euclidean distance to the assigned centroid in 9-dim warning space |
| `model_version` | TEXT | NOT NULL | E.g. `kmeans_k5_seed42` — bumps when the model is retrained |
| `created_at` | TEXT | NOT NULL | ISO 8601 timestamp |

Populated by `backend/train_cluster_model.py`. On the HF Space, the table is also self-healed at cold start (see `_populate_movie_clusters_if_empty()` in `backend/app.py`) so the feature works even when the hydrated `movie_cache.db` pre-dates the K-Means commit.

---

### Table: `warning_feedback`

Thumbs up / thumbs down feedback the user gives on specific warning categories and chat replies.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | INTEGER | PRIMARY KEY, AUTOINCREMENT | Row id |
| `user_id` | INTEGER | | Nullable - anonymous sessions may also leave feedback |
| `movie_id` | INTEGER | NOT NULL | Film |
| `category` | TEXT | | Warning category, or NULL for chat feedback |
| `feedback_type` | TEXT | NOT NULL | `'warning'` or `'chat'` |
| `rating` | TEXT | NOT NULL | `'up'` or `'down'` |
| `chat_message_text` | TEXT | | The chat reply being rated, if applicable |
| `created_at` | TEXT | NOT NULL | ISO 8601 timestamp |

**Indexes:** `idx_warning_feedback_movie_id`, `idx_warning_feedback_user_id`.

---

## Data Sources

| Source | Type | What We Fetch | Rate Limit |
|--------|------|---------------|------------|
| TMDB API | REST | Title, year, genres, runtime, rating, keywords, poster, overview | 50 req/sec |
| Gemini 2.5 Flash | AI API | Content warnings (9 categories) | 15 req/min (free), higher on paid |
| HF Dataset (`abigailkeegan/reelshield-cache`) | File pull | Pre-warmed `movie_cache.db` + classic-ML `.pkl` artifacts on cold start | N/A |
| `all-MiniLM-L6-v2` (sentence-transformers) | Local model | 384-dim embedding per film | N/A — runs in-process |
| `cluster_model.pkl` (K-Means) | Local model | Cluster assignments + content-twins queries | N/A — runs in-process |
| `mpa_classifier.pkl` (LogisticRegression) | Local model | Predicted MPA bucket for the disagreement badge | N/A — runs in-process |
| SQLite | Local DB | Cached movies, warnings, embeddings, cluster assignments | N/A |

---

## Data Flow

```
[Container cold start]
        │
        ▼
Hydrate /data/movie_cache.db from HF Dataset (if missing/empty)
Hydrate /data/{cluster,mpa}_classifier.pkl from HF Dataset
Self-heal movie_clusters table if empty (uses cluster_model.pkl)
        │
        ▼
[Request: User searches "Titanic"]
        │
        ▼
TMDB /search/movie
        │
        ▼
User selects result
        │
        ▼
Check SQLite cache ──── HIT ──▶ Return cached warnings + run MPA classifier
        │                       on cached warning vector → optional badge
       MISS                     ──▶ Return to frontend
        │
        ▼
TMDB /movie/{id}          (title, genres, runtime, rating)
TMDB /movie/{id}/keywords (community content tags)
TMDB /movie/{id}/release_dates (MPA certification)
        │
        ▼
Gemini 2.5 Flash
  Input: title + year + rating + genres + overview + keywords
  Output: JSON with 9 warning categories
        │
        ▼
Save to SQLite cache; run MPA classifier on the new warning vector
        │
        ▼
Return to frontend (warnings + optional mpa_prediction)
```

---

## Backup & Recovery Strategy

**SQLite/Docker (current):**
- SQLite file is mounted at `/data/movie_cache.db` inside the container via the `./data` bind mount in `docker-compose.yml`.
- Backup: `docker run --rm -v movie-warnings_movie_data:/data -v $(pwd):/backup alpine tar czf /backup/db-backup.tar.gz /data`
- On Hugging Face Spaces, the SQLite file lives on the Space's filesystem; production-grade durability is delegated to the planned RDS migration described below.

**Planned production (RDS):**
- Automated daily snapshots via AWS RDS
- Point-in-time recovery enabled
- Cross-region snapshot copy for disaster recovery

---

## Production Architecture (Planned: AWS RDS)

The current Hugging Face Space runs SQLite for demo simplicity, but the schema is designed to migrate to **PostgreSQL on AWS RDS** for production scale. The table layout above is portable as-is - every column type maps cleanly to PostgreSQL (INTEGER → BIGINT/INTEGER, TEXT → TEXT, REAL → DOUBLE PRECISION) and the JSON blobs become `JSONB` for indexable queries.

### Architecture diagram

```
┌────────────────────────────────────────────────────────────────────┐
│                       Hugging Face Space / EC2                      │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │  Flask + Gunicorn (backend/app.py)                           │  │
│  │     ─ /api/search, /api/load_movie, /api/discover, …         │  │
│  └────────────┬─────────────────────────────────────────────────┘  │
│               │                                                     │
└───────────────┼─────────────────────────────────────────────────────┘
                │ psycopg2 (5432, TLS in transit)
                ▼
       ┌────────────────────────────────────┐
       │   AWS RDS - PostgreSQL 15          │
       │   ─ db.t3.micro (dev/MVP)          │
       │   ─ Multi-AZ (prod)                │
       │   ─ Encryption at rest (KMS)       │
       │   ─ Automated 7-day backups        │
       │   ─ Cross-region snapshot copy     │
       └────────────────────────────────────┘
                ▲
                │ /find/{imdb_id}, /movie/{id}, /search/movie
                │ generate_content()
                │
       ┌────────┴────────┐ ┌────────────────┐ ┌──────────────────┐
       │   TMDB API      │ │  OMDb API      │ │  Gemini 2.5 Flash │
       └─────────────────┘ └────────────────┘ └──────────────────┘

In production, the .pkl model artifacts would migrate from the public
HF Dataset to a private S3 bucket alongside the RDS schema, with model
versions referenced from a config table so retrains don't require code
pushes.
```

### Migration plan (SQLite → PostgreSQL RDS)

**Step 1 - Provision RDS:**

| Setting | Value | Reason |
|---------|-------|--------|
| Engine | PostgreSQL 15 | First-class JSONB, mature |
| Instance | db.t3.micro | Sufficient for demo/MVP traffic |
| Storage | 20 GB gp2 | Generous for movie cache |
| Multi-AZ | No (dev), Yes (prod) | Cost vs availability tradeoff |
| Backup | 7-day retention | Recovery window |
| Encryption | At rest (KMS) + in transit (TLS) | API key data in JSON blobs |

**Step 2 - Add the driver to `requirements.txt`:**
```
psycopg2-binary==2.9.9
```

**Step 3 - Wire `DATABASE_URL` into `docker-compose.yml`:**
```yaml
services:
  app:
    environment:
      DATABASE_URL: postgresql://user:pass@your-rds-endpoint:5432/reelshield
```

**Step 4 - Swap the connection logic in `backend/app.py`:**
```python
import psycopg2
DATABASE_URL = os.environ.get("DATABASE_URL")
conn = psycopg2.connect(DATABASE_URL)
```

**Step 5 - Run the migration scripts** (`001_initial_schema.sql`, `002_users_and_social.sql`, `003_movie_embeddings.sql`, `004_movie_clusters.sql`) against the new database. The DDL is SQLite-compatible but uses only standard SQL features, so it runs cleanly on PostgreSQL after replacing `INTEGER PRIMARY KEY AUTOINCREMENT` with `BIGSERIAL PRIMARY KEY`, changing the JSON `TEXT` columns to `JSONB`, and swapping the `BLOB` column on `movie_embeddings` to `BYTEA`.

---

## Query Optimization

**Current queries and their performance:**

```sql
-- Lookup by tmdb_id (primary key) - O(1), instant
SELECT metadata_json FROM movies WHERE tmdb_id = ?;
SELECT warnings_json FROM content_warnings WHERE tmdb_id = ?;

-- Insert/replace - O(log n) on primary key index
INSERT OR REPLACE INTO movies VALUES (?,?,?,?,?,?,?);
```

**Future optimization for scale:**
```sql
-- Add index on title for text search
CREATE INDEX idx_movies_title ON movies(title);

-- Add index on last_updated to find stale cache entries
CREATE INDEX idx_warnings_updated ON content_warnings(last_updated);
```

---

## Analytics Examples

A worked example of running analytics against this schema — average warning severity per category per decade, plus trend findings — is in [`decade-analysis.md`](decade-analysis.md). It includes the `json_extract`-based SQL used to compute the per-category averages from `content_warnings.warnings_json`.
