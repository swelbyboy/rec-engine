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

import json
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np
from dotenv import load_dotenv

from .constraint_engine import run_constraint_engine
from .explanation import _format_constraint_matches
from .models import (
    FINE_RERANK_MODEL,
    LLM_MODEL,
    Candidate,
    CompatibilityResult,
    Constraint,
    ConstraintOperator,
    JobDescription,
)
from .scoring import skill_match_detail_batch

load_dotenv()

_anthropic_client = None
_client_lock = threading.Lock()

# Matches a lone (unpaired) UTF-16 surrogate half — real candidate free text
# (CV/LinkedIn/interview notes) pasted from various sources occasionally
# contains one, which makes the Anthropic API reject the *entire* request
# body with a JSON-encoding error, taking out a whole rerank chunk for a
# single corrupted character. Mirrors Mind's stripLoneSurrogates
# (mind/apps/web/src/lib/reranks/rerank-anthropic.ts).
_LONE_SURROGATE_RE = re.compile(r"[\ud800-\udfff]")


def _strip_lone_surrogates(text: str) -> str:
    return _LONE_SURROGATE_RE.sub("", text) if text else text


def _get_client():
    global _anthropic_client
    if _anthropic_client is None:
        with _client_lock:
            if _anthropic_client is None:
                import anthropic
                _anthropic_client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
    return _anthropic_client


def _call_tool(
    messages: list[dict],
    tool_schema: dict,
    system: str,
    max_tokens: int = 4096,
    model: str = LLM_MODEL,
    cache_system: bool = False,
    retries: int = 1,
    postprocess=None,
    validate=None,
) -> dict:
    """Single tool-forced LLM call, with an optional retry for transient errors.

    cache_system=True marks the system prompt as ephemeral-cacheable — worth
    it once a stage makes several calls per run sharing the same (large,
    static) system prompt, e.g. chunked fine-rerank/triage; not worth the
    extra request shape for a stage that only ever makes one call per run
    (e.g. the coarse role brief).

    No `temperature` param (2026-07-31): claude-sonnet-5 (FINE_RERANK_MODEL)
    — like the rest of the Sonnet 5 / Opus 5 / Fable 5 / 4.7 / 4.8 family —
    rejects ANY non-default temperature/top_p/top_k with a 400 ("temperature
    is deprecated for this model"), so it isn't available as a lever here.
    (Originally added to fight what looked like degenerate output on large
    batches; root-caused 2026-07-31 to a JSON-shape quirk instead — see
    `postprocess` below — so it wasn't the right lever anyway.)

    postprocess, if given, is called with the parsed tool_use input and may
    return a corrected version — applied before `validate`, so a structural
    fix (e.g. un-stringifying a field the model serialized as JSON text
    instead of a native array/object) counts as success rather than
    triggering a retry.

    validate, if given, is called with the (possibly postprocessed) input and
    should raise on a response that's still wrong (e.g. a ranked array
    wildly larger than the batch it was asked to rank) — routed through the
    same retry loop as a real API error, since a structurally-valid-but-wrong
    response wouldn't otherwise trigger the except-based retry at all.
    """
    system_param = (
        [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]
        if cache_system
        else system
    )
    attempt = 0
    while True:
        try:
            print(f"    [LLM] {tool_schema['name']} ({model})...", flush=True)
            response = _get_client().messages.create(
                model=model,
                max_tokens=max_tokens,
                system=system_param,
                tools=[tool_schema],
                tool_choice={"type": "tool", "name": tool_schema["name"]},
                messages=messages,
            )
            for block in response.content:
                if block.type == "tool_use":
                    result = postprocess(block.input) if postprocess is not None else block.input
                    if validate is not None:
                        validate(result)
                    return result
            raise RuntimeError("No tool use block in response")
        except Exception:
            if attempt >= retries:
                raise
            attempt += 1
            print(f"    [LLM] call failed, retrying ({attempt}/{retries})...", flush=True)
            time.sleep(1.5)


def _coerce_stringified_json(field: str):
    """Returns a postprocess fn that un-stringifies `field` if the model
    serialized it as JSON text instead of returning it as a native
    array/object in the tool call.

    Root-caused 2026-07-31 by capturing raw tool_use output for chunks that
    were falling back to "not returned by the rerank stage": the model was
    NOT generating garbage (no degenerate repetition, no runaway token
    spend) — it was producing well-reasoned, correctly-shaped rankings, just
    occasionally handing back `{"ranked": "[{...}, {...}]"}` (the array as a
    JSON string) instead of `{"ranked": [{...}, {...}]}`, and once even
    double-wrapped: `{"ranked": "{\\"ranked\\": [...]}"}`. Good data was being
    discarded as if it were noise. Handles both shapes; leaves the input
    alone (for `validate` to catch) if `field` isn't a string, or is a string
    that isn't parseable JSON even leniently.

    The stringified form isn't always strictly valid JSON either — one
    captured case had a stray trailing comma before a closing brace
    (`..."fit.",\n},\n{"candidate_id": ...` — plausible since a manually
    composed string, unlike a properly tool-encoded array, gets none of the
    structured-output generator's syntax guarantees). Falls back to a
    trailing-comma-stripped reparse before giving up.
    """

    def _parse_lenient(text: str):
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return json.loads(re.sub(r",(\s*[}\]])", r"\1", text))

    def _coerce(parsed: dict) -> dict:
        value = parsed.get(field)
        if not isinstance(value, str):
            return parsed
        try:
            decoded = _parse_lenient(value)
        except (json.JSONDecodeError, TypeError):
            return parsed
        if isinstance(decoded, list):
            return {**parsed, field: decoded}
        if isinstance(decoded, dict) and isinstance(decoded.get(field), list):
            return {**parsed, field: decoded[field]}
        return parsed

    return _coerce


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
hard-constraint filtering (visa, location, clearance, plus clear-cut
compensation/experience-overqualification mismatches, all already checked —
do not re-litigate those). That last check is deliberately lenient: only a
gross mismatch is filtered before reaching you, so a smaller compensation or
experience gap can still be present — see the "Compensation signal" /
"Experience fit" lines and the rule on them below. Your job is to judge FIT:
how well each candidate's skills, experience, and background match what this
role actually needs, using the constraint-match detail and background
provided for each candidate.

For each candidate, assign:
- verdict: "strong_match" | "good_match" | "possible" | "weak_match"
- rationale: 2-3 sentences, specific and evidence-based, for a recruiter to act on

Then return ALL candidates ordered from best to worst fit for this specific role.

Rules:
- Judge fit for THIS role, not general competence.
- Be honest about weak fits — do not inflate verdicts to be polite.
- Ground every claim in the provided candidate data; do not invent experience.
- Flagged-for-review constraint matches are not disqualifying — mention them in
  rationale only if genuinely relevant to fit.
- Each candidate block includes a "Role skill fit" line showing which of the
  role's required/preferred skills are evidenced vs missing (computed directly
  from structured skill data, not inferred by you). Treat missing REQUIRED
  skills as a real fit gap and say so plainly — do not let broad seniority or
  an unrelated but impressive background paper over a candidate having none
  of the specific skills this role needs.
- Each candidate block may also include an "Experience fit" line and/or a
  "Compensation signal" line — both computed directly from structured data,
  not inferred by you, and both only appear for a gap too small to have
  already been filtered out. A candidate flagged this way is not
  automatically a strong match on a junior/mid-level role even at this
  smaller gap: they can still reject the offer, get bored quickly, or expect
  broader scope than the role has. Treat a flagged overqualification/
  compensation gap as seriously as a missing required skill — name it
  plainly in the rationale and let it pull the verdict down — rather than
  defaulting to strong_match purely because their skills and background are
  impressive. This cuts both ways: being below the stated minimum is also a
  real gap, not a rounding error.
