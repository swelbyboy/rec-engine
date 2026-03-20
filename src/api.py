"""FastAPI backend for the candidate recommendation engine."""
from __future__ import annotations

import json
import os
from contextlib import asynccontextmanager
from html.parser import HTMLParser
from io import BytesIO
from pathlib import Path
from typing import Annotated

import asyncio

import httpx
from dotenv import load_dotenv
from fastapi import APIRouter, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .constraint_engine import run_constraint_engine
from .explanation import format_elimination_reason, generate_explanation, generate_explanations_for_pipeline
from .extraction import parse_job_description
from .models import (
    DEFAULT_WEIGHTS,
    PipelineResult,
    RawCandidate,
    RawJob,
)
from .ml_scoring import ML_PROFILES, clear_model_cache
from .retrieval import retrieve_top_k
from .scoring import rank_candidates
from .store import CandidateStore

load_dotenv()

DATA_DIR = Path(__file__).parent.parent / "data"

# ---------------------------------------------------------------------------
# Startup: load fixtures and populate candidate store
# ---------------------------------------------------------------------------
_candidate_store: CandidateStore | None = None
_raw_jobs: list[RawJob] = []


def _load_fixtures() -> None:
    global _candidate_store, _raw_jobs

    jobs_path = DATA_DIR / "jobs.json"
    if jobs_path.exists():
        with open(jobs_path) as f:
            data = json.load(f)
        _raw_jobs = [RawJob(**j) for j in data]

    candidates_path = DATA_DIR / "candidates.json"
    if candidates_path.exists():
        with open(candidates_path) as f:
            raw_list = json.load(f)

        _candidate_store = CandidateStore(DATA_DIR)
        print(f"→ Loading candidate store ({len(raw_list)} candidates)...", flush=True)
        _candidate_store.load(raw_list)
        print(f"  ✓ Store ready: {len(_candidate_store)} candidates", flush=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Run fixture loading in a background thread so the server starts immediately
    # and passes health checks. On re-extraction (cache miss) this can take several
    # minutes; /api/health reports candidates_loaded=0 until it completes.
    asyncio.create_task(asyncio.to_thread(_load_fixtures))
    yield


app = FastAPI(
    title="Candidate Recommendation Engine",
    description="AI-powered candidate ranking for job descriptions.",
    version="0.2.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# All API routes live under /api so they coexist with the static SPA in production.
router = APIRouter()


# ---------------------------------------------------------------------------
# POST /fetch-jd — fetch and strip HTML from a URL
# ---------------------------------------------------------------------------
class _HTMLTextExtractor(HTMLParser):
    """Minimal HTML stripper using stdlib html.parser."""

    SKIP_TAGS = {"script", "style", "head", "noscript"}

    def __init__(self) -> None:
        super().__init__()
        self._chunks: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag.lower() in self.SKIP_TAGS:
            self._skip += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in self.SKIP_TAGS:
            self._skip = max(0, self._skip - 1)

    def handle_data(self, data: str) -> None:
        if self._skip == 0:
            self._chunks.append(data)

    def get_text(self) -> str:
        raw = " ".join(self._chunks)
        # Collapse whitespace
        return " ".join(raw.split())


class FetchJdRequest(BaseModel):
    url: str


@router.post("/fetch-jd")
async def fetch_jd(request: FetchJdRequest) -> JSONResponse:
    """Fetch a URL and return its text content (HTML stripped)."""
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=15) as client:
            resp = await client.get(
                request.url,
                headers={"User-Agent": "Mozilla/5.0 (compatible; RecEngineBot/1.0)"},
            )
        resp.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Remote server returned {exc.response.status_code}",
        )
    except httpx.RequestError as exc:
        raise HTTPException(status_code=502, detail=f"Failed to fetch URL: {exc}")

    parser = _HTMLTextExtractor()
    parser.feed(resp.text)
    text = parser.get_text()

    if not text.strip():
        raise HTTPException(status_code=422, detail="No readable text found at URL")

    return JSONResponse(content={"text": text, "url": str(resp.url)})


# ---------------------------------------------------------------------------
# GET /health
# ---------------------------------------------------------------------------
@router.get("/health")
def health() -> dict:
    n = len(_candidate_store) if _candidate_store else 0
    return {
        "status": "ok" if n > 0 else "loading",
        "candidates_loaded": n,
        "jobs_loaded": len(_raw_jobs),
    }


# ---------------------------------------------------------------------------
# GET /candidates and GET /jobs
# ---------------------------------------------------------------------------
_DISCIPLINE_LABELS: dict[str, str] = {
    "engineering": "Engineering",
    "data": "Data Engineering",
    "ml_ai": "ML / AI",
    "product": "Product",
    "design": "Design",
    "devops": "DevOps / Platform",
    "sales": "Sales",
    "other": "Other",
}


