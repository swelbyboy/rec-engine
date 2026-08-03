"""Structural fit-proxy comparison: rec-engine PoC vs Mind Live vs Mind Fixed
(vs rec-engine LLM-only), computed against ONE shared yardstick per role.

This is NOT a substitute for recruiter judgment or outcome/placement data —
see the "let's discuss/consider/plan" conversation this module came out of.
Real recruiter-action labels exist in mind.shortlist_run_candidates, but
sample size per role is too small to be meaningful on its own; a blind
recruiter evaluation is the credible way to actually prove "better fit". This
module is the cheap, automatable, rough-proxy layer in between: it doesn't
prove better fit, but it does prove (or disprove) whether each system's
top-N candidates plausibly clear the role's own stated bar, using ONE
definition applied identically everywhere.

Method: parse the job's requirements ONCE via extraction.parse_job_description
(this module's own yardstick — deliberately not any one system's self-report,
so no system is graded against its own definitions) and evaluate every
system's top-N candidates against it using the EXACT SAME compliance logic
already validated in funnel_rerank.py's deterministic gates
(skill_match_detail_batch, the experience/compensation-overqualification
deltas) — so "compliant" here literally means "would survive rec-engine's
own gates," applied uniformly to Mind's candidates too, not a new metric
invented just for this report.

Usage:
    python -m src.fit_proxy_report 1409 1596 1360 [--top-n 10]
"""
from __future__ import annotations

import argparse
import re
import sys

import numpy as np

from . import candidate_index, live_data, live_run_store, llm_only_run_store, mind_run_store
from .extraction import parse_job_description
from .funnel_rerank import (
    COMPENSATION_ELIMINATION_RATIO,
    EXPERIENCE_ELIMINATION_YEARS,
    EXPERIENCE_GATE_MAX_TARGET_YEARS,
    SKILL_FLOOR_RATIO,
    TITLE_RELEVANCE_FLOOR,
    _cosine,
    _embed_title,
    _employer_salary_ceiling,
    _salary_over_ratio,
)
from .models import Candidate, Constraint, ConstraintOperator, ConstraintSide, ConstraintType, JobDescription
from .scoring import skill_match_detail_batch

# Same "£145k" / "~£100k" / "£100k+" shapes seen in real Mind candidate_payload
# data (spot-checked live against role 1360) — deliberately looser than
# extraction.py's _MONEY_RE (that one's built for scanning free-text CVs;
# this one only ever sees Mind's own short, already-normalized display string).
_SALARY_RE = re.compile(r"([£$€])\s*([\d,]+(?:\.\d+)?)\s*([kK])?")


def _parse_salary_display(text: str | None) -> tuple[float, str] | None:
    if not text:
        return None
    m = _SALARY_RE.search(text)
    if not m:
        return None
    value = float(m.group(2).replace(",", ""))
    if m.group(3):
        value *= 1000
    symbol = m.group(1)
    currency = {"£": "GBP", "$": "USD", "€": "EUR"}.get(symbol, "GBP")
    return value, currency


def mind_payload_to_candidate(payload: dict) -> Candidate:
    """Adapt Mind's lean candidate_payload snapshot into rec-engine's own
    Candidate model, so compute_candidate_fit() below runs identically for
    Mind's candidates as it does for rec-engine's own — no parallel metric
    definitions to keep in sync.
    """
    cid = str(payload.get("id", ""))
    years = payload.get("yearsExp")
    constraints: list[Constraint] = []
    salary = _parse_salary_display(payload.get("salary"))
    if salary is not None:
        value, currency = salary
        constraints.append(Constraint(
            id=f"{cid}-salary", type=ConstraintType.soft, side=ConstraintSide.candidate,
            category="compensation", canonical_key="salary_min",
            description=f"Salary ~{payload.get('salary')}", value=value,
            operator=ConstraintOperator.min, confidence=1.0, currency=currency,
        ))
    return Candidate(
        id=cid,
        name=payload.get("name") or "Unknown",
        raw_cv="", raw_linkedin="", raw_interview_transcript="",
        years_experience=float(years) if years is not None else 0.0,
        skills=[s for s in (payload.get("skills") or []) if isinstance(s, str)],
        constraints=constraints,
    )


