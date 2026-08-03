"""Read-only adapter onto Mothership's live Supabase data (app/derived schemas).

Fetches the same candidate/job data Mind reads and maps it into rec-engine's
existing Candidate/JobDescription models, so the rest of the pipeline
(constraint engine, funnel rerank) runs unmodified against live data.

Candidate constraints are built deterministically from app.candidates'
already-typed fields (salary_normalized, notice_days, working_model,
requires_visa, deal_breakers, ...) rather than via LLM extraction — Mothership
has already done that parsing work upstream, so re-running an LLM over raw
CV/interview text here would be redundant cost and latency for no accuracy
gain. Job descriptions still go through extraction.py's LLM parsing (see
automated-constraint-extraction), since JD + briefing text is unstructured
prose Mothership doesn't pre-parse into constraints.

No writes: every function here issues a GET against Supabase's PostgREST
interface. Nothing in this module is capable of inserting, updating, or
deleting.
"""
from __future__ import annotations

import json
import os
import re

import httpx
from dotenv import load_dotenv

from .models import Candidate, Constraint, ConstraintOperator, ConstraintSide, ConstraintType, Discipline

_VALID_DISCIPLINES = set(Discipline.__args__)

load_dotenv()

_SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
_SERVICE_ROLE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")


def _headers(profile: str) -> dict[str, str]:
    if not _SUPABASE_URL or not _SERVICE_ROLE_KEY:
        raise RuntimeError(
            "SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY not set — required for live data access"
        )
    return {
        "apikey": _SERVICE_ROLE_KEY,
        "Authorization": f"Bearer {_SERVICE_ROLE_KEY}",
        "Accept-Profile": profile,
    }


_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"[ \t]+")
_BLANK_LINES_RE = re.compile(r"\n{3,}")