@router.get("/candidates")
def list_candidates() -> list[dict]:
    if not _candidate_store:
        return []
    return [
        {
            "id": c.id,
            "name": c.name,
            "years_experience": c.years_experience,
            "seniority_level": c.seniority_level,
            "skills": c.skills,
            "industries": c.industries,
            "management_experience": c.management_experience,
            "career_trajectory": c.career_trajectory,
            "discipline": _DISCIPLINE_LABELS.get(c.discipline, c.discipline),
        }
        for c in _candidate_store.get_all()
    ]


@router.get("/jobs")
def list_jobs() -> list[dict]:
    return [{"id": j.id, "title": j.title, "company": j.company} for j in _raw_jobs]


# ---------------------------------------------------------------------------
# Core pipeline
# ---------------------------------------------------------------------------
def _run_pipeline(
    jd_text: str,
    weights: dict[str, float] | None = None,
    top_n: int = 10,
    retrieve_k: int = 50,
    profile: str | None = None,
) -> dict:
    """Parse JD → retrieve top-K candidates → constraint filter → score → explain.

    Pipeline:
      1. Parse JD (1 LLM call)
      2. Embed JD + cosine similarity over stored embeddings → top-K candidates
      3. Run constraint engine on top-K only
      4. Score and rank (eliminated candidates set aside)
      5. LLM explanation for top-N ranked candidates
    """
    if not _candidate_store or len(_candidate_store) == 0:
        raise HTTPException(status_code=503, detail="Candidate store not loaded")

    # Resolve weights: explicit dict > ML profile > default
    ml_profile: str | None = None
    if weights:
        effective_weights = weights
    elif profile and profile in ML_PROFILES:
        ml_profile = profile
        effective_weights = None
    elif profile:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown profile '{profile}'. Available ML profiles: {list(ML_PROFILES)}",
        )
    else:
        effective_weights = None  # rank_candidates will use DEFAULT_WEIGHTS

    # 1. Parse job description
    print("→ Parsing job description...", flush=True)
    job = parse_job_description(jd_text)
    print(f"  ✓ Job: {job.title} ({len(job.constraints)} constraints)", flush=True)

    # 2. Retrieve top-K semantically relevant candidates
    print(f"→ Retrieving top-{retrieve_k} candidates by embedding similarity...", flush=True)
    retrieved = retrieve_top_k(job, _candidate_store, top_k=retrieve_k)
    candidates = [c for c, _ in retrieved]
    print(f"  ✓ Retrieved {len(candidates)} candidates for re-ranking", flush=True)

    # 3. Constraint engine — run all candidates in parallel
    print("→ Running constraint engine...", flush=True)
    from concurrent.futures import ThreadPoolExecutor, as_completed as _as_completed
    constraint_results: dict[str, object] = {}
    with ThreadPoolExecutor(max_workers=min(len(candidates), 20)) as pool:
        futures = {pool.submit(run_constraint_engine, job, c): c.id for c in candidates}
        for future in _as_completed(futures):
            cid = futures[future]
            constraint_results[cid] = future.result()
    eliminated = sum(1 for r in constraint_results.values() if r.eliminated)
    print(f"  ✓ {eliminated}/{len(candidates)} candidates eliminated", flush=True)

    # 4. Rank
    print("→ Scoring and ranking...", flush=True)
    pipeline_result = rank_candidates(
        job,
        candidates,
        constraint_results,
        weights=effective_weights,
        ml_profile=ml_profile,
        top_n_explanations=top_n,
    )

    # 5. Explain (top-N only, LLM call)
    print(f"→ Generating explanations for top {top_n}...", flush=True)
    candidates_by_id = {c.id: c for c in candidates}
    pipeline_result = generate_explanations_for_pipeline(
        job, candidates_by_id, pipeline_result, top_n=top_n
    )

    # Build review_alerts: aggregate flagged constraint matches across all ranked candidates
    job_constraints_by_id = {c.id: c for c in job.constraints}
    review_alerts = []
    for sc in pipeline_result.ranked_candidates:
        for match in sc.constraint_result.constraint_matches:
            if match.flagged_for_review:
                emp_c = job_constraints_by_id.get(match.employer_constraint_id)
                review_alerts.append({
                    "candidate_id": sc.candidate_id,
                    "candidate_name": sc.name,
                    "constraint": emp_c.description if emp_c else match.employer_constraint_id,
                    "reason": match.reason,
                    "match_type": match.match_type.value,
                    "score": match.score,
                })

    # Format output
    elimination_output = [
        {
            "candidate_id": ec.candidate_id,
            "name": ec.name,
            "elimination_reason": format_elimination_reason(ec.constraint_result),
        }
        for ec in pipeline_result.eliminated_candidates
    ]

    # Candidate constraints not addressed by this JD — surfaced so recruiters can
    # see salary expectations, notice periods, etc. that the JD didn't specify.
    _SURFACE_KEYS = {"salary_min", "salary_max", "notice_period_weeks", "location_city"}

    def _candidate_requirements(sc) -> list[dict]:
        candidate = candidates_by_id.get(sc.candidate_id)
        if not candidate:
            return []
        unmatched_ids = set(sc.constraint_result.unmatched_candidate_constraints)
        return [
            {
                "description": c.description,
                "canonical_key": c.canonical_key,
                "value": c.value,
                "operator": c.operator.value,
                "type": c.type.value,
                "currency": c.currency,
            }
            for c in candidate.constraints
            if c.id in unmatched_ids
            and (c.canonical_key in _SURFACE_KEYS or c.type.value == "hard")
        ]

    ranked_output = [
        {
            "rank": i + 1,
            "candidate_id": sc.candidate_id,
            "name": sc.name,
            "score": sc.score,
            "explanation": sc.explanation,
            "feature_vector": sc.feature_vector.model_dump(),
            "flagged_for_review": sc.constraint_result.flagged_for_review,
            "constraint_matches": [
                {
                    "match_type": m.match_type.value,
                    "compatible": m.compatible,
                    "score": m.score,
                    "reason": m.reason,
                    "flagged": m.flagged_for_review,
                }
                for m in sc.constraint_result.constraint_matches
            ],
            "candidate_requirements": _candidate_requirements(sc),
        }
        for i, sc in enumerate(pipeline_result.ranked_candidates)
    ]

    return {
        "job_id": pipeline_result.job_id,
        "job_title": job.title,
        "retrieved_candidates": len(candidates),
        "ranked_candidates": ranked_output,
        "eliminated_candidates": elimination_output,
        "review_alerts": review_alerts,
        "weights_used": pipeline_result.weights_used,
        "profile_used": profile or ("custom" if weights else "default"),
        "job_details": {
            "company": job.company,
            "seniority": job.seniority,
            "min_years_experience": job.min_years_experience,
            "management_required": job.management_required,
            "required_skills": job.required_skills,
            "preferred_skills": job.preferred_skills,
            "industries_preferred": job.industries_preferred,
            "constraints": [
                {
                    "type": c.type.value,
                    "category": c.category,
                    "description": c.description,
                    "operator": c.operator.value,
                    "canonical_key": c.canonical_key,
                    "value": c.value,
                    "confidence": c.confidence,
                }
                for c in job.constraints
            ],
        },
    }