- If a "Role rubric" block is provided below, it is what the hiring manager
  actually weighted this role on — judge fit primarily against those
  weighted signals, in rough proportion to their listed weights, not generic
  skill overlap. Treat required/preferred skills as a floor, not the whole
  picture, when a rubric is present: a candidate can be a strong rubric fit
  despite a minor skill gap, or a weak one despite full skill coverage, if
  the rubric's higher-weighted signals say so. A "gate" listed in the rubric
  marks a hard flag condition (raise it in rationale if triggered), not an
  ordinary scored signal."""

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


def _format_rubric_signals(rubric: dict | None) -> str:
    """Format a `mind.rubric_configs` row's `signals` into a fine-rerank
    prompt block, mirroring the SIGNALS section Mind's own production
    reranker injects (`buildSignalsSystem`,
    mind/apps/web/src/lib/reranks/rerank-anthropic.ts) — same id/label/tier/
    weight/guidance shape, so the LLM here judges fit against the same
    role-specific weighted criteria Mind's reranker uses instead of generic
    required/preferred skills only.

    Deliberately simpler than Mind's version: Mind has the LLM emit a
    strong/partial/absent/violated verdict PER signal and computes the
    weighted score deterministically afterward (`signal-scoring.ts`) — a
    second scoring pipeline and tool-schema change. This only reshapes the
    PROMPT; rec-engine's existing strong/good/possible/weak_match verdict +
    merge-by-verdict-tier logic (`_fine_rerank_chunk`/`_merge_ranked_batches`)
    is untouched, per CHANGES_VS_MIND_MAIN.md's framing of this as a
    concrete, small change, not a rescoring-pipeline redesign.

    Returns "" (not None) when there's no rubric to inject — the caller
    splices this directly into the prompt, so a missing rubric should just
    mean an absent section, not a conditional the caller has to branch on.
    """
    if not rubric or not rubric.get("signals"):
        return ""

    signals = rubric["signals"]
    scored = sorted(
        (s for s in signals if not s.get("gating")),
        key=lambda s: s.get("weight", 0),
        reverse=True,
    )
    gating = [s for s in signals if s.get("gating")]

    if not scored and not gating:
        return ""

    lines = [
        f"- [{s.get('tier', 'primary')}, weight={s.get('weight', 0)}] "
        f"{s.get('label', s.get('id', 'signal'))}: {s.get('guidance', '')}"
        for s in scored
    ]
    block = (
        "Role rubric — this role has a hiring-manager-defined weighted rubric "
        "(see the rule above on how to use it):\n" + "\n".join(lines)
    )

    if gating:
        gate_lines = [
            f"- \"{s.get('id', 'gate')}\" ({s.get('gate_on', 'counter_evidence')}): {s.get('label', '')}"
            for s in gating
        ]
        block += "\n\nGates (flag in rationale if triggered, do not just silently downrank):\n" + "\n".join(gate_lines)

    return block


# Two-tier, same shape as SKILL_FLOOR_RATIO/TITLE_RELEVANCE_FLOOR below: a
# lenient ELIMINATION threshold (deterministic gate, _apply_*_check) catches
# only clear-cut mismatches; a lower SIGNAL threshold surfaces a smaller gap
# as an explicit, non-eliminating prompt line for fine-rerank to weigh (a
# near-boundary candidate — e.g. 10% over budget — might still reasonably
# take the role, so it isn't cut, but the LLM should still see the number).
# Live-validated against job_order_id 1409 (CoLoop, £70-90K band, 1+ yrs,
# junior): both real over-band candidates found in this role's actual
# fine-rerank output (Chris Arderne £120k/33% over/10 yrs, Qasim Asghar
# £110k/22% over/11 yrs) clear the elimination thresholds below with margin.
EXPERIENCE_SIGNAL_YEARS = 3
EXPERIENCE_ELIMINATION_YEARS = 6
COMPENSATION_SIGNAL_RATIO = 0.15
# 0.30, matching Mind's own production default (`salaryOverBudgetPct`,
# mind/apps/web/src/lib/matching/scoring-engine.ts:891 — "0.0 = flat ceiling,
# 0.3 = legacy 30% buffer"). Originally shipped here at 0.20 with no
# particular justification beyond "lenient"; investigating a WaveLabs
# (job_order_id 1535) false-positive-looking result found Mind's own team
# already tuned this exact threshold in production, and there's no live
# evidence rec-engine's roles need a tighter bar than Mind's. Mind's version
# is also per-role overridable (`role.salaryOverBudgetPct`) — rec-engine's
# isn't yet; worth adding if a specific role needs a different tolerance.
COMPENSATION_ELIMINATION_RATIO = 0.30

# The overqualification check (both the informational line and the elimination
# gate below) applies only when the role's OWN stated minimum is itself this
# low — NOT when job.seniority says "junior"/"mid". Live-found on job_order_id
# 1596 (Calibre, "2+ years... ready to operate at a senior level... This isn't
# a typical junior role"): that framing is exactly the kind of text that gets
# job.seniority extracted as "senior" despite min_years_experience correctly
# staying 2 — a categorical field the model derives from tone/scope language,
# not the same as a directly-stated number. Gating on job.seniority there
# silently disabled the whole check for this role (11-19.5 yr candidates kept
# reaching the top of the shortlist); min_years_experience is the number
# actually stated in the JD text ("2+ years of professional experience") and
# far less ambiguous to extract correctly.
EXPERIENCE_GATE_MAX_TARGET_YEARS = 3


def _employer_salary_ceiling(job: JobDescription) -> tuple[float, str] | None:
    """The employer's stated salary ceiling, if any, found by scanning for a
    `currency`-bearing constraint rather than a specific canonical_key.

    extraction.py's own tool schema documents `currency` as set "for salary
    constraints" and null otherwise — reliable regardless of what
    canonical_key/category string the model happened to pick for that
    constraint. Relying on canonical_key here would reproduce the exact
    failure mode already found and fixed for the UK/visa check: the
    employer-side key drifting per extraction run (there, "uk_based" /
    "location_uk_based" / "work_location_requirement" for the same JD) means
    it often won't exact-match the candidate-side constraint's hardcoded
    "salary_min" key, and salary constraints are short enough that semantic
    (embedding) similarity between generic "salary ~£X" descriptions can't be
    trusted to consistently clear the 0.75 threshold either — so a real
    mismatch can quietly resolve to "no candidate constraint found ->
    compatible" and reach fine-rerank invisibly. This sidesteps that whole
    path with a signal the schema itself guarantees.

    Deliberately does NOT require `type == hard`: whether a stated salary
    band like "£70K-£90K" reads as a strict cap or an advertised range is
    exactly the kind of judgment call LLM extraction is inconsistent on run
    to run — gating on it here would reintroduce the same unreliable-
    classification dependency this function exists to avoid, and would
    silently disable the whole check for any job where that one call happens
    to land on "soft". A currency-bearing constraint is only ever produced
    for an actually-stated compensation figure (never inferred, per
    extraction.py's few-shot examples), so treating any of them as ceiling
    evidence — hard or soft — is safe.

    Prefers an explicit `max`-operator constraint (the natural shape for a
    ceiling); falls back to the highest-valued currency-bearing constraint if
    the model represented a range some other way (e.g. two `requires`/`min`
    constraints for a "£70K-£90K" band instead of one `max`).

    Falls back further to `job.bullhorn_salary` — the ATS's own structured
    job-order salary figure (live_data.fetch_job_raw) — when no constraint
    yields a ceiling at all. Live-checked across all 7 currently-pinned
    roles: only 1 stated an explicit band in its JD prose (extractable into a
    constraint); all 7 had the Bullhorn field populated. Without this
    fallback, the compensation-band gate was a silent no-op for 6 of 7 real
    roles — a structured field beats "did an LLM happen to notice a salary
    mention in free text," same lesson as the currency-over-canonical-key
    fix above, just a different source.
    """
    salary_constraints = [
        c for c in job.constraints
        if c.currency is not None and isinstance(c.value, (int, float))
    ]
    if salary_constraints:
        max_op = [c for c in salary_constraints if c.operator == ConstraintOperator.max]
        best = max(max_op or salary_constraints, key=lambda c: c.value)
        return float(best.value), (best.currency or "")

    if job.bullhorn_salary:
        return job.bullhorn_salary, "GBP"

    return None


def _role_target_line(job: JobDescription) -> str:
    return f"Role target: {job.seniority}-level, {job.min_years_experience}+ yrs experience" if job.min_years_experience or job.seniority else ""


def _candidate_experience_fit_line(job: JobDescription, candidate: Candidate) -> str:
    """Informational only — candidates past EXPERIENCE_ELIMINATION_YEARS never
    reach this (see _apply_experience_overqualification_check); this covers
    the milder SIGNAL-tier gap plus the "under minimum" direction, which
    isn't gated at all (years-of-experience is too weak a proxy to eliminate
    on the low side).
    """
    if job.min_years_experience <= 0:
        return ""
    delta = candidate.years_experience - job.min_years_experience
    if delta < 0:
        return (
            f"\nExperience fit: {candidate.years_experience:.0f} yrs — "
            f"{abs(delta):.0f} yrs UNDER the role's stated {job.min_years_experience}+ yr minimum"
        )
    if job.min_years_experience <= EXPERIENCE_GATE_MAX_TARGET_YEARS and delta >= EXPERIENCE_SIGNAL_YEARS:
        return (
            f"\nExperience fit: {candidate.years_experience:.0f} yrs — {delta:.0f} yrs ABOVE the "
            f"{job.min_years_experience}+ yr minimum this role explicitly states "
            f"(possibly overqualified — see the rule on overqualification above)"
        )
    return f"\nExperience fit: {candidate.years_experience:.0f} yrs vs role's {job.min_years_experience}+ yr minimum"


def _candidate_salary_constraint(candidate: Candidate) -> Constraint | None:
    return next((c for c in candidate.constraints if c.canonical_key == "salary_min"), None)


def _salary_over_ratio(
    candidate: Candidate, salary_ceiling: tuple[float, str] | None
) -> float | None:
    """(candidate salary - ceiling) / ceiling, or None if not comparable
    (no ceiling, no candidate figure, missing/mismatched currency — never
    guess an FX conversion, and never assume a currency-less number is in
    the ceiling's currency). Shared by the SIGNAL-tier prompt line and the
    ELIMINATION-tier deterministic gate so both use the exact same number.

    Requiring cand_c.currency to be explicitly PRESENT (not just checking it
    doesn't mismatch when present) mirrors Mind's own resolveAnnualGbp
    (mind/apps/web/src/lib/matching/scoring-engine.ts:802) — "Bare numbers
    from Bullhorn have no currency context and treating them as GBP causes
    false rejections for international candidates." Zero-impact on the
    current candidate index (every salary_min constraint there does carry a
    currency), but defensive against a candidate row that has a salary
    figure with no currency code recorded.
    """
    if salary_ceiling is None:
        return None
    ceiling_value, ceiling_currency = salary_ceiling
    cand_c = _candidate_salary_constraint(candidate)
    if cand_c is None or not isinstance(cand_c.value, (int, float)):
        return None
    if not cand_c.currency or not ceiling_currency or cand_c.currency.upper() != ceiling_currency.upper():
        return None
    if not ceiling_value:
        return None
    return (float(cand_c.value) - ceiling_value) / ceiling_value


def _compensation_fit_line(candidate: Candidate, salary_ceiling: tuple[float, str] | None) -> str:
    """Informational only — candidates past COMPENSATION_ELIMINATION_RATIO
    never reach this (see _apply_compensation_band_check); this covers the
    milder SIGNAL-tier gap for near-boundary survivors.
    """
    over_ratio = _salary_over_ratio(candidate, salary_ceiling)
    if over_ratio is None or over_ratio <= COMPENSATION_SIGNAL_RATIO:
        return ""
    ceiling_value, ceiling_currency = salary_ceiling  # salary_ceiling is not None here (over_ratio would be)
    cand_value = float(_candidate_salary_constraint(candidate).value)
    return (
        f"\nCompensation signal: candidate's salary figure on file is "
        f"~{ceiling_currency}{cand_value:,.0f} vs this role's stated band up to "
        f"{ceiling_currency}{ceiling_value:,.0f} — {over_ratio:.0%} above the top of the band "
        f"(possibly overqualified/expensive for this role — see the rule above)"
    )


def _format_candidate_block(
    job: JobDescription,
    candidate: Candidate,
    cr: CompatibilityResult,
    skill_detail: tuple[list[str], list[str]],
    salary_ceiling: tuple[float, str] | None = None,
) -> str:
    constraint_block = _format_constraint_matches(cr)
    flagged = " (some constraint matches flagged for review — verify manually)" if cr.flagged_for_review else ""

    matched, missing = skill_detail
    required_missing = [s for s in missing if s in job.required_skills]
    skill_fit_line = ""
    if matched or missing:
        total = len(matched) + len(missing)
        skill_fit_line = f"\nRole skill fit: {len(matched)}/{total} required/preferred skills evidenced"
        if matched:
            skill_fit_line += f" (matched: {', '.join(matched)})"
        if required_missing:
            skill_fit_line += f" — MISSING REQUIRED: {', '.join(required_missing)}"

    experience_fit_line = _candidate_experience_fit_line(job, candidate)
    compensation_line = _compensation_fit_line(candidate, salary_ceiling)

    return f"""### Candidate {candidate.id}: {candidate.name}
Experience: {candidate.years_experience} yrs | Seniority: {candidate.seniority_level}
Skills: {', '.join(candidate.skills[:20]) or 'none listed'}
Background: {_strip_lone_surrogates(candidate.raw_linkedin) or '(no summary)'}
CV notes: {_strip_lone_surrogates(candidate.raw_cv) or '(none)'}
Recruiter call notes: {_strip_lone_surrogates(candidate.raw_interview_transcript) or '(none)'}
{skill_fit_line}{experience_fit_line}{compensation_line}
Constraint match against this role{flagged}:
{constraint_block}"""


def _chunk(items: list, size: int) -> list[list]:
    return [items[i : i + size] for i in range(0, len(items), size)]


# candidates per fine-rerank call. Must satisfy 1024 + 220*N <= 8192 (the max_tokens
# formula in _fine_rerank_chunk) or the model's output gets clipped by that hard cap
# mid-batch — verified 2026-07-31: the previous value of 40 was silently truncating
# every full batch's tool-use JSON, dropping candidates into _merge_ranked_batches'
# "not returned by the rerank stage" fallback at rates from 21% up to 100% depending
# on how verbose that batch's rationales happened to be. 32 is the exact ceiling the
# formula supports (was already documented as the safe number in fine_rerank()'s own
# docstring, just never matched by this constant).
RERANK_BATCH_SIZE = 32


def _fine_rerank_chunk(
    job: JobDescription,
    coarse_brief: dict,
    pool: list[Candidate],
    compatibility_results: dict[str, CompatibilityResult],
    skill_detail: dict[str, tuple[list[str], list[str]]],
    rubric_block: str = "",
    salary_ceiling: tuple[float, str] | None = None,
) -> list[dict]:
    """Rank a single chunk (≤RERANK_BATCH_SIZE) with one batched LLM call.

    Not called directly for a full pool — see fine_rerank(), which chunks and
    merges. Kept separate so each call stays well clear of the max_tokens
    ceiling that a single call over an unbounded pool would hit.

    skill_detail is computed once for the whole pool by the caller (fine_rerank)
    and passed in here — avoids re-running skill_match_detail_batch per chunk.

    rubric_block is pre-formatted text (`_format_rubric_signals`), computed
    once per run by the caller and passed through unchanged — same shape as
    coarse_brief here: role-level context that doesn't vary per chunk.

    salary_ceiling (`_employer_salary_ceiling`) is threaded into each
    candidate block's "Compensation signal" line — see that function's
    docstring for why this doesn't rely on canonical-key constraint matching.
    """
    if not pool:
        return []

    candidate_blocks = "\n\n".join(
        _format_candidate_block(job, c, compatibility_results[c.id], skill_detail.get(c.id, ([], [])), salary_ceiling)
        for c in pool
    )

    rubric_section = f"\n{rubric_block}\n" if rubric_block else ""
    role_target_line = _role_target_line(job)

    prompt = f"""Role: {job.title} at {job.company}
{role_target_line}
Role briefing: {coarse_brief.get('summary', '')}
{rubric_section}
Candidates to rank ({len(pool)} total, all already passed hard-constraint filtering):

{candidate_blocks}"""

    def _validate_ranked(parsed: dict) -> None:
        ranked = parsed.get("ranked")
        # Generous tolerance (2x) — a real pathological response (thousands
        # of entries for a 32-candidate batch) would still trip this; the
        # much more common case — the array serialized as a JSON string
        # instead of natively — is already fixed by _coerce_stringified_json
        # (passed as postprocess) before this ever runs.
        if not isinstance(ranked, list) or len(ranked) > len(pool) * 2:
            got = len(ranked) if isinstance(ranked, list) else type(ranked).__name__
            raise ValueError(
                f"fine-rerank returned {got} items for a {len(pool)}-candidate batch "
                "— not a usable ranking even after JSON-string coercion"
            )

    try:
        result = _call_tool(
            [{"role": "user", "content": prompt}],
            FINE_RERANK_TOOL_SCHEMA,
            FINE_RERANK_SYSTEM,
            max_tokens=min(1024 + 220 * len(pool), 8192),
            model=FINE_RERANK_MODEL,
            cache_system=True,
            retries=3,
            postprocess=_coerce_stringified_json("ranked"),
            validate=_validate_ranked,
        )
    except Exception as exc:
        # Exhausted retries on a genuinely stubborn batch (seen in practice:
        # `ranked` comes back as a bare string instead of an array, or with
        # thousands of repeated entries — a model-side hiccup on this
        # particular batch's content, not a systemic failure). Degrade this
        # ONE chunk to empty rather than crashing the whole run — the caller
        # (fine_rerank -> _merge_ranked_batches) already has a designed path
        # for "candidate present in pool but missing from every chunk's
        # ranked list": it appends them flagged for manual review instead of
        # vanishing or taking every other chunk's real results down too.
        print(f"    [LLM] fine-rerank chunk failed after retries, degrading to empty: {exc}", flush=True)
        return []
    return result.get("ranked", [])


_VERDICT_RANK = {"strong_match": 0, "good_match": 1, "possible": 2, "weak_match": 3}


def _merge_ranked_batches(
    batches: list[list[dict]],
    pool: list[Candidate],
    skill_coverage_by_id: dict[str, int],
) -> list[dict]:
    """Combine per-chunk rerank results into one globally-ordered list.

    Each chunk's verdict is a judgment against fixed role criteria (see
    FINE_RERANK_SYSTEM — "how well each candidate's skills... match what this
    role actually needs"), not a ranking relative to the other candidates in
    that specific chunk, so verdicts stay comparable across chunks with zero
    shared context. Sort by verdict tier first, then by matched-required-skill
    count (already computed, free) as a tiebreaker within a tier — no need for
    Mind's absolute 0-10 rubric redesign just to make this merge valid.

    Any candidate present in `pool` but missing from every chunk's returned
    `ranked` list (the LLM dropped/omitted them, or returned it malformed —
    seen in practice: a plain candidate_id string instead of the expected
    {candidate_id, verdict, rationale} object) is appended at the end,
    flagged for manual review rather than silently vanishing or crashing
    the whole run over one bad item.
    """
    by_id: dict[str, dict] = {}
    for batch in batches:
        for item in batch:
            if not isinstance(item, dict) or "candidate_id" not in item:
                continue
            by_id[item["candidate_id"]] = item

    ordered = sorted(
        by_id.values(),
        key=lambda item: (
            _VERDICT_RANK.get(item.get("verdict"), len(_VERDICT_RANK)),
            -skill_coverage_by_id.get(item["candidate_id"], 0),
        ),
    )

    missing = [c for c in pool if c.id not in by_id]
    for c in missing:
        ordered.append({
            "candidate_id": c.id,
            "verdict": "weak_match",
            "rationale": "Not returned by the rerank stage (dropped or omitted from its batch) — flagged for manual review.",
        })

    return ordered


def fine_rerank(
    job: JobDescription,
    coarse_brief: dict,
    candidates: list[Candidate],
    compatibility_results: dict[str, CompatibilityResult],
    max_candidates: int | None = None,
    max_workers: int = 1,
    rubric: dict | None = None,
) -> list[dict]:
    """Stage 2: rank the constraint-filtered pool with verdict + rationale.

    `rubric`, if given, is a `mind.rubric_configs` row (see
    `mind_rubric_store.get_rubric_for_role`) — formatted once here via
    `_format_rubric_signals` and threaded into every chunk's prompt the same
    way `coarse_brief` already is, so the LLM judges fit against that role's
    actual hiring-manager-defined weighted criteria instead of only generic
    required/preferred skills. None (the default) reproduces today's
    behavior exactly — no rubric section in the prompt.

    Chunks the pool into fixed-size batches (RERANK_BATCH_SIZE) and calls the
    fine-rerank LLM once per chunk. A single call scaling its max_tokens with
    pool size hits Anthropic's output ceiling around ~32 candidates; Mind's
    own production rerank (mind/apps/web/src/lib/reranks/rerank-anthropic.ts)
    solves this the same way: fixed batch size + a merge step, not a bigger
    single call.

    `max_workers` (2026-08-01): default 1 keeps chunks serial, same as
    always — that default came from Mind's own reranker finding concurrent
    long-lived streams starved the event loop in *its* production (Node.js).
    That constraint doesn't transfer to this Python/FastAPI service, and it
    matters here: the normal pipeline narrows to a small rerank pool before
    this stage (a handful of chunks), but the LLM-only pipeline
    (run_llm_only_pipeline) skips that narrowing entirely and can be dozens
    of chunks — serial there means well over an hour per role. Pass
    max_workers > 1 to run chunks concurrently via ThreadPoolExecutor;
    `_merge_ranked_batches` merges by candidate_id and sorts by verdict, so
    completion order never affects the result.

    `max_candidates`, if given, still caps the pool size handled here (dev/
    testing convenience); the real ceiling on how many candidates reach this
    stage now lives in run_live_pipeline's rerank pool sizing.

    Each returned dict also carries `matched_skills`/`missing_required_skills`
    (from the same skill_detail computation, threaded out here instead of
    being discarded after formatting the prompt) — lets a results view show
    the fit signal that already drove the "Role skill fit" prompt line,
    without recomputing it.
    """
    pool = candidates[:max_candidates] if max_candidates is not None else candidates
    if not pool:
        return []

    target_skills = job.required_skills + job.preferred_skills
    skill_detail = skill_match_detail_batch({c.id: c.skills for c in pool}, target_skills)
    skill_coverage_by_id = {c.id: len(skill_detail.get(c.id, ([], []))[0]) for c in pool}
    rubric_block = _format_rubric_signals(rubric)
    salary_ceiling = _employer_salary_ceiling(job)

    chunks = _chunk(pool, RERANK_BATCH_SIZE)
    if max_workers > 1 and len(chunks) > 1:
        with ThreadPoolExecutor(max_workers=max_workers) as pool_executor:
            batches = list(
                pool_executor.map(
                    lambda chunk: _fine_rerank_chunk(
                        job, coarse_brief, chunk, compatibility_results, skill_detail, rubric_block, salary_ceiling
                    ),
                    chunks,
                )
            )
    else:
        batches = [
            _fine_rerank_chunk(job, coarse_brief, chunk, compatibility_results, skill_detail, rubric_block, salary_ceiling)
            for chunk in chunks
        ]

    merged = _merge_ranked_batches(batches, pool, skill_coverage_by_id)

    required = set(job.required_skills)
    for item in merged:
        matched, missing = skill_detail.get(item["candidate_id"], ([], []))
        item["matched_skills"] = matched
        item["missing_required_skills"] = [s for s in missing if s in required]

    return merged


# ---------------------------------------------------------------------------
# Coarse triage: cheap Haiku bucketing ahead of fine-rerank, for large pools
# ---------------------------------------------------------------------------

TRIAGE_SYSTEM = """You are doing a fast, coarse first pass over a large candidate pool for a
specific role, before a more careful review. For each candidate, bucket them:

- "strong": clearly a good fit — evidences the role's core required skills and seniority level
- "maybe": plausible but unclear — partial skill evidence, ambiguous seniority, or missing info
- "no": clearly not a fit — wrong discipline, far below required experience, or minimal skill overlap

Be fast and decisive, not precise — a more careful review happens after this pass.
When genuinely unsure, prefer "maybe" over "no": this pass should never be the
reason a plausible candidate gets dropped."""

TRIAGE_TOOL_SCHEMA = {
    "name": "triage_candidates",
    "description": "Coarsely bucket a batch of candidates for a role.",
    "input_schema": {
        "type": "object",
        "properties": {
            "buckets": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "candidate_id": {"type": "string"},
                        "bucket": {"type": "string", "enum": ["strong", "maybe", "no"]},
                    },
                    "required": ["candidate_id", "bucket"],
                },
            },
        },
        "required": ["buckets"],
    },
}

TRIAGE_CHUNK_SIZE = 40
TRIAGE_TOP_N = 100  # only triage when the passed-filter pool exceeds this — mirrors Mind's own
                     # cutover point (config.rerank.triageTopN) for "fits one fine pass" vs "needs
                     # the coarse funnel first"; reused directly rather than inventing a new number.


def _triage_chunk(job: JobDescription, chunk: list[Candidate]) -> dict[str, str]:
    lines = "\n".join(
        f"- {c.id}: {c.name} | {c.years_experience} yrs, {c.seniority_level} | "
        f"skills: {', '.join(c.skills[:15]) or 'none listed'}"
        for c in chunk
    )
    prompt = f"""Role: {job.title} at {job.company}
Required skills: {', '.join(job.required_skills) or 'none specified'}
Preferred skills: {', '.join(job.preferred_skills) or 'none specified'}
Seniority: {job.seniority} | Min years experience: {job.min_years_experience}

Candidates:
{lines}"""
    try:
        result = _call_tool(
            [{"role": "user", "content": prompt}],
            TRIAGE_TOOL_SCHEMA,
            TRIAGE_SYSTEM,
            max_tokens=4096,
            model=LLM_MODEL,
            cache_system=True,
            retries=1,
        )
    except Exception:
        return {}  # a failed chunk buckets nothing — those candidates default to "maybe" below
    return {b["candidate_id"]: b["bucket"] for b in result.get("buckets", [])}


TRIAGE_CONCURRENCY = 6  # chunks in flight at once


def triage_candidates(job: JobDescription, pool: list[Candidate]) -> dict[str, str]:
    """Coarse strong/maybe/no bucketing ahead of the fine-rerank stage.

    Cheap by design (tiny schema, small fixed max_tokens) — its whole job is
    bucketing, not judgment quality; the fine-rerank LLM does the real
    scoring on whatever survives selection. Any candidate a chunk fails to
    bucket (parse error, dropped chunk) defaults to "maybe" downstream in
    select_by_coarse_bucket — a triage failure degrades to "keep everyone",
    never silently drops the whole pool.

    Run concurrently (plain ThreadPoolExecutor, not new async infrastructure —
    these are short blocking HTTP calls). Mind runs its own Haiku triage
    concurrently too (MAX_CONCURRENCY=4); only their Sonnet fine-rerank stays
    serial, because THAT specific incident was long-lived streaming responses
    starving the event loop — a failure mode that doesn't apply to triage's
    short, non-streaming, small-output calls. fine_rerank stays serial here
    for the same reason it does in Mind's code.
    """
    chunks = _chunk(pool, TRIAGE_CHUNK_SIZE)
    buckets: dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=TRIAGE_CONCURRENCY) as executor:
        for result in executor.map(lambda chunk: _triage_chunk(job, chunk), chunks):
            buckets.update(result)
    return buckets


def select_by_coarse_bucket(pool: list[Candidate], buckets: dict[str, str], top_n: int) -> list[Candidate]:
    """Keep the best non-empty bucket present (strong > maybe > no), capped to top_n.

    Unbucketed candidates default to "maybe", not excluded.
    """
    by_bucket: dict[str, list[Candidate]] = {"strong": [], "maybe": [], "no": []}
    for c in pool:
        by_bucket[buckets.get(c.id, "maybe")].append(c)

    for bucket in ("strong", "maybe", "no"):
        if by_bucket[bucket]:
            return by_bucket[bucket][:top_n]
    return []


def _candidate_flag(candidate: Candidate, canonical_key: str) -> bool | None:
    for c in candidate.constraints:
        if c.canonical_key == canonical_key:
            return bool(c.value)
    return None


SKILL_FLOOR_RATIO = 0.4  # eliminate candidates evidencing below this fraction of required_skills
# Live-validated against job_order_id 1360 (Ankar AI, 6 required skills) and 1650
# (LightWork AI, 15 required skills): at 0.4, top-10 fine-rerank output for both
# showed sensible verdicts (top candidates 4-6/6 and 9-13/15 respectively, no
# glaring required-skill gaps at the top) — raising this wasn't supported by
# fresh evidence, so it's left as-is. The real gap this iteration found was the
# fixed-30 rerank cap silently dropping 98%+ of the filter-passed pool via
# embedding similarity rather than real judgment (see fine_rerank chunking below).
#
# KNOWN EDGE CASE, not fixed (2026-08-03): a ratio floor gets coarse and
# discipline-blind on a SHORT required_skills list. Live-found on job_order_id
# 1596 (Calibre) with only 2 extracted required skills ("LLM AI agents",
# "Full-stack development") — the individual skill matches looked correct on
# inspection (e.g. a clearly full-stack candidate matched "Full-stack
# development", correctly missed the AI-specific term), but ~76% of the FULL
# cross-discipline eligible pool matched neither term at all, since most of
# that pool was never full-stack/AI-agent people to begin with — skill-floor
# ended up doing discipline-filtering work it wasn't designed for, on a list
# too short to carry that signal, collapsing the pool to 34 candidates before
# fine-rerank ever ran. The already-lenient, already-validated
# _apply_title_relevance_check below would be the more appropriate filter for
# a role this thin on required_skills, but it currently runs AFTER (and so is
# starved by) this gate. Possible fix, not built: only hard-eliminate on
# SKILL_FLOOR_RATIO when len(required_skills) is large enough for a
# percentage to be meaningful (e.g. >= 4), same two-tier SIGNAL/ELIMINATION
# idiom already used for compensation/experience above. Flagged as a known
# gap rather than fixed — no fresh evidence yet on the right threshold.


def _apply_skill_floor_check(
    job: JobDescription,
    candidates_with_results: list[tuple[Candidate, CompatibilityResult]],
) -> tuple[list[tuple[Candidate, CompatibilityResult]], list[tuple[Candidate, CompatibilityResult]]]:
    """Deterministic safety-net for skill-fit: constraint_engine.py cannot gate on it.

    Candidate-side constraints (live_data._build_candidate_constraints) are
    built only from salary/notice/working-model/visa/deal-breakers/drivers —
    never from skills. So an employer hard constraint like "deep Node.js/
    NestJS expertise" has no candidate-side counterpart to match against, and
    the engine's phase-3 "no candidate constraint found -> compatible"
    default lets every candidate through regardless of actual skill fit.

    job.required_skills, unlike free-text constraint descriptions, is a
    clean structured list on both sides already (candidate.skills), so this
    checks coverage directly via the existing embedding-based
    skill_match_detail_batch() (scoring.py) rather than trying to match
    skill-shaped Constraint objects — which would reintroduce the same
    canonical-key/category drift that motivated the UK/visa check below.

    Deliberately the OPPOSITE default to the generic constraint engine: there,
    no candidate data means "compatible" (innocent until proven otherwise).
    Here, no evidence of a required skill means the candidate has not
    demonstrated the one thing this check exists to verify — "assume
    compatible" here would just reproduce the bug this gate fixes.
    """
    if not job.required_skills:
        return candidates_with_results, []

    skill_detail = skill_match_detail_batch(
        {c.id: c.skills for c, _ in candidates_with_results}, job.required_skills
    )

    still_passed: list[tuple[Candidate, CompatibilityResult]] = []
    newly_eliminated: list[tuple[Candidate, CompatibilityResult]] = []
    total = len(job.required_skills)
    for c, cr in candidates_with_results:
        matched, missing = skill_detail.get(c.id, ([], list(job.required_skills)))
        coverage = len(matched) / total
        if coverage < SKILL_FLOOR_RATIO:
            cr.elimination_reasons.append(
                f"Deterministic skill-floor check: candidate evidences only "
                f"{len(matched)}/{total} ({coverage:.0%}) of required skills "
                f"(missing: {', '.join(missing)}); below the {SKILL_FLOOR_RATIO:.0%} floor"
            )
            cr.eliminated = True
            newly_eliminated.append((c, cr))
            continue
        still_passed.append((c, cr))

    return still_passed, newly_eliminated


def _apply_compensation_band_check(
    job: JobDescription,
    candidates_with_results: list[tuple[Candidate, CompatibilityResult]],
) -> tuple[list[tuple[Candidate, CompatibilityResult]], list[tuple[Candidate, CompatibilityResult]]]:
    """Deterministic safety-net for compensation-band fit — same gap class as
    _apply_skill_floor_check above, for salary specifically.

    Live-found: candidates already earning well above a role's stated salary
    ceiling (_employer_salary_ceiling) were reaching fine-rerank as "no
    candidate constraint found -> compatible", because candidate-side salary
    is always a SOFT constraint (live_data._build_candidate_constraints) and
    the generic constraint engine's elimination only fires on the EMPLOYER
    constraint's hard/soft type — plus canonical-key drift between the
    employer's LLM-assigned key and the candidate's hardcoded "salary_min"
    key means canonical/semantic matching can miss the pair entirely even
    when the employer side IS hard. This checks the number directly instead,
    the same way the UK/visa check below bypasses canonical-key matching for
    that dimension.

    Lenient by design (COMPENSATION_ELIMINATION_RATIO), matching
    _apply_title_relevance_check's philosophy below: only eliminates a
    clear-cut mismatch. A smaller gap survives with the "Compensation
    signal" prompt line instead (_compensation_fit_line, COMPENSATION_SIGNAL_RATIO).
    """
    ceiling = _employer_salary_ceiling(job)
    if ceiling is None:
        return candidates_with_results, []
    ceiling_value, ceiling_currency = ceiling

    still_passed: list[tuple[Candidate, CompatibilityResult]] = []
    newly_eliminated: list[tuple[Candidate, CompatibilityResult]] = []
    for c, cr in candidates_with_results:
        over_ratio = _salary_over_ratio(c, ceiling)
        if over_ratio is not None and over_ratio > COMPENSATION_ELIMINATION_RATIO:
            cand_value = float(_candidate_salary_constraint(c).value)
            cr.elimination_reasons.append(
                f"Deterministic compensation-band check: candidate's salary figure on file "
                f"(~{ceiling_currency}{cand_value:,.0f}) is {over_ratio:.0%} above this role's "
                f"stated band (up to {ceiling_currency}{ceiling_value:,.0f}) — above the "
                f"{COMPENSATION_ELIMINATION_RATIO:.0%} tolerance"
            )
            cr.eliminated = True
            newly_eliminated.append((c, cr))
            continue
        still_passed.append((c, cr))

    return still_passed, newly_eliminated


def _apply_experience_overqualification_check(
    job: JobDescription,
    candidates_with_results: list[tuple[Candidate, CompatibilityResult]],
) -> tuple[list[tuple[Candidate, CompatibilityResult]], list[tuple[Candidate, CompatibilityResult]]]:
    """Deterministic safety-net for gross overqualification on roles that
    themselves state a low years-of-experience bar — same gap class as
    _apply_skill_floor_check above, for job.min_years_experience, which
    (like skills) is never represented as a Constraint object at all, so the
    generic constraint engine structurally cannot gate on it either.

    Scoped by job.min_years_experience (EXPERIENCE_GATE_MAX_TARGET_YEARS),
    NOT job.seniority — see that constant's own comment for why: extraction
    can label a role "senior" from scope/ownership language even when its
    stated years bar is low (found live on job_order_id 1596, Calibre — "2+
    years... ready to operate at a senior level" extracted min_years=2 but
    plausibly seniority="senior", which would have silently disabled a
    seniority-gated version of this check entirely, letting 10-19.5 yr
    candidates keep reaching the top of that role's shortlist). Extra
    experience relative to a HIGH stated minimum (a genuine senior/lead/
    principal posting) isn't the failure mode this fixes — that's normal,
    often desirable — so a high min_years_experience exempts a role
    regardless of its seniority label too.

    Lenient (EXPERIENCE_ELIMINATION_YEARS), same reasoning as the
    compensation check above and _apply_title_relevance_check below — a
    smaller gap survives with the "Experience fit" prompt line instead.
    Being UNDER the stated minimum is never gated here: years-of-experience
    is too weak a proxy to eliminate on the low side (a strong junior
    candidate a year short of a stated minimum is exactly the kind of
    candidate this pipeline shouldn't be cutting).
    """
    if job.min_years_experience <= 0 or job.min_years_experience > EXPERIENCE_GATE_MAX_TARGET_YEARS:
        return candidates_with_results, []

    still_passed: list[tuple[Candidate, CompatibilityResult]] = []
    newly_eliminated: list[tuple[Candidate, CompatibilityResult]] = []
    for c, cr in candidates_with_results:
        delta = c.years_experience - job.min_years_experience
        if delta > EXPERIENCE_ELIMINATION_YEARS:
            cr.elimination_reasons.append(
                f"Deterministic experience-overqualification check: candidate has "
                f"{c.years_experience:.0f} yrs experience, {delta:.0f} yrs above this "
                f"role's stated {job.min_years_experience}+ yr minimum — "
                f"above the {EXPERIENCE_ELIMINATION_YEARS}-yr tolerance"
            )
            cr.eliminated = True
            newly_eliminated.append((c, cr))
            continue
        still_passed.append((c, cr))

    return still_passed, newly_eliminated


# remote=0 / onsite=5 days-per-week equivalents — "hybrid"/"flexible" are
# deliberately left unmapped (None): a "hybrid" preference could mean 1 day
# or 4, so there's no single number to compare against an employer's stated
# office_days_per_week without guessing. Only a candidate with an
# UNAMBIGUOUS category (fully remote or fully onsite) that structurally
# cannot satisfy what the employer stated gets evaluated at all.
_WORKING_MODEL_DAYS = {"remote": 0.0, "onsite": 5.0}


# Bullhorn's onSite field values, normalized (lowercased, hyphens/spaces
# stripped) -> (days, operator) fallback when the JD prose states no explicit
# office-days figure at all. "Hybrid" is deliberately left unmapped, same
# reasoning as _WORKING_MODEL_DAYS above — no single day-count to infer.
_BULLHORN_ONSITE_REQUIREMENT = {
    "onsite": (5.0, ConstraintOperator.requires),
    "remote": (0.0, ConstraintOperator.max),
}


def _office_days_requirement(job: JobDescription) -> tuple[float, ConstraintOperator] | None:
    """The employer's office-attendance requirement, if any — JD-text
    constraint first (specific, e.g. "3 days/week"), falling back to
    Bullhorn's structured `onSite` field otherwise.

    Live-found on job_order_id 1596 (Calibre): JD prose stated no explicit
    office requirement, but the ATS's own onSite field says "On-Site" — a
    role that's genuinely fully in-office had nothing for the JD-text path
    to find. Same "structured field beats LLM-noticed prose" reasoning as
    _employer_salary_ceiling's Bullhorn fallback.
    """
    for c in job.constraints:
        if c.canonical_key == "office_days_per_week" and isinstance(c.value, (int, float)):
            return float(c.value), c.operator

    if job.bullhorn_working_model:
        normalized = job.bullhorn_working_model.lower().replace("-", "").replace(" ", "")
        return _BULLHORN_ONSITE_REQUIREMENT.get(normalized)

    return None


def _apply_working_model_check(
    job: JobDescription,
    candidates_with_results: list[tuple[Candidate, CompatibilityResult]],
) -> tuple[list[tuple[Candidate, CompatibilityResult]], list[tuple[Candidate, CompatibilityResult]]]:
    """Deterministic safety-net for working-model fit — same gap class as the
    other _apply_*_check gates above, but for a dimension the GENERIC
    constraint engine was already supposed to cover and structurally cannot.

    Investigated live (2026-08-03): the employer side's office-days
    requirement is extracted with canonical_key="office_days_per_week" and a
    NUMERIC value (e.g. 3.0), matching extraction.py's own few-shot example.
    The candidate side is hardcoded to canonical_key="working_arrangement"
    with a CATEGORICAL value ("remote"/"hybrid"/"onsite"/"flexible") in
    live_data._build_candidate_constraints. Two compounding failures, both
    confirmed directly against constraint_engine.py:
    1. canonical_key_match() returns None for this pair — the keys never
       match, so phase 1 never fires (same class of drift already found and
       fixed for UK/visa and salary).
    2. Even forcing a match, _evaluate_operator_pair(requires 3.0, prefers
       "remote") returns (compatible=True, score=0.6) — it can't numerically
       compare a day-count against a category string, so it falls into a
       generic fallback that treats the mismatch as weakly compatible rather
       than a real conflict. A HARD onsite requirement structurally cannot
       eliminate a fully-remote candidate through this path, in any run.

    This sidesteps both failures with a direct numeric comparison, the same
    shape as _apply_compensation_band_check above. Only fires on an
    UNAMBIGUOUS candidate category (remote or onsite — see
    _WORKING_MODEL_DAYS) against an employer constraint with a real number;
    "hybrid"/"flexible" candidates, or roles with no office_days_per_week
    constraint at all, pass through untouched (same "no clear data = don't
    eliminate" posture as every other gate here).
    """
    requirement = _office_days_requirement(job)
    if requirement is None:
        return candidates_with_results, []
    required_days, operator = requirement

    still_passed: list[tuple[Candidate, CompatibilityResult]] = []
    newly_eliminated: list[tuple[Candidate, CompatibilityResult]] = []
    for c, cr in candidates_with_results:
        wc = next((con for con in c.constraints if con.canonical_key == "working_arrangement"), None)
        candidate_days = _WORKING_MODEL_DAYS.get(str(wc.value).lower()) if wc and wc.value else None
        if candidate_days is None:
            still_passed.append((c, cr))
            continue

        incompatible = (
            operator in (ConstraintOperator.requires, ConstraintOperator.min) and candidate_days < required_days
        ) or (operator == ConstraintOperator.max and candidate_days > required_days)

        if incompatible:
            cr.elimination_reasons.append(
                f"Deterministic working-model check: role requires {required_days:.0f} "
                f"office day(s)/week ({operator.value}), candidate is {wc.value} "
                f"({candidate_days:.0f} day(s)/week equivalent) — incompatible"
            )
            cr.eliminated = True
            newly_eliminated.append((c, cr))
            continue
        still_passed.append((c, cr))

    return still_passed, newly_eliminated


TITLE_RELEVANCE_FLOOR = 0.30  # lenient — eliminate only extreme discipline mismatches


def _embed_title(text: str) -> np.ndarray:
    from openai import OpenAI
    client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
    resp = client.embeddings.create(model="text-embedding-3-small", input=[text])
    return np.array(resp.data[0].embedding, dtype=np.float32)


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-10))


def _apply_title_relevance_check(
    job: JobDescription,
    title_embeddings: dict[str, np.ndarray],
    candidates_with_results: list[tuple[Candidate, CompatibilityResult]],
) -> tuple[list[tuple[Candidate, CompatibilityResult]], list[tuple[Candidate, CompatibilityResult]]]:
    """Lenient deterministic gate for job-title / discipline relevance.

    Nothing else in the live pipeline checks this at all: constraint_engine.py
    only ever sees structured salary/location/visa-shaped constraints, and
    retrieval.py's full JD-vs-bio embedding similarity was deliberately kept
    OUT of the pre-filter path (task 9.3 — it conflates skills/constraints
    wording with title and was found to drop genuinely qualified candidates
    before their real constraints were even checked).

    This check is narrower on purpose: it compares ONLY title text (current +
    recent previous titles, via candidate_index.py's title_embedding) against
    the role's title — "is this even the right professional area," not
    general fit. The threshold is deliberately low/lenient: it should only
    catch extreme mismatches (e.g. a Product Manager on a backend-engineering
    role), never cut an adjacent-discipline candidate (a full-stack engineer
    should still surface for a "Product Engineer" role — this is exactly what
    poc_context.md asked for: title matching that's "less strict" than skills).

    Candidates with no precomputed title embedding are passed through
    unchecked — no signal means no basis to eliminate, same "no data ->
    compatible" default as the generic constraint engine.
    """
    job_title_emb = _embed_title(job.title)

    still_passed: list[tuple[Candidate, CompatibilityResult]] = []
    newly_eliminated: list[tuple[Candidate, CompatibilityResult]] = []
    for c, cr in candidates_with_results:
        cand_emb = title_embeddings.get(c.id)
        if cand_emb is None:
            still_passed.append((c, cr))
            continue

        sim = _cosine(job_title_emb, cand_emb)
        if sim < TITLE_RELEVANCE_FLOOR:
            cr.elimination_reasons.append(
                f"Deterministic title-relevance check: candidate's professional "
                f"background scores {sim:.2f} similarity to role title '{job.title}' "
                f"— below the lenient {TITLE_RELEVANCE_FLOOR:.2f} floor (likely a "
                f"different discipline)"
            )
            cr.eliminated = True
            newly_eliminated.append((c, cr))
            continue
        still_passed.append((c, cr))

    return still_passed, newly_eliminated


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

def run_live_pipeline(job_order_id: int, candidate_limit: int | None = None, rerank_limit: int = 200) -> dict:
    """Full live pipeline: fetch -> filter (full universe) -> coarse brief -> fine rerank.

    Hard-constraint filtering (constraint_engine.run_constraint_engine) runs
    over the ENTIRE indexed candidate universe (candidate_index.py) on every
    call, not a pre-shrunk subset — a candidate is only excluded for failing
    a real constraint, never because an embedding-similarity heuristic ranked
    them outside some top-K cutoff before their constraints were even checked.
    This is made tractable by the index precomputing every candidate's
    constraint embeddings once at build time, so this scan makes zero
    per-candidate OpenAI calls; only the job's own constraints get embedded
    fresh (once, for the whole run — see embed_constraints()).

    `rerank_limit` is now a sanity ceiling on total candidates entering the
    (chunked) fine-rerank stage, not "must fit in one call" — fine_rerank()
    itself chunks arbitrarily-sized pools. Narrowing to that ceiling happens
    in two steps, in order: (1) if the filter-passed pool exceeds
    TRIAGE_TOP_N, a cheap Haiku triage pass buckets strong/maybe/no and keeps
    the best non-empty bucket (mirrors Mind's own coarse-funnel cutover); (2)
    only if still above `rerank_limit` after that (rare), the existing
    embedding-similarity top-K trim applies as a last-resort cap — purely for
    prompt size, never a relevance decision (min_similarity=0.0).

    `candidate_limit` is an optional dev/testing cap on how many indexed
    candidates get scanned at all (for fast local iteration on a subset of
    the full table); leave it None to scan everyone, which is what the live
    pipeline should do in real use.
    """
    from . import candidate_index, live_data
    from .constraint_engine import embed_constraints
    from .extraction import parse_job_description
    from .retrieval import retrieve_top_k

    job_raw = live_data.fetch_job_raw(job_order_id)
    job = parse_job_description(
        job_raw["raw_text"], job_id=job_raw["id"], title=job_raw["title"], company=job_raw["company"]
    )
    job.bullhorn_salary = job_raw.get("salary")
    job.bullhorn_working_model = job_raw.get("working_model")

    index = candidate_index.get_cached()
    candidates = index.all_candidates()
    if candidate_limit is not None:
        candidates = candidates[:candidate_limit]

    # Embed the job's own constraints ONCE — reused across every candidate below,
    # instead of re-embedding the same ~10 descriptions on every iteration.
    employer_embeddings = embed_constraints(job.constraints)

    eliminated: list[tuple[Candidate, CompatibilityResult]] = []
    passed: list[tuple[Candidate, CompatibilityResult]] = []
    compat_by_id: dict[str, CompatibilityResult] = {}
    for c in candidates:
        cr = run_constraint_engine(
            job, c,
            employer_embeddings=employer_embeddings,
            candidate_embeddings=index.get_constraint_embeddings(c.id),
        )
        compat_by_id[c.id] = cr
        (eliminated if cr.eliminated else passed).append((c, cr))

    passed, skill_eliminated = _apply_skill_floor_check(job, passed)
    eliminated.extend(skill_eliminated)

    passed, compensation_eliminated = _apply_compensation_band_check(job, passed)
    eliminated.extend(compensation_eliminated)

    passed, experience_eliminated = _apply_experience_overqualification_check(job, passed)
    eliminated.extend(experience_eliminated)

    passed, working_model_eliminated = _apply_working_model_check(job, passed)
    eliminated.extend(working_model_eliminated)

    title_embeddings = {c.id: index.get_title_embedding(c.id) for c, _ in passed}
    title_embeddings = {cid: emb for cid, emb in title_embeddings.items() if emb is not None}
    passed, title_eliminated = _apply_title_relevance_check(job, title_embeddings, passed)
    eliminated.extend(title_eliminated)

    coarse = coarse_role_brief(job)
    passed, newly_eliminated = _apply_location_visa_check(coarse, passed)
    eliminated.extend(newly_eliminated)

    # Narrow to the rerank ceiling, in order: cheap LLM triage first (the
    # mechanism actually designed for "which of these are worth a careful
    # look"), embedding-similarity trim only as a last-resort cap.
    rerank_pool = [c for c, _ in passed]
    if len(rerank_pool) > TRIAGE_TOP_N:
        buckets = triage_candidates(job, rerank_pool)
        rerank_pool = select_by_coarse_bucket(rerank_pool, buckets, top_n=max(rerank_limit, TRIAGE_TOP_N))

    if len(rerank_pool) > rerank_limit:
        pool_index = index.subset([c.id for c in rerank_pool])
        # min_similarity=0.0: these candidates already passed hard-constraint
        # filtering — this is a pure top-K cap for LLM prompt size, not a
        # relevance gate, so it must never return fewer than top_k just
        # because everyone's bio text embeds below some floor.
        retrieved = retrieve_top_k(job, pool_index, top_k=rerank_limit, min_similarity=0.0)
        rerank_pool = [c for c, _similarity in retrieved]

    # Best-effort: Mind's per-role weighted rubric (mind.rubric_configs), if
    # one exists for this role, gets injected into the fine-rerank prompt —
    # see _format_rubric_signals. A missing/unreachable rubric (no Supabase
    # creds, no rubric configured for this role, network error) degrades to
    # the pipeline's existing generic-prompt behavior rather than failing the
    # whole run; the rubric is an enhancement to fine-rerank, not a
    # dependency of it.
    try:
        from . import mind_rubric_store
        rubric = mind_rubric_store.get_rubric_for_role(job_order_id)
    except Exception as exc:
        print(f"    [rubric] lookup failed, continuing without a rubric: {exc}", flush=True)
        rubric = None

    ranked_raw = fine_rerank(job, coarse, rerank_pool, compat_by_id, rubric=rubric)

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
            "matched_skills": item.get("matched_skills", []),
            "missing_required_skills": item.get("missing_required_skills", []),
            "years_experience": c.years_experience,
            "seniority_level": c.seniority_level,
            # candidate_id is already the real Bullhorn candidate id (confirmed
            # against app.bullhorn_candidates) — bullhorn_id is an explicit,
            # UI-facing name for the same value. No direct "open in Bullhorn"
            # link (removed — Bullhorn's own OpenWindow.cfm page is too slow
            # to be worth it); GET /api/live/candidates/{id}/cv is the one
            # thing that actually calls Bullhorn's API, for CV download.
            "bullhorn_id": c.id,
            "linkedin_url": c.linkedin_url,
            "cv_summary": c.raw_cv,
            "call_notes": c.raw_interview_transcript,
        })

    return {
        "job": {
            "id": job.id,
            "title": job.title,
            "company": job.company,
            "required_skills": job.required_skills,
            "preferred_skills": job.preferred_skills,
        },
        "coarse_brief": coarse,
        "rubric_used": (
            {
                "rubric_id": rubric["rubric_id"],
                "version": rubric["version"],
                "role_specific": rubric.get("role_id") == job_order_id,
                "signal_count": len(rubric.get("signals") or []),
            }
            if rubric
            else None
        ),
        "ranked": ranked,
        "eliminated": [
            {"candidate_id": c.id, "name": c.name, "reasons": cr.elimination_reasons}
            for c, cr in eliminated
        ],
        "candidates_considered": len(candidates),
        "candidates_indexed": len(index),
        "candidates_passed_filter": len(passed),
        "candidates_reranked": len(rerank_pool),
    }


LLM_ONLY_MAX_WORKERS = 8


def run_llm_only_pipeline(job_order_id: int, candidate_limit: int | None = None) -> dict:
    """Full-Sonnet comparison variant: the eligible candidate pool straight to
    fine_rerank, none of run_live_pipeline's prefiltering or coarse LLM call.

    Deliberately skips, relative to run_live_pipeline:
    - constraint_engine.run_constraint_engine (hard-constraint filtering)
    - _apply_skill_floor_check / _apply_compensation_band_check /
      _apply_experience_overqualification_check / _apply_working_model_check /
      _apply_title_relevance_check / _apply_location_visa_check
    - coarse_role_brief (the coarse LLM framing call)
    - the Haiku triage_candidates bucketing
    - the embedding-similarity top-K trim

    Every candidate in the index (already gated to Mind's eligible pool at
    fetch time — see live_data._ELIGIBILITY_FILTER — this pipeline doesn't
    re-widen that) goes straight into fine_rerank. compatibility_results is
    built as an unfiltered stub (eliminated=False, no constraint_matches) so
    _format_candidate_block still renders — with an honest "(no employer
    constraints extracted)" line — without needing the constraint engine to
    have actually run. coarse_brief is `{}`, so the prompt's "Role briefing:"
    line is blank rather than fabricated.

    Runs fine_rerank with LLM_ONLY_MAX_WORKERS-way concurrency — at
    RERANK_BATCH_SIZE=32, a ~2,100-candidate eligible pool is ~67 chunks;
    serial (the default everywhere else) would take well over an hour per
    role. See fine_rerank's max_workers docstring for why concurrency is
    safe for this service specifically (it isn't a blanket recommendation —
    Mind's own reranker measured the opposite in Node.js).

    Returns the exact same shape as run_live_pipeline (job/coarse_brief/
    rubric_used/ranked/eliminated/candidates_considered/candidates_indexed/
    candidates_passed_filter/candidates_reranked) so it's a drop-in for
    llm_only_run_store and the existing LiveRecommendResult UI types —
    `eliminated` is always [] here (nothing was filtered), `rubric_used` is
    always None (no rubric lookup — see the module-level comparison doc), and
    candidates_considered/candidates_indexed/candidates_passed_filter/
    candidates_reranked are all the same number (the full pool).
    """
    from . import candidate_index, live_data
    from .extraction import parse_job_description

    job_raw = live_data.fetch_job_raw(job_order_id)
    job = parse_job_description(
        job_raw["raw_text"], job_id=job_raw["id"], title=job_raw["title"], company=job_raw["company"]
    )
    job.bullhorn_salary = job_raw.get("salary")
    job.bullhorn_working_model = job_raw.get("working_model")

    index = candidate_index.get_cached()
    pool = index.all_candidates()
    if candidate_limit is not None:
        pool = pool[:candidate_limit]

    compat_by_id = {c.id: CompatibilityResult(candidate_id=c.id, eliminated=False) for c in pool}

    ranked_raw = fine_rerank(job, {}, pool, compat_by_id, max_workers=LLM_ONLY_MAX_WORKERS)

    candidates_by_id = {c.id: c for c in pool}
    ranked = []
    for item in ranked_raw:
        c = candidates_by_id.get(item["candidate_id"])
        if c is None:
            continue
        ranked.append({
            "candidate_id": c.id,
            "name": c.name,
            "verdict": item["verdict"],
            "rationale": item["rationale"],
            "flagged_for_review": False,
            "matched_skills": item.get("matched_skills", []),
            "missing_required_skills": item.get("missing_required_skills", []),
            "years_experience": c.years_experience,
            "seniority_level": c.seniority_level,
            "bullhorn_id": c.id,
            "linkedin_url": c.linkedin_url,
            "cv_summary": c.raw_cv,
            "call_notes": c.raw_interview_transcript,
        })

    return {
        "job": {
            "id": job.id,
            "title": job.title,
            "company": job.company,
            "required_skills": job.required_skills,
            "preferred_skills": job.preferred_skills,
        },
        "coarse_brief": {},
        "rubric_used": None,  # deliberately skipped — see run_llm_only_pipeline's docstring
        "ranked": ranked,
        "eliminated": [],
        "candidates_considered": len(pool),
        "candidates_indexed": len(pool),
        "candidates_passed_filter": len(pool),
        "candidates_reranked": len(pool),
    }
