"""LLM-powered explanation generation for ranked candidates."""
from __future__ import annotations

import os
import threading

from dotenv import load_dotenv

from .models import (
    LLM_MODEL,
    Candidate,
    CompatibilityResult,
    ConstraintType,
    FeatureVector,
    JobDescription,
    PipelineResult,
    ScoredCandidate,
)

load_dotenv()

_anthropic_client = None
_client_lock = threading.Lock()


def _get_client():
    global _anthropic_client
    if _anthropic_client is None:
        with _client_lock:
            if _anthropic_client is None:
                import anthropic
                _anthropic_client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
    return _anthropic_client


# ---------------------------------------------------------------------------
# Explanation prompt
# ---------------------------------------------------------------------------
EXPLANATION_SYSTEM = """You are a senior recruiter writing structured candidate assessment notes for a hiring manager.

Write in three short paragraphs separated by a blank line:
1. Strengths — where this candidate best matches the role (skills, experience, background)
2. Gaps — the most significant limitations or development areas for this role
3. Practical flags — any logistics, constraints, or verification items worth noting; if everything is clean, say so briefly

Rules:
- Use plain English a hiring manager can act on. No technical jargon.
- Never use terms like "canonical", "score", "delta", "coefficient", "0.67", or any raw numbers.
- Do not describe constraint matches that are COMPATIBLE as problems or concerns.
- Be specific and evidence-based. Do not pad.
- 50–80 words per paragraph, three paragraphs total."""


def _format_constraint_matches(cr: CompatibilityResult) -> str:
    """Render constraint matches as plain-English labels for the LLM."""
    if not cr.constraint_matches:
        return "  (no employer constraints extracted)"

    flagged_ids = set(cr.flagged_for_review)
    lines: list[str] = []
    for m in cr.constraint_matches:
        if not m.compatible:
            status = "DOES NOT MEET"
        elif m.score < 0.7:
            status = "PARTIAL MATCH"
        else:
            status = "MEETS"
        flag = " [needs verification — low confidence extraction]" if m.employer_constraint_id in flagged_ids else ""
        lines.append(f"  [{status}] {m.reason[:120]}{flag}")
    return "\n".join(lines)


def _build_explanation_prompt(
    job: JobDescription,
    candidate: Candidate,
    fv: FeatureVector,
    cr: CompatibilityResult,
    score: float,
) -> str:
    constraint_block = _format_constraint_matches(cr)
    has_flags = bool(cr.flagged_for_review)

    return f"""Job: {job.title} at {job.company}
Candidate: {candidate.name}
Overall score: {score:.2f}/1.00

Feature breakdown:
- Required skills overlap: {fv.required_skills_overlap:.2f}
- Preferred skills overlap: {fv.preferred_skills_overlap:.2f}
- Industry preferred match: {fv.industry_preferred_match:.2f}
- Experience: {candidate.years_experience} yrs vs {job.min_years_experience} min required (delta score: {fv.experience_delta:.2f})
- Seniority: candidate={candidate.seniority_level}, role={job.seniority} (score: {fv.seniority_match:.2f})
- Career trajectory: {candidate.career_trajectory} (score: {fv.career_trajectory_score:.2f})
- Interview score: {fv.interview_score:.2f}
- Culture fit: {fv.culture_fit_score:.2f}
- Management: required={job.management_required}, candidate={candidate.management_experience} (score: {fv.management_match:.2f})
- Soft constraint score: {fv.soft_constraint_score:.2f}

Candidate skills: {', '.join(candidate.skills[:15]) or 'unknown'}
Required skills: {', '.join(job.required_skills[:10]) or 'none specified'}
Preferred skills: {', '.join(job.preferred_skills[:8]) or 'none specified'}

Constraint matches (ONLY discuss what is listed here — do not invent additional issues):
{constraint_block}

Write three short paragraphs (no headers, no bullet lists, plain English):
1. Strengths — specific skills and experience that match this role well
2. Gaps — honest assessment of where this candidate falls short of the requirements
3. Practical flags — logistics issues (location, salary, visa, right to work, availability) or constraint items needing verification; if none, one sentence saying everything checks out{"" if not has_flags else " — include the items flagged for verification"}"""


# ---------------------------------------------------------------------------
# Task 7.1 + 7.2: generate_explanation
# ---------------------------------------------------------------------------
def generate_explanation(
    job: JobDescription,
    candidate: Candidate,
    fv: FeatureVector,
    cr: CompatibilityResult,
    score: float,
) -> str:
    """Generate a human-readable explanation for a ranked candidate via LLM.

    The prompt includes constraint analysis and instructs the model to include
    a flag-for-review section when applicable (task 7.2).
    """
    prompt = _build_explanation_prompt(job, candidate, fv, cr, score)

    message = _get_client().messages.create(
        model=LLM_MODEL,
        max_tokens=512,
        system=EXPLANATION_SYSTEM,
        messages=[{"role": "user", "content": prompt}],
    )
    return message.content[0].text


# ---------------------------------------------------------------------------
# Task 7.3: Top-N threshold — only generate explanations for top N candidates
# ---------------------------------------------------------------------------
def generate_explanations_for_pipeline(
    job: JobDescription,
    candidates_by_id: dict[str, Candidate],
    pipeline_result: PipelineResult,
    top_n: int = 10,
) -> PipelineResult:
    """Populate .explanation fields for the top-N ranked candidates in parallel.

    Uses ThreadPoolExecutor so all LLM calls fire concurrently rather than
    sequentially. Wall-clock time drops from N × latency to ~1 × latency.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    top_candidates = [
        (i, sc)
        for i, sc in enumerate(pipeline_result.ranked_candidates)
        if i < top_n and candidates_by_id.get(sc.candidate_id) is not None
    ]

    print(f"    [explain] Generating {len(top_candidates)} explanations in parallel...", flush=True)

    def _explain(item: tuple[int, object]) -> tuple[int, str]:
        i, sc = item
        candidate = candidates_by_id[sc.candidate_id]
        return i, generate_explanation(
            job, candidate, sc.feature_vector, sc.constraint_result, sc.score
        )

    with ThreadPoolExecutor(max_workers=min(len(top_candidates), 10)) as pool:
        futures = {pool.submit(_explain, item): item for item in top_candidates}
        for future in as_completed(futures):
            i, explanation = future.result()
            pipeline_result.ranked_candidates[i].explanation = explanation

    return pipeline_result


# ---------------------------------------------------------------------------
# Task 7.4: Format elimination reason (no LLM)
# ---------------------------------------------------------------------------
def format_elimination_reason(cr: CompatibilityResult) -> str:
    """Return a structured elimination reason string for a rejected candidate."""
    if not cr.elimination_reasons:
        return "Eliminated: reason unknown."

    lines = ["ELIMINATED — Hard constraint failures:"]
    for reason in cr.elimination_reasons:
        lines.append(f"  • {reason}")

    if cr.flagged_for_review:
        lines.append(
            f"\nAdditionally, {len(cr.flagged_for_review)} constraint(s) were flagged "
            "for review due to low confidence in the extracted data."
        )

    return "\n".join(lines)
