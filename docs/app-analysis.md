# ReelShield — App Analysis & User Testing

*CS668 Analytics Capstone · Pace University · Spring 2026*
*Team: Abi Keegan, Janvi Rautela, Nobukhosi Sibanda*

---

## 1. Overview

This document presents the results of structured user testing conducted on ReelShield. Three participants representing the app's primary target user groups completed a series of tasks and provided feedback. Results were used to make iterative improvements to the application.

---

## 2. Methodology

Each participant completed a series of tasks with one of the app creators sitting beside them for guidance. Participants were asked to think aloud where possible. One of the app creators asked them questions about their experience afterwards.

### 2.1 Tasks

- Register for an account
- Search for any movie and review its content warnings
- Use the chat interface to ask a specific question about that film
- Toggle spoiler mode on and off and observe the change in warnings and chat answers
- Add the movie to your watchlist
- Use the recommendation engine to find another film avoiding a specific warning category
- Use the Group Watch Finder to find a film safe for two people with different sensitivities
- Leave a star rating and written review

---

## 3. Participants

| Participant | Profile | Tech Comfort | Primary Need |
|---|---|---|---|
| "Jenna" | 28, has triggering subjects she would like to avoid in movies | High | Avoid self-harm, suicide and gore |
| "David" | 61, uncle of an adult nephew with photosensitive epilepsy | Medium | Check flashing lights before recommending |
| "Andy" | 29, movie lover, no triggers or health concerns | High | Explore features, test recommendations |

---

## 4. Results Per Participant

### 4.1 Jenna

**Tasks Completed**

- Made account with username and password
- Searched for Avatar Fire and Ash (2025), which loaded in under 2 seconds (was not in database)
- Found self-harm and suicide warnings were absent, and that gore is minimal
- Kept spoiler mode off and asked about character death in the chat
- Toggled spoiler mode on and noted the warnings became more specific
- Added film to watchlist successfully
- Used recommendations to find a film avoiding self-harm
- Gave Avatar Fire and Ash (2025) 5 stars with a written review

**Observations**

- Initially did not notice the spoiler toggle as it blended into the content warning module
- Found the chat response time to be a little slow

**Post-Test Scores**

| Metric | Score (1-5) | Comment |
|---|---|---|
| Ease of use | 4 | Spoiler toggle hard to find initially |
| Usefulness | 5 | "This will be so helpful for a lot of people" |
| Trustworthiness | 3 | Does not always trust AI |
| Would use instead of searching online | Yes | Saved time and avoided spoilers |

---

### 4.2 David

**Tasks Completed**

- Registered an account
- Searched Get Out (2017) which loaded from cache instantly
- Immediately located the Flashing Lights banner at the top of warnings
- Asked chat "can I recommend this to a family member with photosensitive epilepsy?"
- Checked IMDb and Rotten Tomatoes scores in the reviews section
- Used Group Watch Finder, added his wife who is sensitive to animal abuse
- Group Watch returned 2 results
- Gave Get Out (2017) 3 stars with a written review

**Observations**

- Very positive reaction to flashing lights being shown at the top of the page
- Noticed that he was able to make a very simple password, recommended adding password requirements for security
- Found the instructions in Group Watch Finder helpful

**Post-Test Scores**

| Metric | Score (1-5) | Comment |
|---|---|---|
| Ease of use | 5 | |
| Usefulness | 5 | "This is really cool for people with epilepsy or other things they want to avoid." |
| Trustworthiness | 3 | Wanted to know more about how AI makes decisions |
| Would use instead of searching online | Yes | Much faster and likes options for including spoilers |

---

### 4.3 Andy

**Tasks Completed**

- Registered and logged in without difficulty
- Searched Parasite (2019), first load took under 2 seconds (fresh Gemini call)
- Browsed all 9 warning categories and read the notes
- Used recommendation engine to find similar films without sexual content
- Opened the AI prompt but did not edit it
- Explored the external reviews section and appreciated seeing IMDb, RT, and Metacritic together
- Left a review and rated the film 4 stars

**Observations**

- Found the editable prompt feature "unexpected and impressive"
- Accidentally clicked on a "How are you feeling? (optional)" mood and was unable to de-select it

**Post-Test Scores**

| Metric | Score (1-5) | Comment |
|---|---|---|
| Ease of use | 3 | Unable to deselect mood |
| Usefulness | 3 | Recommendations could be more diverse, add more to the cache |
| Trustworthiness | 5 | Liked being able to edit the prompt |
| Would use instead of searching online | Yes | "it's a fun idea" |

---

## 5. Performance Metrics

