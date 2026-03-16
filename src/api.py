"""FastAPI backend for the candidate recommendation engine."""
from __future__ import annotations

import json
import os
from contextlib import asynccontextmanager
from html.parser import HTMLParser
from io import BytesIO
from pathlib import Path
from typing import Annotated

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from .constraint_engine import run_constraint_engine
from .explanation import format_elimination_reason, generate_explanations_for_pipeline
from .extraction import parse_job_description
from .models import (
    DEFAULT_WEIGHTS,
    PipelineResult,
    RawCandidate,
    RawJob,
    WEIGHT_PROFILES,
)
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
    _load_fixtures()
    yield


app = FastAPI(
    title="Candidate Recommendation Engine",
    description="AI-powered candidate ranking for job descriptions.",
    version="0.2.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


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


@app.post("/fetch-jd")
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
@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "candidates_loaded": len(_candidate_store) if _candidate_store else 0,
        "jobs_loaded": len(_raw_jobs),
    }


# ---------------------------------------------------------------------------
# GET /candidates and GET /jobs
# ---------------------------------------------------------------------------
@app.get("/candidates")
def list_candidates() -> list[dict]:
    if not _candidate_store:
        return []
    return [
        {"id": c.id, "name": c.name}
        for c in _candidate_store.get_all()
    ]


@app.get("/jobs")
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

    # Resolve weights: explicit dict > named profile > default
    if weights:
        effective_weights = weights
    elif profile:
        if profile not in WEIGHT_PROFILES:
            raise HTTPException(
                status_code=422,
                detail=f"Unknown profile '{profile}'. Available: {list(WEIGHT_PROFILES)}",
            )
        effective_weights = WEIGHT_PROFILES[profile]
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

    # 3. Constraint engine
    print("→ Running constraint engine...", flush=True)
    constraint_results = {c.id: run_constraint_engine(job, c) for c in candidates}
    eliminated = sum(1 for r in constraint_results.values() if r.eliminated)
    print(f"  ✓ {eliminated}/{len(candidates)} candidates eliminated", flush=True)

    # 4. Rank
    print("→ Scoring and ranking...", flush=True)
    pipeline_result = rank_candidates(
        job,
        candidates,
        constraint_results,
        weights=effective_weights,
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
        "profile_used": profile or ("custom" if weights else "balanced"),
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


@app.post("/recommend")
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
# POST /recommend/upload — multipart form (plain-text or PDF)
# ---------------------------------------------------------------------------
@app.post("/recommend/upload")
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
@app.get("/profiles")
def list_profiles() -> JSONResponse:
    """Return all named weight profiles with their feature weights.

    Pass profile= on /recommend to use a preset (e.g. "skills_first").
    Custom weights via the weights= field override all profiles.
    """
    return JSONResponse(content={
        name: {
            "weights": weights,
            "description": {
                "balanced": "Equal emphasis across skills, experience, and soft signals",
                "skills_first": "Prioritises required and preferred technical skill match",
                "constraints_first": "Heavy weight on constraint compliance — useful for regulated/cleared roles",
                "culture_fit": "Weights interview performance and culture fit over technical match",
            }.get(name, ""),
        }
        for name, weights in WEIGHT_PROFILES.items()
    })


# ---------------------------------------------------------------------------
# GET /evaluate/{job_id} — run pipeline on a fixture job + compare to ground truth
# ---------------------------------------------------------------------------
@app.get("/evaluate/{job_id}")
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
