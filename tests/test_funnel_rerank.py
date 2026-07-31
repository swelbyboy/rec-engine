"""Unit tests for funnel_rerank.py's deterministic elimination stages.

_apply_skill_floor_check calls skill_match_detail_batch (OpenAI embeddings),
so its tests are marked @pytest.mark.integration and skipped unless
OPENAI_API_KEY is set — same convention as tests/test_scoring.py.

Run pure unit tests:
    pytest tests/test_funnel_rerank.py -v -m "not integration"

Run all (requires OPENAI_API_KEY):
    pytest tests/test_funnel_rerank.py -v
"""
import numpy as np
import pytest

from src.funnel_rerank import (
    SKILL_FLOOR_RATIO,
    TITLE_RELEVANCE_FLOOR,
    _apply_skill_floor_check,
    _apply_title_relevance_check,
    _merge_ranked_batches,
    fine_rerank,
    select_by_coarse_bucket,
)
from src.models import Candidate, CompatibilityResult, JobDescription


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def make_job(required_skills: list[str] | None = None, title: str = "Test Job") -> JobDescription:
    return JobDescription(
        id="job-test",
        title=title,
        company="Test Co",
        raw_text="",
        required_skills=required_skills or [],
        preferred_skills=[],
        min_years_experience=0,
        seniority="senior",
        management_required=False,
        industries_preferred=[],
        constraints=[],
    )


def make_candidate(candidate_id: str, skills: list[str] | None = None) -> Candidate:
    return Candidate(
        id=candidate_id,
        name=f"Candidate {candidate_id}",
        raw_cv="",
        raw_linkedin="",
        raw_interview_transcript="",
        years_experience=5.0,
        skills=skills or [],
        industries=[],
        seniority_level="senior",
        management_experience=False,
        interview_score=0.7,
        culture_fit_score=0.7,
        career_trajectory="ascending",
        constraints=[],
    )


def empty_compatibility_result(candidate_id: str) -> CompatibilityResult:
    return CompatibilityResult(
        candidate_id=candidate_id,
        eliminated=False,
        elimination_reasons=[],
        constraint_matches=[],
        unmatched_candidate_constraints=[],
        flagged_for_review=[],
    )


REQUIRED_SKILLS = [
    "Node.js", "NestJS", "TypeScript", "PostgreSQL", "REST API design",
    "microservices", "event-driven architecture", "Docker", "Kubernetes",
    "LLM agents",
]  # 10 skills


# ---------------------------------------------------------------------------
# No-op when the job has no required skills
# ---------------------------------------------------------------------------
def test_no_required_skills_is_noop():
    job = make_job(required_skills=[])
    candidate = make_candidate("cand-001", skills=[])
    cr = empty_compatibility_result("cand-001")

    passed, eliminated = _apply_skill_floor_check(job, [(candidate, cr)])

    assert eliminated == []
    assert passed == [(candidate, cr)]
    assert cr.eliminated is False


# ---------------------------------------------------------------------------
# Coverage-ratio gating (requires real embeddings)
# ---------------------------------------------------------------------------
@pytest.mark.integration
def test_low_coverage_candidate_is_eliminated():
    """A Product-Manager-shaped skill set evidences ~0 of 10 backend skills."""
    job = make_job(required_skills=REQUIRED_SKILLS)
    candidate = make_candidate(
        "cand-pm",
        skills=["Product strategy", "Roadmapping", "Stakeholder management", "Jira", "Figma"],
    )
    cr = empty_compatibility_result("cand-pm")

    passed, eliminated = _apply_skill_floor_check(job, [(candidate, cr)])

    assert passed == []
    assert len(eliminated) == 1
    assert eliminated[0][1].eliminated is True
    reason = eliminated[0][1].elimination_reasons[-1]
    assert "skill-floor" in reason.lower()
    assert f"{SKILL_FLOOR_RATIO:.0%}" in reason


@pytest.mark.integration
def test_high_coverage_candidate_passes():
    """A candidate evidencing most required skills should pass through unchanged."""
    job = make_job(required_skills=REQUIRED_SKILLS)
    candidate = make_candidate(
        "cand-eng",
        skills=[
            "Node.js", "NestJS", "TypeScript", "PostgreSQL", "REST APIs",
            "Microservices architecture", "Docker", "Kubernetes",
        ],
    )
    cr = empty_compatibility_result("cand-eng")

    passed, eliminated = _apply_skill_floor_check(job, [(candidate, cr)])

    assert eliminated == []
    assert len(passed) == 1
    assert passed[0][1].eliminated is False
    assert passed[0][1].elimination_reasons == []


