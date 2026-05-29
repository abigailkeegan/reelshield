"""
ReelShield semantic embeddings layer.

Wraps a sentence-transformers model (all-MiniLM-L6-v2, 384-dim) and provides
embed_text(), embed_movie(), and cosine_top_k() helpers used by:
  - /api/recommendations/<tmdb_id>  (rank similar films by overview semantics)
  - /api/discover                   (match user mood phrase to film overviews)
  - backend/embed_all_movies.py     (offline backfill over the cached library)

Model loading is lazy — the 80 MB MiniLM weights only download on first use,
not at app startup. This keeps cold-start fast for routes that don't touch
embeddings.
"""

from __future__ import annotations

import hashlib
from typing import Iterable, List, Sequence, Tuple

import numpy as np

MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
EMBED_DIM = 384

_model = None


def _get_model():
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer(MODEL_NAME)
    return _model


def embed_text(text: str) -> np.ndarray:
    """One sentence/paragraph in, one normalized 384-dim float32 vector out."""
    if not text or not text.strip():
        return np.zeros(EMBED_DIM, dtype=np.float32)
    vec = _get_model().encode(text, normalize_embeddings=True, show_progress_bar=False)
    return np.asarray(vec, dtype=np.float32)


def embed_texts(texts: Sequence[str]) -> np.ndarray:
    """Batched encode — used by the offline backfill."""
    if not texts:
        return np.zeros((0, EMBED_DIM), dtype=np.float32)
    vecs = _get_model().encode(
        list(texts),
        normalize_embeddings=True,
        show_progress_bar=False,
        batch_size=32,
    )
    return np.asarray(vecs, dtype=np.float32)


def movie_text(metadata: dict) -> str:
    """
    Build the text we embed for a movie. Concatenates the fields most likely
    to carry semantic signal (overview + keywords + genres). Order matters
    less for transformer embeddings than for bag-of-words, but front-loading
    the overview improves retrieval slightly in our tests.
    """
    overview = (metadata.get("overview") or "").strip()
    keywords = metadata.get("keywords") or []
    genres = metadata.get("genres") or []
    parts = [overview]
    if keywords:
        parts.append("Keywords: " + ", ".join(keywords))
    if genres:
        parts.append("Genres: " + ", ".join(genres))
    return " ".join(p for p in parts if p)


def text_hash(text: str) -> str:
    """Short hash used to detect when source text changed and re-embedding is needed."""
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]


def cosine_top_k(
    query: np.ndarray,
    candidates: Iterable[Tuple[int, np.ndarray]],
    k: int = 10,
    exclude_ids: set | None = None,
) -> List[Tuple[int, float]]:
    """
    Rank (id, embedding) candidates by cosine similarity to `query`.
    Both inputs assumed L2-normalized (sentence-transformers does this for us
    when normalize_embeddings=True), so cosine == dot product.

    Returns [(id, similarity), ...] sorted descending, length up to k.
    """
    exclude_ids = exclude_ids or set()
    scored: List[Tuple[int, float]] = []
    for cid, vec in candidates:
        if cid in exclude_ids:
            continue
        sim = float(np.dot(query, vec))
        scored.append((cid, sim))
    scored.sort(key=lambda t: t[1], reverse=True)
    return scored[:k]


def bytes_to_vec(blob: bytes) -> np.ndarray:
    return np.frombuffer(blob, dtype=np.float32)


def vec_to_bytes(vec: np.ndarray) -> bytes:
    return np.asarray(vec, dtype=np.float32).tobytes()
