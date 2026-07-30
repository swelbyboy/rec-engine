"""Persistent embedding index over Mothership's full live candidate pool.

Built once (or refreshed periodically) via `python -m src.candidate_index build`,
so the live pipeline (funnel_rerank.run_live_pipeline) never re-embeds the
whole candidate table on a per-request basis. Two things are precomputed:

  1. A search-text embedding per candidate (for embedding-similarity retrieval).
  2. An embedding per candidate CONSTRAINT (for constraint_engine.py's semantic
     matching phase) — this is what lets run_constraint_engine scan every
     indexed candidate on every request with zero live OpenAI calls on the
     candidate side; only the job's own ~10 constraints get embedded fresh,
     once, per pipeline run.

Incremental: each live candidate row is content-hashed (same pattern as
store.py's fixture cache). A rebuild only re-embeds candidates whose live
data actually changed since the last build; everyone else is reused from
disk. First build embeds the full table; subsequent builds are cheap.

Memory note: a full build holds on the order of 100k constraint embeddings
(~600MB at 1536 dims). build() writes directly into preallocated numpy
arrays rather than accumulating Python lists of vectors and stacking them —
list-then-stack (or a dict-of-dicts rebuilt into flat arrays afterwards)
briefly holds 2-3x that data in memory at once, which is enough to get a
process killed under a constrained memory budget; direct-fill keeps exactly
one copy of each matrix alive at a time.

Storage (under data/live_index/):
  candidates.json          — {candidate_id: {row_hash, candidate: Candidate.model_dump()}}
  embeddings.npz             — parallel `ids` array + `matrix` of search-text vectors
  constraint_embeddings.npz — parallel `keys` array ("candidate_id::constraint_id") + `matrix`
  title_embeddings.npz      — parallel `ids` array + `matrix` of title-only vectors (current +
                               recent previous titles, deliberately narrower than the full
                               search-text embedding above) — feeds funnel_rerank.py's lenient
                               title/discipline relevance gate.

Nothing here writes to Mothership — this only reads app.candidates and
persists locally in rec-engine.
"""
from __future__ import annotations

import json
import hashlib
import os
import sys
import threading
from pathlib import Path

import numpy as np

from . import live_data
from .models import Candidate
from .store import candidate_to_search_text

_INDEX_DIR = Path(__file__).resolve().parent.parent / "data" / "live_index"
_META_PATH = _INDEX_DIR / "candidates.json"
_EMBEDDINGS_PATH = _INDEX_DIR / "embeddings.npz"
_CONSTRAINT_EMB_PATH = _INDEX_DIR / "constraint_embeddings.npz"
_TITLE_EMB_PATH = _INDEX_DIR / "title_embeddings.npz"

_cached_index: "LiveCandidateIndex | None" = None
_cache_lock = threading.Lock()

EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_DIM = 1536  # text-embedding-3-small output size
_EMBED_CHUNK_SIZE = 500


def _row_hash(row: dict) -> str:
    return hashlib.md5(json.dumps(row, sort_keys=True, default=str).encode()).hexdigest()[:16]


def _title_text(row: dict) -> str:
    """Title-only text for a candidate — current + a couple of recent previous
    titles, deliberately excluding skills/CV/constraint text so this embeds
    purely "what kind of role has this person done," not general fit."""
    parts: list[str] = []
    if row.get("current_title"):
        parts.append(str(row["current_title"]))
    prev = row.get("computed_previous_titles") or []
    if isinstance(prev, list):
        parts.extend(str(t) for t in prev[:3] if t)
    return " | ".join(parts) or "unknown professional title"


def _get_openai_client():
    from openai import OpenAI
    return OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))


def _embed_into(matrix: np.ndarray, positions: list[int], texts: list[str]) -> None:
    """Batch-embed `texts` and write results directly into `matrix` rows at
    `positions`, one API-response chunk at a time — no separate array of
    results is ever held alongside the destination matrix."""
    if not texts:
        return
    client = _get_openai_client()
    for start in range(0, len(texts), _EMBED_CHUNK_SIZE):
        chunk_texts = texts[start : start + _EMBED_CHUNK_SIZE]
        chunk_positions = positions[start : start + _EMBED_CHUNK_SIZE]
        resp = client.embeddings.create(model=EMBEDDING_MODEL, input=chunk_texts)
        for pos, item in zip(chunk_positions, resp.data):
            matrix[pos] = item.embedding
        del resp


