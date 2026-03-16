"""Unit tests for feature extraction.

These tests use real LLM calls; set ANTHROPIC_API_KEY before running.
Run: pytest tests/test_extraction.py -v
"""
import pytest

from src.extraction import parse_candidate_source, parse_job_description
from src.models import JobDescription


SAMPLE_JD_TEXT = """
Senior Data Engineer — Apex Fintech Ltd, London

We are looking for a Senior Data Engineer to join our Data Platform team.

Requirements:
- 4+ years of data engineering experience
- Strong proficiency in Python and SQL
- Experience with dbt and Snowflake
- This role requires 5 days per week in our Canary Wharf office
- We do not offer visa sponsorship; candidates must have the right to work in the UK
- Salary up to £85,000

Nice to have: Apache Kafka experience, Great Expectations, Apache Airflow
"""

SAMPLE_CANDIDATE_CV = """
Jane Smith
jane.smith@email.com | London, UK

SENIOR DATA ENGINEER

5 years of experience in fintech data engineering.
Expert in Python, SQL, dbt, and Snowflake.
Currently at Barclays CIB building payment reconciliation pipelines.
British citizen with right to work in UK.
"""


@pytest.mark.integration
def test_parse_jd_returns_required_fields():
    """Parsed JD must have all required fields and at least one constraint."""
    jd = parse_job_description(SAMPLE_JD_TEXT, job_id="test-001")

    assert isinstance(jd, JobDescription)
    assert jd.title, "title must be non-empty"
    assert jd.required_skills, "required_skills must be non-empty"
    assert jd.min_years_experience >= 0
    assert jd.seniority in ("junior", "mid", "senior", "lead", "principal", "staff")
    assert len(jd.constraints) >= 1, "At least one constraint must be extracted"


@pytest.mark.integration
def test_parse_jd_extracts_hard_constraints():
    """Office days and visa should be extracted as hard constraints."""
    jd = parse_job_description(SAMPLE_JD_TEXT, job_id="test-001")

    canonical_keys = {c.canonical_key for c in jd.constraints}
    # At minimum, the office requirement or visa should be picked up
    assert canonical_keys & {"office_days_per_week", "visa_sponsorship"}, (
        f"Expected at least one of office_days_per_week/visa_sponsorship, got: {canonical_keys}"
    )


@pytest.mark.integration
def test_parse_candidate_confidence_range():
    """All confidence values on extracted constraints must be in [0.0, 1.0]."""
    extract = parse_candidate_source(SAMPLE_CANDIDATE_CV, "cv")

    for constraint in extract.get("constraints", []):
        confidence = float(constraint["confidence"])
        assert 0.0 <= confidence <= 1.0, (
            f"Confidence out of range: {confidence} for constraint: {constraint}"
        )


@pytest.mark.integration
def test_parse_candidate_returns_skills():
    """CV extraction must return a non-empty skills list."""
    extract = parse_candidate_source(SAMPLE_CANDIDATE_CV, "cv")
    assert extract.get("skills"), "skills must be non-empty for a CV with clear skill mentions"


@pytest.mark.integration
def test_parse_jd_does_not_infer_missing_salary():
    """If JD has no salary info, no salary constraint should be extracted."""
    no_salary_jd = """
    Senior Data Engineer — Acme Corp, London

    We need an experienced data engineer with Python and SQL skills.
    Must be in the office 3 days per week.
    """
    jd = parse_job_description(no_salary_jd, job_id="test-002")
    salary_constraints = [
        c for c in jd.constraints
        if c.canonical_key in ("salary_min", "salary_max")
    ]
    assert not salary_constraints, (
        "Should not infer salary constraints when none are stated"
    )
