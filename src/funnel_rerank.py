"""Coarse-then-fine LLM ranking funnel mirroring Mind's current matching model.

Mind's matching shape is: hard-cutoff filter -> coarse LLM extraction of role
requirements -> fine-grained LLM rerank producing verdicts. The filter stage
here is rec-engine's existing constraint_engine.py (unmodified). Structured
extraction of skills/seniority/constraints already happens in extraction.py's
parse_job_description — this module adds one more lightweight coarse call for
recruiter-facing framing and flexibility judgment, then the fine-grained rerank
itself.

Deliberately NOT used here: scoring.py / ml_scoring.py (weighted-linear / ML
scoring) — see design.md decision 2. The final candidate order comes solely
from this coarse-then-fine LLM funnel.
"""
from __future__ import annotations

import os
import threading

from dotenv import load_dotenv

from .constraint_engine import run_constraint_engine
from .explanation import _format_constraint_matches
from .models import LLM_MODEL, Candidate, CompatibilityResult, JobDescription

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


def _call_tool(messages: list[dict], tool_schema: dict, system: str, max_tokens: int = 4096) -> dict:
    print(f"    [LLM] {tool_schema['name']}...", flush=True)
    response = _get_client().messages.create(
        model=LLM_MODEL,
        max_tokens=max_tokens,
        system=system,
        tools=[tool_schema],
        tool_choice={"type": "tool", "name": tool_schema["name"]},
        messages=messages,
    )
    for block in response.content:
        if block.type == "tool_use":
            return block.input
    raise RuntimeError("No tool use block in response")


# ---------------------------------------------------------------------------
# Stage 1: coarse role briefing
# ---------------------------------------------------------------------------

COARSE_SYSTEM = """You are a senior recruiter preparing a role briefing before sourcing candidates.

Given a job's extracted requirements and hard constraints, produce:
1. A short (2-3 sentence) plain-English summary of what this role actually needs
2. Flexibility notes: for each hard constraint, judge whether it reads as
   genuinely non-negotiable or whether the phrasing/context suggests some flex
   is realistic (e.g. a salary cap on a role that's hard to fill, a clearance
   requirement that's truly fixed by law/contract). Be conservative — only call
   out flex where the text gives a real signal, not by default.
3. Two targeted yes/no/unclear questions used for a deterministic cross-check
   against structured candidate data (location and right-to-work are common
   enough, and phrased inconsistently enough across job postings, that they get
   a dedicated check rather than relying on free-text constraint matching):
   - requires_uk_based: does this role require the candidate to already be
     based in / have the right to work in the UK, with no visa sponsorship?
   - offers_visa_sponsorship: does the employer explicitly offer or allow visa
     sponsorship for this role?

This briefing guides how a second-pass reviewer weighs borderline candidates —
it does not override the constraints themselves."""

COARSE_TOOL_SCHEMA = {
    "name": "summarize_role",
    "description": "Produce a recruiter-facing role briefing with flexibility judgment.",
    "input_schema": {
        "type": "object",
        "properties": {
            "summary": {"type": "string"},
            "flexibility_notes": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "constraint_description": {"type": "string"},
                        "flex_judgment": {
                            "type": "string",
                            "enum": ["rigid", "some_flex", "likely_flexible"],
                        },
                        "reason": {"type": "string"},
                    },
                    "required": ["constraint_description", "flex_judgment", "reason"],
                },
            },
            "requires_uk_based": {"type": "string", "enum": ["yes", "no", "unclear"]},
            "offers_visa_sponsorship": {"type": "string", "enum": ["yes", "no", "unclear"]},
        },
        "required": ["summary", "flexibility_notes", "requires_uk_based", "offers_visa_sponsorship"],
    },
}


def coarse_role_brief(job: JobDescription) -> dict:
    """Stage 1: recruiter-facing role summary + flexibility judgment on hard constraints."""
    hard_constraints = [c for c in job.constraints if c.type.value == "hard"]
    constraint_lines = "\n".join(
        f"- [{c.category}] {c.description} (operator={c.operator.value}, value={c.value})"
        for c in hard_constraints
    ) or "(no hard constraints extracted)"

    prompt = f"""Role: {job.title} at {job.company}
Seniority: {job.seniority} | Min years experience: {job.min_years_experience}
Required skills: {', '.join(job.required_skills) or 'none specified'}
Preferred skills: {', '.join(job.preferred_skills) or 'none specified'}

Hard constraints:
{constraint_lines}"""

    return _call_tool([{"role": "user", "content": prompt}], COARSE_TOOL_SCHEMA, COARSE_SYSTEM)


