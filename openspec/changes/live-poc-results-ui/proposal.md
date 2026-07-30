## Why

Live pipeline runs (`run_live_pipeline`) take minutes over the full ~17.6k
candidate universe (chunked LLM triage + fine-rerank), but nothing about a
run is saved — the result only ever lives in the React panel's in-memory
state for that one page load. A user who navigates away, refreshes, or wants
to revisit a completed run has to re-run the whole pipeline from scratch just
to look at results they already generated. Separately, now that the pipeline
itself is validated (skill-floor tuning, title/discipline gate, chunked
rerank), the results view is the next real gap: it's a single panel with a
short rationale and no way to see the underlying fit signals, and there's no
link back to the actual Bullhorn candidate record a recruiter would need to
act on a match.

## What Changes

- Persist each `run_live_pipeline` result (job, coarse brief, ranked list,
  eliminated list, counts) keyed by a run id, so a completed run can be
  fetched and displayed again without re-running the pipeline.
- Split `LivePocPanel` into two panes: role/job details (title, company,
  coarse brief, hard constraints) on the left, ranked candidates on the right.
- Add a candidate list/detail endpoint for run history (list past runs for a
  job, fetch one run by id).
- Expand each candidate card in the ranked results with more of the fit
  signal already computed by the pipeline but not currently surfaced (e.g.
  skill match detail, years experience, seniority, flagged-for-review state)
  so a recruiter can judge fit without reading only the short rationale.
- Add the candidate's Bullhorn ID to each card, linking out to their record
  in Bullhorn.
- Produce a markdown summary (`CHANGES_VS_MAIN.md` or similar, exact name
  decided in design) documenting what changed on `poc/live-matchmaking`
  versus Mind's `main` branch and why — a reference doc, not app behavior.

## Capabilities

### New Capabilities
- `live-run-persistence`: storing and retrieving completed `run_live_pipeline`
  results by run id, so results survive past the initial request/response and
  can be viewed later without re-running the pipeline.
- `live-results-ui`: the two-pane results layout (role details vs. ranked
  candidates), expanded per-candidate fit detail, and the Bullhorn ID/link on
  each candidate card.

### Modified Capabilities
(none — `funnel-rerank`/`live-data-adapter`/`automated-constraint-extraction`
from the prior change are unaffected; this change adds a persistence layer
and UI around their existing output, it doesn't change pipeline behavior)

## Impact

- New code: a persistence module in rec-engine (storage format/location
  decided in design — this is a PoC, so a simple approach like on-disk
  JSON/SQLite is in scope, not a new managed database).
- `src/api.py`: new endpoint(s) for listing/fetching past runs; `POST
  /api/live/recommend` starts persisting its result instead of only
  returning it.
- `ui/src/components/LivePocPanel.tsx`: restructured into two panes; likely
  split into sub-components (role detail pane, candidate card, candidate
  list) rather than one large component.
- `ui/src/types.ts` / `ui/src/lib/api.ts`: new types/calls for run
  history/detail.
- No changes to `funnel_rerank.py`'s pipeline logic itself, `constraint_engine.py`,
  or `candidate_index.py` — this change is entirely about persisting and
  displaying results the pipeline already produces.
- New reference doc summarizing branch changes vs. Mind's `main` (no code
  impact).