def rec_engine_candidate(candidate_id: str) -> Candidate | None:
    """Pull the full Candidate (skills + salary constraint) for a rec-engine-
    ranked candidate_id straight from the live index — the persisted run JSON
    only carries matched_skills/missing_required_skills/years_experience, not
    the full skills list or salary constraint, and re-deriving those from the
    index (already validated as current — see the compensation-gate fix
    session) is simpler than widening the persisted run shape just for this
    report.
    """
    return candidate_index.get_cached().get(candidate_id)


def compute_candidate_fit(
    job: JobDescription,
    candidate: Candidate,
    *,
    job_title_embedding: np.ndarray | None = None,
    candidate_title_embedding: np.ndarray | None = None,
) -> dict:
    """One candidate's compliance against `job`'s own stated bar — same
    thresholds as funnel_rerank.py's deterministic gates, so a candidate
    marked non-compliant here is, by definition, one rec-engine's own
    pipeline would already exclude.

    title_ok reuses funnel_rerank._apply_title_relevance_check's own
    threshold (TITLE_RELEVANCE_FLOOR) and cosine-similarity logic — same
    "no data = compatible" default as everything else here: title_ok stays
    True (not evaluated) when either embedding is unavailable, rather than
    penalizing a candidate for missing data. Deliberately NOT extended to
    working_model — investigated live and found structurally broken (employer
    canonical_key office_days_per_week never matches candidate-side
    working_arrangement, and even a forced pairing evaluates as
    compatible=True regardless — see the session notes), so there's no
    validated gate here to mirror yet.
    """
    skill_coverage: float | None = None
    if job.required_skills:
        detail = skill_match_detail_batch({candidate.id: candidate.skills}, job.required_skills)
        matched, _missing = detail.get(candidate.id, ([], list(job.required_skills)))
        skill_coverage = len(matched) / len(job.required_skills)
    skill_floor_ok = skill_coverage is None or skill_coverage >= SKILL_FLOOR_RATIO

    experience_ok = True
    if job.min_years_experience > 0 and job.min_years_experience <= EXPERIENCE_GATE_MAX_TARGET_YEARS:
        delta = candidate.years_experience - job.min_years_experience
        experience_ok = delta <= EXPERIENCE_ELIMINATION_YEARS

    ceiling = _employer_salary_ceiling(job)
    over_ratio = _salary_over_ratio(candidate, ceiling)
    compensation_ok = over_ratio is None or over_ratio <= COMPENSATION_ELIMINATION_RATIO

    title_similarity: float | None = None
    title_ok = True
    if job_title_embedding is not None and candidate_title_embedding is not None:
        title_similarity = _cosine(job_title_embedding, candidate_title_embedding)
        title_ok = title_similarity >= TITLE_RELEVANCE_FLOOR

    return {
        "candidate_id": candidate.id,
        "name": candidate.name,
        "skill_coverage": skill_coverage,
        "skill_floor_ok": skill_floor_ok,
        "experience_ok": experience_ok,
        "compensation_ok": compensation_ok,
        "title_similarity": title_similarity,
        "title_ok": title_ok,
        "fully_clean": skill_floor_ok and experience_ok and compensation_ok and title_ok,
    }


def _summarize(rows: list[dict]) -> dict:
    n = len(rows)
    if n == 0:
        return {"n": 0}
    coverages = [r["skill_coverage"] for r in rows if r["skill_coverage"] is not None]
    return {
        "n": n,
        "avg_skill_coverage": (sum(coverages) / len(coverages)) if coverages else None,
        "pct_experience_ok": sum(r["experience_ok"] for r in rows) / n,
        "pct_compensation_ok": sum(r["compensation_ok"] for r in rows) / n,
        "pct_title_ok": sum(r["title_ok"] for r in rows) / n,
        "pct_fully_clean": sum(r["fully_clean"] for r in rows) / n,
    }


