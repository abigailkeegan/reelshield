#!/usr/bin/env python3
"""
Compute the quantified before/after evaluation metrics reported in
docs/app-analysis.md § 7.2.

The four metric sections are deliberately mixed: two of them evaluate
classic-ML models the project trained (the MPA-rating logistic-regression
classifier and the K-Means content-twins clusterer), and two measure
non-ML changes (the lift from re-ranking with pretrained sentence-
transformer embeddings, and the recovery rate of the `--fix-ghosts`
data-quality CLI). The filename predates a precision pass on the word
"ML" and is kept for compatibility with the doc references already
pointing at it.

Run from the repo root with the project's data/movie_cache.db present:

    python data-engineering/compute_ml_metrics.py

Produces a plain-text report on stdout. The numbers in app-analysis.md
were captured from one run of this script against the live cache; new
runs will track the cache as it grows.
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import numpy as np

# Make 'backend.*' imports resolve when the script is run from repo root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

DB = "data/movie_cache.db"


def section(n: int, title: str) -> None:
    print()
    print(f"## {n}. {title}")
    print()


def cosine(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-9))


def euclidean(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.linalg.norm(a - b))


def main() -> None:
    print("=" * 70)
    print("REELSHIELD — QUANTIFIED EVALUATION METRICS")
    print("(two classic-ML models: MPA + K-Means;")
    print(" two non-ML measurements: embedding rerank, ghost recovery)")
    print("=" * 70)

    # ─── 1. --fix-ghosts recovery rate ───────────────────────────────
    section(1, "--fix-ghosts recovery rate")
    conn = sqlite3.connect(DB)
    rows = conn.execute("SELECT tmdb_id, warnings_json FROM content_warnings").fetchall()
    conn.close()

    ghosts = 0
    recovered_sevs: list[int] = []
    for _tid, wj in rows:
        try:
            w = json.loads(wj or "{}").get("spoiler_free", {})
        except json.JSONDecodeError:
            continue
        confs = [v.get("confidence", 0) for v in w.values()]
        sevs = [v.get("severity", 0) for v in w.values()]
        if not confs:
            continue
        if sum(confs) / len(confs) < 0.4:
            ghosts += 1
        else:
            recovered_sevs.append(sum(sevs))

    print(f"  Total cached films:                {len(rows)}")
    print(f"  Remaining low-confidence (ghosts): {ghosts}")
    print(f"  Recovered / well-assessed films:   {len(recovered_sevs)}")
    print(f"  Historical pre-fix-ghosts: 174 ghosts of ~395 cached")
    print(f"  Recovery rate (174 - {ghosts}) / 174 = {(174 - ghosts) / 174 * 100:.1f}%")
    print()
    print(f"  Severity distribution of recovered films (0..27 scale):")
    print(f"    mean   = {np.mean(recovered_sevs):.2f}")
    print(f"    median = {np.median(recovered_sevs):.0f}")
    print(f"    std    = {np.std(recovered_sevs):.2f}")

    # ─── 2. MPA classifier ───────────────────────────────────────────
    section(2, "MPA classifier: confusion matrix + per-class metrics")
    from sklearn.model_selection import train_test_split
    from sklearn.metrics import classification_report, confusion_matrix
    from backend.mpa_classifier import LABEL_NAMES, extract_training_data, train_model

    td = extract_training_data(DB)
    print(f"  Training samples: {len(td.y)}")
    print(
        f"  Class balance: family={int((td.y == 0).sum())}, "
        f"teen={int((td.y == 1).sum())}, adult={int((td.y == 2).sum())}"
    )

    X_train, X_test, y_train, y_test = train_test_split(
        td.X, td.y, test_size=0.2, random_state=42, stratify=td.y
    )
    model = train_model(X_train, y_train)
    y_pred = model.predict(X_test)
    y_proba = model.predict_proba(X_test)

    cm = confusion_matrix(y_test, y_pred)
    print(f"\n  Held-out test set: {len(y_test)} films")
    print(f"\n  Confusion matrix (rows=actual, cols=predicted):")
    print(f"           pred:family teen adult")
    for i, name in enumerate(LABEL_NAMES):
        print(f"  actual:{name:6s} {cm[i][0]:6d} {cm[i][1]:4d} {cm[i][2]:5d}")
    print()
    print(classification_report(y_test, y_pred, target_names=LABEL_NAMES, digits=3, zero_division=0))

    # Badge-surfacing rate: filter on the 70% confidence + disagreement gate.
    n_surfaced = 0
    for i in range(len(y_test)):
        pred_idx = int(y_pred[i])
        actual_idx = int(y_test[i])
        conf = float(y_proba[i][pred_idx])
        if conf >= 0.70 and pred_idx != actual_idx:
            n_surfaced += 1
    print(f"  Badge would surface on {n_surfaced} / {len(y_test)} test films "
          f"({n_surfaced / len(y_test) * 100:.1f}%)")

    # ─── 3. K-Means clustering ───────────────────────────────────────
    section(3, "K-Means clustering: cluster quality")
    from sklearn.metrics import silhouette_score
    from backend.cluster_engine import assign_clusters, extract_features, train_clusters

    X, ids = extract_features(DB)
    km = train_clusters(X, n_clusters=5, random_state=42)
    labels, dists = assign_clusters(km, X)

    print(f"  Films clustered: {len(ids)}")
    print(f"  Silhouette score: {silhouette_score(X, labels):.3f}  "
          f"(higher is better; >0.25 typically meaningful for low-dim data)")
    print()
    print(f"  Per-cluster sizes + avg within-cluster distance:")
    for c in range(5):
        mask = labels == c
        size = int(mask.sum())
        avg_d = float(dists[mask].mean()) if size else 0.0
        name = km.cluster_names.get(c, f"Cluster {c}")
        print(f"    cluster {c} ({name:38s}) size={size:3d}  avg_dist={avg_d:.2f}")

    centroids = km.kmeans.cluster_centers_
    within = float(np.mean(dists))
    between = float(np.mean([
        np.linalg.norm(centroids[i] - centroids[j])
        for i in range(5)
        for j in range(i + 1, 5)
    ]))
    print()
    print(f"  mean within-cluster:   {within:.2f}")
    print(f"  mean between-centroid: {between:.2f}")
    print(f"  ratio (within/between, lower=tighter): {within / between:.2f}")

    # ─── 4. Embedding re-ranking: semantic-similarity lift ───────────
    section(4, "Sentence-transformer embeddings: semantic-similarity vs baseline")
    conn = sqlite3.connect(DB)
    emb_rows = conn.execute("SELECT tmdb_id, embedding FROM movie_embeddings").fetchall()
    warn_rows = conn.execute("SELECT tmdb_id, warnings_json FROM content_warnings").fetchall()
    conn.close()

    emb_map = {tid: np.frombuffer(emb, dtype=np.float32) for tid, emb in emb_rows}
    warn_vecs: dict[int, np.ndarray] = {}
    for tid, wj in warn_rows:
        try:
            w = json.loads(wj or "{}").get("spoiler_free", {})
        except json.JSONDecodeError:
            continue
        confs = [v.get("confidence", 0) for v in w.values()]
        if not confs or sum(confs) / len(confs) < 0.4:
            continue
        sevs = np.array([v.get("severity", 0) for v in w.values()], dtype=float)
        warn_vecs[tid] = sevs

    anchors = [t for t in emb_map if t in warn_vecs][:50]
    warn_only_sim: list[float] = []
    emb_rerank_sim: list[float] = []
    for src in anchors:
        src_emb = emb_map[src]
        src_warn = warn_vecs[src]
        others = [t for t in warn_vecs if t != src and t in emb_map]
        by_warn = sorted(others, key=lambda t: euclidean(src_warn, warn_vecs[t]))[:5]
        by_emb = sorted(others, key=lambda t: -cosine(src_emb, emb_map[t]))[:5]
        warn_only_sim.append(float(np.mean([cosine(src_emb, emb_map[t]) for t in by_warn])))
        emb_rerank_sim.append(float(np.mean([cosine(src_emb, emb_map[t]) for t in by_emb])))

    print(f"  Sampled {len(anchors)} anchor films")
    print(f"  Comfort-distance only: mean cosine = {np.mean(warn_only_sim):.3f}, "
          f"median = {np.median(warn_only_sim):.3f}")
    print(f"  Embedding re-ranking:  mean cosine = {np.mean(emb_rerank_sim):.3f}, "
          f"median = {np.median(emb_rerank_sim):.3f}")
    lift_abs = float(np.mean(emb_rerank_sim) - np.mean(warn_only_sim))
    lift_rel = float(np.mean(emb_rerank_sim) / np.mean(warn_only_sim) - 1)
    print(f"  Lift: +{lift_abs * 100:.1f} pp absolute, +{lift_rel * 100:.1f}% relative")


if __name__ == "__main__":
    main()
