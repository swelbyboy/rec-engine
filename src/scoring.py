"""Weighted linear scoring model for candidate ranking."""
from __future__ import annotations

import os
import threading
from functools import lru_cache

import numpy as np

from .models import (
    Candidate,
    CompatibilityResult,
    DEFAULT_WEIGHTS,
    EliminatedCandidate,
    FeatureVector,
    JobDescription,
    PipelineResult,
    ScoredCandidate,
)


# ---------------------------------------------------------------------------
# Skill similarity — embedding-based, domain-anchored, no hardcoded rules
# ---------------------------------------------------------------------------

# Minimum cosine similarity to count two skills as equivalent.
# Prefixing with "skill: " anchors embeddings to the skill domain, which
# significantly improves discrimination between name variants vs unrelated skills:
#   "skill: airflow" vs "skill: apache airflow" → 0.77 (same tool)
#   "skill: pyspark" vs "skill: spark"          → 0.79 (same ecosystem)
#   "skill: python"  vs "skill: javascript"     → 0.64 (different)
# Works for any domain (tech, HR, legal, medical) — no domain-specific rules.
_SKILL_MATCH_THRESHOLD = 0.75


def jaccard_similarity(a: list[str], b: list[str]) -> float:
    """Exact Jaccard similarity (kept for unit tests; not used in scoring)."""
    set_a = {s.strip().lower() for s in a}
    set_b = {s.strip().lower() for s in b}
    if not set_a and not set_b:
        return 1.0
    if not set_a or not set_b:
        return 0.0
    return len(set_a & set_b) / len(set_a | set_b)


def skill_coverage(candidate_skills: list[str], target_skills: list[str]) -> float:
    """What fraction of target skills does the candidate have?

    Uses embedding cosine similarity with a "skill: " domain prefix.
    The prefix anchors embeddings to the skill namespace, improving
    discrimination between name variants and genuinely different skills.
    No hardcoded aliases, prefixes, or domain-specific rules.

    Asymmetric recall: extra candidate skills do not lower the score.
    All embeddings are LRU-cached — zero extra API cost on repeated calls.
    """
    if not target_skills:
        return 1.0
    if not candidate_skills:
        return 0.0

    def _skill_emb(s: str) -> tuple[float, ...]:
        return _embed_cached(f"skill: {s.strip().lower()}")

    target_embs = [_skill_emb(s) for s in target_skills]
    candidate_embs = [_skill_emb(s) for s in candidate_skills]

    matched = sum(
        1
        for t_emb in target_embs
        if max(_cosine(t_emb, c_emb) for c_emb in candidate_embs) >= _SKILL_MATCH_THRESHOLD
    )
    return matched / len(target_skills)


# ---------------------------------------------------------------------------
# Embedding-based industry similarity
# ---------------------------------------------------------------------------

_openai_client = None
_client_lock = threading.Lock()


def _get_openai_client():
    global _openai_client
    if _openai_client is None:
        with _client_lock:
            if _openai_client is None:
                from openai import OpenAI
                _openai_client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
    return _openai_client


@lru_cache(maxsize=512)
def _embed_cached(text: str) -> tuple[float, ...]:
    """Embed a short text string, cached by content.

    Returns a tuple (hashable) so lru_cache works. Industry names are short
    and stable — each unique string is embedded at most once per server run.
    """
    response = _get_openai_client().embeddings.create(
        model="text-embedding-3-small", input=[text]
    )
    return tuple(response.data[0].embedding)


def _cosine(a: tuple[float, ...], b: tuple[float, ...]) -> float:
    va = np.array(a, dtype=np.float32)
    vb = np.array(b, dtype=np.float32)
    denom = np.linalg.norm(va) * np.linalg.norm(vb)
    return float(np.dot(va, vb) / denom) if denom > 1e-10 else 0.0


def _industry_similarity(
    candidate_industries: list[str],
    job_industries: list[str],
) -> float:
    """Semantic similarity between candidate's industries and job's preferred industries.

    For each job-preferred industry, finds the best-matching candidate industry
    by cosine similarity and averages those scores.

    Returns 1.0 when the job has no industry preference — any background is
    fully acceptable, so the feature contributes no penalty. (0.5 would be
    non-discriminative noise: equal for all candidates, adding no ranking signal.)

    All embeddings are cached — repeated scoring calls add zero API cost.
    """
    if not job_industries:
        return 1.0  # no preference stated → full score, no penalty
    if not candidate_industries:
        return 0.0  # preference stated but candidate has no industry data

    job_embs = [_embed_cached(i.lower().strip()) for i in job_industries]
    can_embs = [_embed_cached(i.lower().strip()) for i in candidate_industries]

    # For each required industry, take the best candidate match
    scores = [
        max(_cosine(job_emb, can_emb) for can_emb in can_embs)
        for job_emb in job_embs
    ]
    return float(np.mean(scores))


