#!/usr/bin/env python3
"""
One-shot backfill: walks every row in `movies`, computes the sentence-transformer
embedding for its overview + keywords + genres, and stores it in `movie_embeddings`.

Idempotent. Skips a movie if its current text_hash matches what's already stored
for the same model. Re-running after adding new films only embeds the newcomers.

Usage:
    python backend/embed_all_movies.py
    python backend/embed_all_movies.py --force          # re-embed everything
    python backend/embed_all_movies.py --limit 50       # stop after 50 movies
    python backend/embed_all_movies.py --batch-size 16  # tune for memory
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.embeddings import (  # noqa: E402
    MODEL_NAME,
    embed_texts,
    movie_text,
    text_hash,
    vec_to_bytes,
)

DEFAULT_DB = os.environ.get("DB_PATH", "./data/movie_cache.db")


def _connect(db_path: str) -> sqlite3.Connection:
    if not Path(db_path).exists():
        sys.exit(f"ERROR: database not found at {db_path}")
    return sqlite3.connect(db_path)


def _ensure_table(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS movie_embeddings (
            tmdb_id    INTEGER PRIMARY KEY,
            embedding  BLOB    NOT NULL,
            model_name TEXT    NOT NULL,
            text_hash  TEXT    NOT NULL,
            created_at TEXT    NOT NULL,
            FOREIGN KEY (tmdb_id) REFERENCES movies(tmdb_id) ON DELETE CASCADE
        )
    """)
    conn.commit()


def _movies_to_embed(conn: sqlite3.Connection, force: bool) -> list[tuple[int, str]]:
    """
    Returns [(tmdb_id, text_to_embed), ...] for movies that need (re-)embedding.
    Skips rows whose stored text_hash already matches (unless --force).
    """
    rows = conn.execute(
        "SELECT m.tmdb_id, m.metadata_json, e.text_hash, e.model_name "
        "FROM movies m LEFT JOIN movie_embeddings e ON m.tmdb_id = e.tmdb_id"
    ).fetchall()
    out: list[tuple[int, str]] = []
    for tmdb_id, metadata_json, stored_hash, stored_model in rows:
        try:
            metadata = json.loads(metadata_json) if metadata_json else {}
        except json.JSONDecodeError:
            continue
        text = movie_text(metadata)
        if not text.strip():
            continue
        if not force and stored_hash == text_hash(text) and stored_model == MODEL_NAME:
            continue
        out.append((tmdb_id, text))
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=DEFAULT_DB, help=f"SQLite path (default: {DEFAULT_DB})")
    parser.add_argument("--force", action="store_true", help="Re-embed every movie")
    parser.add_argument("--limit", type=int, help="Stop after N movies")
    parser.add_argument("--batch-size", type=int, default=32)
    args = parser.parse_args()

    conn = _connect(args.db)
    _ensure_table(conn)

    todo = _movies_to_embed(conn, args.force)
    if args.limit:
        todo = todo[: args.limit]

    if not todo:
        print("Nothing to embed — every movie is up to date for this model.")
        return

    print(f"Embedding {len(todo)} movies using {MODEL_NAME}…")
    t0 = time.time()
    for start in range(0, len(todo), args.batch_size):
        batch = todo[start : start + args.batch_size]
        texts = [t for _, t in batch]
        vecs = embed_texts(texts)
        now = datetime.now().isoformat()
        conn.executemany(
            "INSERT OR REPLACE INTO movie_embeddings VALUES (?,?,?,?,?)",
            [
                (tmdb_id, vec_to_bytes(vec), MODEL_NAME, text_hash(text), now)
                for (tmdb_id, text), vec in zip(batch, vecs)
            ],
        )
        conn.commit()
        done = min(start + args.batch_size, len(todo))
        print(f"  {done}/{len(todo)}  ({done / (time.time() - t0):.1f} movies/sec)")

    conn.close()
    print(f"Done in {time.time() - t0:.1f}s.")


if __name__ == "__main__":
    main()
