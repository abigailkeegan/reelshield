"""
ReelShield content-cluster engine.

K-Means over the 9-dim warning severity vector. Films in the same cluster
share a "content profile" — similar mix of violence, language, sexual
content, etc. — independent of theme or plot.

This complements the sentence-transformer "similar films" feature:
  - Embeddings cluster films by *what they're about* (Inception ↔ The Matrix)
  - K-Means clusters films by *what's in them* (Inception ↔ another
    moderate-violence sci-fi thriller with similar warning profile)

Used by /api/content_twins/<tmdb_id> to return films in the same cluster,
ranked by squared distance to the source film in warning space.
"""

from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import dataclass

import numpy as np

WARNING_CATEGORIES = [
    "violence_gore", "self_harm_suicide",
    "miscarriage_pregnancy_loss", "sexual_content_nudity",
    "animal_abuse", "substances", "language",
    "horror_intensity", "flashing_lights",
]

DEFAULT_K = 5
GHOST_CONFIDENCE_FLOOR = 0.4
MODEL_PATH_DEFAULT = os.environ.get("CLUSTER_MODEL_PATH", "/data/cluster_model.pkl")

# Human-readable archetype names. We assign them in severity-rank order so
# every cluster ends up with a distinct label and the spectrum is intuitive
# even when the underlying centroid argmax collides (e.g. two clusters with
# violence_gore as their dominant feature). Lowest total severity = index 0.
SEVERITY_RANKED_LABELS_K5 = [
    "Family-safe / low-content",
    "Moderate action & intensity",
    "Adult drama",
    "Intense action & horror",
    "Heavy mature content",
]


@dataclass
class ClusterModel:
    kmeans:        object              # sklearn KMeans
    n_clusters:    int
    cluster_names: dict[int, str]      # cluster_id -> human label
    feature_names: list[str]


def _film_warning_vector(warnings_json: dict) -> tuple[np.ndarray, float]:
    """Return (9-dim severity vector, avg_confidence) for a film."""
    sf = warnings_json.get("spoiler_free") or {}
    sevs = np.zeros(9, dtype=np.float32)
    confs = np.zeros(9, dtype=np.float32)
    for i, cat in enumerate(WARNING_CATEGORIES):
        d = sf.get(cat) or {}
        sevs[i] = float(d.get("severity") or 0)
        confs[i] = float(d.get("confidence") or 0.0)
    return sevs, float(np.mean(confs))


def extract_features(db_path: str) -> tuple[np.ndarray, list[int]]:
    """Pull (severity_matrix, tmdb_ids) for every well-assessed film."""
    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        "SELECT m.tmdb_id, cw.warnings_json "
        "FROM movies m JOIN content_warnings cw USING(tmdb_id)"
    ).fetchall()
    conn.close()
    X, ids = [], []
    for tmdb_id, wj in rows:
        try:
            w = json.loads(wj or "{}")
        except json.JSONDecodeError:
            continue
        vec, avg_conf = _film_warning_vector(w)
        if avg_conf < GHOST_CONFIDENCE_FLOOR:
            continue
        X.append(vec)
        ids.append(tmdb_id)
    if not X:
        raise RuntimeError("No well-assessed films to cluster.")
    return np.vstack(X), ids


def _label_clusters(centroids: np.ndarray) -> dict[int, str]:
    """Assign human-readable archetype names by severity rank — lowest-total
    cluster gets the first label, highest-total gets the last. Guarantees
    distinct labels and a coherent spectrum across the cluster set."""
    totals = centroids.sum(axis=1)
    severity_rank = np.argsort(totals)  # ascending
    n = len(severity_rank)
    if n == len(SEVERITY_RANKED_LABELS_K5):
        labels = SEVERITY_RANKED_LABELS_K5
    else:
        # Generic fallback for K != 5
        labels = [f"Tier {i + 1}" for i in range(n)]
    return {int(severity_rank[i]): labels[i] for i in range(n)}


