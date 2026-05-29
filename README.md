---
title: ReelShield
emoji: 🎬
colorFrom: red
colorTo: purple
sdk: docker
pinned: false
---

# 🎬 ReelShield

> AI-powered content warnings for movies, powered by Gemini + TMDB.
> Built for viewers with trauma sensitivities, parents, and anyone who needs to know what's in a film before watching.

**Live demo:** https://huggingface.co/spaces/abigailkeegan/ReelShield
**Poster:** [docs/poster.pptx](docs/poster.pptx) · [PNG preview](docs/poster.png)

---

## Research Question

**How can viewers with trauma sensitivities, epilepsy, or parental concerns quickly and accurately determine whether a film contains specific content triggers - without relying on vague MPA ratings or spoiler-heavy reviews?**

Current MPA ratings (G, PG, PG-13, R) are too broad for specific sensitivities. Existing tools require manual browsing through long reviews. ReelShield combines TMDB metadata with Gemini AI film knowledge to generate specific, spoiler-free content warnings with confidence scores in under 15 seconds.

**Target users:** Parents, trauma survivors, people with photosensitive epilepsy, neurodivergent viewers
**Measurable impact:** Cached-film lookups complete in **<1 second** (SQLite hit, measured locally and in `docs/app-analysis.md` §5); fresh Gemini-generated warnings complete in **under 2 seconds** for the films the testing participants searched. The pre-app baseline ("estimated ~5 minutes via manual cross-referencing of Common Sense Media + IMDb Parents Guide for a single trigger category") is an informal team estimate rather than a measured study — replacing it with a controlled before/after measurement is noted in `docs/app-analysis.md` §8 as a future testing iteration.

---

## Features

- AI content warnings - 9 categories: violence & gore, self-harm & suicide, miscarriage / pregnancy loss, sexual content & nudity, animal abuse, substances, language, horror intensity, flashing lights
- Spoiler-safe chat: ask follow-up questions about the film without revealing plot twists
- Personalized recommendations: comfort-distance ranking over the user's sensitivity profile, re-ranked by sentence-transformer embeddings (`all-MiniLM-L6-v2`) for semantic relevance, and broadened with K-Means cluster neighbors so the severity filter has a larger candidate pool to draw from
- Content twins (K-Means): surface other films in the same warning-profile cluster, ranked by distance in 9-dim severity space
- MPA-disagreement badge: a logistic-regression classifier predicts a family / teen / adult bucket from the warning vector; a badge flags confident disagreements with the TMDB rating
- Discover (mood-aware): free-text mood matching with contrastive scoring against `avoid_tones` so "horror as comfort" queries don't surface horror
- Group watch finder: find films that work for everyone in the room
- User accounts: save preferences and viewing history across sessions
- Watchlists: track films you want to see
- Reviews: read and write reviews with content-warning context
- External ratings: aggregated scores pulled from third-party sources

---

## Architecture

```
Browser (HTML + CSS + JS)
         |
    Flask + Gunicorn
    /api/search  /api/load_movie  /api/chat  /api/content_twins  /api/discover  /health
         |              |                  |                            |
    TMDB API      Gemini 2.5 Flash    Classic-ML models           Pretrained DL (off-the-shelf)
    (metadata)    (warnings)          · K-Means cluster engine    · MiniLM sentence-transformer
                                        (cluster_model.pkl)         (`all-MiniLM-L6-v2`)
                                      · MPA-rating classifier       — embeddings cached in
                                        (mpa_classifier.pkl)          movie_embeddings table
         |
    SQLite
    (movie_cache.db, .pkl artifacts in /data)
         ^
         |
    HF Dataset (abigailkeegan/reelshield-cache)
    cold-start hydration of DB + .pkl artifacts
```

---

## Project Structure