# Seniority ordering for level matching
_SENIORITY_ORDER = {
    "junior": 1,
    "mid": 2,
    "senior": 3,
    "lead": 4,
    "principal": 5,
    "staff": 5,
}


def _seniority_match(job_seniority: str, candidate_seniority: str) -> float:
    """Ordinal distance across the seniority ladder — graduated, not binary.

    senior vs lead → 0.8 (one step apart)
    senior vs junior → 0.6 (two steps apart)
    senior vs senior → 1.0 (exact match)

    Both levels default to 'mid' (rank 2) if unrecognised.
    """
    max_rank = max(_SENIORITY_ORDER.values())  # 5
    job_rank = _SENIORITY_ORDER.get(job_seniority.lower(), 2)
    can_rank = _SENIORITY_ORDER.get(candidate_seniority.lower(), 2)
    return 1.0 - abs(job_rank - can_rank) / max_rank


def _career_trajectory_score(trajectory: str) -> float:
    """Soft signal — intentionally low-weight and not highly penalising.

    Ascending careers are favoured, but lateral moves (into a new industry, for
    example) are common and legitimate. Mixed trajectories reflect career changes
    that may be exactly what a hiring manager wants. Values kept close together
    so this feature nudges rather than dominates.
    """
    mapping = {"ascending": 0.85, "lateral": 0.65, "mixed": 0.60}
    return mapping.get(trajectory, 0.65)


def _experience_delta(candidate_years: float, job_min: int) -> float:
    """Asymmetric experience scoring: below minimum = 0, above = linear 0.5→1.0.

    Rationale:
    - Under minimum: the candidate doesn't meet the bar. Score 0 regardless of
      how close they are — ranking within the unqualified band adds no value.
    - At minimum: score 0.5 — they qualify, but bring no surplus experience.
    - Above minimum: more is always better. Linear from 0.5 at minimum to 1.0
      at minimum + 5 years. Capped at 1.0 — diminishing returns beyond that.

    When job_min is 0 (no experience requirement), any experience is a plus:
    a new grad scores 0.5, a 5-year veteran scores 1.0.
    """
    if job_min == 0:
        return 0.5 + 0.5 * min(candidate_years / 5.0, 1.0)
    if candidate_years < job_min:
        return 0.0
    surplus = candidate_years - job_min
    return 0.5 + 0.5 * min(surplus / 5.0, 1.0)


def _effective_weights(candidate: Candidate, base_weights: dict[str, float]) -> dict[str, float]:
    """Return per-candidate weights adjusted for data availability.

    Problem: interview_score and culture_fit_score default to 0.5 when no
    interview transcript exists. Together they carry 5% of the total weight
    (reduced from 15% — both are LLM-assessed proxies with bias risk).
    For un-interviewed candidates this adds a flat 0.025 to every score — equal
    for everyone, non-discriminative, and it makes pre/post-interview rankings
    incomparable (a score of 0.72 before an interview is not the same as 0.72
    after).

    Fix: when no transcript is present, zero those two weights and redistribute
    to required_skills_overlap — the most objective signal we do have.
    Weights are then normalised so they always sum to 1.0.

    Extensibility: this pattern generalises. Any feature with missing data can
    have its weight redistributed rather than contributing a neutral constant.
    A production system would do this per-feature based on data quality flags.
    """
    w = dict(base_weights)

    has_interview = bool(candidate.raw_interview_transcript.strip())
    if not has_interview:
        freed = w.get("interview_score", 0.0) + w.get("culture_fit_score", 0.0)
        w["interview_score"] = 0.0
        w["culture_fit_score"] = 0.0
        w["required_skills_overlap"] = w.get("required_skills_overlap", 0.0) + freed

    # Normalise so weights always sum to 1.0 — scores remain interpretable
    # regardless of what custom weights the caller passes.
    total = sum(w.values())
    if total > 0:
        w = {k: v / total for k, v in w.items()}

    return w


def _soft_constraint_score(constraint_result: CompatibilityResult) -> float:
    """Mean of all constraint match scores, including soft failures.

    Non-eliminated candidates can still have incompatible soft constraints
    (compatible=False on a soft-type constraint). These must be included so
    they penalise the score — previously they were silently excluded, which
    caused candidates with explicit soft-constraint failures to rank as if the
    mismatch didn't exist.

    Hard constraint failures never appear here because those candidates are
    eliminated before scoring.
    """
    scores = [m.score for m in constraint_result.constraint_matches]
    if not scores:
        return 1.0  # no constraints → no penalty
    return sum(scores) / len(scores)


