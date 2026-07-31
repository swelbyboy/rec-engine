"""Persistence for completed LLM-only pipeline runs.

Sibling to live_run_store.py, same shape and same reasons — a full
run_llm_only_pipeline() call over the whole eligible candidate pool (no
constraint filtering, no triage, no embedding trim — see funnel_rerank.py)
takes even longer than the regular PoC pipeline, so results are persisted
here rather than only living in the API response / React state for one page
load. Kept in its own directory (not live_run_store's) since it's a
genuinely different pipeline producing directly comparable but distinct
results for the same role — mixing them would make "which pipeline produced
this run" ambiguous from the store alone.

Flat JSON files under data/llm_only_runs/, not a database — same rationale
as live_run_store.py: the only access patterns needed are "list summaries for
a job" and "get one by id," neither of which benefits from a query engine.

data/llm_only_runs/ contains real candidate PII (same as data/live_index/) —
it's gitignored, not committed.
"""
from __future__ import annotations

import json
import threading
import uuid
from pathlib import Path

_RUNS_DIR = Path(__file__).resolve().parent.parent / "data" / "llm_only_runs"
_INDEX_PATH = _RUNS_DIR / "index.json"

_write_lock = threading.Lock()


def _run_path(run_id: str) -> Path:
    return _RUNS_DIR / f"{run_id}.json"


def _load_index() -> list[dict]:
    if not _INDEX_PATH.exists():
        return []
    return json.loads(_INDEX_PATH.read_text())


def save_run(job_order_id: int, result: dict) -> str:
    """Persist a completed run_llm_only_pipeline() result. Returns the new run_id.

    Generates the run_id here (not accepted from the caller) so callers never
    need to coordinate on uniqueness. Stamps result["run_id"] before writing
    (mutates the caller's dict in place too) so the persisted file is
    self-describing — GET /api/live/runs/{run_id} returns exactly what gets
    written here, no separate "attach the id after the fact" step needed.
    """
    run_id = uuid.uuid4().hex[:12]
    result["run_id"] = run_id

    job = result.get("job", {})
    summary = {
        "run_id": run_id,
        "job_order_id": job_order_id,
        "completed_at": _now_iso(),
        "title": job.get("title", ""),
        "company": job.get("company", ""),
        "candidates_considered": result.get("candidates_considered"),
        "candidates_passed_filter": result.get("candidates_passed_filter"),
        "candidates_reranked": result.get("candidates_reranked"),
    }

    with _write_lock:
        _RUNS_DIR.mkdir(parents=True, exist_ok=True)
        _run_path(run_id).write_text(json.dumps(result))

        index = _load_index()
        index.append(summary)
        _INDEX_PATH.write_text(json.dumps(index))

    return run_id


def list_runs(job_order_id: int) -> list[dict]:
    """Summaries for a job's past runs, newest-first.

    index.json is append-only in save order, so reversing it is a correct,
    deterministic newest-first ordering — sorting by the completed_at
    timestamp instead would risk ties if two saves land in the same tick.
    """
    index = _load_index()
    matches = [s for s in index if s["job_order_id"] == job_order_id]
    return list(reversed(matches))


def get_run(run_id: str) -> dict | None:
    """Full persisted result for one run, or None if it doesn't exist."""
    path = _run_path(run_id)
    if not path.exists():
        return None
    return json.loads(path.read_text())


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()