def train_clusters(X: np.ndarray, n_clusters: int = DEFAULT_K, random_state: int = 42) -> ClusterModel:
    from sklearn.cluster import KMeans
    km = KMeans(n_clusters=n_clusters, random_state=random_state, n_init=10)
    km.fit(X)
    return ClusterModel(
        kmeans=km,
        n_clusters=n_clusters,
        cluster_names=_label_clusters(km.cluster_centers_),
        feature_names=list(WARNING_CATEGORIES),
    )


def assign_clusters(model: ClusterModel, X: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Return (cluster_ids, distance_to_centroid) for each film in X."""
    km = model.kmeans
    cluster_ids = km.predict(X)
    centroids   = km.cluster_centers_
    # Euclidean distance to each film's assigned centroid
    dists = np.linalg.norm(X - centroids[cluster_ids], axis=1)
    return cluster_ids, dists


def save_model(model: ClusterModel, path: str = MODEL_PATH_DEFAULT) -> None:
    import joblib
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    joblib.dump(
        {
            "kmeans":        model.kmeans,
            "n_clusters":    model.n_clusters,
            "cluster_names": model.cluster_names,
            "feature_names": model.feature_names,
        },
        path,
    )


def load_model(path: str = MODEL_PATH_DEFAULT) -> ClusterModel | None:
    import joblib
    if not os.path.exists(path):
        return None
    b = joblib.load(path)
    return ClusterModel(**b)


def find_twins(
    db_path:     str,
    tmdb_id:     int,
    top_k:       int = 8,
) -> list[dict]:
    """Return up to top_k films in the same cluster as `tmdb_id`, ranked by
    Euclidean distance in warning-vector space. Source film is excluded.

    Each entry: {tmdb_id, title, year, poster, distance, cluster_id, cluster_name}.
    """
    conn = sqlite3.connect(db_path)
    src_row = conn.execute(
        "SELECT cluster_id FROM movie_clusters WHERE tmdb_id=?", (tmdb_id,)
    ).fetchone()
    if not src_row:
        conn.close()
        return []
    src_cluster = int(src_row[0])

    # Source film's warning vector
    src_warn_row = conn.execute(
        "SELECT warnings_json FROM content_warnings WHERE tmdb_id=?", (tmdb_id,)
    ).fetchone()
    if not src_warn_row:
        conn.close()
        return []
    src_vec, _ = _film_warning_vector(json.loads(src_warn_row[0]))

    # All other films in the same cluster
    rows = conn.execute(
        """SELECT m.tmdb_id, m.title, m.year, m.metadata_json, cw.warnings_json
           FROM movie_clusters mc
           JOIN movies m ON mc.tmdb_id = m.tmdb_id
           JOIN content_warnings cw ON mc.tmdb_id = cw.tmdb_id
           WHERE mc.cluster_id = ? AND mc.tmdb_id != ?""",
        (src_cluster, tmdb_id),
    ).fetchall()
    conn.close()

    out = []
    for tid, title, year, mj, wj in rows:
        try:
            m = json.loads(mj or "{}")
            w = json.loads(wj or "{}")
        except json.JSONDecodeError:
            continue
        vec, _ = _film_warning_vector(w)
        d = float(np.linalg.norm(vec - src_vec))
        out.append({
            "tmdb_id":  tid,
            "title":    title,
            "year":     year,
            "poster":   (
                f"https://image.tmdb.org/t/p/w200{m['poster_path']}"
                if m.get("poster_path") else None
            ),
            "distance": round(d, 3),
            "cluster_id":   src_cluster,
        })
    out.sort(key=lambda d: d["distance"])
    return out[:top_k]


def get_cluster_name(db_path: str, tmdb_id: int) -> tuple[int, str] | None:
    """Return (cluster_id, cluster_name) for a film, or None if unassigned."""
    model = load_model()
    if model is None:
        return None
    conn = sqlite3.connect(db_path)
    row = conn.execute(
        "SELECT cluster_id FROM movie_clusters WHERE tmdb_id=?", (tmdb_id,)
    ).fetchone()
    conn.close()
    if not row:
        return None
    cid = int(row[0])
    return cid, model.cluster_names.get(cid, f"Cluster {cid}")