# ---------------------------------------------------------------------------
# Stage 2: fine-grained rerank
# ---------------------------------------------------------------------------

FINE_RERANK_SYSTEM = """You are a senior recruiter producing a ranked shortlist for a hiring manager.

You are given a role briefing and a pool of candidates who have already passed
hard-constraint filtering (visa, location, salary range, clearance, etc. have
already been checked — do not re-litigate those). Your job is to judge FIT:
how well each candidate's skills, experience, and background match what this
role actually needs, using the constraint-match detail and background provided
for each candidate.

For each candidate, assign:
- verdict: "strong_match" | "good_match" | "possible" | "weak_match"
- rationale: 2-3 sentences, specific and evidence-based, for a recruiter to act on

Then return ALL candidates ordered from best to worst fit for this specific role.

Rules:
- Judge fit for THIS role, not general competence.
- Be honest about weak fits — do not inflate verdicts to be polite.
- Ground every claim in the provided candidate data; do not invent experience.
- Flagged-for-review constraint matches are not disqualifying — mention them in
  rationale only if genuinely relevant to fit."""

FINE_RERANK_TOOL_SCHEMA = {
    "name": "rank_candidates",
    "description": "Rank a pool of pre-filtered candidates for a role.",
    "input_schema": {
        "type": "object",
        "properties": {
            "ranked": {
                "type": "array",
                "description": "ALL candidates from the pool, ordered best-fit first",
                "items": {
                    "type": "object",
                    "properties": {
                        "candidate_id": {"type": "string"},
                        "verdict": {
                            "type": "string",
                            "enum": ["strong_match", "good_match", "possible", "weak_match"],
                        },
                        "rationale": {"type": "string"},
                    },
                    "required": ["candidate_id", "verdict", "rationale"],
                },
            },
        },
        "required": ["ranked"],
    },
}


def _format_candidate_block(candidate: Candidate, cr: CompatibilityResult) -> str:
    constraint_block = _format_constraint_matches(cr)
    flagged = " (some constraint matches flagged for review — verify manually)" if cr.flagged_for_review else ""
    return f"""### Candidate {candidate.id}: {candidate.name}
Experience: {candidate.years_experience} yrs | Seniority: {candidate.seniority_level}
Skills: {', '.join(candidate.skills[:20]) or 'none listed'}
Background: {candidate.raw_linkedin or '(no summary)'}
CV notes: {candidate.raw_cv or '(none)'}
Recruiter call notes: {candidate.raw_interview_transcript or '(none)'}

Constraint match against this role{flagged}:
{constraint_block}"""


def fine_rerank(
    job: JobDescription,
    coarse_brief: dict,
    candidates: list[Candidate],
    compatibility_results: dict[str, CompatibilityResult],
    max_candidates: int = 40,
) -> list[dict]:
    """Stage 2: rank the constraint-filtered pool with verdict + rationale.

    Single batched call rather than one call per candidate — cheaper, faster,
    and lets the model make relative judgments across the whole pool rather
    than scoring each candidate in isolation.
    """
    pool = candidates[:max_candidates]
    if not pool:
        return []

    candidate_blocks = "\n\n".join(
        _format_candidate_block(c, compatibility_results[c.id]) for c in pool
    )

    prompt = f"""Role: {job.title} at {job.company}
Role briefing: {coarse_brief.get('summary', '')}

Candidates to rank ({len(pool)} total, all already passed hard-constraint filtering):

{candidate_blocks}"""

    result = _call_tool(
        [{"role": "user", "content": prompt}],
        FINE_RERANK_TOOL_SCHEMA,
        FINE_RERANK_SYSTEM,
        max_tokens=min(1024 + 220 * len(pool), 8192),
    )
    return result.get("ranked", [])


def _candidate_flag(candidate: Candidate, canonical_key: str) -> bool | None:
    for c in candidate.constraints:
        if c.canonical_key == canonical_key:
            return bool(c.value)
    return None


