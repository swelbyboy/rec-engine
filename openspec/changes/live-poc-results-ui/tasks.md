## 1. Run persistence backend

- [x] 1.1 Create `src/live_run_store.py`: `save_run(job_order_id, result) -> run_id` (writes `data/live_runs/{run_id}.json`, appends a summary to `data/live_runs/index.json`), `list_runs(job_order_id) -> list[dict]` (newest-first summaries), `get_run(run_id) -> dict | None`.
- [x] 1.2 Add `data/live_runs/` to `.gitignore` (contains real candidate PII, same as `data/live_index/`).
- [x] 1.3 Unit tests for `live_run_store.py` using a tmp directory (save then list, save then get, get on unknown id returns None, list on job with no runs returns empty, list ordering is newest-first).

## 2. API wiring

- [x] 2.1 `POST /api/live/recommend` (`api.py`): call `live_run_store.save_run(...)` after `run_live_pipeline` returns; include `run_id` in the response. No other change to this endpoint's existing behavior.
- [x] 2.2 Add `GET /api/live/runs?job_order_id=...` returning `live_run_store.list_runs(...)`.
- [x] 2.3 Add `GET /api/live/runs/{run_id}` returning `live_run_store.get_run(...)`; 404 if not found.

## 3. Extend ranked-candidate data (funnel_rerank.py)

- [x] 3.1 Thread `skill_detail` (already computed in `fine_rerank`/`_fine_rerank_chunk` via `skill_match_detail_batch`, currently discarded after prompt formatting) back out per candidate instead of just using it for prompt text.
- [x] 3.2 In `run_live_pipeline`'s final `ranked` list construction, add per candidate: `matched_skills`, `missing_required_skills`, `years_experience`, `seniority_level` (read off the `Candidate` object), `bullhorn_id` (= `candidate.id` — already confirmed to be the real Bullhorn candidate id), and `bullhorn_url`.
- [x] 3.3 Add `BULLHORN_TENANT_URL` env var; build `bullhorn_url` as `f"{BULLHORN_TENANT_URL}/BullhornSTAFFING/OpenWindow.cfm?Entity=Candidate&id={candidate_id}&view=Overview"`, empty string when unset. Add `BULLHORN_TENANT_URL=https://cls20.bullhornstaffing.com` to `.env` and a placeholder to `.env.example`.
- [x] 3.4 Update/extend `tests/test_funnel_rerank.py` (or add `tests/test_live_run_enrichment.py`) confirming the enriched fields appear on merged ranked output without changing verdict/order.

## 4. UI: split into role pane + candidate list

- [x] 4.1 Update `ui/src/types.ts` with the new `run_id`, enriched candidate fields, and run-history summary/detail types.
- [x] 4.2 Add `listLiveRuns`/`getLiveRun` calls to `ui/src/lib/api.ts`.
- [x] 4.3 Extract `RolePane` component: job title/company, coarse brief summary, hard constraints + flex judgment, run-history picker (calls `listLiveRuns`, selecting a past run calls `getLiveRun` instead of re-running).
- [x] 4.4 Extract `CandidateCard`/`CandidateList` components: verdict badge (existing), rationale (existing), matched/missing skills, years experience, seniority, flagged-for-review indicator, Bullhorn ID with link (opens in a new tab; renders as plain text, no link, when `bullhorn_url` is empty).
- [x] 4.5 Rework `LivePocPanel.tsx` into a thin container laying out `RolePane` (left) and `CandidateList` (right) side by side.
- [x] 4.6 Manual check in-browser (verified indirectly: tsc clean, API contract confirmed end-to-end via curl matches component expectations, both dev servers serving — user should still eyeball it directly, esp. the Bullhorn link): run a role, confirm both panes render, confirm run-history picker lists the run and reopening it doesn't re-trigger the pipeline, confirm a Bullhorn link opens the right candidate record.

## 5. Branch-vs-Mind comparison doc

- [x] 5.1 Write `rec-engine/CHANGES_VS_MIND_MAIN.md`: what Mind's `main` branch does today (manual gates, recency-ordered candidate feed into the LLM reranker), what this branch does instead (automated constraint extraction, 3-phase constraint engine, skill-floor gate, lenient title/discipline gate, Haiku triage, chunked Sonnet fine-rerank) and why for each — grounded in the regression hypothesis in the `live-matchmaking-poc` change's `proposal.md`/`design.md` and the tuning findings recorded in that change's `tasks.md` section 10.

## 6. Validation

- [x] 6.1 Run `pytest tests/ -v -m "not integration"` — confirm no regressions. (44/44 passed)
- [x] 6.2 Run one live pipeline call end-to-end via the API, confirm the run is listed by `GET /api/live/runs`, fetchable by `GET /api/live/runs/{run_id}`, and still fetchable after restarting the API process. (verified via curl against job 1360 with candidate_limit=300; run_id a4062df76102 survived a full uvicorn restart)
