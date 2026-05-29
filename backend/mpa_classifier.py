"""
ReelShield MPA-rating classifier.

A multinomial logistic regression that predicts a film's MPA rating bucket
from its Gemini-generated warning vector. Trained on the cached movies that
have both a stored us_certification and an avg-confidence above the ghost
threshold.

Two uses:
  1. Sanity check on Gemini outputs. When predict_one(film) disagrees with
     the stored us_certification, the film is flagged for re-assessment —
     Gemini probably under- or over-reported severity somewhere.
  2. Real-ML defensibility. Unlike the sentence-transformer (which is a
     pretrained black box used zero-shot), this model has its own train/test
     split, learned coefficients, and reported metrics — i.e. classic ML.

Categories (the 9-dim warning vector):
    violence_gore, self_harm_suicide, miscarriage_pregnancy_loss,
    sexual_content_nudity, animal_abuse, substances, language,
    horror_intensity, flashing_lights

Feature vector per film (19 dimensions):
    [severity_0..severity_8, confidence_0..confidence_8, year_normalized]

Label buckets:
    0 = family    (G, PG)
    1 = teen      (PG-13)
    2 = adult     (R, NC-17)
NR and empty MPA fields are dropped.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Iterable, Sequence

import numpy as np

# Lazy-imported sklearn / joblib so importing this module is cheap until you
# actually train or predict.

WARNING_CATEGORIES = [
    "violence_gore", "self_harm_suicide",
    "miscarriage_pregnancy_loss", "sexual_content_nudity",
    "animal_abuse", "substances", "language",
    "horror_intensity", "flashing_lights",
]

LABEL_NAMES = ["family", "teen", "adult"]
CERT_TO_LABEL = {
    "G": 0, "PG": 0,
    "PG-13": 1,
    "R": 2, "NC-17": 2,
}
GHOST_CONFIDENCE_FLOOR = 0.4

MODEL_PATH_DEFAULT = os.environ.get("MPA_MODEL_PATH", "/data/mpa_classifier.pkl")


@dataclass
class TrainingData:
    X: np.ndarray            # shape (n_samples, 19)
    y: np.ndarray            # shape (n_samples,)
    tmdb_ids: list[int]
    feature_names: list[str]


def _year_norm(year_str: str | None) -> float:
    """Map a 4-digit year string to a [0, 1] feature.
    Roughly: 1920 -> 0.0, 2025 -> 1.0. Out-of-range or empty -> 0.5."""
    try:
        y = int(str(year_str or "")[:4])
    except (ValueError, TypeError):
        return 0.5
    if y < 1920 or y > 2025:
        return 0.5
    return (y - 1920) / (2025 - 1920)


def _film_features(warnings_json: dict, year: str | None) -> tuple[np.ndarray, float]:
    """Return (feature_vector_19d, avg_confidence)."""
    sf = warnings_json.get("spoiler_free") or {}
    sevs = np.zeros(9, dtype=np.float32)
    confs = np.zeros(9, dtype=np.float32)
    for i, cat in enumerate(WARNING_CATEGORIES):
        d = sf.get(cat) or {}
        sevs[i] = float(d.get("severity") or 0)
        confs[i] = float(d.get("confidence") or 0.0)
    avg_conf = float(np.mean(confs)) if confs.size else 0.0
    yn = _year_norm(year)
    vec = np.concatenate([sevs, confs, np.array([yn], dtype=np.float32)])
    return vec, avg_conf


def feature_names() -> list[str]:
    sev_names = [f"sev_{c}" for c in WARNING_CATEGORIES]
    conf_names = [f"conf_{c}" for c in WARNING_CATEGORIES]
    return sev_names + conf_names + ["year_norm"]


def extract_training_data(db_path: str) -> TrainingData:
    """Pull all films whose MPA rating maps to a label AND whose avg
    confidence is above the ghost floor. Returns aligned arrays."""
    import sqlite3
    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        "SELECT m.tmdb_id, m.year, m.metadata_json, cw.warnings_json "
        "FROM movies m JOIN content_warnings cw USING(tmdb_id)"
    ).fetchall()
    conn.close()

    X_list: list[np.ndarray] = []
    y_list: list[int] = []
    ids: list[int] = []
    for tmdb_id, year, mj, wj in rows:
        try:
            meta = json.loads(mj or "{}")
            warn = json.loads(wj or "{}")
        except json.JSONDecodeError:
            continue
        cert = (meta.get("us_certification") or "").strip().upper()
        if cert not in CERT_TO_LABEL:
            continue
        feat, avg_conf = _film_features(warn, year)
        if avg_conf < GHOST_CONFIDENCE_FLOOR:
            continue
        X_list.append(feat)
        y_list.append(CERT_TO_LABEL[cert])
        ids.append(tmdb_id)

    if not X_list:
        raise RuntimeError("No labelable films found — check cache + confidence floor.")
    return TrainingData(
        X=np.vstack(X_list),
        y=np.array(y_list, dtype=np.int64),
        tmdb_ids=ids,
        feature_names=feature_names(),
    )


def train_model(X: np.ndarray, y: np.ndarray, random_state: int = 42):
    """Fit a multinomial LogisticRegression. Uses class_weight='balanced'
    so the relative class sizes (R-rated tends to dominate) don't bias
    the decision boundary."""
    from sklearn.linear_model import LogisticRegression
    # sklearn >= 1.7 dropped the multi_class kwarg; lbfgs auto-detects
    # multinomial when there are >2 classes.
    model = LogisticRegression(
        solver="lbfgs",
        class_weight="balanced",
        C=1.0,
        max_iter=1000,
        random_state=random_state,
    )
    model.fit(X, y)
    return model


def evaluate(model, X_test: np.ndarray, y_test: np.ndarray) -> dict:
    from sklearn.metrics import (
        accuracy_score, classification_report, confusion_matrix, f1_score,
    )
    y_pred = model.predict(X_test)
    return {
        "accuracy":      float(accuracy_score(y_test, y_pred)),
        "macro_f1":      float(f1_score(y_test, y_pred, average="macro")),
        "weighted_f1":   float(f1_score(y_test, y_pred, average="weighted")),
        "report":        classification_report(y_test, y_pred, target_names=LABEL_NAMES, digits=3),
        "confusion":     confusion_matrix(y_test, y_pred).tolist(),
    }


def save_model(model, path: str = MODEL_PATH_DEFAULT) -> None:
    import joblib
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    joblib.dump({"model": model, "feature_names": feature_names()}, path)


def load_model(path: str = MODEL_PATH_DEFAULT):
    """Returns (model, feature_names) or None if no model on disk."""
    import joblib
    if not os.path.exists(path):
        return None
    bundle = joblib.load(path)
    return bundle["model"], bundle["feature_names"]


def predict_one(model, warnings_json: dict, year: str | None) -> dict:
    """Predict label + probabilities for a single film."""
    feat, _ = _film_features(warnings_json, year)
    pred_idx = int(model.predict(feat.reshape(1, -1))[0])
    proba    = model.predict_proba(feat.reshape(1, -1))[0]
    return {
        "label_idx":     pred_idx,
        "label":         LABEL_NAMES[pred_idx],
        "probabilities": {name: float(p) for name, p in zip(LABEL_NAMES, proba)},
    }


def disagreement_report(model, db_path: str) -> list[dict]:
    """For every labelable film, compare prediction vs stored MPA.
    Returns rows where they disagree — these are candidates for re-seeding
    or human review."""
    import sqlite3
    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        "SELECT m.tmdb_id, m.title, m.year, m.metadata_json, cw.warnings_json "
        "FROM movies m JOIN content_warnings cw USING(tmdb_id)"
    ).fetchall()
    conn.close()

    out: list[dict] = []
    for tmdb_id, title, year, mj, wj in rows:
        try:
            meta = json.loads(mj or "{}")
            warn = json.loads(wj or "{}")
        except json.JSONDecodeError:
            continue
        cert = (meta.get("us_certification") or "").strip().upper()
        if cert not in CERT_TO_LABEL:
            continue
        feat, avg_conf = _film_features(warn, year)
        if avg_conf < GHOST_CONFIDENCE_FLOOR:
            continue
        pred_idx = int(model.predict(feat.reshape(1, -1))[0])
        actual_idx = CERT_TO_LABEL[cert]
        if pred_idx != actual_idx:
            proba = model.predict_proba(feat.reshape(1, -1))[0]
            out.append({
                "tmdb_id":     tmdb_id,
                "title":       title,
                "year":        year,
                "mpa_actual":  cert,
                "predicted":   LABEL_NAMES[pred_idx],
                "confidence":  float(proba[pred_idx]),
            })
    out.sort(key=lambda d: -d["confidence"])
    return out