# ---------------------------------------------------------------------------
# POST /recommend — JSON body
# ---------------------------------------------------------------------------
class RecommendRequest(BaseModel):
    jd_text: str
    weights: dict[str, float] | None = None
    profile: str | None = None  # named weight profile (see GET /profiles)
    top_n: int = 10
    retrieve_k: int = 50


@router.post("/recommend")
def recommend(request: RecommendRequest) -> JSONResponse:
    """Run the full recommendation pipeline for a job description text."""
    if not request.jd_text.strip():
        raise HTTPException(status_code=422, detail="jd_text must not be empty")
    try:
        result = _run_pipeline(
            request.jd_text,
            request.weights,
            request.top_n,
            request.retrieve_k,
            request.profile,
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Pipeline error: {exc}") from exc
    return JSONResponse(content=result)


# ---------------------------------------------------------------------------
# POST /recommend/stream — SSE: emit candidates as explanations complete
# ---------------------------------------------------------------------------
def _job_details_dict(job) -> dict:
    return {
        "company": job.company,
        "seniority": job.seniority,
        "min_years_experience": job.min_years_experience,
        "management_required": job.management_required,
        "required_skills": job.required_skills,
        "preferred_skills": job.preferred_skills,
        "industries_preferred": job.industries_preferred,
        "constraints": [
            {
                "type": c.type.value, "category": c.category, "description": c.description,
                "operator": c.operator.value, "canonical_key": c.canonical_key,
                "value": c.value, "confidence": c.confidence,
            }
            for c in job.constraints
        ],
    }


@router.post("/recommend/stream")
async def recommend_stream(request: RecommendRequest) -> StreamingResponse:
    """Pipeline with SSE streaming: ranked list emitted after scoring, then
    explanations streamed one-by-one as they complete in parallel."""
    if not request.jd_text.strip():
        raise HTTPException(status_code=422, detail="jd_text must not be empty")
    if not _candidate_store or len(_candidate_store) == 0:
        raise HTTPException(status_code=503, detail="Candidate store not loaded")

    def _emit(data: dict) -> str:
        return f"data: {json.dumps(data)}\n\n"

    async def generate():
        try:
            # Resolve weights
            ml_profile: str | None = None
            if request.weights:
                effective_weights = request.weights
            elif request.profile and request.profile in ML_PROFILES:
                ml_profile = request.profile
                effective_weights = None
            elif request.profile:
                yield _emit({"type": "error", "message": f"Unknown profile '{request.profile}'. Available ML profiles: {list(ML_PROFILES)}"})
                return
            else:
                effective_weights = None

            # 1. Parse JD
            yield _emit({"type": "step", "step": "parsing"})
            job = await asyncio.to_thread(parse_job_description, request.jd_text)

            # 2. Retrieve
            yield _emit({"type": "step", "step": "retrieving"})
            retrieved = await asyncio.to_thread(
                retrieve_top_k, job, _candidate_store, request.retrieve_k
            )
            candidates = [c for c, _ in retrieved]

            # 3. Constraint engine (parallel)
            yield _emit({"type": "step", "step": "constraints"})
            constraint_list = await asyncio.gather(
                *[asyncio.to_thread(run_constraint_engine, job, c) for c in candidates]
            )
            constraint_results = {c.id: r for c, r in zip(candidates, constraint_list)}

            # 4. Score and rank
            yield _emit({"type": "step", "step": "scoring"})
            pipeline_result = rank_candidates(
                job, candidates, constraint_results,
                weights=effective_weights,
                ml_profile=ml_profile,
                top_n_explanations=request.top_n,
            )

            # Build review alerts
            job_constraints_by_id = {c.id: c for c in job.constraints}
            review_alerts = []
            for sc in pipeline_result.ranked_candidates:
                for match in sc.constraint_result.constraint_matches:
                    if match.flagged_for_review:
                        emp_c = job_constraints_by_id.get(match.employer_constraint_id)
                        review_alerts.append({
                            "candidate_id": sc.candidate_id,
                            "candidate_name": sc.name,
                            "constraint": emp_c.description if emp_c else match.employer_constraint_id,
                            "reason": match.reason,
                            "match_type": match.match_type.value,
                            "score": match.score,
                        })

            candidates_by_id = {c.id: c for c in candidates}
            _SURFACE_KEYS = {"salary_min", "salary_max", "notice_period_weeks", "location_city"}

            def _candidate_requirements_stream(sc) -> list[dict]:
                candidate = candidates_by_id.get(sc.candidate_id)
                if not candidate:
                    return []
                unmatched_ids = set(sc.constraint_result.unmatched_candidate_constraints)
                return [
                    {
                        "description": c.description,
                        "canonical_key": c.canonical_key,
                        "value": c.value,
                        "operator": c.operator.value,
                        "type": c.type.value,
                        "currency": c.currency,
                    }
                    for c in candidate.constraints
                    if c.id in unmatched_ids
                    and (c.canonical_key in _SURFACE_KEYS or c.type.value == "hard")
                ]

            def _ranked_entry(i: int, sc) -> dict:
                return {
                    "rank": i + 1,
                    "candidate_id": sc.candidate_id,
                    "name": sc.name,
                    "score": sc.score,
                    "explanation": "",
                    "feature_vector": sc.feature_vector.model_dump(),
                    "flagged_for_review": sc.constraint_result.flagged_for_review,
                    "constraint_matches": [
                        {"match_type": m.match_type.value, "compatible": m.compatible,
                         "score": m.score, "reason": m.reason, "flagged": m.flagged_for_review}
                        for m in sc.constraint_result.constraint_matches
                    ],
                    "candidate_requirements": _candidate_requirements_stream(sc),
                }

            # Emit full ranked structure (no explanations yet) — UI shows cards immediately
            yield _emit({
                "type": "meta",
                "job_id": pipeline_result.job_id,
                "job_title": job.title,
                "job_details": _job_details_dict(job),
                "ranked_candidates": [_ranked_entry(i, sc) for i, sc in enumerate(pipeline_result.ranked_candidates)],
                "eliminated_candidates": [
                    {"candidate_id": ec.candidate_id, "name": ec.name,
                     "elimination_reason": format_elimination_reason(ec.constraint_result)}
                    for ec in pipeline_result.eliminated_candidates
                ],
                "review_alerts": review_alerts,
                "retrieved_candidates": len(candidates),
                "weights_used": pipeline_result.weights_used,
                "profile_used": request.profile or ("custom" if request.weights else "default"),
            })

            # 5. Generate explanations in parallel, emit as each completes
            yield _emit({"type": "step", "step": "explaining"})
            top_n = min(request.top_n, len(pipeline_result.ranked_candidates))
            queue: asyncio.Queue = asyncio.Queue()

            async def _explain_one(rank_idx: int, sc) -> None:
                candidate = candidates_by_id.get(sc.candidate_id)
                if not candidate:
                    await queue.put((rank_idx, ""))
                    return
                try:
                    text = await asyncio.to_thread(
                        generate_explanation,
                        job, candidate, sc.feature_vector, sc.constraint_result, sc.score,
                    )
                except Exception:
                    text = ""
                await queue.put((rank_idx, text))

            top_candidates = list(enumerate(pipeline_result.ranked_candidates[:top_n]))
            for task_coro in [_explain_one(i, sc) for i, sc in top_candidates]:
                asyncio.create_task(task_coro)

            for _ in range(len(top_candidates)):
                rank_idx, explanation = await queue.get()
                yield _emit({"type": "explanation", "rank": rank_idx + 1, "explanation": explanation})

            yield _emit({"type": "done"})

        except Exception as exc:
            yield _emit({"type": "error", "message": str(exc)})

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ---------------------------------------------------------------------------
# POST /recommend/upload — multipart form (plain-text or PDF)
# ---------------------------------------------------------------------------
@router.post("/recommend/upload")
async def recommend_upload(
    file: UploadFile = File(...),
    weights: str = Form(default="{}"),
    top_n: int = Form(default=10),
) -> JSONResponse:
    """Run the recommendation pipeline from an uploaded JD file (txt or PDF)."""
    content_type = file.content_type or ""
    filename = file.filename or ""

    raw_bytes = await file.read()

    if content_type == "application/pdf" or filename.lower().endswith(".pdf"):
        try:
            from pypdf import PdfReader
            reader = PdfReader(BytesIO(raw_bytes))
            jd_text = "\n".join(page.extract_text() or "" for page in reader.pages)
        except Exception as exc:
            raise HTTPException(
                status_code=422, detail=f"Failed to extract text from PDF: {exc}"
            )
    else:
        try:
            jd_text = raw_bytes.decode("utf-8")
        except UnicodeDecodeError:
            jd_text = raw_bytes.decode("latin-1")

    if not jd_text.strip():
        raise HTTPException(status_code=422, detail="Uploaded file produced no text")

    try:
        parsed_weights = json.loads(weights) if weights else {}
    except json.JSONDecodeError:
        raise HTTPException(status_code=422, detail="weights must be valid JSON")

    try:
        result = _run_pipeline(jd_text, parsed_weights or None, top_n)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Pipeline error: {exc}") from exc
    return JSONResponse(content=result)


# ---------------------------------------------------------------------------
# GET /profiles — list named weight profiles
# ---------------------------------------------------------------------------
@router.get("/profiles")
def list_profiles() -> JSONResponse:
    """Return available ML scoring profiles.

    Pass profile= on /recommend to use an ML model (e.g. "logistic" or "gbt").
    Custom weights via the weights= field bypass profiles entirely.
    """
    return JSONResponse(content={
        "logistic": {
            "type": "ml",
            "description": (
                "Logistic regression trained on labeled recruiter decisions. "
                "Linear decision boundary with learned feature weights."
            ),
        },
        "gbt": {
            "type": "ml",
            "description": (
                "Gradient-boosted classifier trained on labeled recruiter decisions. "
                "Captures non-linear feature interactions (skill x seniority synergy, "
                "skill threshold cliff, experience-skill substitution)."
            ),
        },
    })


# ---------------------------------------------------------------------------
# GET /evaluate/{job_id} — run pipeline on a fixture job + compare to ground truth
# ---------------------------------------------------------------------------
@router.get("/evaluate/{job_id}")
def evaluate(job_id: str, profile: str | None = None) -> JSONResponse:
    """Run the full pipeline on a fixture job and score against hand-labelled ground truth.

    Returns Kendall's tau, NDCG@5, elimination precision/recall, and a per-candidate
    rank comparison showing where the system agrees or diverges from expert judgement.

    Uses retrieve_k = total candidates so elimination accuracy is computed over all
    candidates (not just the top-K semantic retrieval subset).
    """
    # Find fixture job
    raw_job = next((j for j in _raw_jobs if j.id == job_id), None)
    if not raw_job:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found in fixtures")

    # Load ground truth
    gt_path = DATA_DIR / "ground_truth.json"
    if not gt_path.exists():
        raise HTTPException(status_code=404, detail="data/ground_truth.json not found")

    with open(gt_path) as f:
        ground_truth_data = json.load(f)

    gt = next((g for g in ground_truth_data if g["job_id"] == job_id), None)
    if not gt:
        raise HTTPException(status_code=404, detail=f"No ground truth entry for '{job_id}'")

    # Run pipeline over all candidates (not just top-K) for full evaluation coverage
    n_candidates = len(_candidate_store) if _candidate_store else 50
    try:
        result = _run_pipeline(
            raw_job.description,
            weights=None,
            top_n=n_candidates,
            retrieve_k=n_candidates,
            profile=profile,
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Pipeline error: {exc}") from exc

    predicted_ranked = [r["candidate_id"] for r in result["ranked_candidates"]]
    predicted_eliminated = [e["candidate_id"] for e in result["eliminated_candidates"]]

    from .evaluation import evaluate_ranking
    metrics = evaluate_ranking(
        predicted_ranked=predicted_ranked,
        predicted_eliminated=predicted_eliminated,
        ground_truth_ranked=gt["expected_ranking"],
        ground_truth_eliminated=gt["expected_eliminated"],
    )

    return JSONResponse(content={
        "job_id": job_id,
        "job_label": gt.get("label", raw_job.title),
        "ground_truth_notes": gt.get("notes", ""),
        "profile_used": result.get("profile_used", "balanced"),
        "pipeline": {
            "ranked_candidates": predicted_ranked,
            "eliminated_candidates": predicted_eliminated,
        },
        "ground_truth": {
            "expected_ranking": gt["expected_ranking"],
            "expected_eliminated": gt["expected_eliminated"],
        },
        "metrics": metrics,
        "review_alerts": result.get("review_alerts", []),
    })


# ---------------------------------------------------------------------------
# GET /model/metrics — AUC, Brier score, log loss for both models on held-out test set
# ---------------------------------------------------------------------------
def _compute_metrics() -> dict:
    """Load training data + both models, reproduce the 80/20 split, return error metrics."""
    from .ml_scoring import FEATURE_ORDER, _MODELS_DIR

    try:
        import joblib
        import numpy as np
        from sklearn.metrics import brier_score_loss, log_loss as sklearn_log_loss, roc_auc_score
        from sklearn.model_selection import train_test_split
    except ImportError as exc:
        raise HTTPException(status_code=500, detail=f"scikit-learn not installed: {exc}")

    td_path = DATA_DIR / "training_data.json"
    if not td_path.exists():
        raise HTTPException(status_code=404, detail="training_data.json not found")

    with open(td_path) as f:
        td = json.load(f)
    records = td.get("records", [])
    if len(records) < 10:
        raise HTTPException(status_code=422, detail="Not enough records to evaluate")

    X = np.array([r["features"] for r in records], dtype=np.float64)
    y = np.array([r["outcome"] for r in records], dtype=np.int32)
    _, X_test, _, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

    result: dict = {"n_test": len(y_test), "feature_names": FEATURE_ORDER}
    for profile, filename in [("logistic", "logistic_regression.joblib"), ("gbt", "gradient_boosted.joblib")]:
        path = _MODELS_DIR / filename
        if not path.exists():
            continue
        model = joblib.load(path)
        proba = model.predict_proba(X_test)[:, 1]
        result[profile] = {
            "auc": float(roc_auc_score(y_test, proba)),
            "brier_score": float(brier_score_loss(y_test, proba)),
            "log_loss": float(sklearn_log_loss(y_test, proba)),
        }

    return result


@router.get("/model/metrics")
def model_metrics() -> JSONResponse:
    """Compute AUC, Brier score, and log loss for both models on the held-out test split."""
    try:
        result = _compute_metrics()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return JSONResponse(content=result)


# ---------------------------------------------------------------------------
# GET /model/weights — logistic coefficients + GBT feature importances
# ---------------------------------------------------------------------------
@router.get("/model/weights")
def model_weights() -> JSONResponse:
    """Return feature weights for trained models.

    Logistic: scaled coefficients (positive = boosts shortlisting probability).
    GBT: feature importances (sum to 1, always positive).
    """
    from .ml_scoring import FEATURE_ORDER, _MODELS_DIR

    try:
        import joblib
    except ImportError:
        raise HTTPException(status_code=500, detail="joblib not installed")

    result: dict = {"feature_names": FEATURE_ORDER}

    def _extract(path, profile):
        if not path.exists():
            return None
        model = joblib.load(path)
        if profile == "logistic":
            # Stored as Pipeline(scaler, clf)
            clf = model.named_steps["clf"]
            return {"weights": clf.coef_[0].tolist(), "type": "coefficients"}
        else:
            # May be bare classifier (old) or Pipeline (retrained)
            clf = model.named_steps["clf"] if hasattr(model, "named_steps") else model
            return {"weights": clf.feature_importances_.tolist(), "type": "importances"}

    for profile, filename in [("logistic", "logistic_regression.joblib"), ("gbt", "gradient_boosted.joblib")]:
        extracted = _extract(_MODELS_DIR / filename, profile)
        if extracted:
            result[profile] = extracted

    return JSONResponse(content=result)


# ---------------------------------------------------------------------------
# POST /feedback — append recruiter decisions to feedback.jsonl
# ---------------------------------------------------------------------------
class _FeedbackRecord(BaseModel):
    candidate_id: str
    job_id: str
    features: list[float]
    outcome: int  # 0 or 1
    source: str = "recruiter"


class _FeedbackRequest(BaseModel):
    records: list[_FeedbackRecord]


@router.post("/feedback")
def submit_feedback(request: _FeedbackRequest) -> JSONResponse:
    feedback_path = DATA_DIR / "feedback.jsonl"
    feedback_path.parent.mkdir(parents=True, exist_ok=True)
    with open(feedback_path, "a") as f:
        for rec in request.records:
            f.write(json.dumps(rec.model_dump()) + "\n")
    total = sum(1 for _ in open(feedback_path)) if feedback_path.exists() else 0
    return JSONResponse(content={"saved": len(request.records), "total_feedback": total})


# ---------------------------------------------------------------------------
# POST /training-data/upload — merge CSV or JSON into training_data.json
# ---------------------------------------------------------------------------
@router.post("/training-data/upload")
async def upload_training_data(file: UploadFile = File(...)) -> JSONResponse:
    from .ml_scoring import FEATURE_ORDER

    content = await file.read()
    filename = (file.filename or "").lower()

    new_records: list[dict] = []
    if filename.endswith(".csv"):
        import csv, io
        reader = csv.DictReader(io.StringIO(content.decode("utf-8")))
        for row in reader:
            try:
                features = [float(row[k]) for k in FEATURE_ORDER]
                outcome = int(float(row["outcome"]))
                new_records.append({"features": features, "outcome": outcome})
            except (KeyError, ValueError):
                continue
    else:
        try:
            data = json.loads(content)
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=422, detail=f"Invalid JSON: {exc}")
        raw = data.get("records", data) if isinstance(data, dict) else data
        for r in raw:
            try:
                new_records.append({
                    "features": [float(v) for v in r["features"]],
                    "outcome": int(r["outcome"]),
                })
            except (KeyError, ValueError, TypeError):
                continue

    if not new_records:
        raise HTTPException(status_code=422, detail="No valid records found in uploaded file")

    td_path = DATA_DIR / "training_data.json"
    if td_path.exists():
        with open(td_path) as f:
            td = json.load(f)
    else:
        td = {"version": 1, "feature_names": FEATURE_ORDER, "records": []}

    existing = td.get("records", [])
    next_id = len(existing) + 1
    for rec in new_records:
        existing.append({"id": f"upload-{next_id:04d}", **rec})
        next_id += 1
    td["records"] = existing
    td["n_records"] = len(existing)

    with open(td_path, "w") as f:
        json.dump(td, f, indent=2)

    return JSONResponse(content={"records_added": len(new_records), "total_records": len(existing)})


# ---------------------------------------------------------------------------
# POST /retrain — retrain logistic + GBT models in-process
# ---------------------------------------------------------------------------
_REGRESSION_TOLERANCE = 0.01  # max allowable AUC drop before gate blocks save


def _do_retrain(force: bool = False) -> dict:
    """Synchronous retraining — runs in FastAPI threadpool via run_in_executor."""
    import datetime
    from .ml_scoring import FEATURE_ORDER, _MODELS_DIR

    # Load training_data.json
    td_path = DATA_DIR / "training_data.json"
    records: list[dict] = []
    if td_path.exists():
        with open(td_path) as f:
            td = json.load(f)
        records.extend(td.get("records", []))

    # Load feedback.jsonl
    feedback_path = DATA_DIR / "feedback.jsonl"
    if feedback_path.exists():
        with open(feedback_path) as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        rec = json.loads(line)
                        records.append({"features": rec["features"], "outcome": rec["outcome"]})
                    except (json.JSONDecodeError, KeyError):
                        continue

    if len(records) < 10:
        raise HTTPException(status_code=422, detail=f"Need at least 10 records to retrain, got {len(records)}")

    try:
        import numpy as np
        from sklearn.ensemble import GradientBoostingClassifier
        from sklearn.linear_model import LogisticRegression
        from sklearn.metrics import roc_auc_score
        from sklearn.model_selection import cross_val_score, train_test_split
        from sklearn.pipeline import Pipeline
        from sklearn.preprocessing import StandardScaler
        import joblib
    except ImportError as exc:
        raise HTTPException(status_code=500, detail=f"scikit-learn not installed: {exc}")

    X = np.array([r["features"] for r in records], dtype=np.float64)
    y = np.array([r["outcome"] for r in records], dtype=np.int32)

    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

    # Logistic
    log_pipe = Pipeline([
        ("scaler", StandardScaler()),
        ("clf", LogisticRegression(C=1.0, solver="lbfgs", max_iter=1000)),
    ])
    from sklearn.metrics import brier_score_loss, log_loss as sklearn_log_loss

    log_pipe.fit(X_train, y_train)
    log_proba = log_pipe.predict_proba(X_test)[:, 1]
    log_auc = float(roc_auc_score(y_test, log_proba))
    log_brier = float(brier_score_loss(y_test, log_proba))
    log_logloss = float(sklearn_log_loss(y_test, log_proba))
    log_cv = cross_val_score(log_pipe, X, y, cv=5, scoring="roc_auc")

    # GBT
    gbt_pipe = Pipeline([
        ("scaler", StandardScaler()),
        ("clf", GradientBoostingClassifier(n_estimators=200, max_depth=4, learning_rate=0.05,
                                            subsample=0.8, min_samples_leaf=10, random_state=42)),
    ])
    gbt_pipe.fit(X_train, y_train)
    gbt_proba = gbt_pipe.predict_proba(X_test)[:, 1]
    gbt_auc = float(roc_auc_score(y_test, gbt_proba))
    gbt_brier = float(brier_score_loss(y_test, gbt_proba))
    gbt_logloss = float(sklearn_log_loss(y_test, gbt_proba))
    gbt_cv = cross_val_score(gbt_pipe, X, y, cv=5, scoring="roc_auc")

    # Regression gate — block save if both models regress beyond tolerance (unless forced)
    meta_path = _MODELS_DIR / "metadata.json"
    if not force and meta_path.exists():
        try:
            with open(meta_path) as f:
                old_meta = json.load(f)
            old_log_auc = old_meta.get("models", {}).get("logistic", {}).get("auc")
            old_gbt_auc = old_meta.get("models", {}).get("gbt", {}).get("auc")
            if old_log_auc is not None and old_gbt_auc is not None:
                log_regressed = log_auc < old_log_auc - _REGRESSION_TOLERANCE
                gbt_regressed = gbt_auc < old_gbt_auc - _REGRESSION_TOLERANCE
                if log_regressed and gbt_regressed:
                    raise HTTPException(
                        status_code=409,
                        detail={
                            "message": "Retraining would regress both models. Use force=true to override.",
                            "regression": {
                                "logistic": {"old_auc": old_log_auc, "new_auc": log_auc},
                                "gbt": {"old_auc": old_gbt_auc, "new_auc": gbt_auc},
                            },
                        },
                    )
        except HTTPException:
            raise
        except Exception:
            pass  # Unreadable old metadata — skip gate

    # Save
    _MODELS_DIR.mkdir(parents=True, exist_ok=True)
    joblib.dump(log_pipe, _MODELS_DIR / "logistic_regression.joblib")
    joblib.dump(gbt_pipe, _MODELS_DIR / "gradient_boosted.joblib")

    trained_at = datetime.datetime.utcnow().isoformat() + "Z"
    meta = {
        "trained_at": trained_at,
        "total_records": len(records),
        "feature_names": FEATURE_ORDER,
        "models": {
            "logistic": {
                "auc": log_auc, "cv_auc": float(log_cv.mean()), "cv_auc_std": float(log_cv.std()),
                "brier_score": log_brier, "log_loss": log_logloss,
            },
            "gbt": {
                "auc": gbt_auc, "cv_auc": float(gbt_cv.mean()), "cv_auc_std": float(gbt_cv.std()),
                "brier_score": gbt_brier, "log_loss": gbt_logloss,
            },
        },
    }
    with open(_MODELS_DIR / "metadata.json", "w") as f:
        json.dump(meta, f, indent=2)

    clear_model_cache()
    return meta


@router.post("/retrain")
async def retrain_models(force: bool = False) -> JSONResponse:
    try:
        result = await asyncio.to_thread(lambda: _do_retrain(force=force))
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Retraining failed: {exc}")
    return JSONResponse(content={
        "logistic": result["models"]["logistic"],
        "gbt": result["models"]["gbt"],
        "total_records": result["total_records"],
        "trained_at": result["trained_at"],
    })


# ---------------------------------------------------------------------------
# GET /model/status — metadata.json + feedback + training data counts
# ---------------------------------------------------------------------------
@router.get("/model/status")
def model_status() -> JSONResponse:
    meta_path = Path(__file__).parent.parent / "models" / "metadata.json"
    meta: dict = {}
    if meta_path.exists():
        with open(meta_path) as f:
            meta = json.load(f)

    feedback_count = 0
    feedback_path = DATA_DIR / "feedback.jsonl"
    if feedback_path.exists():
        feedback_count = sum(1 for line in open(feedback_path) if line.strip())

    training_data_count = 0
    td_path = DATA_DIR / "training_data.json"
    if td_path.exists():
        with open(td_path) as f:
            td = json.load(f)
        training_data_count = len(td.get("records", []))

    return JSONResponse(content={
        **meta,
        "feedback_count": feedback_count,
        "training_data_count": training_data_count,
    })


# ---------------------------------------------------------------------------
# Register /api router + serve built React SPA
# ---------------------------------------------------------------------------
app.include_router(router, prefix="/api")

# Serve the Vite build output in production (ui/dist must exist).
# All /api/* requests are handled above; anything else falls through to the SPA.
_ui_dist = Path(__file__).parent.parent / "ui" / "dist"
if _ui_dist.exists():
    app.mount("/", StaticFiles(directory=str(_ui_dist), html=True), name="ui")
