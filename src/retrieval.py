"""Embedding-based candidate retrieval.

Implements the retrieval stage of the pipeline:

  JD text
    ↓  embed (1 API call)
  JD embedding
    ↓  cosine similarity (numpy, O(n), sub-millisecond for n < 100k)
  Ranked candidate IDs
    ↓  take top-K
  Candidates for re-ranking (constraint engine + scoring)

This replaces the naive approach of running the full pipeline over every
candidate on each query.
"""
from __future__ import annotations

import os

import numpy as np

from .models import Candidate, JobDescription
from .store import CandidateStore

_openai_client = None

EMBEDDING_MODEL = "text-embedding-3-small"


def _get_openai_client():
    global _openai_client
    if _openai_client is None:
        from openai import OpenAI
        _openai_client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
    return _openai_client


def _embed_text(text: str) -> np.ndarray:
    response = _get_openai_client().embeddings.create(
        model=EMBEDDING_MODEL, input=[text]
    )
    return np.array(response.data[0].embedding, dtype=np.float32)


def job_to_search_text(job: JobDescription) -> str:
    """Rich natural-language representation of a JD for embedding.

    Mirrors the structure of candidate_to_search_text() so that
    cosine similarity is meaningful across the two spaces.
    """
    parts: list[str] = [
        f"{job.title} at {job.company}.",
        f"Seniority: {job.seniority}.",
    ]
    if job.required_skills:
        parts.append(f"Required skills: {', '.join(job.required_skills)}.")
    if job.preferred_skills:
        parts.append(f"Preferred skills: {', '.join(job.preferred_skills)}.")
    if job.min_years_experience:
        parts.append(f"{job.min_years_experience}+ years of experience required.")
    if job.industries_preferred:
        parts.append(f"Preferred industries: {', '.join(job.industries_preferred)}.")
    if job.management_required:
        parts.append("People management required.")
    for c in job.constraints:
        parts.append(c.description)
    return " ".join(parts)


def retrieve_top_k(
    job: JobDescription,
    store: CandidateStore,
    top_k: int = 50,
) -> list[tuple[Candidate, float]]:
    """Return top-K candidates by semantic similarity to the job description.

    If the job has a specific discipline (not 'other'), candidates are pre-filtered
    to that discipline before embedding similarity is computed. This prevents
    sales roles from returning engineering candidates and vice versa.
    If discipline filtering would leave fewer than top_k candidates, the filter
    is relaxed to include 'other' discipline candidates as well.
    """
    ids, matrix = store.embedding_matrix()
    if not ids:
        return []

    # Discipline pre-filter: build a mask of candidate indices to consider
    job_discipline = getattr(job, "discipline", "other")
    all_candidates = [store.get(cid) for cid in ids]

    if job_discipline != "other":
        # Primary: same discipline; secondary: 'other' (unclassified) as fallback
        primary_mask = np.array([
            i for i, c in enumerate(all_candidates)
            if c is not None and c.discipline == job_discipline
        ])
        fallback_mask = np.array([
            i for i, c in enumerate(all_candidates)
            if c is not None and c.discipline == "other"
        ])
        # Use primary only if enough candidates; otherwise include fallback too
        if len(primary_mask) >= min(top_k, 5):
            candidate_mask = primary_mask
        elif len(primary_mask) > 0:
            candidate_mask = np.concatenate([primary_mask, fallback_mask])
        else:
            # No candidates of this discipline in the pool — return nothing rather
            # than surfacing cross-discipline candidates.
            print(
                f"  [retrieval] No candidates found for discipline '{job_discipline}' — returning empty.",
                flush=True,
            )
            return []
        print(
            f"  [retrieval] Discipline filter '{job_discipline}': "
            f"{len(primary_mask)} primary + {len(fallback_mask)} fallback candidates",
            flush=True,
        )
    else:
        candidate_mask = np.arange(len(ids))

    filtered_ids = [ids[i] for i in candidate_mask]
    filtered_matrix = matrix[candidate_mask]

    job_text = job_to_search_text(job)
    print(f"  [retrieval] Embedding JD: '{job.title}'...", flush=True)
    job_emb = _embed_text(job_text)

    # Normalised cosine similarity: dot(norm(job), norm(candidates))
    job_norm = job_emb / (np.linalg.norm(job_emb) + 1e-10)
    row_norms = np.linalg.norm(filtered_matrix, axis=1, keepdims=True) + 1e-10
    normed_matrix = filtered_matrix / row_norms
    scores = normed_matrix @ job_norm  # shape: (n_filtered,)

    k = min(top_k, len(filtered_ids))
    top_indices = np.argsort(scores)[::-1][:k]

    results: list[tuple[Candidate, float]] = []
    for idx in top_indices:
        cid = filtered_ids[int(idx)]
        candidate = store.get(cid)
        if candidate is not None:
            results.append((candidate, float(scores[idx])))

    print(
        f"  [retrieval] Retrieved {len(results)}/{len(ids)} candidates "
        f"(top score: {results[0][1]:.3f}, bottom: {results[-1][1]:.3f})",
        flush=True,
    )
    return results
