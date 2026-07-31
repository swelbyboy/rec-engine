## Context

Confirmed live (not assumed) that rec-engine's existing `SUPABASE_SERVICE_ROLE_KEY`
can already read Mind's `mind` schema via PostgREST (`Accept-Profile: mind`) —
pulled real rows from `mind.shortlist_runs` and `mind.shortlist_run_candidates`
for job_order_id 1650 directly. Mind's own `role_id` in these tables is the
same Bullhorn job order id rec-engine already uses (`job_order_id`) — no id
mapping needed. Per Mind's own `docs/AUDIT_TRAIL.md`/CLAUDE.md:
`shortlist_runs` carries run-level metadata (`run_id`, `role_id`,
`run_started_at`, `created_by`, `scorer_version`); `shortlist_run_candidates`
carries one row per considered candidate (`reranker_rank`, `reranker_score`,
`reranker_tier`, `reranker_strengths`, `reranker_concerns`,
`reranker_signals`, `candidate_name`, `hard_filter_pass`, etc.) —
`reranker_tier` (e.g. "Strong Match") is the closest equivalent to
rec-engine's own verdict badges.

See `proposal.md` for why a comparison view matters now (this branch's PoC vs.
Mind's live behavior vs. Mind's regression fix from `restore-legacy-score-default`,
tracked in Mind's own repo).

## Goals / Non-Goals

**Goals:**
- Let a user see rec-engine PoC / Mind Live / Mind Fixed rankings for one
  role side by side, sourced from data that already exists.
- Zero new credentials, zero cross-repo API calls — pure Supabase reads.

**Non-Goals:**
- Triggering a Mind rerank from rec-engine — out of scope (see proposal).
  Generating the "Fixed" data point is a manual step in Mind's own UI on the
  fixed branch.
- Any scoring/normalization to make the three systems' outputs numerically
  comparable (e.g. mapping Mind's 0-100 score onto rec-engine's 4-tier
  verdict) — shown as each system's own native output, side by side, not
  merged into one ranking.
- Writing to `mind.*` in any way — read-only, matching this branch's existing
  posture toward Mothership/Mind data.

## Decisions

**1. New `src/mind_run_store.py`, mirroring `live_run_store.py`'s shape.**
`list_runs(role_id) -> list[dict]` (reads `mind.shortlist_runs`, filtered +
ordered by `run_started_at` desc) and `get_run(run_id) -> dict | None` (reads
`mind.shortlist_run_candidates` for that run_id, ordered by `reranker_rank`,
joined with the parent run's metadata). Naming/shape deliberately parallels
the existing rec-engine run store so the two API endpoints and their UI
consumers stay consistent rather than inventing a second pattern.

**2. New endpoints: `GET /api/mind/runs?role_id=...` and
`GET /api/mind/runs/{run_id}`.** Same shape as the existing
`/api/live/runs`/`/api/live/runs/{run_id}` pair, just backed by
`mind_run_store` instead of `live_run_store`.

**3. Shared role selector reuses `fetch_active_mind_roles()`.** Already
returns exactly the role set Mind's own UI shows (`mind.pinned_roles` joined
to `app.bullhorn_job_orders`) — the same list already powers the existing
Live PoC tab's job picker, so the Compare tab's role selector is the same
component/data source, not a new list.

**4. New `MindCandidateCard` component, not a reuse of `LiveCandidateCard`.**
Mind's data shape (`reranker_tier`, `reranker_strengths`/`concerns`,
numeric `reranker_score`) differs enough from rec-engine's
(`verdict`/`rationale`/matched-skills) that forcing one shared component
would need a lossy adapter layer in both directions. Two small, honest
components are simpler than one component with two personalities.

**5. Mind Live vs. Mind Fixed are the same run-picker component, twice.**
Both columns use the same `mind_run_store` read path; the only difference is
which run_id a user selects in each column's independent picker (e.g. picking
the newest `v6-all-reasons-gates` run for Live, and the newest
`v7-legacy-score-default` run — once `restore-legacy-score-default` ships —
for Fixed). No special-casing "Live" vs "Fixed" server-side; it's purely a UI
labeling/selection convenience.

## Risks / Trade-offs

- **[Risk]** `reranker_breakdown`/`reranker_signals`/`candidate_payload` are
  large JSONB blobs (seen up to several KB per row in testing) — fetching a
  full run's candidates could be a heavier payload than rec-engine's own runs.
  → **Mitigation**: `get_run` selects only the fields the UI actually
  renders (rank, score, tier, name, strengths, concerns), not `select=*`.
- **[Risk]** Mind's schema/column names could change independently of this
  repo (separate codebase, separate deploy cadence). → **Mitigation**: this
  is inherent to reading another team's live schema directly; acceptable for
  a PoC-scale comparison tool, not building a stable contract either side
  commits to.
- **[Trade-off]** No automated "which is better" scoring — this view is for
  human eyeballing, matching how the original regression was diagnosed
  (qualitative comparison), not a new quantitative benchmark.
