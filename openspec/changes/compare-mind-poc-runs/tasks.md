## 1. Mind read adapter

- [x] 1.1 Create `src/mind_run_store.py`: `list_runs(role_id) -> list[dict]` (reads `mind.shortlist_runs`, newest-first) and `get_run(run_id) -> dict | None` (reads `mind.shortlist_run_candidates` for that run_id ordered by `reranker_rank`, selecting only rank/score/tier/name/strengths/concerns fields, not `select=*`).
- [x] 1.2 Unit tests for `mind_run_store.py` (mock the Supabase HTTP calls — this reads a live external schema, don't hit it in unit tests).

## 2. API wiring

- [x] 2.1 Add `GET /api/mind/runs?role_id=...` returning `mind_run_store.list_runs(...)`.
- [x] 2.2 Add `GET /api/mind/runs/{run_id}` returning `mind_run_store.get_run(...)`; 404 if not found.

## 3. UI: Compare tab

- [x] 3.1 Add `ui/src/types.ts` types for Mind run summaries/candidates.
- [x] 3.2 Add `listMindRuns`/`getMindRun` calls to `ui/src/lib/api.ts`.
- [x] 3.3 Build `MindCandidateCard` component (name, reranker rank/score, tier badge, strengths/concerns).
- [x] 3.4 Build `ComparePanel` component: one shared role selector (reusing the existing job-picker data source), three columns (rec-engine PoC reusing existing `listLiveRuns`/`getLiveRun` + `LiveCandidateCard`; Mind Live and Mind Fixed each with their own run-picker sourced from `listMindRuns` + `MindCandidateCard`).
- [x] 3.5 Add a new "Compare" tab in `App.tsx` alongside the existing Live PoC tab.
- [x] 3.6 Manual check in-browser: pick a role with real Mind history (e.g. job_order_id 1650), confirm all three columns render independently and an empty column (e.g. no rec-engine PoC run yet for that role) doesn't block the others.

## 4. Validation

- [x] 4.1 Run `pytest tests/ -v -m "not integration"` — confirm no regressions.
- [ ] 4.2 Once Mind's `restore-legacy-score-default` change has a real run persisted, do one real 3-way comparison for the same role Mind's audit trail already has live data for, and sanity-check the columns actually reflect three distinct ranking behaviors.
