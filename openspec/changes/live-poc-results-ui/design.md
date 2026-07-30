## Context

`run_live_pipeline` (`src/funnel_rerank.py`) already returns everything a
results view needs (job, coarse brief, ranked list with verdict/rationale,
eliminated list, counts) — nothing persists it, and `LivePocPanel.tsx` holds
it only in React state for that page load. Confirmed while investigating
requirement 4: `Candidate.id` throughout this pipeline (sourced from
`app.candidates.candidate_id`) already IS the real Bullhorn candidate ID —
cross-checked candidate_id 11091 against `app.bullhorn_candidates.id` 11091,
same person (Nour Alhrishi) in both. No new ID field or mapping is needed,
just a link built from it. Mind's own code
(`apps/web/src/lib/bullhorn/rejection-collector.ts`) already builds Bullhorn
candidate deep-links the same way rec-engine will need to:
`${BULLHORN_TENANT_URL}/BullhornSTAFFING/OpenWindow.cfm?Entity=Candidate&id={id}&view=Overview`.
User confirmed the tenant: `https://cls20.bullhornstaffing.com` (e.g.
`https://cls20.bullhornstaffing.com/BullhornSTAFFING/OpenWindow.cfm?Entity=Candidate&id=11128`).
`BULLHORN_TENANT_URL` isn't currently set in rec-engine's `.env` — needs
adding (see Decisions) — and still degrades to "no link, ID still shown" if
ever unset, same as Mind's own `tenantUrl()` helper.

## Goals / Non-Goals

**Goals:**
- Make a completed run's results durably viewable without re-running the
  pipeline.
- Split the results view into role-detail and candidate-list panes.
- Surface fit signal the pipeline already computes (skill match detail,
  experience, seniority, flagged-for-review) that today only reaches the LLM
  prompt, not the API response.
- Link each candidate card to their Bullhorn record.
- Document, for a reader unfamiliar with this branch, what changed vs. how
  Mind's `main` branch currently matches candidates and why.

**Non-Goals:**
- A real database/migration story — this is a PoC; flat JSON files on disk
  are sufficient at PoC scale (dozens of runs, not a multi-user production
  system).
- Editing or acting on candidates (sendouts, notes, status changes) — this
  stays read-only/view-only, consistent with the rest of this PoC.
- Any change to ranking/elimination logic itself — the additions to
  `funnel_rerank.py` here only extend what data accompanies each already-
  ranked candidate in the response; they don't change who gets ranked or in
  what order.

## Decisions

**1. Persist runs as flat JSON files under `data/live_runs/`, not a database.**
New module `src/live_run_store.py`:
- `save_run(job_order_id, result) -> run_id` — writes
  `data/live_runs/{run_id}.json` (run_id = `uuid4().hex[:12]`, generated here,
  not by the caller) and appends a summary entry (run_id, job_order_id,
  completed_at, title/company, considered/passed/reranked counts) to
  `data/live_runs/index.json`.
- `list_runs(job_order_id) -> list[dict]` — reads `index.json`, filters by
  job, returns newest-first.
- `get_run(run_id) -> dict | None` — reads `data/live_runs/{run_id}.json`.

Alternative considered: SQLite (stdlib, no new dependency). Rejected —
`run_live_pipeline`'s result is already a plain JSON-shaped dict and the only
access patterns needed are "list summaries for a job" and "get one by id,"
neither of which benefits from a query engine; flat files also match the
existing precedent in this repo (`candidate_index.py` already persists JSON +
`.npz` under `data/`). `data/live_runs/` is gitignored, same as
`data/live_index/` — persisted runs contain real candidate PII.

**2. Persistence lives in the API layer, not inside `run_live_pipeline`.**
`api.py`'s `/api/live/recommend` handler calls `live_run_store.save_run(...)`
after `run_live_pipeline` returns, and includes the new `run_id` in the
response. `run_live_pipeline` itself stays a pure function with no
side effects — keeps it testable/composable the way it is today, and mirrors
how `candidate_index.py` (storage) is already a separate concern from
`funnel_rerank.py` (pipeline logic).