def _strip_html(text: str) -> str:
    """Bullhorn description fields carry rich-text HTML; flatten to plain text."""
    if not text:
        return ""
    text = re.sub(r"</(p|li|div|br)\s*>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = _TAG_RE.sub("", text)
    text = _WHITESPACE_RE.sub(" ", text)
    text = _BLANK_LINES_RE.sub("\n\n", text)
    return text.strip()


def _get(table: str, profile: str, params: dict) -> list[dict]:
    resp = httpx.get(
        f"{_SUPABASE_URL}/rest/v1/{table}",
        headers=_headers(profile),
        params=params,
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


# ---------------------------------------------------------------------------
# Jobs
# ---------------------------------------------------------------------------

def fetch_active_mind_roles(limit: int = 30) -> list[dict]:
    """List the roles Mind is actively matchmaking for right now.

    Deliberately NOT a Bullhorn status/is_open filter — Mind's own /api/roles
    (apps/web/src/app/api/roles/route.ts) determines its active-role list
    purely from mind.pinned_roles (pinned_by='admin'); a 2026-07-27 redesign
    where "the pin is the curation act", with no status/owner/date filter at
    all. Mirroring that exact source here (instead of the broader is_open set
    this originally used) means the PoC's role picker always matches what a
    recruiter actually sees in Mind, which matters for an apples-to-apples
    side-by-side demo.
    """
    pins = _get(
        "pinned_roles",
        "mind",
        {
            "select": "role_id,pinned_at",
            "pinned_by": "eq.admin",
            "order": "pinned_at.desc",
            "limit": str(limit),
        },
    )
    role_ids = [p["role_id"] for p in pins]
    if not role_ids:
        return []

    id_list = ",".join(str(i) for i in role_ids)
    rows = _get(
        "bullhorn_job_orders",
        "app",
        {"select": "id,title,raw_data", "id": f"in.({id_list})"},
    )

    by_id: dict[int, dict] = {}
    for row in rows:
        raw_data = row.get("raw_data") or {}
        if isinstance(raw_data, str):
            raw_data = json.loads(raw_data) if raw_data else {}
        company = (raw_data.get("clientCorporation") or {}).get("name", "")
        by_id[row["id"]] = {
            "job_order_id": row["id"],
            "job_title": row.get("title") or "",
            "company_name": company,
        }

    # Preserve pin order (most-recently-pinned first), matching Mind's buildPinnedRoleList.
    return [by_id[rid] for rid in role_ids if rid in by_id]


def fetch_job_raw(job_order_id: int) -> dict:
    """Fetch a job order's title/company/raw text (description + Bullhorn briefing)
    plus its structured salary figure.

    Bullhorn's JobOrder entity carries two free-text fields inside `raw_data`:
    `description` (the internal brief written after intake — what's referred to
    as the "job briefing") and `publicDescription` (the external job-ad copy).
    Both are combined into raw_text so extraction sees the full picture.

    `salary` (raw_data.salary, a single GBP figure — no separate currency field
    on this entity; every job order in this tenant is GBP) is the ATS's own
    structured budget figure, set by whoever created the job order — separate
    from, and more reliably present than, whatever an LLM might notice in the
    free-text JD/briefing prose. Spot-checked live across all 7 currently-pinned
    roles: every one has this field populated, vs. only 1 of 7 stating an
    explicit salary band in its JD text. None when the field is 0/absent (a
    genuinely unset job order, not a real zero-salary role).
    """
    rows = _get(
        "bullhorn_job_orders",
        "app",
        {"select": "id,title,raw_data", "id": f"eq.{job_order_id}", "limit": "1"},
    )
    if not rows:
        raise ValueError(f"No job order found for id={job_order_id}")
    row = rows[0]
    raw_data = row.get("raw_data") or {}
    if isinstance(raw_data, str):
        # Bullhorn's raw_data mirror is sometimes double-JSON-encoded at the source.
        raw_data = json.loads(raw_data) if raw_data else {}

    dim_rows = _get(
        "dim_job_order",
        "app",
        {"select": "company_name", "job_order_id": f"eq.{job_order_id}", "limit": "1"},
    )
    company = dim_rows[0]["company_name"] if dim_rows else raw_data.get("clientCorporation", {}).get("name", "")

    briefing = _strip_html(raw_data.get("description") or "")
    public_jd = _strip_html(raw_data.get("publicDescription") or "")
    raw_text = "\n\n---\n\n".join(part for part in (public_jd, briefing) if part)

    salary = raw_data.get("salary")
    salary = float(salary) if isinstance(salary, (int, float)) and salary > 0 else None

    # Bullhorn's own onSite field (e.g. "On-Site" / "Remote" / "Hybrid") —
    # a structured working-model signal, same "trust the ATS field over
    # LLM-noticed JD prose" reasoning as `salary` above. Spot-checked live
    # on job_order_id 1596 (Calibre): the JD prose states no explicit office
    # requirement at all, but this field says "On-Site" — without this
    # fallback, funnel_rerank._apply_working_model_check has nothing to gate
    # on for a role that's actually fully onsite.
    working_model = raw_data.get("onSite") or None

    return {
        "id": str(job_order_id),
        "title": row.get("title") or "",
        "company": company or "",
        "raw_text": raw_text,
        "salary": salary,
        "working_model": working_model,
    }


# ---------------------------------------------------------------------------
# Candidates
# ---------------------------------------------------------------------------

_CANDIDATE_SELECT = ",".join([
    "candidate_id", "first_name", "last_name", "location", "location_display", "is_uk", "is_london",
    "salary_normalized", "salary_currency", "salary_type", "notice_days", "notice_display",
    "working_model", "computed_years_exp", "current_title", "current_company",
    "computed_previous_companies", "computed_previous_titles", "computed_industries",
    "computed_is_job_hopper", "computed_has_consulting_bg", "current_company_is_startup",
    "current_company_is_large", "has_degree", "degree_level", "field_of_study",
    "certifications", "headline", "cv_summary", "skills", "title_families",
    "requires_visa", "visa_status_text", "prescreen_summary", "reason_for_leaving",
    "current_situation", "recruiter_assessment", "drivers", "deal_breakers", "tech_signals",
    "linkedin_url", "date_added", "has_cv", "has_prescreen_notes", "is_mind_eligible",
])

# Deterministic pre-pool eligibility gate (2026-07-31), reverse-engineered against
# Mind's own "Available candidates" funnel (Prescreened & UK -> CV+LinkedIn -> Not in
# process, YTD = 2,107) by cross-checking a real exported sample of eligible candidate
# ids. Best reproduction found: 2,138 (1.5% off target, ~81% recall on the sample) —
# NOT exact, since is_uk/mind_eligible_since show staleness against whatever live
# computation actually backs the dashboard (some known-eligible rows have
# location=None -> is_uk defaults false; some have mind_eligible_since entirely null).
# Shipped as the closest available approximation rather than continuing to guess field
# combinations against precomputed serving-layer snapshots. See git log / PR for the
# investigation. Previously this table's full ~17.6k rows went in completely
# unfiltered — this is a large improvement even if not pixel-perfect.
_YTD_START = "2026-01-01"

_ELIGIBILITY_FILTER = {
    "is_uk": "eq.true",
    "has_cv": "eq.true",
    "linkedin_url": "not.is.null",
    "has_prescreen_notes": "eq.true",
    "mind_eligible_since": f"gte.{_YTD_START}",
}

# "Not in process" = no non-terminal Bullhorn job submission anywhere. app.candidates
# has no per-candidate pipeline-stage field of its own, so this is read from
# raw.bullhorn_job_submissions — a registry-pinned raw exception per Mind's own
# docs/ARCHITECTURE.md (mind itself is allowed to read this raw table directly).
_TERMINAL_SUBMISSION_STATUSES = {
    "Rejected", "Candidate Rejected", "Client Rejected", "Consultant Rejected", "Placed",
}


def _fetch_in_process_candidate_ids() -> set[int]:
    """Candidate ids with at least one active (non-terminal) job submission right now."""
    ids: set[int] = set()
    start = 0
    page_size = 1000
    while True:
        resp = httpx.get(
            f"{_SUPABASE_URL}/rest/v1/bullhorn_job_submissions",
            headers={**_headers("raw"), "Range-Unit": "items", "Range": f"{start}-{start + page_size - 1}"},
            params={"select": "candidate_id,status"},
            timeout=60,
        )
        resp.raise_for_status()
        page = resp.json()
        for row in page:
            if row.get("status") not in _TERMINAL_SUBMISSION_STATUSES and row.get("candidate_id") is not None:
                ids.add(row["candidate_id"])
        if len(page) < page_size:
            break
        start += page_size
    return ids


def fetch_candidates_raw(candidate_ids: list[int] | None = None, limit: int = 200) -> list[dict]:
    params = {"select": _CANDIDATE_SELECT, "limit": str(limit)}
    if candidate_ids:
        id_list = ",".join(str(i) for i in candidate_ids)
        params["candidate_id"] = f"in.({id_list})"
    return _get("candidates", "app", params)


def fetch_cv_file_ref(candidate_id: int) -> dict | None:
    """Bullhorn file id/name for a candidate's CV, from derived.cv_parsed.

    On-demand, single-candidate lookup (not baked into candidate_index.py's
    bulk build) — CV download is a per-candidate action a recruiter takes
    while looking at one card, not a signal every one of ~17.6k candidates
    needs precomputed. Returns None if the candidate has no CV on record.
    """
    rows = _get(
        "cv_parsed", "derived",
        {"select": "bullhorn_file_id,bullhorn_file_name", "candidate_id": f"eq.{candidate_id}", "limit": "1"},
    )
    if not rows or not rows[0].get("bullhorn_file_id"):
        return None
    return rows[0]


def fetch_all_candidates_raw(page_size: int = 1000) -> list[dict]:
    """Fetch every eligible row in app.candidates, paginating past PostgREST's per-request row cap.

    Used to build the full candidate embedding index (candidate_index.py) —
    not for per-request pipeline runs, which read the index instead of
    hitting Supabase for the whole table each time.

    Gated by _ELIGIBILITY_FILTER (is_uk + has_cv + linkedin_url + has_prescreen_notes +
    mind_eligible_since >= YTD, deterministic — not a soft Constraint) plus an
    in-process exclusion against raw.bullhorn_job_submissions, and ordered by
    date_added desc (most-recently-added first, matching Mind's own gates-only
    recency ordering) rather than raw candidate_id — the pool built here becomes
    LiveCandidateIndex.all_candidates()'s iteration order, i.e. the pre-constraint
    scan order every pipeline run sees before hard cutoffs / triage / rerank.
    """
    in_process_ids = _fetch_in_process_candidate_ids()

    all_rows: list[dict] = []
    start = 0
    while True:
        resp = httpx.get(
            f"{_SUPABASE_URL}/rest/v1/candidates",
            headers={**_headers("app"), "Range-Unit": "items", "Range": f"{start}-{start + page_size - 1}"},
            params={"select": _CANDIDATE_SELECT, "order": "date_added.desc", **_ELIGIBILITY_FILTER},
            timeout=60,
        )
        resp.raise_for_status()
        page = resp.json()
        all_rows.extend(row for row in page if row["candidate_id"] not in in_process_ids)
        if len(page) < page_size:
            break
        start += page_size
    return all_rows


def _seniority_from_years(years: float) -> str:
    if years >= 10:
        return "lead"
    if years >= 6:
        return "senior"
    if years >= 3:
        return "mid"
    return "junior"


def _build_candidate_constraints(row: dict) -> list[Constraint]:
    constraints: list[Constraint] = []
    cid = str(row["candidate_id"])

    # salary_type in {contract_day, contract_hourly}: salary_normalized is a
    # day/hourly RATE, not an annual figure — building a "salary_min" floor
    # constraint from it would compare, e.g., a £600 day rate against an
    # annual salary band as if it were £600/year (reads as wildly UNDER any
    # real ceiling, silently hiding an actually-expensive contractor rather
    # than flagging one). Mind's own scoring engine carves this out explicitly
    # (mind/apps/web/src/lib/matching/scoring-engine.ts:874-887 — "comparing a
    # £500/day contractor against a £100k/year permanent budget is
    # meaningless and would false-reject every contractor"). ~7% of the
    # eligible pool (153/2138 candidates) is contract_day/contract_hourly —
    # skipping constraint creation entirely here means both the constraint
    # engine's general salary matching and funnel_rerank's compensation-band
    # gate correctly treat these candidates as "no comparable salary data"
    # (the existing no-data-is-compatible default) instead of comparing rates
    # across incompatible units.
    is_contractor = row.get("salary_type") in ("contract_day", "contract_hourly")
    if row.get("salary_normalized") and not is_contractor:
        constraints.append(Constraint(
            id=f"{cid}-salary", type=ConstraintType.soft, side=ConstraintSide.candidate,
            category="compensation", canonical_key="salary_min",
            description=f"Desired salary ~{row.get('salary_display') or row['salary_normalized']}",
            value=row["salary_normalized"], operator=ConstraintOperator.min,
            confidence=1.0, currency=row.get("salary_currency"),
        ))

    if row.get("location_display"):
        constraints.append(Constraint(
            id=f"{cid}-location", type=ConstraintType.soft, side=ConstraintSide.candidate,
            category="location", canonical_key="candidate_location",
            description=f"Based in {row['location_display']}",
            value=row["location_display"], operator=ConstraintOperator.requires,
            confidence=1.0,
        ))

    # Deterministic UK-based flag (Mothership's own is_uk classifier, not re-derived
    # here) as a *separate*, plainly-phrased boolean constraint. "uk_based" is a
    # canonical_key seen in practice from the JD extractor for UK-location
    # requirements — giving this an exact-match shot at Phase 1, rather than relying
    # solely on embedding similarity, which measured only ~0.34 between "Must be
    # UK-based" and a free-text "Based in Miami, United States" description in
    # testing — well under the 0.75 semantic-match threshold, so a real country
    # mismatch was silently passing through as "no data, assume compatible."
    if row.get("is_uk") is not None:
        constraints.append(Constraint(
            id=f"{cid}-uk-based", type=ConstraintType.soft, side=ConstraintSide.candidate,
            category="location", canonical_key="uk_based",
            description=f"UK-based: {'Yes' if row['is_uk'] else 'No'}",
            value=bool(row["is_uk"]), operator=ConstraintOperator.requires,
            confidence=1.0,
        ))

    if row.get("working_model") and row["working_model"] != "unknown":
        constraints.append(Constraint(
            id=f"{cid}-work-model", type=ConstraintType.soft, side=ConstraintSide.candidate,
            category="location", canonical_key="working_arrangement",
            description=f"Prefers {row['working_model']} working",
            value=row["working_model"], operator=ConstraintOperator.prefers,
            confidence=1.0,
        ))

    if row.get("notice_days") is not None:
        constraints.append(Constraint(
            id=f"{cid}-notice", type=ConstraintType.soft, side=ConstraintSide.candidate,
            category="scheduling", canonical_key="notice_period_days",
            description=row.get("notice_display") or f"{row['notice_days']} days notice",
            value=row["notice_days"], operator=ConstraintOperator.max,
            confidence=1.0,
        ))

    if row.get("requires_visa") is True:
        constraints.append(Constraint(
            id=f"{cid}-visa", type=ConstraintType.hard, side=ConstraintSide.candidate,
            category="visa", canonical_key="work_authorization",
            description=row.get("visa_status_text") or "Requires visa sponsorship",
            value=True, operator=ConstraintOperator.requires,
            confidence=0.9,
        ))

    for i, item in enumerate(row.get("deal_breakers") or []):
        if not isinstance(item, str) or not item.strip():
            continue
        constraints.append(Constraint(
            id=f"{cid}-dealbreaker-{i}", type=ConstraintType.hard, side=ConstraintSide.candidate,
            category="values", canonical_key=None,
            description=item.strip(), value=None, operator=ConstraintOperator.excludes,
            confidence=0.75,
        ))

    for i, item in enumerate(row.get("drivers") or []):
        if not isinstance(item, str) or not item.strip():
            continue
        constraints.append(Constraint(
            id=f"{cid}-driver-{i}", type=ConstraintType.soft, side=ConstraintSide.candidate,
            category="culture", canonical_key=None,
            description=item.strip(), value=None, operator=ConstraintOperator.prefers,
            confidence=0.6,
        ))

    return constraints


def candidate_row_to_model(row: dict) -> Candidate:
    name = " ".join(p for p in (row.get("first_name"), row.get("last_name")) if p).strip() or "Unknown"
    years = row.get("computed_years_exp") or 0.0

    cv_parts = [row.get("headline"), row.get("cv_summary")]
    if row.get("certifications"):
        cv_parts.append("Certifications: " + ", ".join(row["certifications"]))
    raw_cv = "\n".join(p for p in cv_parts if p)

    linkedin_parts = []
    if row.get("current_title") or row.get("current_company"):
        linkedin_parts.append(f"Current: {row.get('current_title') or ''} at {row.get('current_company') or ''}".strip())
    if row.get("computed_previous_titles") and row.get("computed_previous_companies"):
        prev = list(zip(row["computed_previous_titles"], row["computed_previous_companies"]))
        linkedin_parts.append("Previous: " + "; ".join(f"{t} at {c}" for t, c in prev))
    if row.get("location_display"):
        linkedin_parts.append(f"Location: {row['location_display']}")
    if row.get("computed_industries"):
        linkedin_parts.append("Industries: " + ", ".join(row["computed_industries"]))
    raw_linkedin = "\n".join(linkedin_parts)

    interview_parts = [
        row.get("prescreen_summary"), row.get("current_situation"),
        row.get("reason_for_leaving"), row.get("recruiter_assessment"),
    ]
    if row.get("tech_signals"):
        interview_parts.append("Tech discussed: " + ", ".join(row["tech_signals"]))
    raw_interview_transcript = "\n".join(p for p in interview_parts if p)

    skills = row.get("skills") or []
    if not isinstance(skills, list):
        skills = []

    title_families = row.get("title_families") or []
    discipline: Discipline = "other"
    if isinstance(title_families, list) and title_families and title_families[0] in _VALID_DISCIPLINES:
        discipline = title_families[0]

    return Candidate(
        id=str(row["candidate_id"]),
        name=name,
        raw_cv=raw_cv,
        raw_linkedin=raw_linkedin,
        raw_interview_transcript=raw_interview_transcript,
        years_experience=float(years),
        skills=skills,
        industries=row.get("computed_industries") or [],
        seniority_level=_seniority_from_years(float(years)),
        management_experience=False,  # not reliably inferable from typed fields; funnel-rerank reasons over raw text instead
        education_level=row.get("degree_level") or "bachelor",
        interview_score=0.5,
        culture_fit_score=0.5,
        constraints=_build_candidate_constraints(row),
        discipline=discipline,
        linkedin_url=row.get("linkedin_url") or "",
    )


def fetch_candidates(candidate_ids: list[int] | None = None, limit: int = 200) -> list[Candidate]:
    return [candidate_row_to_model(row) for row in fetch_candidates_raw(candidate_ids, limit)]
