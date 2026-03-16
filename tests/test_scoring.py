"""Unit tests for the scoring model.

Most tests require no API calls. Tests that call build_feature_vector with
non-empty skills or industries use the OpenAI embeddings API and are marked
@pytest.mark.integration — they are skipped unless OPENAI_API_KEY is set.

Run pure unit tests:
    pytest tests/test_scoring.py -v -m "not integration"

Run all (requires OPENAI_API_KEY):
    pytest tests/test_scoring.py -v
"""
import pytest

from src.models import (
    Candidate,
    CompatibilityResult,
    ConstraintMatch,
    DEFAULT_WEIGHTS,
    FeatureVector,
    JobDescription,
    MatchType,
)
from src.scoring import (
    build_feature_vector,
    jaccard_similarity,
    rank_candidates,
    score_candidate,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def perfect_feature_vector(candidate_id: str = "cand-test") -> FeatureVector:
    return FeatureVector(
        candidate_id=candidate_id,
        required_skills_overlap=1.0,
        preferred_skills_overlap=1.0,
        industry_preferred_match=1.0,
        experience_delta=1.0,
        seniority_match=1.0,
        career_trajectory_score=1.0,
        interview_score=1.0,
        culture_fit_score=1.0,
        management_match=1.0,
        soft_constraint_score=1.0,
    )


def empty_compatibility_result(candidate_id: str = "cand-test") -> CompatibilityResult:
    return CompatibilityResult(
        candidate_id=candidate_id,
        eliminated=False,
        elimination_reasons=[],
        constraint_matches=[],
        unmatched_candidate_constraints=[],
        flagged_for_review=[],
    )


def make_job(
    required_skills: list[str] | None = None,
    preferred_skills: list[str] | None = None,
    min_years_experience: int = 0,
    seniority: str = "senior",
    management_required: bool = False,
    industries_preferred: list[str] | None = None,
) -> JobDescription:
    return JobDescription(
        id="job-test",
        title="Test Job",
        company="Test Co",
        raw_text="",
        required_skills=required_skills or [],
        preferred_skills=preferred_skills or [],
        min_years_experience=min_years_experience,
        seniority=seniority,
        management_required=management_required,
        industries_preferred=industries_preferred or [],
        constraints=[],
    )


def make_candidate(
    skills: list[str] | None = None,
    years_experience: float = 5.0,
    seniority_level: str = "senior",
    management_experience: bool = False,
    industries: list[str] | None = None,
    interview_score: float = 0.8,
    culture_fit_score: float = 0.7,
    career_trajectory: str = "ascending",
) -> Candidate:
    return Candidate(
        id="cand-test",
        name="Test Candidate",
        raw_cv="",
        raw_linkedin="",
        raw_interview_transcript="",
        years_experience=years_experience,
        skills=skills or [],
        industries=industries or [],
        seniority_level=seniority_level,
        management_experience=management_experience,
        interview_score=interview_score,
        culture_fit_score=culture_fit_score,
        career_trajectory=career_trajectory,
        constraints=[],
    )


# ---------------------------------------------------------------------------
# Task 6.5 — all features at 1.0 with default weights → score == 1.0
# ---------------------------------------------------------------------------
def test_all_features_max_score():
    """When all 10 features are 1.0 and default weights are used, score must equal 1.0."""
    fv = perfect_feature_vector()
    score = score_candidate(fv, DEFAULT_WEIGHTS)
    assert abs(score - 1.0) < 1e-6, f"Expected 1.0, got {score}"


def test_default_weights_sum_to_one():
    """Default weights must sum to 1.0 so a perfect vector scores exactly 1.0."""
    total = sum(DEFAULT_WEIGHTS.values())
    assert abs(total - 1.0) < 1e-6, f"Default weights sum to {total}, expected 1.0"


# ---------------------------------------------------------------------------
# Task 6.6 — experience_delta clamped to 0 when candidate is under-experienced
# ---------------------------------------------------------------------------
def test_experience_delta_below_minimum_is_zero():
    """Any candidate below the minimum scores 0.0 regardless of how close they are."""
    job = make_job(min_years_experience=5)
    for years in [0.0, 2.0, 4.9]:
        candidate = make_candidate(years_experience=years)
        cr = empty_compatibility_result()
        fv = build_feature_vector(job, candidate, cr)
        assert fv.experience_delta == 0.0, (
            f"Expected 0.0 for {years} years vs min 5, got {fv.experience_delta}"
        )


def test_experience_delta_at_minimum_is_half():
    """Exactly meeting the minimum scores 0.5 — qualifies but no surplus."""
    job = make_job(min_years_experience=5)
    candidate = make_candidate(years_experience=5.0)
    cr = empty_compatibility_result()
    fv = build_feature_vector(job, candidate, cr)
    assert abs(fv.experience_delta - 0.5) < 1e-6, (
        f"Expected 0.5 at minimum, got {fv.experience_delta}"
    )


def test_experience_delta_surplus_grows():
    """More experience above minimum always increases the score."""
    job = make_job(min_years_experience=5)
    cr = empty_compatibility_result()

    scores = []
    for years in [5.0, 7.0, 10.0, 15.0]:
        fv = build_feature_vector(job, make_candidate(years_experience=years), cr)
        scores.append(fv.experience_delta)

    assert scores == sorted(scores), f"Scores should increase with experience: {scores}"


def test_experience_delta_capped_at_one():
    """Five or more years over minimum should cap at 1.0."""
    job = make_job(min_years_experience=5)
    candidate = make_candidate(years_experience=15.0)  # 10 years over
    cr = empty_compatibility_result()
    fv = build_feature_vector(job, candidate, cr)
    assert fv.experience_delta == 1.0, (
        f"Expected 1.0 when well above minimum, got {fv.experience_delta}"
    )


def test_experience_delta_two_years_surplus():
    """Two years over minimum (5) → 0.5 + 0.5*(2/5) = 0.7."""
    job = make_job(min_years_experience=5)
    candidate = make_candidate(years_experience=7.0)
    cr = empty_compatibility_result()
    fv = build_feature_vector(job, candidate, cr)
    assert abs(fv.experience_delta - 0.7) < 1e-6, (
        f"Expected 0.7 (2 years surplus), got {fv.experience_delta}"
    )


# ---------------------------------------------------------------------------
# Jaccard similarity tests
# ---------------------------------------------------------------------------
def test_jaccard_perfect_overlap():
    assert jaccard_similarity(["Python", "SQL"], ["python", "sql"]) == 1.0


def test_jaccard_no_overlap():
    assert jaccard_similarity(["Python"], ["Java"]) == 0.0


def test_jaccard_partial_overlap():
    result = jaccard_similarity(["Python", "SQL", "dbt"], ["Python", "SQL", "Spark"])
    assert abs(result - 2 / 4) < 1e-6  # |intersection|=2, |union|=4


def test_jaccard_empty_lists():
    assert jaccard_similarity([], []) == 1.0
    assert jaccard_similarity([], ["Python"]) == 0.0
    assert jaccard_similarity(["Python"], []) == 0.0


# ---------------------------------------------------------------------------
# build_feature_vector tests
# ---------------------------------------------------------------------------
@pytest.mark.integration
def test_industry_preferred_match_hit():
    """Requires OPENAI_API_KEY — calls embeddings API."""
    job = make_job(industries_preferred=["fintech", "payments"])
    candidate = make_candidate(industries=["Fintech", "Banking"])
    cr = empty_compatibility_result()
    fv = build_feature_vector(job, candidate, cr)
    # "fintech" candidate vs "fintech" job should score near 1.0; banking vs payments moderate
    assert fv.industry_preferred_match > 0.5


@pytest.mark.integration
def test_industry_preferred_match_miss():
    """Requires OPENAI_API_KEY — calls embeddings API."""
    job = make_job(industries_preferred=["fintech"])
    candidate = make_candidate(industries=["healthcare"])
    cr = empty_compatibility_result()
    fv = build_feature_vector(job, candidate, cr)
    assert fv.industry_preferred_match < 0.6


def test_management_match_true():
    job = make_job(management_required=True)
    candidate = make_candidate(management_experience=True)
    cr = empty_compatibility_result()
    fv = build_feature_vector(job, candidate, cr)
    assert fv.management_match == 1.0


def test_management_mismatch():
    job = make_job(management_required=True)
    candidate = make_candidate(management_experience=False)
    cr = empty_compatibility_result()
    fv = build_feature_vector(job, candidate, cr)
    assert fv.management_match == 0.3


# ---------------------------------------------------------------------------
# score_candidate: custom weights
# ---------------------------------------------------------------------------
def test_score_candidate_zero_required_skills():
    """Score with all features at 1.0 except required_skills_overlap=0 should equal 1 - its weight."""
    fv = FeatureVector(
        candidate_id="cand-test",
        required_skills_overlap=0.0,
        preferred_skills_overlap=1.0,
        industry_preferred_match=1.0,
        experience_delta=1.0,
        seniority_match=1.0,
        career_trajectory_score=1.0,
        interview_score=1.0,
        culture_fit_score=1.0,
        management_match=1.0,
        soft_constraint_score=1.0,
    )
    expected = 1.0 - DEFAULT_WEIGHTS["required_skills_overlap"]
    score = score_candidate(fv, DEFAULT_WEIGHTS)
    assert abs(score - expected) < 1e-4, f"Expected {expected}, got {score}"


# ---------------------------------------------------------------------------
# rank_candidates: eliminated candidates should not appear in ranked list
# ---------------------------------------------------------------------------
def test_rank_candidates_eliminates_correctly():
    # No skills on job or candidates — avoids embedding API calls while still
    # testing the elimination/ranking logic.
    job = make_job()
    cand_ok = make_candidate()
    cand_ok.id = "cand-ok"

    cand_elim = make_candidate()
    cand_elim.id = "cand-elim"
    cand_elim.name = "Eliminated Candidate"

    cr_ok = empty_compatibility_result("cand-ok")
    cr_elim = CompatibilityResult(
        candidate_id="cand-elim",
        eliminated=True,
        elimination_reasons=["Hard constraint fail: office days"],
        constraint_matches=[],
        unmatched_candidate_constraints=[],
        flagged_for_review=[],
    )

    result = rank_candidates(
        job,
        [cand_ok, cand_elim],
        {"cand-ok": cr_ok, "cand-elim": cr_elim},
    )

    assert len(result.ranked_candidates) == 1
    assert result.ranked_candidates[0].candidate_id == "cand-ok"
    assert len(result.eliminated_candidates) == 1
    assert result.eliminated_candidates[0].candidate_id == "cand-elim"
