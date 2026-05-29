"""
ReelShield Comfort Distance Recommendation Engine
=================================================
An alternative recommender that scores movies by how well they fill
the user's comfort space — rather than penalising content, it rewards
movies that engage with content the user is comfortable with.

Core philosophy:
  Nobby's engine asks: "How safe is this movie?"
  This engine asks:    "How engaging is this movie within what I can handle?"

A movie with zero content in every category scores poorly here — it's
technically safe but potentially dull. A movie that sits just inside the
user's comfort boundary scores highest, because it uses the content space
the user is actually comfortable with.

Find Movies priority order:
  1. Hard exclusion  — any movie exceeding a sensitive category threshold
                       is removed entirely before scoring
  2. Boundary proximity — how close to the user's comfort edge (without
                          exceeding it) across non-sensitive categories
  3. Engagement bonus   — content richness in categories the user is not
                          sensitive to at all
  4. MMR diversity pass — same as Nobby's engine, warning-vector only
                          (genres excluded from scoring entirely)

Group Watch priority order:
  1. Hard exclusion applied per-member — if ANY member's sensitive
     category is exceeded, the movie is excluded
  2. Per-member comfort distance scores aggregated with equal weighting
  3. Engagement bonus from the union of non-sensitive categories
  4. MMR diversity pass
"""

import numpy as np
from typing import List, Dict, Optional, Tuple

# ── Feature space (must match ml_recommender.py exactly) ──────
CATEGORIES: List[str] = [
    "violence_gore",
    "self_harm_suicide",
    "miscarriage_pregnancy_loss",
    "sexual_content_nudity",
    "animal_abuse",
    "substances",
    "language",
    "horror_intensity",
    "flashing_lights",
]
CAT_INDEX: Dict[str, int] = {c: i for i, c in enumerate(CATEGORIES)}
N_CATS = len(CATEGORIES)

# ── Severity threshold map ─────────────────────────────────────
# A user's "sensitivity" maps to a hard ceiling in normalised [0,1] space.
# severity 0 = none (0.0), 1 = mild (0.33), 2 = moderate (0.67), 3 = severe (1.0)
# Sensitive categories get ceiling = 0.0  (nothing tolerated above none)
# Non-sensitive categories get ceiling = 1.0 (anything goes)
SENSITIVE_CEILING    = 0.0    # hard floor: no content at all in flagged categories
NON_SENSITIVE_FLOOR  = 0.0    # movies with nothing score this on engagement

# ── Scoring weight constants ───────────────────────────────────
W_PROXIMITY   = 0.60   # how close to the comfort edge (the main signal)
W_ENGAGEMENT  = 0.40   # content richness in non-sensitive categories

# Group scoring
W_GROUP_PROXIMITY  = 0.65
W_GROUP_ENGAGEMENT = 0.35

# ── MMR diversity config (same as Nobby's engine) ─────────────
MMR_LAMBDA = 0.7
TOP_N_MIN  = 2
TOP_N_MAX  = 5

# ── Data quality ───────────────────────────────────────────────
DATA_COMPLETENESS_THRESHOLD = 0.5


# ── Math utilities ────────────────────────────────────────────

