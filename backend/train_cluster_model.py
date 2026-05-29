#!/usr/bin/env python3
"""
Train the K-Means content-cluster model and populate movie_clusters.

Pulls every well-assessed film, fits K-Means (default K=5) on the 9-dim
warning severity vector, prints centroid profiles + cluster sizes, saves
the model to data/cluster_model.pkl, and writes cluster assignments to
the movie_clusters table.

Usage:
    python backend/train_cluster_model.py
    python backend/train_cluster_model.py --k 6
    python backend/train_cluster_model.py --dry-run   # train+report, don't write DB
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np  # noqa: E402

from backend.cluster_engine import (  # noqa: E402
    DEFAULT_K, MODEL_PATH_DEFAULT, WARNING_CATEGORIES,
    assign_clusters, extract_features, save_model, train_clusters,
)

DEFAULT_DB = os.environ.get("DB_PATH", "./data/movie_cache.db")


def _ensure_table(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS movie_clusters (
            tmdb_id INTEGER PRIMARY KEY,
            cluster_id INTEGER NOT NULL,
            distance_to_centroid REAL,
            model_version TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (tmdb_id) REFERENCES movies(tmdb_id) ON DELETE CASCADE
        )
    """)
    conn.commit()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db",  default=DEFAULT_DB)
    parser.add_argument("--out", default=MODEL_PATH_DEFAULT)
    parser.add_argument("--k", type=int, default=DEFAULT_K, help=f"Number of clusters (default {DEFAULT_K})")
    parser.add_argument("--random-state", type=int, default=42)
    parser.add_argument("--dry-run", action="store_true", help="Train and report but don't save model or write DB")
    args = parser.parse_args()

    print(f"Loading features from {args.db} …")
    X, ids = extract_features(args.db)
    print(f"  {len(ids)} well-assessed films, {X.shape[1]}-dim warning vector\n")

    print(f"Training K-Means with K={args.k} …")
    model = train_clusters(X, n_clusters=args.k, random_state=args.random_state)
    cluster_ids, dists = assign_clusters(model, X)

    print(f"Cluster summary:\n")
    centroids = model.kmeans.cluster_centers_
    for c in range(args.k):
        mask = (cluster_ids == c)
        size = int(np.sum(mask))
        avg_dist = float(np.mean(dists[mask])) if size else 0.0
        name = model.cluster_names.get(c, f"Cluster {c}")
        print(f"  Cluster {c} ({name})  size={size}  avg_dist={avg_dist:.2f}")
        # Centroid profile (rounded severities)
        for i, cat in enumerate(WARNING_CATEGORIES):
            v = centroids[c, i]
            bar = "█" * int(round(v * 4))
            print(f"    {cat:<30} {v:.2f}  {bar}")
        print()

    if args.dry_run:
        print("[dry-run] not saving model or writing DB")
        return

    save_model(model, args.out)
    print(f"Saved model -> {args.out}")

    model_version = f"kmeans_k{args.k}_seed{args.random_state}"
    conn = sqlite3.connect(args.db)
    _ensure_table(conn)
    now = datetime.now().isoformat()
    conn.executemany(
        "INSERT OR REPLACE INTO movie_clusters VALUES (?,?,?,?,?)",
        [
            (int(tmdb_id), int(cid), float(d), model_version, now)
            for tmdb_id, cid, d in zip(ids, cluster_ids, dists)
        ],
    )
    conn.commit()
    conn.close()
    print(f"Wrote {len(ids)} rows to movie_clusters (model_version={model_version})")


if __name__ == "__main__":
    main()