class LiveCandidateIndex:
    """In-memory view of the persisted index — implements retrieval.EmbeddingStore."""

    def __init__(
        self,
        ids: list[str],
        matrix: np.ndarray,
        candidates: dict[str, Candidate],
        constraint_embeddings: dict[str, dict[str, np.ndarray]],
        title_embeddings: dict[str, np.ndarray] | None = None,
    ):
        self._ids = ids
        self._matrix = matrix
        self._candidates = candidates
        self._constraint_embeddings = constraint_embeddings
        self._title_embeddings = title_embeddings or {}

    def embedding_matrix(self) -> tuple[list[str], np.ndarray]:
        return self._ids, self._matrix

    def get(self, candidate_id: str) -> Candidate | None:
        return self._candidates.get(candidate_id)

    def get_constraint_embeddings(self, candidate_id: str) -> dict[str, np.ndarray]:
        """Precomputed embedding per constraint id for one candidate — feeds
        constraint_engine.run_constraint_engine(candidate_embeddings=...)."""
        return self._constraint_embeddings.get(candidate_id, {})

    def get_title_embedding(self, candidate_id: str) -> np.ndarray | None:
        """Precomputed title-only embedding — feeds funnel_rerank.py's
        lenient title/discipline relevance gate."""
        return self._title_embeddings.get(candidate_id)

    def all_candidates(self) -> list[Candidate]:
        return list(self._candidates.values())

    def subset(self, ids: list[str]) -> "LiveCandidateIndex":
        """A view restricted to the given candidate ids — reuses already-computed
        embeddings, no new API calls. Used to narrow a constraint-passed pool
        for the LLM rerank stage via retrieval, without re-embedding anyone."""
        keep = [cid for cid in ids if cid in self._candidates]
        pos = {cid: i for i, cid in enumerate(self._ids)}
        rows = [pos[cid] for cid in keep if cid in pos]
        dim = self._matrix.shape[1] if self._matrix.ndim == 2 and self._matrix.shape[0] else 0
        matrix = self._matrix[rows] if rows else np.empty((0, dim), dtype=np.float32)
        candidates = {cid: self._candidates[cid] for cid in keep}
        constraint_embeddings = {cid: self._constraint_embeddings.get(cid, {}) for cid in keep}
        title_embeddings = {cid: self._title_embeddings[cid] for cid in keep if cid in self._title_embeddings}
        return LiveCandidateIndex(keep, matrix, candidates, constraint_embeddings, title_embeddings)

    def __len__(self) -> int:
        return len(self._candidates)