# ---------------------------------------------------------------------------
# Task 6.1: build_feature_vector
# ---------------------------------------------------------------------------
def build_feature_vector(
    job: JobDescription,
    candidate: Candidate,
    constraint_result: CompatibilityResult,
) -> FeatureVector:
    """Compute all 10 features for a non-eliminated candidate."""
    return FeatureVector(
        candidate_id=candidate.id,
        required_skills_overlap=skill_coverage(candidate.skills, job.required_skills),
        preferred_skills_overlap=skill_coverage(candidate.skills, job.preferred_skills),
        industry_preferred_match=_industry_similarity(
            candidate.industries, job.industries_preferred
        ),
        experience_delta=_experience_delta(
            candidate.years_experience, job.min_years_experience
        ),
        seniority_match=_seniority_match(job.seniority, candidate.seniority_level),
        career_trajectory_score=_career_trajectory_score(candidate.career_trajectory),
        interview_score=candidate.interview_score,
        culture_fit_score=candidate.culture_fit_score,
        management_match=(
            1.0 if job.management_required == candidate.management_experience else 0.3
        ),
        soft_constraint_score=_soft_constraint_score(constraint_result),
    )


# ---------------------------------------------------------------------------
# Task 6.3: score_candidate
# ---------------------------------------------------------------------------
def score_candidate(
    feature_vector: FeatureVector,
    weights: dict[str, float] | None = None,
) -> float:
    """Return the weighted linear sum score for a candidate (0.0–1.0).

    Weights are expected to already be normalised (via _effective_weights).
    Passing un-normalised weights still works — the score is clamped to [0,1].
    """
    w = weights if weights is not None else DEFAULT_WEIGHTS
    total = (
        feature_vector.required_skills_overlap * w.get("required_skills_overlap", 0.38)
        + feature_vector.preferred_skills_overlap * w.get("preferred_skills_overlap", 0.10)
        + feature_vector.industry_preferred_match * w.get("industry_preferred_match", 0.12)
        + feature_vector.experience_delta * w.get("experience_delta", 0.10)
        + feature_vector.seniority_match * w.get("seniority_match", 0.08)
        + feature_vector.career_trajectory_score * w.get("career_trajectory_score", 0.05)
        + feature_vector.interview_score * w.get("interview_score", 0.03)
        + feature_vector.culture_fit_score * w.get("culture_fit_score", 0.02)
        + feature_vector.management_match * w.get("management_match", 0.04)
        + feature_vector.soft_constraint_score * w.get("soft_constraint_score", 0.08)
    )
    return round(min(1.0, max(0.0, total)), 6)


# ---------------------------------------------------------------------------
# Task 6.4: rank_candidates
# ---------------------------------------------------------------------------
def rank_candidates(
    job: JobDescription,
    candidates: list[Candidate],
    constraint_results: dict[str, CompatibilityResult],
    weights: dict[str, float] | None = None,
    top_n_explanations: int = 10,
) -> PipelineResult:
    """Filter eliminated candidates and rank survivors by score descending.

    Args:
        job: Parsed job description.
        candidates: All parsed candidate objects.
        constraint_results: Mapping of candidate_id → CompatibilityResult.
        weights: Optional custom weight dict (uses DEFAULT_WEIGHTS if None).
        top_n_explanations: Number of top candidates to generate explanations for
            (set on ScoredCandidate.explanation placeholder; actual generation happens
            in the explanation layer).

    Returns:
        PipelineResult with ranked_candidates and eliminated_candidates.
    """
    base_weights = weights or DEFAULT_WEIGHTS

    ranked: list[ScoredCandidate] = []
    eliminated: list[EliminatedCandidate] = []

    for candidate in candidates:
        cr = constraint_results.get(candidate.id)
        if cr is None:
            continue

        if cr.eliminated:
            eliminated.append(
                EliminatedCandidate(
                    candidate_id=candidate.id,
                    name=candidate.name,
                    elimination_reasons=cr.elimination_reasons,
                    constraint_result=cr,
                )
            )
        else:
            fv = build_feature_vector(job, candidate, cr)
            # Compute per-candidate weights: redistributes interview/culture weights
            # when no transcript exists, then normalises to sum=1.0
            effective = _effective_weights(candidate, base_weights)
            score = score_candidate(fv, effective)
            ranked.append(
                ScoredCandidate(
                    candidate_id=candidate.id,
                    name=candidate.name,
                    score=score,
                    feature_vector=fv,
                    constraint_result=cr,
                    explanation="",  # populated by explanation layer
                )
            )

    # Sort ranked candidates by score descending
    ranked.sort(key=lambda sc: sc.score, reverse=True)

    return PipelineResult(
        job_id=job.id,
        ranked_candidates=ranked,
        eliminated_candidates=eliminated,
        weights_used=base_weights,  # show base weights; effective weights vary per candidate
    )
