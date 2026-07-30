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
from typing import Protocol

import numpy as np

from .models import Candidate, JobDescription

_openai_client = None


class EmbeddingStore(Protocol):
    """Anything retrieve_top_k can search: an ID-ordered embedding matrix plus lookup by ID.

    Implemented by both the fixture-backed CandidateStore (store.py) and the
    persisted live-candidate index (candidate_index.py) — retrieval doesn't
    care which candidate source it's ranking.
    """

    def embedding_matrix(self) -> tuple[list[str], np.ndarray]: ...
    def get(self, candidate_id: str) -> Candidate | None: ...

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


_MIN_RETRIEVAL_SIMILARITY = 0.25  # candidates below this cosine sim are semantically irrelevant


def retrieve_top_k(
    job: JobDescription,
    store: EmbeddingStore,
    top_k: int = 50,
    min_similarity: float | None = None,
) -> list[tuple[Candidate, float]]:
    """Return top-K candidates by semantic similarity to the job description.

    Candidates with cosine similarity below min_similarity are excluded before
    ranking (defaults to _MIN_RETRIEVAL_SIMILARITY). This naturally handles
    cross-discipline cases (e.g. a sales JD scores very low against tech
    candidates) without any hardcoded discipline rules.

    Pass min_similarity=0.0 when narrowing a pool that's already been
    positively qualified some other way (e.g. candidates who already passed
    hard-constraint filtering) — a relevance floor makes sense before any
    compatibility check has run, but applying it again afterwards, purely to
    cap how many go into an LLM prompt, risks returning empty (and silently
    dropping otherwise-qualified candidates) if everyone happens to have
    sparse bio text that embeds below the floor.
    """
    if min_similarity is None:
        min_similarity = _MIN_RETRIEVAL_SIMILARITY

    ids, matrix = store.embedding_matrix()
    if not ids:
        return []

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

    # Apply minimum similarity threshold — excludes semantically irrelevant candidates
    eligible = np.where(scores >= min_similarity)[0]
    if len(eligible) == 0:
        print(
            f"  [retrieval] No candidates above similarity threshold "
            f"{min_similarity} (best: {scores.max():.3f}) — returning empty.",
            flush=True,
        )
        return []

    eligible_scores = scores[eligible]
    k = min(top_k, len(eligible))
    top_indices = eligible[np.argsort(eligible_scores)[::-1][:k]]

    results: list[tuple[Candidate, float]] = []
    for idx in top_indices:
        cid = filtered_ids[int(idx)]
        candidate = store.get(cid)
        if candidate is not None:
            results.append((candidate, float(scores[idx])))

    print(
        f"  [retrieval] Retrieved {len(results)}/{len(ids)} candidates "
        f"(top: {results[0][1]:.3f}, bottom: {results[-1][1]:.3f}, "
        f"below threshold: {len(filtered_ids) - len(eligible)})",
        flush=True,
    )
    return results