def build(force: bool = False) -> int:
    """Build or incrementally refresh the live candidate embedding index.

    Pass force=True to re-embed every candidate regardless of whether their
    live row changed. Returns the number of candidates indexed — call load()
    afterwards to get a usable LiveCandidateIndex (kept as a separate step so
    a plain CLI build doesn't have to hold everything it just wrote in memory
    a second time).
    """
    _INDEX_DIR.mkdir(parents=True, exist_ok=True)

    cached_meta: dict[str, dict] = {}
    cached_search_by_id: dict[str, np.ndarray] = {}
    cached_constraint_by_key: dict[str, np.ndarray] = {}
    cached_title_by_id: dict[str, np.ndarray] = {}
    if not force and _META_PATH.exists() and _EMBEDDINGS_PATH.exists():
        print("[candidate_index] Loading existing index from disk for incremental reuse...", flush=True)
        cached_meta = json.loads(_META_PATH.read_text())
        with np.load(_EMBEDDINGS_PATH) as npz:
            ids_arr, mat = npz["ids"], npz["matrix"]
            cached_search_by_id = {str(cid): mat[i] for i, cid in enumerate(ids_arr)}
    if not force and _CONSTRAINT_EMB_PATH.exists():
        with np.load(_CONSTRAINT_EMB_PATH) as npz:
            keys_arr, mat = npz["keys"], npz["matrix"]
            cached_constraint_by_key = {str(k): mat[i] for i, k in enumerate(keys_arr)}
    if not force and _TITLE_EMB_PATH.exists():
        with np.load(_TITLE_EMB_PATH) as npz:
            ids_arr, mat = npz["ids"], npz["matrix"]
            cached_title_by_id = {str(cid): mat[i] for i, cid in enumerate(ids_arr)}
    if cached_meta:
        print(f"[candidate_index] Loaded cache for {len(cached_meta)} candidates.", flush=True)

    print("[candidate_index] Fetching all candidates from app.candidates...", flush=True)
    rows = live_data.fetch_all_candidates_raw()
    print(f"[candidate_index] {len(rows)} candidate rows fetched.", flush=True)

    meta: dict[str, dict] = {}
    search_ids: list[str] = []
    search_matrix = np.empty((len(rows), EMBEDDING_DIM), dtype=np.float32)
    to_embed_search_positions: list[int] = []
    to_embed_search_texts: list[str] = []
    title_matrix = np.empty((len(rows), EMBEDDING_DIM), dtype=np.float32)
    to_embed_title_positions: list[int] = []
    to_embed_title_texts: list[str] = []

    # First pass: resolve everyone's row + constraints, filling search_matrix
    # directly from cache where possible. Constraint keys/cache-hits are
    # recorded now; the constraint matrix itself is allocated after this loop
    # once we know the total constraint count.
    constraint_keys: list[str] = []
    constraint_cache_hits: list[tuple[int, str]] = []  # (position, cache key)
    to_embed_constraint_positions: list[int] = []
    to_embed_constraint_texts: list[str] = []

    for i, row in enumerate(rows):
        cid = str(row["candidate_id"])
        row_hash = _row_hash(row)
        prior = cached_meta.get(cid)
        unchanged = bool(prior and prior.get("row_hash") == row_hash)

        search_ids.append(cid)
        if unchanged and cid in cached_search_by_id:
            meta[cid] = prior
            candidate = Candidate(**prior["candidate"])
            search_matrix[i] = cached_search_by_id[cid]
        else:
            candidate = live_data.candidate_row_to_model(row)
            meta[cid] = {"row_hash": row_hash, "candidate": candidate.model_dump(mode="json")}
            to_embed_search_positions.append(i)
            to_embed_search_texts.append(candidate_to_search_text(candidate))

        if unchanged and cid in cached_title_by_id:
            title_matrix[i] = cached_title_by_id[cid]
        else:
            to_embed_title_positions.append(i)
            to_embed_title_texts.append(_title_text(row))

        for constraint in candidate.constraints:
            key = f"{cid}::{constraint.id}"
            pos = len(constraint_keys)
            constraint_keys.append(key)
            if unchanged and key in cached_constraint_by_key:
                constraint_cache_hits.append((pos, key))
            else:
                to_embed_constraint_positions.append(pos)
                to_embed_constraint_texts.append(constraint.description)

    del cached_meta

    if to_embed_search_texts:
        print(f"[candidate_index] Embedding {len(to_embed_search_texts)} candidate search-text profiles "
              f"({len(rows) - len(to_embed_search_texts)} unchanged, reused from cache)...", flush=True)
        _embed_into(search_matrix, to_embed_search_positions, to_embed_search_texts)
    else:
        print("[candidate_index] No candidates changed — search-text embeddings already current.", flush=True)
    del cached_search_by_id

    if to_embed_title_texts:
        print(f"[candidate_index] Embedding {len(to_embed_title_texts)} candidate title profiles "
              f"({len(rows) - len(to_embed_title_texts)} unchanged, reused from cache)...", flush=True)
        _embed_into(title_matrix, to_embed_title_positions, to_embed_title_texts)
    else:
        print("[candidate_index] No candidates changed — title embeddings already current.", flush=True)
    del cached_title_by_id

    _META_PATH.write_text(json.dumps(meta))
    np.savez_compressed(_EMBEDDINGS_PATH, ids=np.array(search_ids), matrix=search_matrix)
    np.savez_compressed(_TITLE_EMB_PATH, ids=np.array(search_ids), matrix=title_matrix)
    del search_matrix, title_matrix, meta

    constraint_matrix = np.empty((len(constraint_keys), EMBEDDING_DIM), dtype=np.float32)
    for pos, key in constraint_cache_hits:
        constraint_matrix[pos] = cached_constraint_by_key[key]
    del cached_constraint_by_key, constraint_cache_hits

    if to_embed_constraint_texts:
        print(f"[candidate_index] Embedding {len(to_embed_constraint_texts)} candidate constraints...", flush=True)
        _embed_into(constraint_matrix, to_embed_constraint_positions, to_embed_constraint_texts)
    else:
        print("[candidate_index] No candidate constraints changed — constraint embeddings already current.", flush=True)

    np.savez_compressed(_CONSTRAINT_EMB_PATH, keys=np.array(constraint_keys), matrix=constraint_matrix)

    print(f"[candidate_index] Index written: {len(search_ids)} candidates, "
          f"{len(constraint_keys)} constraint embeddings ({_INDEX_DIR}).", flush=True)
    return len(search_ids)


