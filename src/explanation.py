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
EXPLANATION_SYSTEM = """You are a senior recruiter writing structured candidate assessment notes.
Be concise (150–250 words), specific, and evidence-based.
Write in plain prose — no bullet lists, no markdown headers.

CRITICAL: Base your assessment ONLY on the data explicitly provided below.
Do NOT invent constraint conflicts, concerns, or strengths not present in the constraint matches list.
If a constraint shows COMPATIBLE, do not describe it as a conflict or concern."""


def _format_constraint_matches(cr: CompatibilityResult) -> str:
    """Render constraint matches as a grounded, labelled list for the LLM."""
    if not cr.constraint_matches:
        return "  (no employer constraints extracted)"

    flagged_ids = set(cr.flagged_for_review)
    lines: list[str] = []
    for m in cr.constraint_matches:
        if not m.compatible:
            status = "INCOMPATIBLE"
        elif m.score < 0.7:
            status = "SOFT MISMATCH"
        else:
            status = "COMPATIBLE"
        flag = " [low confidence — needs verification]" if m.employer_constraint_id in flagged_ids else ""
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

Write a 150–250 word recruiter assessment covering:
1. Fit summary — strongest alignment points based on the feature scores above
2. Constraint analysis — describe only the constraints listed above; use the COMPATIBLE/SOFT MISMATCH/INCOMPATIBLE labels to guide your language
{"3. Flag-for-review — list what a recruiter should verify (low-confidence extractions only)" if has_flags else ""}

Do not include section headers. Write in continuous prose."""


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
    """Populate .explanation fields for the top-N ranked candidates (in-place).

    Eliminated candidates get a structured string (no LLM call) per task 7.4.
    Candidates ranked beyond top_n get an empty explanation.

    Returns the same PipelineResult with explanations populated.
    """
    # Top-N ranked candidates → LLM explanation
    for i, sc in enumerate(pipeline_result.ranked_candidates):
        if i >= top_n:
            break
        candidate = candidates_by_id.get(sc.candidate_id)
        if candidate is None:
            continue
        print(f"    [explain] {candidate.name}...", flush=True)
        sc.explanation = generate_explanation(
            job, candidate, sc.feature_vector, sc.constraint_result, sc.score
        )

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