```
movie-warnings/
├── frontend/
│   ├── templates/
│   │   └── index.html                  # Jinja-rendered markup
│   └── static/
│       ├── css/main.css                # Design tokens + component styles
│       └── js/app.js                   # All client-side behavior
├── backend/
│   ├── app.py                          # Flask app: routes, TMDB, Gemini, DB, model + .pkl hydration
│   ├── comfort_distance_recommender.py # Recommendation scoring
│   ├── embeddings.py                   # Sentence-transformer (MiniLM) helpers
│   ├── embed_all_movies.py             # One-shot embedding backfill
│   ├── cluster_engine.py               # K-Means content-twins model + queries
│   ├── train_cluster_model.py          # CLI: fit K-Means, write movie_clusters table
│   ├── mpa_classifier.py               # Logistic-regression MPA-bucket classifier
│   ├── train_mpa_classifier.py         # CLI: train MPA classifier + report metrics
│   ├── seed_movies.py                  # Cache-seeding helper (single-pass)
│   ├── seed_bulk.py                    # Cache-seeding helper (bulk runner)
│   └── seed_direct.py                  # Direct Gemini seeding + --fix-ghosts mode
├── data-engineering/
│   ├── README.md                       # Schema docs, data flow
│   ├── migrations/
│   │   ├── 001_initial_schema.sql
│   │   ├── 002_users_and_social.sql
│   │   ├── 003_movie_embeddings.sql
│   │   └── 004_movie_clusters.sql
│   ├── diagrams/
│   │   └── er-diagram.md
│   └── decade-analysis.md
├── docs/
│   ├── personas/
│   │   └── user-personas.md            # 3 personas + journey maps
│   ├── wireframes/
│   │   └── wireframes.md               # All screens + style guide
│   └── app-analysis.md                 # Testing, metrics, iterations
├── tests/
│   ├── conftest.py                     # Shared Flask client + Gemini mock
│   ├── test_app.py                     # Backend unit + integration tests
│   └── test_frontend.py                # Page renders, WCAG hooks, /api/* routes resolve
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── .env.example                        # Safe to commit - no real keys
├── .env                                # Your real keys - gitignored
└── README.md
```

---

## Database Setup

The `movie_cache.db` SQLite database is **not included in this repository** - it's gitignored to keep the repo small.

You don't need to do anything special before the first run: when the container starts, ReelShield will create an empty `./data/movie_cache.db` and populate it on demand the first time each movie is searched.

If you want to pre-warm the cache so initial searches feel instant, run the seed script after the container is up:

```
docker compose exec app python backend/seed_movies.py
```

This walks a curated list of films, calls `/api/load_movie` for each, and stores the warnings in the cache file mounted at `./data/movie_cache.db`.

---

## Quick Start (Docker)

### 1. Install Docker Desktop
Download from https://www.docker.com/products/docker-desktop

### 2. Get API Keys

| Service | URL | Cost |
|---------|-----|------|
| TMDB | https://www.themoviedb.org/settings/api | Free |
| Gemini | https://aistudio.google.com/app/apikey | Free tier available |

### 3. Configure environment
```
cp .env.example .env
```
Edit `.env` and replace the placeholder values with your real keys:
```
TMDB_API_KEY=your_real_key_here
GEMINI_API_KEY=your_real_key_here
```

### 4. Build and run
```
docker compose up --build
```

Open http://localhost:7860 in your browser.  
To stop: Ctrl+C or `docker compose down`

### Subsequent runs
```
docker compose up
```

---

## Development (without Docker)

Docker is the recommended path, but the backend and frontend can also be run directly on the host for faster iteration.

### Backend

```
pip install -r requirements.txt
export TMDB_API_KEY=your_key
export GEMINI_API_KEY=your_key
export DB_PATH=./data/movie_cache.db
gunicorn --bind 0.0.0.0:7860 --workers 1 --timeout 120 backend.app:app
```

Then open http://localhost:7860.

API routes live in `backend/app.py` (search, load_movie, chat, prompt, watchlist, group, discover, reviews, feedback, auth). The recommendation engine is in `backend/comfort_distance_recommender.py`. A cache-warming helper lives at `backend/seed_movies.py`.

### Frontend

The UI is a **single Jinja-rendered page** served by Flask at `GET /`. The source lives at `frontend/templates/index.html`, with the CSS and JavaScript extracted into `frontend/static/css/main.css` and `frontend/static/js/app.js`. See [`frontend/README.md`](frontend/README.md) for the section map and accessibility contract.

To iterate on the UI without rebuilding the Docker image, run gunicorn (or `flask --app backend.app run --debug`) on the host. Edits to the template and the static files are picked up on browser refresh.

### Tests

```
python -m pytest tests/ -v
```

Backend tests live in `tests/test_app.py` (health, search, prompt, chat, warning shape). Frontend tests live in `tests/test_frontend.py` (page renders, required sections present, WCAG hooks present, every `/api/*` URL the JS calls resolves to a real Flask route, style-guide CSS tokens present). The shared client + Gemini-mock fixture is in `tests/conftest.py`.