def _apply_location_visa_check(
    coarse_brief: dict,
    candidates_with_results: list[tuple[Candidate, CompatibilityResult]],
) -> tuple[list[tuple[Candidate, CompatibilityResult]], list[tuple[Candidate, CompatibilityResult]]]:
    """Deterministic safety-net for the UK-based / visa-sponsorship dimension.

    The generic constraint engine's canonical-key + embedding matching proved
    unreliable for this specific dimension in testing: the employer-side
    canonical_key drifts across separate extraction runs ("uk_based" /
    "location_uk_based" / "work_location_requirement" all seen for the same
    JD across different calls), and even near-identical phrasings ("Must be
    UK-based" vs "UK-based: Yes") scored well under the embedding
    semantic-match threshold (0.65 vs a 0.75 cutoff). Since Mothership gives
    clean boolean ground truth for this (is_uk, requires_visa) and it's one of
    the most common, highest-stakes recruiting filters, it gets a dedicated,
    deterministic check here rather than relying solely on free-text
    constraint matching.
    """
    requires_uk = coarse_brief.get("requires_uk_based") == "yes"
    sponsors_visa = coarse_brief.get("offers_visa_sponsorship") == "yes"

    still_passed: list[tuple[Candidate, CompatibilityResult]] = []
    newly_eliminated: list[tuple[Candidate, CompatibilityResult]] = []
    for c, cr in candidates_with_results:
        is_uk = _candidate_flag(c, "uk_based")
        needs_sponsorship = _candidate_flag(c, "work_authorization")  # True = candidate needs sponsorship

        if requires_uk and not sponsors_visa and is_uk is False:
            cr.elimination_reasons.append(
                "Deterministic location check: role requires UK-based candidates with "
                "no sponsorship; candidate's recorded location is not UK-based"
            )
            cr.eliminated = True
            newly_eliminated.append((c, cr))
            continue

        if requires_uk and not sponsors_visa and needs_sponsorship is True:
            cr.elimination_reasons.append(
                "Deterministic visa check: role does not offer sponsorship; candidate requires it"
            )
            cr.eliminated = True
            newly_eliminated.append((c, cr))
            continue

        still_passed.append((c, cr))

    return still_passed, newly_eliminated


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def run_live_pipeline(job_order_id: int, candidate_limit: int = 150, rerank_limit: int = 40) -> dict:
    """Full live pipeline: fetch -> extract -> filter -> coarse brief -> fine rerank."""
    from . import live_data
    from .extraction import parse_job_description

    job_raw = live_data.fetch_job_raw(job_order_id)
    job = parse_job_description(
        job_raw["raw_text"], job_id=job_raw["id"], title=job_raw["title"], company=job_raw["company"]
    )

    candidates = live_data.fetch_candidates(limit=candidate_limit)

    eliminated: list[tuple[Candidate, CompatibilityResult]] = []
    passed: list[tuple[Candidate, CompatibilityResult]] = []
    compat_by_id: dict[str, CompatibilityResult] = {}
    for c in candidates:
        cr = run_constraint_engine(job, c)
        compat_by_id[c.id] = cr
        (eliminated if cr.eliminated else passed).append((c, cr))

    coarse = coarse_role_brief(job)
    passed, newly_eliminated = _apply_location_visa_check(coarse, passed)
    eliminated.extend(newly_eliminated)

    ranked_raw = fine_rerank(
        job, coarse, [c for c, _ in passed], compat_by_id, max_candidates=rerank_limit
    )

    candidates_by_id = {c.id: c for c, _ in passed}
    ranked = []
    for item in ranked_raw:
        c = candidates_by_id.get(item["candidate_id"])
        if c is None:
            continue
        cr = compat_by_id[c.id]
        ranked.append({
            "candidate_id": c.id,
            "name": c.name,
            "verdict": item["verdict"],
            "rationale": item["rationale"],
            "flagged_for_review": bool(cr.flagged_for_review),
        })

    return {
        "job": {"id": job.id, "title": job.title, "company": job.company},
        "coarse_brief": coarse,
        "ranked": ranked,
        "eliminated": [
            {"candidate_id": c.id, "name": c.name, "reasons": cr.elimination_reasons}
            for c, cr in eliminated
        ],
        "candidates_considered": len(candidates),
        "candidates_passed_filter": len(passed),
    }