def load() -> LiveCandidateIndex:
    """Load the persisted index from disk — no Supabase or OpenAI calls.

    Raises FileNotFoundError if the index hasn't been built yet.
    """
    if not (_META_PATH.exists() and _EMBEDDINGS_PATH.exists()):
        raise FileNotFoundError(
            f"No live candidate index found at {_INDEX_DIR}. "
            "Build it once with: python -m src.candidate_index build"
        )
    meta = json.loads(_META_PATH.read_text())
    with np.load(_EMBEDDINGS_PATH) as npz:
        ids_arr, mat = npz["ids"], npz["matrix"]
        search_emb = {str(cid): mat[i] for i, cid in enumerate(ids_arr)}

    constraint_emb: dict[str, dict[str, np.ndarray]] = {}
    if _CONSTRAINT_EMB_PATH.exists():
        with np.load(_CONSTRAINT_EMB_PATH) as npz:
            for key, vec in zip(npz["keys"], npz["matrix"]):
                cid, _, constraint_id = str(key).partition("::")
                constraint_emb.setdefault(cid, {})[constraint_id] = vec

    title_emb: dict[str, np.ndarray] = {}
    if _TITLE_EMB_PATH.exists():
        with np.load(_TITLE_EMB_PATH) as npz:
            ids_arr, mat = npz["ids"], npz["matrix"]
            title_emb = {str(cid): mat[i] for i, cid in enumerate(ids_arr)}

    ids = [cid for cid in meta if cid in search_emb]
    matrix = (
        np.stack([search_emb[cid] for cid in ids])
        if ids else np.empty((0, 0), dtype=np.float32)
    )
    candidates = {cid: Candidate(**meta[cid]["candidate"]) for cid in ids}
    return LiveCandidateIndex(ids, matrix, candidates, constraint_emb, title_emb)


def get_cached() -> LiveCandidateIndex:
    """Load the index once per process and reuse it on every subsequent call.

    load() parses ~370MB of embeddings and reconstructs ~17.6k Candidate
    objects from disk — expensive enough that doing it fresh on every single
    run_live_pipeline() request (as it used to) is pure waste once nothing
    about the on-disk index has changed. Call clear_cache() after rebuilding
    the index (in a separate `python -m src.candidate_index build` process)
    to make the next call here pick up the new data.
    """
    global _cached_index
    if _cached_index is None:
        with _cache_lock:
            if _cached_index is None:
                _cached_index = load()
    return _cached_index


def clear_cache() -> None:
    """Drop the in-process cached index so the next get_cached() reloads from disk."""
    global _cached_index
    with _cache_lock:
        _cached_index = None


if __name__ == "__main__":
    command = sys.argv[1] if len(sys.argv) > 1 else "build"
    if command == "build":
        count = build(force="--force" in sys.argv)
        print(f"Done — {count} candidates indexed.")
    else:
        print(f"Unknown command '{command}'. Usage: python -m src.candidate_index build [--force]")
        sys.exit(1)