def _l2_normalize(v: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(v)
    return v / n if n > 1e-9 else np.zeros_like(v)


# ── Feature builders ──────────────────────────────────────────

def _movie_vector(warnings: Dict) -> np.ndarray:
    """
    Confidence-weighted severity vector, values in [0, 1].
    Missing confidence defaults to 1.0 (conservative).
    """
    v = np.zeros(N_CATS, dtype=float)
    for cat, idx in CAT_INDEX.items():
        w          = (warnings or {}).get(cat) or {}
        severity   = float(w.get("severity",   0))
        confidence = float(w.get("confidence", 1.0))
        v[idx]     = (severity / 3.0) * confidence
    return v


def _data_completeness(warnings: Dict) -> float:
    if not warnings:
        return 0.0
    present = sum(
        1 for cat in CATEGORIES
        if (warnings.get(cat) or {}).get("severity") is not None
    )
    return present / N_CATS


def _completeness_penalty(completeness: float) -> float:
    if completeness >= DATA_COMPLETENESS_THRESHOLD:
        return 1.0
    floor = 0.6
    return floor + (1.0 - floor) * (completeness / DATA_COMPLETENESS_THRESHOLD)


def _sensitivity_mask(sensitivities: List[str]) -> np.ndarray:
    """Boolean mask: True for each category the user is sensitive to."""
    mask = np.zeros(N_CATS, dtype=bool)
    for cat in (sensitivities or []):
        if cat in CAT_INDEX:
            mask[CAT_INDEX[cat]] = True
    return mask


# ── Core scoring ──────────────────────────────────────────────

def _hard_exclude(movie_vec: np.ndarray, sensitive_mask: np.ndarray) -> bool:
    """
    Returns True if the movie should be excluded entirely.
    A movie is excluded if ANY sensitive category has non-zero severity
    (i.e. anything above 'None').
    """
    return bool(np.any(movie_vec[sensitive_mask] > SENSITIVE_CEILING))


def _proximity_score(
    movie_vec:      np.ndarray,
    sensitive_mask: np.ndarray,
) -> float:
    """
    0–100. Measures how close the movie sits to the comfort boundary
    across NON-sensitive categories.

    For each non-sensitive category:
      - A movie at 100% severity scores 100 (maximally engaging)
      - A movie at 0% severity scores 0 (nothing there)
      - Linear interpolation between

    The result is the mean across non-sensitive categories.
    Movies that have already passed hard exclusion have 0 in sensitive dims,
    so we only look at non-sensitive dims here.

    If the user has no non-sensitive categories (all 9 flagged), returns
    100.0 — the movie passed hard exclusion, which is the only bar that matters.
    """
    non_sensitive = ~sensitive_mask
    if not np.any(non_sensitive):
        return 100.0
    scores = movie_vec[non_sensitive]  # values in [0, 1]
    return round(float(np.mean(scores)) * 100.0, 1)


def _engagement_score(
    movie_vec:      np.ndarray,
    sensitive_mask: np.ndarray,
) -> float:
    """
    0–100 content richness score across non-sensitive categories.

    Similar to proximity but uses a non-linear curve that rewards
    moderate content more than extreme content — a movie that has
    moderate language and mild violence (for a user not sensitive to either)
    scores higher than one that goes all the way to maximum severity,
    which may feel gratuitous even if technically tolerated.

    Curve: score = 1 - (severity - 0.6)^2 / 0.36  for severity > 0.6
                   severity / 0.6                   for severity <= 0.6
    Peak at severity = 0.6 (moderate, normalised).
    """
    non_sensitive = ~sensitive_mask
    if not np.any(non_sensitive):
        return 100.0

    scores = np.zeros(int(np.sum(non_sensitive)), dtype=float)
    for i, sev in enumerate(movie_vec[non_sensitive]):
        if sev <= 0.6:
            scores[i] = sev / 0.6          # rises linearly to 1.0 at sev=0.6
        else:
            scores[i] = 1.0 - ((sev - 0.6) ** 2) / 0.36   # drops off above 0.6

    return round(float(np.mean(scores)) * 100.0, 1)


# ── Human-readable helpers ────────────────────────────────────

def _comfort_note(
    movie_vec:      np.ndarray,
    sensitive_mask: np.ndarray,
) -> str:
    """Short human-readable explanation of why a movie scored as it did."""
    non_sensitive = ~sensitive_mask
    active_non_sensitive = [
        CATEGORIES[i].replace("_", " ")
        for i in range(N_CATS)
        if non_sensitive[i] and movie_vec[i] > 0.1
    ]
    if not active_non_sensitive:
        return "Very clean film — minimal content across all categories"
    if len(active_non_sensitive) == 1:
        return f"Engages with {active_non_sensitive[0]} within your comfort range"
    return f"Rich content in: {', '.join(active_non_sensitive[:3])}"


def _confidence_label(score: float, completeness: float) -> str:
    base = "Recommended" if score >= 75 else "Use your judgement" if score >= 50 else "Proceed with caution"
    if completeness < DATA_COMPLETENESS_THRESHOLD:
        base += " (limited warning data)"
    return base


# ── MMR diversity pass (warning-vector only, no genres) ───────

def _mmr_select(
    scored:     List[Dict],
    movie_vecs: Dict[int, np.ndarray],
    top_n:      int,
    score_key:  str   = "final_score",
    lam:        float = MMR_LAMBDA,
) -> List[Dict]:
    """
    Max-Marginal-Relevance greedy selection using warning vectors only.
    Genres are intentionally excluded — diversity is measured by content
    profile, not by genre label.
    """
    if not scored:
        return []

    n = min(max(min(top_n, TOP_N_MAX), TOP_N_MIN), len(scored))

    norm_vecs: Dict[int, np.ndarray] = {
        tid: _l2_normalize(v) for tid, v in movie_vecs.items()
    }
    _zero_vec = (
        np.zeros_like(next(iter(norm_vecs.values())))
        if norm_vecs else np.zeros(N_CATS)
    )

    remaining: set              = set(range(len(scored)))
    selected:  List[Dict]       = []
    sel_norms: List[np.ndarray] = []

    seed_tid = scored[0]["tmdb_id"]
    selected.append(scored[0])
    sel_norms.append(norm_vecs.get(seed_tid, _zero_vec))
    remaining.discard(0)

    while len(selected) < n and remaining:
        best_idx: Optional[int] = None
        best_val: float         = -float("inf")
        best_tid: float         = float("inf")

        for idx in remaining:
            item      = scored[idx]
            tid       = item["tmdb_id"]
            rel_score = float(item.get(score_key) or 0.0) / 100.0

            if tid in norm_vecs and sel_norms:
                iv      = norm_vecs[tid]
                max_sim = max(float(np.dot(iv, sv)) for sv in sel_norms)
            else:
                max_sim = 0.0

            mmr_val = lam * rel_score - (1.0 - lam) * max_sim
            if mmr_val > best_val or (mmr_val == best_val and tid < best_tid):
                best_val, best_idx, best_tid = mmr_val, idx, tid

        if best_idx is not None:
            remaining.discard(best_idx)
            selected.append(scored[best_idx])
            sel_tid = scored[best_idx]["tmdb_id"]
            sel_norms.append(norm_vecs.get(sel_tid, _zero_vec))
        else:
            break

    return selected


# ── Public API ────────────────────────────────────────────────

def comfort_find_movies(
    candidates:         List[Dict],
    user_sensitivities: List[str],
    top_n:              int = 5,
    apply_mmr:          bool = True,
) -> List[Dict]:
    """
    Comfort Distance ranker for /api/discover (alternative to recommend_find_movies).

    Steps:
      1. Hard-exclude any movie with non-zero severity in a sensitive category.
      2. Score remaining movies on proximity + engagement within comfort space.
      3. Apply data completeness penalty.
      4. MMR diversity pass (warning vectors only) — set apply_mmr=False to
         return every survivor sorted by final_score so a downstream step
         (e.g. mood blending in /api/discover) can re-rank the full pool.

    Each candidate dict must have:
      tmdb_id, title, warnings (dict keyed by category),
      year (optional), poster (optional).

    Returns up to top_n dicts with comfort scoring fields.
    """
    if not candidates:
        return []

    sensitive_mask = _sensitivity_mask(user_sensitivities)

    results:    List[Dict]            = []
    movie_vecs: Dict[int, np.ndarray] = {}

    for c in candidates:
        warnings  = c.get("warnings", {})
        movie_vec = _movie_vector(warnings)

        # Step 1: hard exclusion
        if np.any(sensitive_mask) and _hard_exclude(movie_vec, sensitive_mask):
            continue

        comp      = _data_completeness(warnings)
        comp_mult = _completeness_penalty(comp)

        # Step 2: score within comfort space
        p_score = _proximity_score(movie_vec, sensitive_mask)
        e_score = _engagement_score(movie_vec, sensitive_mask)

        raw_final = p_score * W_PROXIMITY + e_score * W_ENGAGEMENT
        final     = round(raw_final * comp_mult, 1)

        movie_vecs[c["tmdb_id"]] = movie_vec   # warning dims only, no genres

        results.append({
            "tmdb_id":           c["tmdb_id"],
            "title":             c["title"],
            "year":              c.get("year", ""),
            "proximity_score":   p_score,
            "engagement_score":  e_score,
            "final_score":       final,
            "comfort_note":      _comfort_note(movie_vec, sensitive_mask),
            "watch_confidence":  _confidence_label(final, comp),
            "data_completeness": round(comp, 2),
            "poster":            c.get("poster"),
        })

    results.sort(key=lambda x: x["final_score"], reverse=True)
    if not apply_mmr:
        return results
    return _mmr_select(results, movie_vecs, top_n, score_key="final_score")


def comfort_group_movies(
    candidates:              List[Dict],
    logged_in_sensitivities: List[str],
    members_ordered:         List[Dict],   # [{"name": str, "sensitivities": [...]}]
    top_n:                   int = 5,
) -> List[Dict]:
    """
    Comfort Distance group ranker for /api/group/recommend.

    Hard exclusion is applied across ALL members — if any member's sensitive
    category appears in the movie at any severity, the movie is excluded.
    Remaining movies are scored per-member and aggregated equally.

    Each member dict: {"name": str, "sensitivities": List[str]}
    """
    if not candidates:
        return []

    # Build per-person sensitivity masks
    all_people: List[Tuple[str, np.ndarray]] = [
        ("you", _sensitivity_mask(logged_in_sensitivities))
    ] + [
        (m.get("name") or f"Member {i+1}", _sensitivity_mask(m.get("sensitivities") or []))
        for i, m in enumerate(members_ordered)
    ]

    # Union mask for hard exclusion: exclude if ANY person's sensitive category triggered
    union_mask = np.zeros(N_CATS, dtype=bool)
    for _, mask in all_people:
        union_mask |= mask

    results:    List[Dict]            = []
    movie_vecs: Dict[int, np.ndarray] = {}

    for c in candidates:
        warnings  = c.get("warnings", {})
        movie_vec = _movie_vector(warnings)

        # Hard exclusion across all members
        if np.any(union_mask) and _hard_exclude(movie_vec, union_mask):
            continue

        comp      = _data_completeness(warnings)
        comp_mult = _completeness_penalty(comp)

        # Per-member scores (each person's non-sensitive space may differ)
        per_member_scores = []
        for name, mask in all_people:
            p = _proximity_score(movie_vec, mask)
            e = _engagement_score(movie_vec, mask)
            score = round(p * W_GROUP_PROXIMITY + e * W_GROUP_ENGAGEMENT, 1)
            per_member_scores.append({"name": name, "comfort_score": score})

        # Equal-weight aggregate
        group_score = round(
            float(np.mean([m["comfort_score"] for m in per_member_scores])) * comp_mult, 1
        )

        movie_vecs[c["tmdb_id"]] = movie_vec

        results.append({
            "tmdb_id":           c["tmdb_id"],
            "title":             c["title"],
            "year":              c.get("year", ""),
            "group_score":       group_score,
            "member_scores":     per_member_scores,
            "comfort_note":      _comfort_note(movie_vec, union_mask),
            "watch_confidence":  _confidence_label(group_score, comp),
            "data_completeness": round(comp, 2),
            "poster":            c.get("poster"),
        })

    results.sort(key=lambda x: x["group_score"], reverse=True)
    return _mmr_select(results, movie_vecs, top_n, score_key="group_score")
