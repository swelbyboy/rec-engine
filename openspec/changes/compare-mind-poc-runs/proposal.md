## Why

The live-matchmaking-poc change's whole premise is that this branch's
filtering/ranking approach out-performs Mind's current ("gates-only") matching
— but validating that today means eyeballing rec-engine's own output and
separately eyeballing Mind's admin UI, with no easy way to see both side by
side for the same role, let alone against a third data point once Mind's
gates-only regression fix (`restore-legacy-score-default`, Mind repo) ships.
A single view comparing rec-engine's PoC, Mind's live production ranking, and
Mind's fixed-branch ranking for the same role makes that comparison concrete
instead of anecdotal.

## What Changes

- Add a read adapter for Mind's own persisted rerank data
  (`mind.shortlist_runs` / `mind.shortlist_run_candidates`), reusing the
  Supabase service-role credentials rec-engine already has — confirmed live
  that these credentials can already read the `mind` schema, so this needs no
  new credentials and no call to Mind's own Next.js API.
- Add a new "Compare" tab in the UI: one shared role selector, three columns
  (rec-engine PoC, Mind Live, Mind Fixed), each showing its own ranked list
  for the same role.
- Each Mind column gets a run-picker (defaulting to most recent) sourced from
  `mind.shortlist_runs` for that role — "Mind Live" and "Mind Fixed" are the
  same read mechanism, distinguished only by which run the user selects
  (e.g. by `scorer_version`, once `restore-legacy-score-default` ships and
  bumps it).
- Explicitly excludes: triggering a Mind rerank remotely from rec-engine.
  Generating a "Mind Fixed" data point requires running Mind's fixed branch
  and triggering a rerank through Mind's own UI first — rec-engine only
  visualizes runs that already exist in `mind.shortlist_run_candidates`.

## Capabilities

### New Capabilities
- `mind-run-comparison`: reading Mind's persisted rerank runs (list + detail,
  read-only) and presenting them alongside a rec-engine PoC run for the same
  role in a single three-column comparison view.

### Modified Capabilities
(none — `live-run-persistence`/`live-results-ui` from the prior change are
reused as-is for the rec-engine PoC column, not modified)

## Impact

- New code: a Mind-schema read adapter (mirrors `live_run_store.py`'s shape:
  list runs for a role, fetch one run's candidates), new API endpoint(s), a
  new UI tab and its components.
- No changes to `funnel_rerank.py`, `constraint_engine.py`, or any pipeline
  logic — this is purely a read/visualization feature over data that already
  exists (rec-engine's own persisted runs + Mind's own persisted runs).
- No changes to Mind's codebase from this change (Mind's own regression fix
  is tracked separately, `restore-legacy-score-default`).
- Read-only against `mind.*` — no writes, consistent with this branch's
  existing read-only posture toward Mothership/Mind data.
