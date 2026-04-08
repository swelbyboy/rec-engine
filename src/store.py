"""Offline candidate store with content-hash caching and embeddings.

Candidates are parsed from fixtures exactly once. Results (parsed Candidate +
embedding vector) are cached in data/processed/<id>.json. On subsequent runs,
only candidates whose raw source data has changed are re-processed.

Pipeline:
  fixtures (candidates.json)
       ↓  [first run or source changed]
  LLM extraction (parse_candidate)
       ↓
  Embedding (text-embedding-3-small)
       ↓
  Cache (data/processed/<id>.json)
       ↓  [all subsequent runs]
  In-memory store (Candidate + np.ndarray)
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import numpy as np

from .models import Candidate

_openai_client = None

EMBEDDING_MODEL = "text-embedding-3-small"

# Increment this whenever the Candidate schema gains new extracted fields.
# Any cached file with a different version is treated as stale and re-processed.
CACHE_SCHEMA_VERSION = 3  # v3: discipline now extracted by LLM (was always defaulting to "other")


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


def _raw_hash(raw: dict) -> str:
    """Content hash of raw candidate data — used to detect stale cache."""
    return hashlib.md5(
        json.dumps(raw, sort_keys=True).encode()
    ).hexdigest()[:16]


def candidate_to_search_text(candidate: Candidate) -> str:
    """Rich natural-language representation of a candidate for embedding.

    Captures skills, experience, industries, and constraint summaries so that
    semantic retrieval finds relevant candidates even with vocabulary mismatch
    (e.g. 'Apache Airflow' vs 'Airflow').
    """
    parts: list[str] = [
        f"{candidate.name} — {candidate.seniority_level} with "
        f"{candidate.years_experience:.0f} years of experience.",
    ]
    if candidate.skills:
        parts.append(f"Skills: {', '.join(candidate.skills)}.")
    if candidate.industries:
        parts.append(f"Industries: {', '.join(candidate.industries)}.")
    if candidate.management_experience:
        parts.append("Has people management experience.")
    for c in candidate.constraints:
        parts.append(c.description)
    return " ".join(parts)


class CandidateStore:
    """Pre-processed candidate store backed by a file cache.

    Usage:
        store = CandidateStore(Path("data"))
        store.load(raw_candidates)   # idempotent: only processes new/changed
        candidates = store.get_all()
        ids, matrix = store.embedding_matrix()
    """

    def __init__(self, data_dir: Path) -> None:
        self.cache_dir = data_dir / "processed"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._candidates: dict[str, Candidate] = {}
        self._embeddings: dict[str, np.ndarray] = {}

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------

    def load(self, raw_candidates: list[dict]) -> None:
        """Load all candidates, processing only those not in cache or stale."""
        stale: list[dict] = []
        fresh: list[dict] = []

        for raw in raw_candidates:
            cid = raw["id"]
            cache_path = self.cache_dir / f"{cid}.json"
            if cache_path.exists():
                cached = json.loads(cache_path.read_text())
                if (
                    cached.get("source_hash") == _raw_hash(raw)
                    and cached.get("schema_version") == CACHE_SCHEMA_VERSION
                ):
                    fresh.append(raw)
                    self._load_from_cache(cid, cached)
                    continue
            stale.append(raw)

        if fresh:
            print(
                f"  [store] {len(fresh)} candidates loaded from cache.",
                flush=True,
            )

        if stale:
            print(
                f"  [store] Processing {len(stale)} new/changed candidates...",
                flush=True,
            )
            for raw in stale:
                self._process_and_cache(raw)

    def _load_from_cache(self, cid: str, cached: dict) -> None:
        self._candidates[cid] = Candidate(**cached["candidate"])
        self._embeddings[cid] = np.array(cached["embedding"], dtype=np.float32)

    def _process_and_cache(self, raw: dict) -> None:
        # Lazy import to avoid circular dependency at module level
        from .extraction import parse_candidate

        cid = raw["id"]
        print(f"    → {raw['name']}...", flush=True)

        candidate = parse_candidate(raw)

        try:
            embedding = _embed_text(candidate_to_search_text(candidate))
        except Exception as exc:
            print(f"    ⚠ Embedding failed for {cid} — stored without embedding (retrieval will skip): {exc}", flush=True)
            self._candidates[cid] = candidate
            return

        self._candidates[cid] = candidate
        self._embeddings[cid] = embedding

        cache_path = self.cache_dir / f"{cid}.json"
        cache_path.write_text(
            json.dumps(
                {
                    "schema_version": CACHE_SCHEMA_VERSION,
                    "source_hash": _raw_hash(raw),
                    "candidate": candidate.model_dump(mode="json"),
                    "embedding": embedding.tolist(),
                }
            )
        )

    # ------------------------------------------------------------------
    # Access
    # ------------------------------------------------------------------

    def get(self, candidate_id: str) -> Candidate | None:
        return self._candidates.get(candidate_id)

    def get_all(self) -> list[Candidate]:
        return list(self._candidates.values())

    def embedding_matrix(self) -> tuple[list[str], np.ndarray]:
        """Return (ordered_ids, matrix[n_candidates, embedding_dim])."""
        ids = list(self._embeddings.keys())
        if not ids:
            return [], np.empty((0, 0), dtype=np.float32)
        matrix = np.stack([self._embeddings[i] for i in ids])
        return ids, matrix

    def __len__(self) -> int:
        return len(self._candidates)