# ---------------------------------------------------------------------------
# _merge_ranked_batches — pure logic, no API calls
# ---------------------------------------------------------------------------
def test_merge_sorts_by_verdict_tier_then_skill_coverage():
    pool = [make_candidate("a"), make_candidate("b"), make_candidate("c"), make_candidate("d")]
    batches = [
        [
            {"candidate_id": "a", "verdict": "possible", "rationale": "r-a"},
            {"candidate_id": "b", "verdict": "strong_match", "rationale": "r-b"},
        ],
        [
            {"candidate_id": "c", "verdict": "strong_match", "rationale": "r-c"},
            {"candidate_id": "d", "verdict": "weak_match", "rationale": "r-d"},
        ],
    ]
    # b and c are both strong_match (from different chunks) — c has higher
    # skill coverage, so it should be ranked ahead of b within that tier.
    skill_coverage = {"a": 1, "b": 2, "c": 5, "d": 0}

    merged = _merge_ranked_batches(batches, pool, skill_coverage)

    assert [item["candidate_id"] for item in merged] == ["c", "b", "a", "d"]


def test_merge_appends_missing_candidates_flagged_for_review():
    pool = [make_candidate("a"), make_candidate("b")]
    # "b" never appears in any chunk's returned output (dropped/omitted).
    batches = [[{"candidate_id": "a", "verdict": "good_match", "rationale": "r-a"}]]

    merged = _merge_ranked_batches(batches, pool, {"a": 3, "b": 0})

    assert [item["candidate_id"] for item in merged] == ["a", "b"]
    assert merged[1]["verdict"] == "weak_match"
    assert "not returned" in merged[1]["rationale"].lower()


def test_merge_skips_malformed_items_without_crashing():
    """Seen in practice: a chunk occasionally returns a plain candidate_id
    string instead of the expected {candidate_id, verdict, rationale} object.
    That candidate should fall through to the missing-candidate fallback,
    not crash the whole merge."""
    pool = [make_candidate("a"), make_candidate("b")]
    batches = [
        [
            {"candidate_id": "a", "verdict": "good_match", "rationale": "r-a"},
            "b",  # malformed — a bare string instead of an object
        ]
    ]

    merged = _merge_ranked_batches(batches, pool, {"a": 2, "b": 0})

    assert [item["candidate_id"] for item in merged] == ["a", "b"]
    assert merged[1]["verdict"] == "weak_match"


def test_merge_dedupes_candidate_appearing_in_multiple_chunks():
    pool = [make_candidate("a")]
    # Same candidate appearing twice (e.g. a repair-adjacent edge case) —
    # last-seen entry wins; no duplicate rows in the final list.
    batches = [
        [{"candidate_id": "a", "verdict": "possible", "rationale": "first"}],
        [{"candidate_id": "a", "verdict": "strong_match", "rationale": "second"}],
    ]

    merged = _merge_ranked_batches(batches, pool, {"a": 1})

    assert len(merged) == 1
    assert merged[0]["rationale"] == "second"


# ---------------------------------------------------------------------------
# select_by_coarse_bucket — pure logic, no API calls
# ---------------------------------------------------------------------------
def test_select_by_coarse_bucket_prefers_best_nonempty_bucket():
    pool = [make_candidate(cid) for cid in ("a", "b", "c", "d")]
    buckets = {"a": "no", "b": "strong", "c": "maybe", "d": "strong"}

    selected = select_by_coarse_bucket(pool, buckets, top_n=10)

    assert {c.id for c in selected} == {"b", "d"}


def test_select_by_coarse_bucket_unbucketed_defaults_to_maybe():
    pool = [make_candidate(cid) for cid in ("a", "b")]
    buckets = {"a": "no"}  # "b" is missing — a failed/dropped triage chunk

    selected = select_by_coarse_bucket(pool, buckets, top_n=10)

    assert {c.id for c in selected} == {"b"}


def test_select_by_coarse_bucket_respects_top_n():
    pool = [make_candidate(cid) for cid in ("a", "b", "c")]
    buckets = {"a": "strong", "b": "strong", "c": "strong"}

    selected = select_by_coarse_bucket(pool, buckets, top_n=2)

    assert len(selected) == 2


