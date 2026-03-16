"""Unit tests for the constraint compatibility engine.

These tests run entirely in Python — no LLM or API calls required.
Run: pytest tests/test_constraints.py -v
"""
import pytest

from src.constraint_engine import (
    canonical_key_match,
    run_constraint_engine,
)
from src.models import (
    Candidate,
    CompatibilityResult,
    Constraint,
    ConstraintOperator,
    ConstraintSide,
    ConstraintType,
    JobDescription,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def make_constraint(
    canonical_key: str,
    value,
    operator: ConstraintOperator,
    constraint_type: ConstraintType = ConstraintType.hard,
    side: ConstraintSide = ConstraintSide.employer,
    confidence: float = 0.97,
    cid: str | None = None,
) -> Constraint:
    return Constraint(
        id=cid or f"{canonical_key}-{side.value}",
        type=constraint_type,
        side=side,
        category="test",
        description=f"{canonical_key} {operator.value} {value}",
        canonical_key=canonical_key,
        value=value,
        operator=operator,
        weight=1.0,
        confidence=confidence,
    )


def make_job(constraints: list[Constraint]) -> JobDescription:
    return JobDescription(
        id="job-test",
        title="Test Job",
        company="Test Co",
        raw_text="",
        required_skills=[],
        preferred_skills=[],
        min_years_experience=0,
        seniority="senior",
        management_required=False,
        constraints=constraints,
    )


def make_candidate(constraints: list[Constraint]) -> Candidate:
    return Candidate(
        id="cand-test",
        name="Test Candidate",
        raw_cv="",
        raw_linkedin="",
        raw_interview_transcript="",
        years_experience=5.0,
        skills=[],
        industries=[],
        seniority_level="senior",
        management_experience=False,
        constraints=constraints,
    )


# ---------------------------------------------------------------------------
# Task 5.6 — office_days_per_week requires 5 vs max 2 → hard fail, eliminated
# ---------------------------------------------------------------------------
def test_office_days_hard_fail():
    """Employer requires 5 days in office; candidate max is 2 → eliminated."""
    emp_c = make_constraint("office_days_per_week", 5, ConstraintOperator.requires)
    can_c = make_constraint(
        "office_days_per_week",
        2,
        ConstraintOperator.max,
        side=ConstraintSide.candidate,
        cid="office-cand",
    )

    job = make_job([emp_c])
    candidate = make_candidate([can_c])

    result = run_constraint_engine(job, candidate)

    assert result.eliminated, "Candidate should be eliminated"
    assert result.elimination_reasons, "Should have at least one elimination reason"

    # Check the match itself
    match = canonical_key_match(emp_c, can_c)
    assert match is not None
    assert match.compatible is False
    assert match.score == 0.0
    assert match.match_type.value == "canonical_key"


# ---------------------------------------------------------------------------
# Task 5.7 — salary_max 85000 vs salary_min 90000 → hard fail, eliminated
# ---------------------------------------------------------------------------
def test_salary_hard_fail():
    """Employer max salary is 85,000; candidate min is 90,000 → eliminated."""
    emp_c = make_constraint("salary_max", 85000, ConstraintOperator.max)
    can_c = make_constraint(
        "salary_min",
        90000,
        ConstraintOperator.min,
        side=ConstraintSide.candidate,
        cid="salary-cand",
    )

    # salary_max (emp) vs salary_min (cand) — different canonical keys, no direct match
    # Simulate via same canonical key using salary_max on both sides
    emp_c2 = make_constraint("salary_max", 85000, ConstraintOperator.max)
    can_c2 = make_constraint(
        "salary_max",
        90000,
        ConstraintOperator.min,
        side=ConstraintSide.candidate,
        cid="salary-cand2",
    )

    match = canonical_key_match(emp_c2, can_c2)
    assert match is not None
    assert match.compatible is False, "90000 min > 85000 max — incompatible"
    assert match.score == 0.0

    job = make_job([emp_c2])
    candidate = make_candidate([can_c2])
    result = run_constraint_engine(job, candidate)
    assert result.eliminated, "Candidate should be eliminated on salary conflict"


# ---------------------------------------------------------------------------
# Task 5.8 — soft mismatch (four_day_week) → compatible, score < 1.0, not eliminated
# ---------------------------------------------------------------------------
def test_soft_mismatch_four_day_week():
    """Candidate prefers four-day week; employer doesn't offer it → not eliminated, score < 1.0."""
    # Employer has a hard requirement for 5-day full-time (office_days_per_week)
    # and candidate prefers 4-day week (four_day_week)
    can_c = make_constraint(
        "four_day_week",
        True,
        ConstraintOperator.prefers,
        constraint_type=ConstraintType.soft,
        side=ConstraintSide.candidate,
        cid="4day-cand",
    )

    # No matching employer constraint — so no-match path fires for this candidate preference
    job = make_job([])
    candidate = make_candidate([can_c])
    result = run_constraint_engine(job, candidate)

    assert not result.eliminated, "Soft mismatch should not eliminate candidate"
    # The candidate constraint is unmatched (no employer counterpart)
    assert can_c.id in result.unmatched_candidate_constraints

    # Now test with an employer constraint that prefers full-time
    emp_c = make_constraint(
        "four_day_week",
        False,
        ConstraintOperator.prefers,
        constraint_type=ConstraintType.soft,
        cid="4day-emp",
    )
    match = canonical_key_match(emp_c, can_c)
    assert match is not None
    assert match.compatible is True, "Soft mismatch should be compatible"
    assert match.score < 1.0, f"Score should be < 1.0 for a mismatch, got {match.score}"


# ---------------------------------------------------------------------------
# Task 5.9 — employer hard constraint with no candidate counterpart → compatible
# ---------------------------------------------------------------------------
def test_employer_hard_constraint_no_candidate_counterpart():
    """Employer has a hard constraint; candidate has nothing matching → compatible, no penalty."""
    emp_c = make_constraint(
        "management_required",
        True,
        ConstraintOperator.requires,
        constraint_type=ConstraintType.hard,
    )

    job = make_job([emp_c])
    candidate = make_candidate([])  # No constraints on candidate side

    result = run_constraint_engine(job, candidate)

    assert not result.eliminated, "Should not be eliminated when candidate has no counterpart"
    assert not result.elimination_reasons

    # The match should be no_candidate_constraint
    assert result.constraint_matches
    match = result.constraint_matches[0]
    assert match.match_type.value == "no_candidate_constraint"
    assert match.compatible is True
    assert match.score == 1.0


# ---------------------------------------------------------------------------
# Additional: canonical key match returns None for different keys
# ---------------------------------------------------------------------------
def test_canonical_key_match_different_keys_returns_none():
    emp_c = make_constraint("office_days_per_week", 5, ConstraintOperator.requires)
    can_c = make_constraint(
        "four_day_week",
        True,
        ConstraintOperator.prefers,
        side=ConstraintSide.candidate,
        cid="4d-cand",
    )
    result = canonical_key_match(emp_c, can_c)
    assert result is None


# ---------------------------------------------------------------------------
# Additional: compatible canonical match
# ---------------------------------------------------------------------------
def test_canonical_key_match_compatible():
    """Employer requires 3 days; candidate max is 3 → compatible."""
    emp_c = make_constraint("office_days_per_week", 3, ConstraintOperator.requires)
    can_c = make_constraint(
        "office_days_per_week",
        3,
        ConstraintOperator.max,
        side=ConstraintSide.candidate,
        cid="office-cand-ok",
    )
    match = canonical_key_match(emp_c, can_c)
    assert match is not None
    assert match.compatible is True
    assert match.score == 1.0
    assert match.match_type.value == "canonical_key"
