#!/usr/bin/env python3
"""Generate synthetic labeled training data for ML model training.

Each record is a 10-dimensional feature vector (matching the FeatureVector schema
in scoring.py) paired with a binary recruiter outcome: 1 = shortlisted, 0 = rejected.

The true underlying probability function includes both linear and non-linear
components so that:
  - Logistic regression can partially fit the data (~78% AUC)
  - Gradient-boosted trees can fit it more completely (~87% AUC)

Non-linear components encoded in the true signal:
  1. Skill × seniority interaction — a candidate needs BOTH; neither alone suffices
  2. Hard cliff below 0.55 skill coverage — unqualified regardless of other signals
  3. Experience compensates for marginal skill match (only in the 0.55–0.72 band)
  4. Soft constraint score as a near-quadratic gate — low compliance is
     disproportionately damaging (not just linearly bad)

Usage:
    python scripts/generate_training_data.py
"""

import json
import pathlib

import numpy as np

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

N_SAMPLES = 500
SEED = 42


def _generate_feature_vector(rng: np.random.Generator) -> np.ndarray:
    """Generate a plausible 10-dim feature vector.

    Distributions mirror what the real pipeline produces:
    - required/preferred skills: correlated via a shared latent 'skill quality'
    - career_trajectory_score: discrete {0.60, 0.65, 0.85}
    - management_match: discrete {0.3, 1.0}
    - interview/culture: correlated pair; 20% of candidates have no transcript (→ 0.5)
    - soft_constraint_score: right-skewed — most candidates pass most constraints
    """
    skill_quality = rng.beta(2, 2)  # latent quality, mean=0.5, symmetric

    rso = float(np.clip(rng.normal(skill_quality, 0.18), 0.0, 1.0))
    pso = float(np.clip(rng.normal(skill_quality * 0.88, 0.20), 0.0, 1.0))

    ipm = float(rng.beta(2.5, 2.0))   # mean 0.56 — industry often partially matches
    exp = float(rng.beta(2, 3))        # mean 0.40 — surplus experience is common but not huge
    snr = float(np.clip(rng.normal(0.68, 0.22), 0.0, 1.0))  # seniority often near-match

    traj = float(rng.choice([0.60, 0.65, 0.85], p=[0.15, 0.30, 0.55]))  # mostly ascending

    # 80% of candidates have interview transcripts; 20% get the default 0.5
    has_transcript = rng.random() > 0.20
    if has_transcript:
        isc = float(rng.beta(3, 2))                             # mean 0.60, slight +ve skew
        cfs = float(np.clip(rng.normal(isc, 0.08), 0.0, 1.0))  # correlated with interview
    else:
        isc, cfs = 0.5, 0.5

    mgm = float(rng.choice([0.3, 1.0], p=[0.30, 0.70]))   # 70% management match
    scs = float(rng.beta(4, 1.5))      # mean 0.73 — right-skewed, most constraints pass

    return np.array([rso, pso, ipm, exp, snr, traj, isc, cfs, mgm, scs])


def _true_probability(features: np.ndarray) -> float:
    """Non-linear true probability of shortlisting.

    Combines a linear base (matching the current hand-tuned weights) with four
    non-linear terms that logistic regression cannot capture but GBT can.
    """
    rso, pso, ipm, exp, snr, traj, isc, cfs, mgm, scs = features

    # --- Linear base (mirrors current DEFAULT_WEIGHTS) ---
    base = (
        0.35 * rso + 0.10 * pso + 0.12 * ipm
        + 0.10 * exp + 0.08 * snr + 0.05 * traj
        + 0.03 * isc + 0.02 * cfs + 0.04 * mgm + 0.08 * scs
    )

    # --- Non-linear term 1: skill × seniority interaction ---
    # A candidate needs BOTH strong skill coverage AND correct seniority.
    # The multiplicative interaction means neither alone is sufficient.
    # A linear model can only add their separate contributions.
    synergy = 0.18 * rso * snr

    # --- Non-linear term 2: hard cliff below 0.55 skill coverage ---
    # Below this threshold the candidate is practically unqualified regardless
    # of other signals — a discontinuous step that linear models approximate
    # poorly with a smooth slope.
    threshold_penalty = -0.30 if rso < 0.55 else 0.0

    # --- Non-linear term 3: experience compensates for marginal skill match ---
    # When skill coverage is borderline (0.55–0.72), extra experience can tip
    # the balance. Outside this band the effect is absent — it is a conditional
    # interaction between two features, not a universal bonus.
    exp_compensation = 0.12 * exp if 0.55 <= rso <= 0.72 else 0.0

    # --- Non-linear term 4: soft constraint compliance as a quadratic gate ---
    # Low constraint compliance is disproportionately damaging (scs² < scs for
    # scs < 1), whereas high compliance provides diminishing returns.
    # A linear weight on scs would underestimate the penalty at low values.
    constraint_gate = 0.10 * (scs ** 2 - scs)

    combined = base + synergy + threshold_penalty + exp_compensation + constraint_gate

    # Logistic transform — centre at 0.57 to achieve ~35% shortlisting rate
    p = 1.0 / (1.0 + np.exp(-8.0 * (combined - 0.57)))
    return float(np.clip(p, 0.02, 0.98))


def main() -> None:
    rng = np.random.default_rng(SEED)

    records = []
    for i in range(N_SAMPLES):
        features = _generate_feature_vector(rng)
        p = _true_probability(features)
        outcome = int(rng.random() < p)
        records.append({
            "id": f"train-{i + 1:04d}",
            "features": [round(float(x), 6) for x in features],
            "outcome": outcome,
            "outcome_label": "shortlisted" if outcome == 1 else "rejected",
        })

    shortlisted = sum(r["outcome"] for r in records)
    rejected = N_SAMPLES - shortlisted

    output = {
        "version": 1,
        "description": (
            "Mock labeled training data simulating recruiter shortlisting decisions. "
            "Each record is a (feature_vector[10], outcome) pair where outcome=1 means "
            "shortlisted and outcome=0 means rejected. "
            "The true signal includes non-linear components (skill×seniority interaction, "
            "skill threshold cliff at 0.55, experience-skill substitution in 0.55-0.72 "
            "band, quadratic constraint gate) so gradient-boosted models outperform "
            "logistic regression on this data."
        ),
        "feature_names": FEATURE_NAMES,
        "n_records": N_SAMPLES,
        "shortlisted_count": shortlisted,
        "rejected_count": rejected,
        "shortlist_rate": round(shortlisted / N_SAMPLES, 3),
        "seed": SEED,
        "records": records,
    }

    out_path = pathlib.Path(__file__).parent.parent / "data" / "training_data.json"
    out_path.write_text(json.dumps(output, indent=2))

    print(f"Generated {N_SAMPLES} records → {out_path}")
    print(f"  Shortlisted: {shortlisted} ({shortlisted / N_SAMPLES:.1%})")
    print(f"  Rejected:    {rejected} ({rejected / N_SAMPLES:.1%})")


if __name__ == "__main__":
    main()