def test_select_by_coarse_bucket_all_no_still_returns_pool():
    """"no" is the only non-empty bucket — still forwarded, not zeroed out.

    Matches Mind's own fail-safe: triage should never be the sole reason a
    pool goes from something to nothing; the fine-rerank stage still gets a
    chance to judge, same as when triage fails to bucket anyone at all.
    """
    pool = [make_candidate(cid) for cid in ("a", "b")]
    buckets = {"a": "no", "b": "no"}

    selected = select_by_coarse_bucket(pool, buckets, top_n=10)

    assert {c.id for c in selected} == {"a", "b"}


# ---------------------------------------------------------------------------
# _apply_title_relevance_check — cosine-threshold logic, with a fake embedder
# so this stays a pure/fast test (no live OpenAI call)
# ---------------------------------------------------------------------------
def test_title_relevance_check_eliminates_low_similarity(monkeypatch):
    import src.funnel_rerank as fr

    job = make_job(title="Backend Engineer")
    monkeypatch.setattr(fr, "_embed_title", lambda text: np.array([1.0, 0.0]))

    close = make_candidate("close")
    far = make_candidate("far")
    title_embeddings = {
        "close": np.array([0.9, 0.1]),   # cosine ~0.99 — same discipline
        "far": np.array([0.0, 1.0]),     # cosine 0.0 — clearly different discipline
    }
    pairs = [
        (close, empty_compatibility_result("close")),
        (far, empty_compatibility_result("far")),
    ]

    passed, eliminated = _apply_title_relevance_check(job, title_embeddings, pairs)

    assert [c.id for c, _ in passed] == ["close"]
    assert [c.id for c, _ in eliminated] == ["far"]
    assert eliminated[0][1].eliminated is True
    assert "title-relevance" in eliminated[0][1].elimination_reasons[-1].lower()


def test_title_relevance_check_passes_through_missing_embeddings(monkeypatch):
    import src.funnel_rerank as fr

    job = make_job(title="Backend Engineer")
    monkeypatch.setattr(fr, "_embed_title", lambda text: np.array([1.0, 0.0]))

    candidate = make_candidate("no-embedding")
    pairs = [(candidate, empty_compatibility_result("no-embedding"))]

    # No entry in title_embeddings for this candidate — no signal, no elimination.
    passed, eliminated = _apply_title_relevance_check(job, {}, pairs)

    assert eliminated == []
    assert [c.id for c, _ in passed] == ["no-embedding"]


def test_title_relevance_floor_is_lenient():
    """Sanity check the constant itself stays in the 'lenient' range the plan
    calls for — should catch extreme mismatches only, not adjacent disciplines."""
    assert 0.0 < TITLE_RELEVANCE_FLOOR <= 0.4


# ---------------------------------------------------------------------------
# fine_rerank enrichment — matched/missing skills attached without changing
# verdict/order. Fakes out the LLM call and embedding batch so this stays a
# fast, non-integration test.
# ---------------------------------------------------------------------------
def test_fine_rerank_attaches_skill_detail_without_changing_order(monkeypatch):
    import src.funnel_rerank as fr

    job = make_job(required_skills=["Python", "React"], title="Engineer")
    candidates = [make_candidate("a"), make_candidate("b")]
    compat = {
        "a": empty_compatibility_result("a"),
        "b": empty_compatibility_result("b"),
    }

    fake_skill_detail = {
        "a": (["Python", "React"], []),
        "b": (["Python"], ["React"]),
    }
    monkeypatch.setattr(fr, "skill_match_detail_batch", lambda *_args, **_kw: fake_skill_detail)

    fake_ranked = [
        {"candidate_id": "a", "verdict": "strong_match", "rationale": "great fit"},
        {"candidate_id": "b", "verdict": "good_match", "rationale": "missing React"},
    ]
    monkeypatch.setattr(fr, "_fine_rerank_chunk", lambda *_args, **_kw: fake_ranked)

    result = fine_rerank(job, {}, candidates, compat)

    assert [item["candidate_id"] for item in result] == ["a", "b"]
    assert [item["verdict"] for item in result] == ["strong_match", "good_match"]
    assert result[0]["matched_skills"] == ["Python", "React"]
    assert result[0]["missing_required_skills"] == []
    assert result[1]["matched_skills"] == ["Python"]
    assert result[1]["missing_required_skills"] == ["React"]
