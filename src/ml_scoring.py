"""ML-based candidate scoring using trained logistic regression or GBT models.

Models are loaded lazily on first use and cached in-process.
Run scripts/train_models.py to generate the joblib files before using these profiles.
"""
from __future__ import annotations

import pathlib
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from .models import FeatureVector

_MODELS_DIR = pathlib.Path(__file__).parent.parent / "models"

# Feature names in the exact order used during training (must match train_models.py)
FEATURE_ORDER = [
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

# Profile name -> model filename
ML_PROFILES: dict[str, str] = {
    "logistic": "logistic_regression.joblib",
    "gbt": "gradient_boosted.joblib",
}

_model_cache: dict[str, object] = {}


def _load_model(profile: str) -> object:
    """Load and in-process-cache a trained model by profile name."""
    if profile in _model_cache:
        return _model_cache[profile]

    try:
        import joblib
    except ImportError as exc:
        raise ImportError(
            "joblib is required for ML scoring. Install scikit-learn: pip install scikit-learn"
        ) from exc

    model_path = _MODELS_DIR / ML_PROFILES[profile]
    if not model_path.exists():
        raise FileNotFoundError(
            f"Trained model not found at {model_path}. "
            "Run scripts/train_models.py to train the models first."
        )

    model = joblib.load(model_path)
    _model_cache[profile] = model
    return model


def fv_to_array(fv: "FeatureVector") -> np.ndarray:
    """Convert a FeatureVector to a (1, 10) float64 array in training order."""
    return np.array([[getattr(fv, name) for name in FEATURE_ORDER]], dtype=np.float64)


def clear_model_cache() -> None:
    """Invalidate the in-process model cache so next call reloads from disk."""
    _model_cache.clear()


def score_with_ml(fv: "FeatureVector", profile: str) -> float:
    """Return the shortlisting probability predicted by a trained ML model.

    The score is class-1 probability from predict_proba(), clipped to [0, 1].
    Directly comparable with the weighted linear scores from score_candidate().
    """
    model = _load_model(profile)
    prob = model.predict_proba(fv_to_array(fv))[0][1]
    return float(np.clip(prob, 0.0, 1.0))
