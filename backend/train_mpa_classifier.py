#!/usr/bin/env python3
"""
Train the MPA-rating classifier.

Pulls every well-assessed film with an MPA label out of the cache, fits a
multinomial logistic regression with 80/20 stratified train/test split,
prints metrics, saves the fitted model to data/mpa_classifier.pkl, and
optionally lists films where the model disagrees with the stored MPA
(those are candidates for re-seeding).

Usage:
    python backend/train_mpa_classifier.py
    python backend/train_mpa_classifier.py --no-save         # train + evaluate only
    python backend/train_mpa_classifier.py --disagreements   # also list misclassified
    python backend/train_mpa_classifier.py --top-coefficients 10
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np  # noqa: E402

from backend.mpa_classifier import (  # noqa: E402
    LABEL_NAMES, MODEL_PATH_DEFAULT, disagreement_report,
    evaluate, extract_training_data, feature_names, save_model, train_model,
)

DEFAULT_DB = os.environ.get("DB_PATH", "./data/movie_cache.db")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db",   default=DEFAULT_DB)
    parser.add_argument("--out",  default=MODEL_PATH_DEFAULT)
    parser.add_argument("--no-save",  action="store_true", help="Skip writing the .pkl")
    parser.add_argument("--disagreements", action="store_true",
                        help="Print films where the trained model disagrees with the stored MPA")
    parser.add_argument("--top-coefficients", type=int, default=5,
                        help="Show top N features per class by absolute coefficient")
    parser.add_argument("--random-state", type=int, default=42)
    args = parser.parse_args()

    print(f"Loading training data from {args.db} …")
    data = extract_training_data(args.db)
    n = len(data.y)
    print(f"  {n} labelable films "
          f"(family={int(np.sum(data.y == 0))}, "
          f"teen={int(np.sum(data.y == 1))}, "
          f"adult={int(np.sum(data.y == 2))})")
    print(f"  Feature space: {data.X.shape[1]}-dimensional")

    from sklearn.model_selection import train_test_split
    X_train, X_test, y_train, y_test = train_test_split(
        data.X, data.y,
        test_size=0.20,
        stratify=data.y,
        random_state=args.random_state,
    )
    print(f"  Train: {len(y_train)} | Test: {len(y_test)}")

    print("\nTraining multinomial logistic regression …")
    model = train_model(X_train, y_train, random_state=args.random_state)

    print("\n=== Evaluation on 20% held-out test set ===")
    metrics = evaluate(model, X_test, y_test)
    print(f"Accuracy:    {metrics['accuracy']:.3f}")
    print(f"Macro F1:    {metrics['macro_f1']:.3f}")
    print(f"Weighted F1: {metrics['weighted_f1']:.3f}")
    print("\nPer-class breakdown:")
    print(metrics["report"])
    print("Confusion matrix (rows=actual, cols=predicted, order=family/teen/adult):")
    for row, name in zip(metrics["confusion"], LABEL_NAMES):
        print(f"  {name:<7} {row}")

    if args.top_coefficients > 0:
        print(f"\n=== Top {args.top_coefficients} features per class (|coefficient|) ===")
        fns = feature_names()
        for class_idx, class_name in enumerate(LABEL_NAMES):
            coefs = model.coef_[class_idx]
            order = np.argsort(-np.abs(coefs))[: args.top_coefficients]
            print(f"\n  {class_name}:")
            for i in order:
                sign = "+" if coefs[i] > 0 else "-"
                print(f"    {sign} {abs(coefs[i]):.3f}  {fns[i]}")

    if not args.no_save:
        save_model(model, args.out)
        print(f"\nSaved model -> {args.out}")

    if args.disagreements:
        print("\n=== Films where the model disagrees with stored MPA ===")
        diffs = disagreement_report(model, args.db)
        if not diffs:
            print("  None.")
        else:
            print(f"  {len(diffs)} disagreements (most confident first):")
            for d in diffs[:25]:
                print(f"    {d['title']:<40} "
                      f"actual={d['mpa_actual']:<6} "
                      f"predicted={d['predicted']:<7} "
                      f"conf={d['confidence']:.2f}")


if __name__ == "__main__":
    main()