**3. New endpoints: `GET /api/live/runs` and `GET /api/live/runs/{run_id}`.**
`GET /api/live/runs?job_order_id=...` returns `list_runs(...)` (summaries,
for a run-history picker in the UI). `GET /api/live/runs/{run_id}` returns
`get_run(...)` (full detail, same shape `/api/live/recommend` already
returns) — 404 if the run doesn't exist. The existing
`POST /api/live/recommend` is unchanged apart from adding `run_id` to its
response — no breaking change for the current caller.

**4. Extend (not redesign) the `ranked` payload with already-computed fit data.**
`fine_rerank()`/`_fine_rerank_chunk()` already compute
`skill_match_detail_batch()` per candidate to build the "Role skill fit"
prompt line, but discard it after formatting the prompt. Thread it back out
alongside the verdict/rationale so `run_live_pipeline`'s final `ranked` list
can include `matched_skills`, `missing_required_skills`,
`years_experience`, and `seniority_level` per candidate (the latter two read
straight off the already-fetched `Candidate` object) plus `bullhorn_id` and
`bullhorn_url` (candidate_id already is the Bullhorn id — see Context).
`bullhorn_url` is built server-side as
`f"{BULLHORN_TENANT_URL}/BullhornSTAFFING/OpenWindow.cfm?Entity=Candidate&id={candidate_id}&view=Overview"`
(empty string when `BULLHORN_TENANT_URL` isn't set) so the tenant URL config
never needs to reach the frontend. Add `BULLHORN_TENANT_URL` to
`rec-engine/.env`/`.env.example` (value: `https://cls20.bullhornstaffing.com`,
confirmed live).

**5. UI split into `RolePane` and `CandidateList`/`CandidateCard` components.**
`LivePocPanel.tsx` becomes a thin container: left `RolePane` (job title/
company, coarse brief summary, hard constraints + flex judgment, and a run-
history picker sourced from `GET /api/live/runs`), right `CandidateList`
rendering one `CandidateCard` per ranked candidate (verdict badge, rationale,
matched/missing skills, years experience, seniority, flagged-for-review
indicator, Bullhorn ID + link). Selecting a past run from the history picker
calls `GET /api/live/runs/{run_id}` instead of re-running the pipeline —
this is what makes a completed run revisitable without waiting minutes again.

**6. Branch-vs-Mind comparison doc lives at repo root: `CHANGES_VS_MIND_MAIN.md`.**
Placed at `rec-engine/` root (not inside this OpenSpec change's folder) so it
survives past this change being archived — it's a standing reference for
anyone picking up the branch, not a change-scoped working doc. Content is a
narrative comparison (what Mind's `main` does today: manual gates + recency-
ordered LLM rerank; what this branch does: automated constraint extraction +
3-phase constraint engine + skill-floor + lenient title/discipline gate +
Haiku triage + chunked Sonnet fine-rerank) and why, drawing on the regression
hypothesis already documented in `proposal.md`/`design.md` of the
`live-matchmaking-poc` change and the tuning findings from this session
(section 10 of that change's `tasks.md`) — not a literal git diff, since Mind
and rec-engine are separate codebases.

## Risks / Trade-offs

- **[Risk]** Flat JSON files have no concurrent-write protection. →
  **Mitigation**: acceptable for a single-process PoC dev server; each save
  is one run's worth of writes (append to index + write one file), not a
  high-frequency path.
- **[Risk]** `data/live_runs/` will grow unbounded over time (no eviction). →
  **Mitigation**: fine at PoC scale; not solving retention/cleanup here.
- **[Trade-off]** Extending `funnel_rerank.py`'s output shape touches a file
  this session already changed significantly. → **Mitigation**: the change
  is additive (new fields on the `ranked` dict) and doesn't touch the
  chunking/merge/elimination logic validated in this session; existing tests
  for those stay valid.

## Open Questions

- Exact `BULLHORN_TENANT_URL` value isn't in any local `.env`/`.env.example`
  checked in Mind's repo (may only exist in a deploy environment). Doesn't
  change the approach: the link degrades to "no link, ID still shown" when
  unset, same as Mind's own `tenantUrl()` helper does. Needs the actual value
  added to `rec-engine/.env` before the link is live; safe to defer.
