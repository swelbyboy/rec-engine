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
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np
from dotenv import load_dotenv

from .constraint_engine import run_constraint_engine
from .explanation import _format_constraint_matches
from .models import FINE_RERANK_MODEL, LLM_MODEL, Candidate, CompatibilityResult, JobDescription
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
) -> dict:
    """Single tool-forced LLM call, with an optional retry for transient errors.

    cache_system=True marks the system prompt as ephemeral-cacheable — worth
    it once a stage makes several calls per run sharing the same (large,
    static) system prompt, e.g. chunked fine-rerank/triage; not worth the
    extra request shape for a stage that only ever makes one call per run
    (e.g. the coarse role brief).
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
                    return block.input
            raise RuntimeError("No tool use block in response")
        except Exception:
            if attempt >= retries:
                raise
            attempt += 1
            print(f"    [LLM] call failed, retrying ({attempt}/{retries})...", flush=True)
            time.sleep(1.5)


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
  rationale only if genuinely relevant to fit.
- Each candidate block includes a "Role skill fit" line showing which of the
  role's required/preferred skills are evidenced vs missing (computed directly
  from structured skill data, not inferred by you). Treat missing REQUIRED
  skills as a real fit gap and say so plainly — do not let broad seniority or
  an unrelated but impressive background paper over a candidate having none
  of the specific skills this role needs."""

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


def _format_candidate_block(
    job: JobDescription,
    candidate: Candidate,
    cr: CompatibilityResult,
    skill_detail: tuple[list[str], list[str]],
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

    return f"""### Candidate {candidate.id}: {candidate.name}
Experience: {candidate.years_experience} yrs | Seniority: {candidate.seniority_level}
Skills: {', '.join(candidate.skills[:20]) or 'none listed'}
Background: {_strip_lone_surrogates(candidate.raw_linkedin) or '(no summary)'}
CV notes: {_strip_lone_surrogates(candidate.raw_cv) or '(none)'}
Recruiter call notes: {_strip_lone_surrogates(candidate.raw_interview_transcript) or '(none)'}
{skill_fit_line}
Constraint match against this role{flagged}:
{constraint_block}"""


def _chunk(items: list, size: int) -> list[list]:
    return [items[i : i + size] for i in range(0, len(items), size)]


RERANK_BATCH_SIZE = 40  # candidates per fine-rerank call — reused from the prior single-call default


def _fine_rerank_chunk(
    job: JobDescription,
    coarse_brief: dict,
    pool: list[Candidate],
    compatibility_results: dict[str, CompatibilityResult],
    skill_detail: dict[str, tuple[list[str], list[str]]],
) -> list[dict]:
    """Rank a single chunk (≤RERANK_BATCH_SIZE) with one batched LLM call.

    Not called directly for a full pool — see fine_rerank(), which chunks and
    merges. Kept separate so each call stays well clear of the max_tokens
    ceiling that a single call over an unbounded pool would hit.

    skill_detail is computed once for the whole pool by the caller (fine_rerank)
    and passed in here — avoids re-running skill_match_detail_batch per chunk.
    """
    if not pool:
        return []

    candidate_blocks = "\n\n".join(
        _format_candidate_block(job, c, compatibility_results[c.id], skill_detail.get(c.id, ([], [])))
        for c in pool
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
        model=FINE_RERANK_MODEL,
        cache_system=True,
        retries=1,
    )
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
) -> list[dict]:
    """Stage 2: rank the constraint-filtered pool with verdict + rationale.

    Chunks the pool into fixed-size batches (RERANK_BATCH_SIZE) and calls the
    fine-rerank LLM once per chunk, serially — not one big call. A single call
    scaling its max_tokens with pool size hits Anthropic's output ceiling
    around ~32 candidates; Mind's own production rerank
    (mind/apps/web/src/lib/reranks/rerank-anthropic.ts) solves this the same
    way: fixed batch size + serial calls (concurrent long-lived streams were
    found to starve the event loop in production) + a merge step, not a
    bigger single call.

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

    chunks = _chunk(pool, RERANK_BATCH_SIZE)
    batches = [
        _fine_rerank_chunk(job, coarse_brief, chunk, compatibility_results, skill_detail)
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


def _bullhorn_url(candidate_id: str) -> str:
    """Deep-link to a candidate's record in Bullhorn, or "" if not configured.

    candidate_id is already the real Bullhorn candidate id (see
    _apply_title_relevance_check's neighbourhood — confirmed by cross-checking
    app.candidates.candidate_id against app.bullhorn_candidates.id for the
    same person). URL pattern mirrors Mind's own
    apps/web/src/lib/bullhorn/rejection-collector.ts, which degrades to no
    link the same way when its tenant URL isn't configured.
    """
    tenant = os.environ.get("BULLHORN_TENANT_URL", "").rstrip("/")
    if not tenant:
        return ""
    return f"{tenant}/BullhornSTAFFING/OpenWindow.cfm?Entity=Candidate&id={candidate_id}&view=Overview"


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

    ranked_raw = fine_rerank(job, coarse, rerank_pool, compat_by_id)

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
            # against app.bullhorn_candidates) — bullhorn_id/bullhorn_url are
            # explicit, UI-facing names for the same value rather than a new field.
            "bullhorn_id": c.id,
            "bullhorn_url": _bullhorn_url(c.id),
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
        "candidates_indexed": len(index),
        "candidates_passed_filter": len(passed),
        "candidates_reranked": len(rerank_pool),
    }
