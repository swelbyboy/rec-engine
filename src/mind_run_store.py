"""Read-only adapter onto Mind's own persisted rerank data.

Reads `mind.shortlist_runs` / `mind.shortlist_run_candidates` via PostgREST
(`Accept-Profile: mind`), reusing rec-engine's existing
`SUPABASE_SERVICE_ROLE_KEY` — confirmed live that these credentials can
already read the `mind` schema, so this needs no new credentials and no call
to Mind's own Next.js API. Mirrors live_run_store.py's shape (list_runs/
get_run) so the Compare tab's Mind columns stay consistent with the
rec-engine PoC column's own data-access pattern.

No writes: every function here issues a GET against Supabase's PostgREST
interface, matching this repo's existing read-only posture toward
Mothership/Mind-owned data. See openspec/changes/compare-mind-poc-runs.
"""
from __future__ import annotations

import os

import httpx
from dotenv import load_dotenv

load_dotenv()

_SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
_SERVICE_ROLE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")


def _headers() -> dict[str, str]:
    if not _SUPABASE_URL or not _SERVICE_ROLE_KEY:
        raise RuntimeError(
            "SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY not set — required for Mind schema access"
        )
    return {
        "apikey": _SERVICE_ROLE_KEY,
        "Authorization": f"Bearer {_SERVICE_ROLE_KEY}",
        "Accept-Profile": "mind",
    }


def _get(table: str, params: dict) -> list[dict]:
    resp = httpx.get(
        f"{_SUPABASE_URL}/rest/v1/{table}",
        headers=_headers(),
        params=params,
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


# Run-level summary fields — enough to distinguish which run is which
# (id, when, scorer version, who ran it) without opening each one.
_RUN_SELECT = "run_id,role_id,run_started_at,scorer_version,created_by"

# Only the fields the UI actually renders, not `select=*` — reranker_breakdown
# and reranker_taxonomy are large JSONB blobs a comparison view has no use
# for. candidate_payload IS included (unlike those two): it's the lean ~3KB
# snapshot Mind itself captures for its own dashboard (id/name/title/company/
# yearsExp/skills/etc, not the full ~50KB CandidateDetail), and it's what
# lets the Mind card show the same meta-row/skill-chip structure as
# rec-engine's own card instead of a bare rank+score+tier line.
_CANDIDATE_SELECT = ",".join([
    "candidate_id",
    "candidate_name",
    "reranker_rank",
    "reranker_score",
    "reranker_tier",
    "reranker_strengths",
    "reranker_concerns",
    "reranker_signals",
    "hard_filter_pass",
    "candidate_payload",
])


def list_runs(role_id: int) -> list[dict]:
    """Summaries of Mind's past rerank runs for a role, newest-first."""
    return _get("shortlist_runs", {
        "select": _RUN_SELECT,
        "role_id": f"eq.{role_id}",
        "order": "run_started_at.desc",
    })


def get_run(run_id: str) -> dict | None:
    """One Mind run's metadata plus its full candidate list, ranked first.

    Two flat GETs (run row, then candidate rows) rather than a PostgREST
    embedded join, mirroring live_run_store.get_run's own shape — simple and
    doesn't depend on cross-schema embed support being enabled.
    """
    runs = _get("shortlist_runs", {"select": _RUN_SELECT, "run_id": f"eq.{run_id}", "limit": "1"})
    if not runs:
        return None
    run = runs[0]

    candidates = _get("shortlist_run_candidates", {
        "select": _CANDIDATE_SELECT,
        "run_id": f"eq.{run_id}",
        "order": "reranker_rank.asc",
    })

    return {**run, "candidates": candidates}
