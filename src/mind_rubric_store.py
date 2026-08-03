"""Read-only adapter onto Mind's own per-role weighted rubric
(`mind.rubric_configs`) — reused the same way `mind_run_store.py` reads
`mind.shortlist_runs`: PostgREST GET with `Accept-Profile: mind`, the
existing `SUPABASE_SERVICE_ROLE_KEY`, no new credentials.

This is the piece the analysis in CHANGES_VS_MIND_MAIN.md ("Why Mind's
per-role rubric weighting was not ported (yet)") flagged as the real,
structural source of rec-engine's ranking-quality gap: rec-engine's
fine-rerank prompt only ever saw generic required/preferred skills, with no
visibility into what a role's shortlist should actually be optimizing for
(e.g. skill match was only 10% of Mind's score for role 1360). This module
fetches that same rubric so `funnel_rerank.py` can inject it into the
fine-rerank prompt the same way `coarse_role_brief` already gets injected —
see `_format_rubric_signals` there.

Only the `signals` shape is read (current/preferred scoring path per the
2026-06-25 migration) — legacy `dimensions`-only rows (nullable `signals`)
are treated the same as "no rubric" and skipped, matching the PoC's existing
posture of degrading to its generic prompt rather than reimplementing a
second, older rubric format.

No writes: same read-only posture as mind_run_store.py.
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


# Lean select — only what _format_rubric_signals (funnel_rerank.py) needs to
# render the prompt block, not the full row (taxonomy/penalties/hard_filters/
# output_schema/sha256/created_by/dimensions/parent_id are all unused here).
_RUBRIC_SELECT = "id,rubric_id,version,role_id,signals,created_at"


def _latest(params: dict) -> dict | None:
    resp = httpx.get(
        f"{_SUPABASE_URL}/rest/v1/rubric_configs",
        headers=_headers(),
        params={"select": _RUBRIC_SELECT, "order": "created_at.desc", "limit": "1", **params},
        timeout=30,
    )
    resp.raise_for_status()
    rows = resp.json()
    return rows[0] if rows else None


def get_rubric_for_role(role_id: int) -> dict | None:
    """Latest signals-based rubric for a role.

    Resolution mirrors Mind's own admin picker (`rubric-configs/route.ts`),
    minus the human-in-the-loop choice — that route hands the operator both
    role-specific rows AND reusable `role_id IS NULL` templates and lets them
    pick; there's no automated pipeline calling into this today, so this
    picks deterministically instead: the most recently created role-specific
    rubric if one has `signals` populated, else the most recently created
    global template, else None.

    Returns None (not raises) for "no usable rubric" — a legacy
    dimensions-only row, a role with no rubric configured at all, or (via the
    caller's own try/except) missing Supabase creds — every one of these is
    the same case for the caller: fall back to the generic fine-rerank
    prompt, exactly like today.
    """
    role_specific = _latest({"role_id": f"eq.{role_id}"})
    if role_specific and role_specific.get("signals"):
        return role_specific

    global_template = _latest({"role_id": "is.null"})
    if global_template and global_template.get("signals"):
        return global_template

    return None
