#!/usr/bin/env python3
"""Train logistic regression and gradient-boosted models on labeled recruiter data.

Trains two models on the 10-dimensional feature vector:
  1. Logistic Regression (L2-regularised, StandardScaler) -- interpretable, linear
  2. Gradient Boosting Classifier -- captures non-linear interactions

Both output calibrated shortlisting probabilities via predict_proba().
Trained models are saved to models/ for use via the 'logistic' and 'gbt' profiles.

Usage:
    pip install scikit-learn
    python3 scripts/train_models.py
"""

import json
import pathlib

import numpy as np
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, roc_auc_score
from sklearn.model_selection import cross_val_score, train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
import joblib

ROOT = pathlib.Path(__file__).parent.parent
DATA_PATH = ROOT / "data" / "training_data.json"
MODELS_DIR = ROOT / "models"

FEATURE_NAMES = [
    "required_skills_overlap",
    "preferred_skills_overlap",
    "industry_preferred_match",
    "experience_delta",
    "seniority_match",
    "career_trajectory_score",
    "interview_score",
    "culture_fit_score",
    "management_match",
    "soft_constraint_score",
]


def load_data() -> tuple[np.ndarray, np.ndarray]:
    data = json.loads(DATA_PATH.read_text())
    X = np.array([r["features"] for r in data["records"]], dtype=np.float64)
    y = np.array([r["outcome"] for r in data["records"]], dtype=np.int32)
    print(f"Loaded {len(data['records'])} records from {DATA_PATH.name}")
    print(f"  Shortlisted: {y.sum()} ({y.mean():.1%})  Rejected: {(~y.astype(bool)).sum()}")
    return X, y


def train_logistic(X_train: np.ndarray, y_train: np.ndarray) -> Pipeline:
    """L2-regularised logistic regression with StandardScaler preprocessing."""
    model = Pipeline([
        ("scaler", StandardScaler()),
        ("clf", LogisticRegression(C=1.0, max_iter=1000, random_state=42, solver="lbfgs")),
    ])
    model.fit(X_train, y_train)
    return model


def train_gbt(X_train: np.ndarray, y_train: np.ndarray) -> GradientBoostingClassifier:
    """Gradient-boosted classifier tuned to capture 2-way feature interactions.

    Hyperparameter rationale:
    - n_estimators=200: enough trees to model the skill×seniority interaction and
      the constraint quadratic gate without over-fitting a 500-record dataset
    - max_depth=4: captures up to 4-way interactions; depth 3-4 is standard for
      tabular data with 10 features
    - learning_rate=0.05: slow learning rate improves generalisation vs. high lr
    - subsample=0.8: stochastic GB reduces variance on small datasets
    - min_samples_leaf=10: prevents leaf nodes with too few samples (avoids overfitting)
    """
    model = GradientBoostingClassifier(
        n_estimators=200,
        max_depth=4,
        learning_rate=0.05,
        subsample=0.8,
        min_samples_leaf=10,
        random_state=42,
    )
    model.fit(X_train, y_train)
    return model


def evaluate(
    name: str,
    model: object,
    X_train: np.ndarray,
    y_train: np.ndarray,
    X_test: np.ndarray,
    y_test: np.ndarray,
) -> dict:
    y_prob = model.predict_proba(X_test)[:, 1]
    y_pred = model.predict(X_test)

    test_auc = roc_auc_score(y_test, y_prob)
    test_acc = accuracy_score(y_test, y_pred)

    X_full = np.vstack([X_train, X_test])
    y_full = np.concatenate([y_train, y_test])
    cv_scores = cross_val_score(model, X_full, y_full, cv=5, scoring="roc_auc")

    print(f"\n{name}")
    print(f"  Test AUC:        {test_auc:.3f}")
    print(f"  Test accuracy:   {test_acc:.3f}")
    print(f"  CV AUC (5-fold): {cv_scores.mean():.3f} +/- {cv_scores.std():.3f}")

    return {
        "test_auc": round(test_auc, 4),
        "test_accuracy": round(test_acc, 4),
        "cv_auc_mean": round(float(cv_scores.mean()), 4),
        "cv_auc_std": round(float(cv_scores.std()), 4),
    }