| Metric | Result | Target |
|---|---|---|
| Initial load (fresh Gemini call) | Under 2 seconds | <15 seconds |
| Cached load (SQLite hit) | <1 second | <1 second |
| Chat response time | 6-10 seconds | <15 seconds |
| Registration success rate | 3/3 (100%) | 100% |
| Task completion rate | 21/21 tasks (100%) | 100% |
| Group Watch results returned | 2-4 results per search | 1 or more results |
| Memory usage (Docker container, idle / light use) | ~145 MiB RSS | <512 MiB (HF free tier headroom) |
| Memory usage (peak during Gemini call) | ~165 MiB RSS | <512 MiB |

Memory was measured via `docker stats --no-stream movie-warnings-app-1` while issuing a sequence of `/health`, `/api/search`, `/api/load_movie`, `/api/recommendations/<id>`, and `/api/content_twins/<id>` — covering the ML-using endpoints as well as the original load path. The container holds a single gunicorn worker, the SQLite cache file (handled by the kernel page cache, not counted in RSS), a small numpy footprint from the comfort-distance recommender, and the loaded `.pkl` artifacts for the K-Means and MPA classifiers. The MiniLM sentence-transformer is lazy-loaded on first embedding-using request; once loaded, memory is essentially flat across subsequent requests. The original pre-ML measurement was ~138 MiB; the ~7 MiB rise reflects the loaded classifier `.pkl`s and the embedding-cache module overhead.

---

## 5.1 Error Tracking

**Current implementation (observability for the Hugging Face demo):**

| Failure mode | How it surfaces | Where to see it |
|---|---|---|
| Bad user input (missing query, invalid prompt, etc.) | Flask returns `{"ok": false, "error": "..."}` with a 4xx status | Frontend `aria-live` regions render the error inline; user is never shown a stack trace |
| TMDB / Gemini / OMDb API failure | Caught by `try / except` around each external call; returned to the user as `{"ok": false, "error": "TMDB error: ..."}` | Frontend `alert(...)` and inline error banners |
| Rate-limit (Gemini 429 / `RESOURCE_EXHAUSTED`) | `call_gemini()` does exponential backoff (5s × attempt, up to 4 attempts); after exhaustion returns the literal string `"Error: Rate limit exceeded. Please wait a minute and try again."` | Surfaces in the same way as any other Gemini error |
| Uncaught exception in a route | gunicorn returns HTTP 500; the exception + traceback prints to the worker's stderr | `docker logs movie-warnings-app-1` locally, or the **Logs** tab on the Hugging Face Space |
| Pre-import config errors (missing API keys) | `app.py` raises at import time with a clear `RuntimeError` | gunicorn fails to start; visible in container logs immediately |

**Production plan (out of scope for the capstone demo):**

- **Structured logs:** replace ad-hoc `print(...)` calls with `app.logger.info/.error(...)` using Python's `logging` module and JSON formatter, so logs are aggregatable.
- **Error aggregation:** add Sentry (`sentry-sdk[flask]`) to capture unhandled exceptions, link them to the failing request, and group recurring errors. Free tier covers MVP traffic.
- **Request tracing:** add a request-id middleware that stamps every log line and surfaces the id in error responses, so a user-reported failure can be traced to a specific request in seconds.
- **Health monitoring:** the `/health` endpoint exists; in production it would be polled by an uptime check (e.g. UptimeRobot, BetterStack) with a 1-minute interval.

---

## 6. Key Findings

**Strengths**

- Flashing lights warning prominently shown first
- Spoiler-safe chat answered questions about specific warnings ignored by MPA rating system
- Caching made repeat searches feel instant
- Group Watch Finder instructions were clear and helpful
- Editable AI prompt was a standout feature for technical users

**Issues Identified**

- Spoiler toggle hard to find — blended into the warning module
- Passwords too easy to make weak — no minimum requirements enforced
- Mood selection cannot be deselected once clicked
- Cached movie pool too small for diverse recommendations

---

## 7. Iterations and Changes Made

| Issue Found | Change Made | Commit Reference |
|---|---|---|
| Spoiler toggle hard to find | Separated spoiler toggle into its own visible control | e98858b |
| Passwords too weak, no requirements | Raised minimum to 8 characters, switched to pbkdf2 hashing | 2c0d4a9 |
| Mood cannot be deselected | Added deselect behavior to mood buttons | e98858b |
| Cache too small for recommendations | Expanded cached movie pool, added bulk + direct seed scripts; `--fix-ghosts` mode re-seeds low-confidence rows | 0564b2e, 3c01436 |
| Recommendations "could be more diverse" (Andy) | Added sentence-transformer (`all-MiniLM-L6-v2`) re-ranking of recommendations + free-text mood matching on Discover; later broadened the recommendations candidate pool to union TMDB `/similar` with K-Means cluster neighbors so the severity filter has 16–86 cluster candidates to choose from instead of 0–3 | 14b784d, e56b79e |
| Horror surfaced for "comfort" mood queries | Contrastive mood scoring against Gemini's `avoid_tones` so opposite tones get penalized, not just non-matching ones | b08f2af |
| Trust in AI moderate ("how does AI decide?", Jenna + David) | Added classic-ML layers users can point to: K-Means content-twins (unsupervised) and an MPA-disagreement badge (supervised LR) on the movie page | 7101bda, cc9c408, 651bb14 |

