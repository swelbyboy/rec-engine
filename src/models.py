from __future__ import annotations
from enum import Enum
from typing import Literal
from pydantic import BaseModel, Field

Discipline = Literal["engineering", "data", "ml_ai", "product", "design", "devops", "sales", "other"]


LLM_MODEL = "claude-haiku-4-5"


class ConstraintType(str, Enum):
    hard = "hard"
    soft = "soft"


class ConstraintSide(str, Enum):
    employer = "employer"
    candidate = "candidate"


class ConstraintOperator(str, Enum):
    requires = "requires"
    max = "max"
    min = "min"
    prefers = "prefers"
    excludes = "excludes"
    one_of = "one_of"


class Constraint(BaseModel):
    id: str
    type: ConstraintType
    side: ConstraintSide
    category: str  # e.g. "location", "compensation", "visa", "skills", "culture"
    description: str
    canonical_key: str | None = None  # e.g. "office_days_per_week", "salary_min"
    value: str | float | bool | list | dict | None = None
    operator: ConstraintOperator
    weight: float = Field(default=1.0, ge=0.0, le=1.0)
    confidence: float = Field(ge=0.0, le=1.0)
    currency: str | None = None  # ISO 4217 code for salary constraints: "GBP", "USD", "EUR"


class JobDescription(BaseModel):
    id: str
    title: str
    company: str
    raw_text: str
    required_skills: list[str] = []
    preferred_skills: list[str] = []
    min_years_experience: int = 0
    seniority: str  # e.g. "junior", "mid", "senior", "lead", "principal"
    management_required: bool = False
    industries_preferred: list[str] = []
    industries_acceptable: list[str] = []
    constraints: list[Constraint] = []
    discipline: Discipline = "other"


class Candidate(BaseModel):
    id: str
    name: str
    raw_cv: str
    raw_linkedin: str
    raw_interview_transcript: str
    years_experience: float = 0.0
    skills: list[str] = []
    industries: list[str] = []
    seniority_level: str = "mid"
    management_experience: bool = False
    education_level: str = "bachelor"
    career_trajectory: Literal["ascending", "lateral", "mixed"] = "ascending"
    interview_score: float = Field(default=0.5, ge=0.0, le=1.0)
    culture_fit_score: float = Field(default=0.5, ge=0.0, le=1.0)
    constraints: list[Constraint] = []
    discipline: Discipline = "other"


class MatchType(str, Enum):
    canonical_key = "canonical_key"
    semantic = "semantic"
    no_candidate_constraint = "no_candidate_constraint"
    no_match = "no_match"


class ConstraintMatch(BaseModel):
    employer_constraint_id: str
    candidate_constraint_id: str | None = None
    match_type: MatchType
    compatible: bool
    score: float = Field(ge=0.0, le=1.0)  # 1.0 = full match, 0.0 = hard fail
    reason: str = ""
    flagged_for_review: bool = False


class CompatibilityResult(BaseModel):
    candidate_id: str
    eliminated: bool
    elimination_reasons: list[str] = []
    constraint_matches: list[ConstraintMatch] = []
    unmatched_candidate_constraints: list[str] = []  # constraint IDs
    flagged_for_review: list[str] = []  # constraint IDs


class FeatureVector(BaseModel):
    candidate_id: str
    required_skills_overlap: float = Field(ge=0.0, le=1.0)
    preferred_skills_overlap: float = Field(ge=0.0, le=1.0)
    industry_preferred_match: float = Field(ge=0.0, le=1.0)
    experience_delta: float = Field(ge=0.0, le=1.0)
    seniority_match: float = Field(ge=0.0, le=1.0)
    career_trajectory_score: float = Field(ge=0.0, le=1.0)
    interview_score: float = Field(ge=0.0, le=1.0)
    culture_fit_score: float = Field(ge=0.0, le=1.0)
    management_match: float = Field(ge=0.0, le=1.0)
    soft_constraint_score: float = Field(ge=0.0, le=1.0)


DEFAULT_WEIGHTS: dict[str, float] = {
    "required_skills_overlap": 0.38,   # +0.10 from reduced proxy signals below
    "preferred_skills_overlap": 0.10,
    "industry_preferred_match": 0.12,
    "experience_delta": 0.10,
    "seniority_match": 0.08,
    "career_trajectory_score": 0.05,   # soft signal, intentionally low weight
    "interview_score": 0.03,           # LLM-assessed proxy — reduced to limit bias risk
    "culture_fit_score": 0.02,         # LLM-assessed proxy — reduced to limit bias risk
    "management_match": 0.04,
    "soft_constraint_score": 0.08,
}



class ScoredCandidate(BaseModel):
    candidate_id: str
    name: str
    score: float = Field(ge=0.0, le=1.0)
    feature_vector: FeatureVector
    constraint_result: CompatibilityResult
    explanation: str = ""


class EliminatedCandidate(BaseModel):
    candidate_id: str
    name: str
    elimination_reasons: list[str]
    constraint_result: CompatibilityResult


class PipelineResult(BaseModel):
    job_id: str
    ranked_candidates: list[ScoredCandidate]
    eliminated_candidates: list[EliminatedCandidate]
    weights_used: dict[str, float]


# Raw fixture types (before LLM parsing)

class RawCandidate(BaseModel):
    id: str
    name: str
    cv: str
    linkedin: str
    interview_transcript: str


class RawJob(BaseModel):
    id: str
    title: str
    company: str
    description: str