def _fmt_pct(x: float | None) -> str:
    return "n/a" if x is None else f"{x:.0%}"


_MIND_FIXED_MARKER = "legacy-score"  # mirrors ComparePanel.tsx's isFixedScorerVersion


def _latest_mind_run(job_order_id: int, *, fixed: bool) -> dict | None:
    runs = mind_run_store.list_runs(job_order_id)  # newest-first
    family = [r for r in runs if (_MIND_FIXED_MARKER in (r.get("scorer_version") or "")) == fixed]
    if not family:
        return None
    return mind_run_store.get_run(family[0]["run_id"])


def _rows_from_mind_run(
    run: dict, job: JobDescription, top_n: int, job_title_embedding: np.ndarray | None = None
) -> list[dict]:
    """Mind's candidate_payload carries a plain `title` string, not a
    precomputed embedding (unlike rec-engine's own candidates, which reuse
    the index's title_embeddings.npz for free) — so a fresh OpenAI embedding
    call happens here per candidate when job_title_embedding is provided.
    Small, real marginal cost (~10 candidates per role); worth it for the
    same-methodology guarantee _embed_title already gives everywhere else.
    """
    candidates = sorted(run.get("candidates", []), key=lambda c: c.get("reranker_rank") or 10**9)
    rows = []
    for c in candidates[:top_n]:
        payload = c.get("candidate_payload") or {}
        if not payload:
            continue
        candidate_title_embedding = None
        if job_title_embedding is not None and payload.get("title"):
            candidate_title_embedding = _embed_title(payload["title"])
        rows.append(compute_candidate_fit(
            job, mind_payload_to_candidate(payload),
            job_title_embedding=job_title_embedding,
            candidate_title_embedding=candidate_title_embedding,
        ))
    return rows