---

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `TMDB_API_KEY` | Yes | TMDB REST API key - used for search, metadata, keywords, MPA certifications |
| `GEMINI_API_KEY` | Yes | Google AI Studio key - drives all content-warning generation and chat |
| `OMDB_API_KEY` | No | OMDb key - enriches the "External Reviews" panel with IMDb / Rotten Tomatoes / Metacritic scores. Without it that section is simply empty. |
| `SECRET_KEY` | No (prod: Yes) | Flask session signing key. If unset, a fresh random key is generated on each container start, which invalidates existing user sessions. Set this to a stable value in production. |
| `DB_PATH` | No | SQLite file path inside the container. Defaults to `/data/movie_cache.db`. |
| `REELSHIELD_BASE` | No | Base URL `backend/seed_movies.py` hits to populate the cache. Defaults to `http://localhost:7860`. |
| `REELSHIELD_CACHE_REPO` | No | HF Dataset to hydrate `movie_cache.db` and the `.pkl` model artifacts from on cold start. Defaults to `abigailkeegan/reelshield-cache`. |
| `CLUSTER_MODEL_PATH` | No | Override path for the K-Means model. Defaults to `/data/cluster_model.pkl`. |
| `MPA_MODEL_PATH` | No | Override path for the MPA classifier. Defaults to `/data/mpa_classifier.pkl`. |

---

## API Reference

**Core**

| Method | Endpoint | Body | Description |
|--------|----------|------|-------------|
| POST | /api/search | {"query": "Titanic"} | Search movies |
| POST | /api/load_movie | {"tmdb_id": 597, "spoiler_mode": false} | Load movie + generate warnings |
| POST | /api/chat | {"message": "...", "spoiler_mode": false} | Chat about movie |
| GET | /api/prompt | - | Get current AI prompt |
| POST | /api/prompt | {"prompt": "..."} | Update AI prompt |
| POST | /api/prompt/reset | - | Reset to default prompt |
| GET | /health | - | Health check |

**Auth**

| Method | Endpoint | Body | Description |
|--------|----------|------|-------------|
| POST | /api/register | {"username": "...", "password": "..."} | Create account |
| POST | /api/login | {"username": "...", "password": "..."} | Log in (sets session cookie) |
| POST | /api/logout | - | Clear session |
| GET | /api/me | - | Current user |

**Watchlist & profile**

| Method | Endpoint | Body | Description |
|--------|----------|------|-------------|
| GET | /api/watchlist | - | List the user's watchlist |
| POST | /api/watchlist/<tmdb_id> | - | Add a movie |
| DELETE | /api/watchlist/<tmdb_id> | - | Remove a movie |
| GET | /api/watchlist/check/<tmdb_id> | - | Is this movie on the watchlist? |
| POST | /api/watchlist/rank | - | Rank watchlist by the user's sensitivities |
| GET | /api/profile/sensitivities | - | Read user sensitivity profile |
| POST | /api/profile/sensitivities | {"sensitivities": [...]} | Update profile |

**Reviews & recommendations**

| Method | Endpoint | Body | Description |
|--------|----------|------|-------------|
| GET | /api/reviews/<tmdb_id> | - | User reviews for a film |
| POST | /api/reviews/<tmdb_id> | {"rating": 4, "review_text": "..."} | Post a review |
| GET | /api/external_reviews/<tmdb_id> | - | IMDb / RT / Metacritic scores (OMDb) |
| POST | /api/recommendations/<tmdb_id> | {"avoid": "violence_gore"} | "Similar without..." |
| GET | /api/content_twins/<tmdb_id> | - | K-Means cluster neighbors, ranked by distance in warning-vector space |
| POST | /api/feedback | {"movie_id": 597, "category": "...", "feedback_type": "warning", "rating": "up"} | Thumbs up/down on a warning or chat reply |

**Discover & group**

| Method | Endpoint | Body | Description |
|--------|----------|------|-------------|
| POST | /api/discover | {"mood": "...", "avoid": [...]} | Mood + avoid-warnings discovery |
| POST | /api/group/merge | {"members": [...]} | Merge multiple sensitivity profiles |
| POST | /api/group/recommend | {"members": [...], "mood": "..."} | Find films safe for the group |

##  Full Documentation

| Document | Location |
|----------|----------|
| User Personas + Journey Maps | docs/personas/user-personas.md |
| Wireframes + Style Guide | docs/wireframes/wireframes.md |
| High-fidelity HTML mockups (5 screens) | docs/wireframes/mockups/ |
| Testing + Performance Analysis | docs/app-analysis.md |
| Data Schema | data-engineering/README.md |
| SQL DDL | data-engineering/migrations/ (001 initial, 002 users + social, 003 embeddings, 004 clusters) |
| Accessibility audit (Lighthouse) | docs/wireframes/accessibility/README.md |
| ER Diagram | data-engineering/diagrams/er-diagram.md |
| Decade Analysis (analytics example) | data-engineering/decade-analysis.md |