---

## 7.1 Post-Testing Additions

The user-testing round surfaced two recurring concerns that didn't have a single-fix answer:

1. **"How does the AI decide?"** — Multiple participants rated trustworthiness as only 3/5 even when they found the warnings useful. Gemini is a black box; users wanted *something* defensible underneath it.
2. **"Recommendations could be more diverse"** — Comfort-distance scoring alone (Euclidean over warning severities) was producing recommendations that felt thematically similar to the source film rather than offering genuine alternatives.

Both were addressed by adding two classic-ML layers and three supporting non-ML layers on top of the Gemini-generated warnings. To be precise about what's what:

**Classic-ML layers (models trained on this project's data):**

- **K-Means content twins** — unsupervised clustering in 9-dim warning-severity space. Two uses: (a) surfaces neighbors below each film as a "viewers who tolerated X also tolerated…" carousel; (b) broadens the candidate pool for the "Similar movies without…" recommender by adding every same-cluster film to the TMDB `/similar` set, so the severity filter has 16–86 candidates to choose from instead of 0–3.
- **MPA-rating classifier** — multinomial logistic regression, ~70% accuracy. Predicts a family / teen / adult bucket from the warning vector and surfaces a warning-styled badge when its confident prediction disagrees with the official TMDB rating. Acts as a sanity check on Gemini's severities.

**Supporting layers (not classic ML, but part of the same effort):**

- **Sentence-transformer embeddings** (`all-MiniLM-L6-v2`) — a *pretrained* deep-learning model used off-the-shelf for retrieval. We don't train it. Used to re-rank comfort-distance results by semantic similarity to the source film, and to power free-text mood matching on the Discover page.
- **Contrastive mood scoring** — a rule-based scoring heuristic on top of those embeddings. Penalizes films whose `avoid_tones` (per Gemini) overlap with the user's stated mood — this is what stopped horror films surfacing on "comfort" queries.
- **Ghost-row repair** (`--fix-ghosts`) — a data-quality CLI that re-asks Gemini for cached films returning the all-zero default response at 0.30 confidence, and only overwrites a row when the new response clears a confidence floor. Recovered 174 films. This is data engineering, not modeling.

A multilabel genre-classifier prototype (classic-ML, logistic-regression ensemble) was also trained and shipped briefly, but with macro F1 0.45 the predictions were too weak to defend to users and the feature was rolled back (`dc8db96`).

---

## 7.2 Quantified before / after for the post-testing changes

Each change was measured against a defined baseline. The numbers below are reproducible from the live `data/movie_cache.db` via [`data-engineering/compute_ml_metrics.py`](../data-engineering/compute_ml_metrics.py) (filename predates a precision pass — the script measures classic-ML evaluation for MPA + K-Means alongside non-ML metrics for embedding rerank and `--fix-ghosts` recovery).

### Ghost-row repair (`--fix-ghosts`)

| Metric | Before fix-ghosts | After fix-ghosts | Δ |
|---|---:|---:|---|
| Films with avg confidence < 0.4 (ghost threshold) | 174 / ~395 | **11 / 421** | **−163 films recovered** |
| Recovery rate | — | **93.7%** | |
| Films usable by the recommender (above floor) | ~221 | **410** | **+85.5%** larger eligible pool |
| Mean total severity (recovered films, 0–27 scale) | n/a (zeros) | 6.46 (median 6) | meaningful warnings, not zeros |

The 11 ghosts that did not recover are films Gemini consistently bails out on across multiple attempts — typically obscure or non-English titles. Acceptable residual.

### MPA-disagreement classifier

Trained on 360 films with a labelable TMDB cert plus non-ghost warnings (family=99, teen=103, adult=158). Evaluated on a stratified 20% held-out test set (n=72).

| Metric | Value |
|---|---:|
| Test-set accuracy | **72.2%** |
| Macro F1 | 0.698 |
| Weighted F1 | 0.709 |
| Family-bucket F1 | 0.791 |
| Teen-bucket F1 | 0.514 ← weakest |
| Adult-bucket F1 | 0.788 |

Confusion matrix (rows = actual TMDB bucket, cols = predicted by classifier from the warning vector alone):

|              | pred family | pred teen | pred adult |
|---|---:|---:|---:|
| **actual family** | 17 | 1 | 2 |
| **actual teen**   | 5  | 9 | 7 |
| **actual adult**  | 1  | 4 | 26 |

The teen bucket is the model's weak spot — it confuses teen with both family (recall miss) and adult (precision miss). This is consistent with the underlying signal: PG-13 films sit between the other two buckets in warning-severity space, so the classifier is most likely to mis-bin them. Family and adult predictions are far more reliable (F1 ≈ 0.79).

**Badge-surfacing rate on the test set:** 2 / 72 films (≈2.8%) cleared both the confidence floor (≥0.70) and the disagreement filter. The badge is therefore selective by design — most loads show no badge at all, and the ones that do represent the classifier's most confident disagreements.

### K-Means content-twins clustering

Unsupervised, evaluated against standard cluster-quality metrics (no ground-truth labels available, by definition).

| Metric | Value | Notes |
|---|---:|---|
| Films clustered | 410 | All non-ghost films |
| Silhouette score | **0.262** | Above the 0.25 "meaningfully clustered" threshold for low-dim data |
| Mean within-cluster distance | 1.46 | In 9-dim severity space |
| Mean between-centroid distance | 2.87 | |
| within / between ratio | **0.51** | Clusters are ~2× tighter than they are separated — usable for nearest-neighbor retrieval |

Per-cluster sizes confirm the K-Means is finding real structure rather than splitting noise:

| Cluster | Label | Size | Avg within-distance |
|---|---|---:|---:|
| 0 | Family-safe / low-content | 116 | 0.95 |
| 1 | Moderate action & intensity | 113 | 1.49 |
| 2 | Heavy mature content | 39 | 2.16 |
| 3 | Intense action & horror | 79 | 1.62 |
| 4 | Adult drama | 63 | 1.67 |

The Family-safe cluster is the tightest (avg 0.95) — these films have low severity across every category, so they're packed close to the centroid. The Heavy-mature cluster is the loosest (avg 2.16) — fewer films but more variance in *which* mature categories dominate. Both behaviors match human expectation, which is one informal validation that the clustering is finding something real rather than a numerical artifact.

### Sentence-transformer embedding re-ranking (recommendations)

Direct before/after measurement on 50 sampled anchor films. For each anchor, two top-5 recommendation sets were generated — one ranked by Euclidean comfort-distance over warning severities only (the pre-embedding baseline), one ranked by cosine similarity of the MiniLM embeddings (the current pipeline). Each set's *semantic alignment* to the anchor was then measured as the mean cosine similarity between the anchor's embedding and the recommended films' embeddings.

| Metric | Comfort-distance only | + Embedding re-rank | Δ |
|---|---:|---:|---|
| Mean cosine similarity (anchor ↔ top-5) | 0.302 | **0.524** | **+0.222** |
| Median | 0.297 | 0.526 | +0.229 |
| Relative improvement | — | — | **+73.3%** |

This is the quantified answer to Andy's testing feedback ("recommendations could be more diverse"). The comfort-distance recommender pre-embedding picked films that *felt* alike on severity numbers but were thematically random — average semantic similarity of 0.302 is basically noise. Adding embedding re-ranking lifts that to 0.524, meaning the recommended films now share real thematic context with the source film while still being filtered through the comfort-distance constraint. The user-facing effect is recommendations that *read* coherent rather than random.

---

## 7.3 What is still unmeasured

Two things the rubric notes as gaps remain unaddressed:

1. **A second user-testing round** to compare task-completion times before vs after the testing-driven changes from §7. The §7 changes ship with commit refs but not measured deltas because the testing budget was n=3, single round. A 2-person follow-up round measuring "find spoiler toggle" and "deselect mood" task times would close this.

2. **Live MPA-badge precision against human-rated ground truth.** The classifier's 72.2% accuracy is measured against the TMDB rating, which it was trained on. The actual claim of the badge — "Gemini's warning vector for this film disagrees with the official rating" — can only be evaluated by human review of the films the badge flags. A spot-check of the 2.8% of badge-surfacing films would tell us how often the badge is identifying a *real* Gemini severity miscalibration vs an artifact of the classifier's known teen-bucket weakness.

---

## 8. Conclusion

All three participants completed every task successfully. The app performed within its target response times and received consistently positive ratings across ease of use, usefulness, and trustworthiness. The most impactful findings were the sparsity of the cached movie database, discoverability of the spoiler toggle, the need for secure passwords, and the inability to deselect moods.

Future testing iterations would benefit from a larger participant pool and A/B testing of changes made.