def run_report(job_order_id: int, top_n: int = 10) -> list[tuple[str, list[dict]]]:
    job_raw = live_data.fetch_job_raw(job_order_id)
    print(f"\n=== job_order_id={job_order_id}: {job_raw['title']} @ {job_raw['company']} ===")

    job = parse_job_description(
        job_raw["raw_text"], job_id=job_raw["id"], title=job_raw["title"], company=job_raw["company"]
    )
    job.bullhorn_salary = job_raw.get("salary")
    ceiling = _employer_salary_ceiling(job)
    has_jd_salary_constraint = any(c.currency is not None for c in job.constraints)
    if not ceiling:
        ceiling_str = "none stated"
    elif has_jd_salary_constraint:
        ceiling_str = f"{ceiling[1]}{ceiling[0]:,.0f} (JD text)"
    else:
        ceiling_str = f"{ceiling[1]}{ceiling[0]:,.0f} (Bullhorn field)"
    print(f"Yardstick: {job.seniority}-level, {job.min_years_experience}+ yrs, "
          f"salary ceiling {ceiling_str}, {len(job.required_skills)} required skills: "
          f"{', '.join(job.required_skills) or '(none)'}")

    job_title_embedding = _embed_title(job.title)
    index = candidate_index.get_cached()

    systems: list[tuple[str, list[dict]]] = []

    rec_runs = live_run_store.list_runs(job_order_id)
    if rec_runs:
        run = live_run_store.get_run(rec_runs[0]["run_id"])
        rows = []
        for item in run.get("ranked", [])[:top_n]:
            candidate = rec_engine_candidate(item["candidate_id"])
            if candidate is not None:
                rows.append(compute_candidate_fit(
                    job, candidate,
                    job_title_embedding=job_title_embedding,
                    candidate_title_embedding=index.get_title_embedding(candidate.id),
                ))
        systems.append(("rec-engine PoC", rows))
    else:
        systems.append(("rec-engine PoC", []))

    llm_only_runs = llm_only_run_store.list_runs(job_order_id)
    if llm_only_runs:
        run = llm_only_run_store.get_run(llm_only_runs[0]["run_id"])
        rows = []
        for item in run.get("ranked", [])[:top_n]:
            candidate = rec_engine_candidate(item["candidate_id"])
            if candidate is not None:
                rows.append(compute_candidate_fit(
                    job, candidate,
                    job_title_embedding=job_title_embedding,
                    candidate_title_embedding=index.get_title_embedding(candidate.id),
                ))
        systems.append(("rec-engine LLM-only", rows))

    mind_live = _latest_mind_run(job_order_id, fixed=False)
    systems.append((
        "Mind Live",
        _rows_from_mind_run(mind_live, job, top_n, job_title_embedding) if mind_live else [],
    ))

    mind_fixed = _latest_mind_run(job_order_id, fixed=True)
    systems.append((
        "Mind Fixed",
        _rows_from_mind_run(mind_fixed, job, top_n, job_title_embedding) if mind_fixed else [],
    ))

    print(f"\n{'system':<22}{'n':>4}{'avg skill cov':>16}{'exp ok':>10}{'comp ok':>10}{'title ok':>10}{'fully clean':>14}")
    for label, rows in systems:
        s = _summarize(rows)
        if s["n"] == 0:
            print(f"{label:<22}{'—':>4}  (no run found)")
            continue
        print(
            f"{label:<22}{s['n']:>4}{_fmt_pct(s['avg_skill_coverage']):>16}"
            f"{_fmt_pct(s['pct_experience_ok']):>10}{_fmt_pct(s['pct_compensation_ok']):>10}"
            f"{_fmt_pct(s['pct_title_ok']):>10}{_fmt_pct(s['pct_fully_clean']):>14}"
        )

    return systems


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "job_order_ids", nargs="*", type=int,
        help="Specific job_order_ids to report on. Omit when using --all.",
    )
    parser.add_argument(
        "--all", action="store_true",
        help="Run against every currently pinned/active Mind role (live_data.fetch_active_mind_roles — "
             "the same source the UI's job picker uses) instead of listing ids by hand.",
    )
    parser.add_argument("--top-n", type=int, default=10)
    args = parser.parse_args()

    if args.all:
        roles = live_data.fetch_active_mind_roles(limit=50)
        job_order_ids = [r["job_order_id"] for r in roles]
        print(f"--all: running against {len(job_order_ids)} pinned roles: {job_order_ids}")
    elif args.job_order_ids:
        job_order_ids = args.job_order_ids
    else:
        parser.error("provide one or more job_order_ids, or pass --all")

    # Accumulated across every role for a combined aggregate at the end —
    # only printed when more than one role actually ran, since a single-role
    # aggregate would just repeat that role's own table.
    aggregate: dict[str, list[dict]] = {}
    successful_roles = 0

    for job_order_id in job_order_ids:
        try:
            systems = run_report(job_order_id, top_n=args.top_n)
            successful_roles += 1
            for label, rows in systems:
                aggregate.setdefault(label, []).extend(rows)
        except Exception as exc:
            print(f"\n=== job_order_id={job_order_id}: FAILED ({exc}) ===", file=sys.stderr)

    if successful_roles > 1:
        print(f"\n\n=== AGGREGATE across {successful_roles} roles ===")
        print(f"{'system':<22}{'n':>4}{'avg skill cov':>16}{'exp ok':>10}{'comp ok':>10}{'title ok':>10}{'fully clean':>14}")
        for label, rows in aggregate.items():
            s = _summarize(rows)
            if s["n"] == 0:
                print(f"{label:<22}{'—':>4}  (no data)")
                continue
            print(
                f"{label:<22}{s['n']:>4}{_fmt_pct(s['avg_skill_coverage']):>16}"
                f"{_fmt_pct(s['pct_experience_ok']):>10}{_fmt_pct(s['pct_compensation_ok']):>10}"
                f"{_fmt_pct(s['pct_title_ok']):>10}{_fmt_pct(s['pct_fully_clean']):>14}"
            )


if __name__ == "__main__":
    main()