def print_importances(name: str, model: object) -> None:
    print(f"\n{name} -- feature importances:")
    if hasattr(model, "feature_importances_"):
        importances = model.feature_importances_
    elif hasattr(model, "named_steps"):
        coefs = model.named_steps["clf"].coef_[0]
        importances = np.abs(coefs) / np.abs(coefs).sum()
    else:
        return
    pairs = sorted(zip(FEATURE_NAMES, importances), key=lambda x: x[1], reverse=True)
    for fname, imp in pairs:
        bar = "#" * int(imp * 40)
        print(f"  {fname:<30} {imp:.3f}  {bar}")


def main() -> None:
    MODELS_DIR.mkdir(exist_ok=True)

    X, y = load_data()
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y
    )
    print(f"\nTrain: {len(X_train)} samples  |  Test: {len(X_test)} samples")

    print("\n--- Logistic Regression ---")
    lr_model = train_logistic(X_train, y_train)
    lr_metrics = evaluate("Logistic Regression", lr_model, X_train, y_train, X_test, y_test)
    print_importances("Logistic Regression", lr_model)

    print("\n--- Gradient Boosted Trees ---")
    gbt_model = train_gbt(X_train, y_train)
    gbt_metrics = evaluate("Gradient Boosted Trees", gbt_model, X_train, y_train, X_test, y_test)
    print_importances("Gradient Boosted Trees", gbt_model)

    # Save models
    lr_path = MODELS_DIR / "logistic_regression.joblib"
    gbt_path = MODELS_DIR / "gradient_boosted.joblib"
    joblib.dump(lr_model, lr_path)
    joblib.dump(gbt_model, gbt_path)

    # Save metadata
    metadata = {
        "trained_on": DATA_PATH.name,
        "n_train": len(X_train),
        "n_test": len(X_test),
        "feature_names": FEATURE_NAMES,
        "models": {
            "logistic": {
                "file": "logistic_regression.joblib",
                "profile_name": "logistic",
                "description": (
                    "L2-regularised logistic regression with StandardScaler. "
                    "Linear decision boundary -- interpretable coefficients. "
                    "Cannot capture feature interactions or threshold effects."
                ),
                "hyperparameters": {"C": 1.0, "solver": "lbfgs", "max_iter": 1000},
                "metrics": lr_metrics,
            },
            "gbt": {
                "file": "gradient_boosted.joblib",
                "profile_name": "gbt",
                "description": (
                    "Gradient-boosted classifier (sklearn). Captures non-linear "
                    "interactions: skill x seniority synergy, skill threshold cliff, "
                    "experience-skill substitution, quadratic constraint gate."
                ),
                "hyperparameters": {
                    "n_estimators": 200,
                    "max_depth": 4,
                    "learning_rate": 0.05,
                    "subsample": 0.8,
                    "min_samples_leaf": 10,
                },
                "metrics": gbt_metrics,
            },
        },
    }
    meta_path = MODELS_DIR / "metadata.json"
    meta_path.write_text(json.dumps(metadata, indent=2))

    print(f"\nSaved: {lr_path.name}  {gbt_path.name}  {meta_path.name}")
    print("\n" + "=" * 50)
    print("Summary:")
    print(f"  Logistic Regression  AUC: {lr_metrics['test_auc']:.3f}  CV: {lr_metrics['cv_auc_mean']:.3f}")
    print(f"  Gradient Boosted     AUC: {gbt_metrics['test_auc']:.3f}  CV: {gbt_metrics['cv_auc_mean']:.3f}")
    print("=" * 50)


if __name__ == "__main__":
    main()
