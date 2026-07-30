## Why

Feedback indicates Mind's candidate matchmaking has regressed. Investigation traced this to Mind's "gates-only redesign": the 18 soft-matching signals that used to drive ranking are now dormant, candidates are filtered by brittle exact-match hard cutoffs, and ordering into the LLM reranker is driven by recency rather than fit. The hypothesis is that the regression sits in the *filtering* stage, not the downstream LLM reranking Mind already trusts. This change prototypes a fix — automated, semantic constraint filtering feeding the same coarse-then-fine LLM ranking shape — running against live production data, so it can be demonstrated side by side against Mind's current output on real open roles.

## What Changes

- Introduce a live-data adapter that reads candidate and job data directly from Mothership's Supabase Postgres (`app` schema), the same read-only source Mind itself consumes, replacing rec-engine's synthetic JSON fixtures for this PoC.
- Introduce automated constraint extraction that derives structured, typed constraints from a job's raw description *and* its Bullhorn job briefing text, replacing Mind's manually configured gates for this PoC.
- Reuse rec-engine's existing 3-phase constraint engine (exact canonical-key match → semantic/embedding fallback → no-match-is-compatible) unmodified as the filtering stage.
- Introduce a two-stage LLM ranking funnel (coarse requirement/flexibility extraction, then fine-grained rerank with per-candidate verdict and rationale) that mirrors Mind's current ranking model, replacing rec-engine's default weighted-linear/ML scoring for this PoC.
- Surface ranked results and rationale through rec-engine's existing React UI.
- Explicitly excludes any part of the outreach funnel (candidate/hiring-manager communication, Slack cards, sendouts) — matchmaking only.
- Explicitly excludes trained ML models (logistic regression / gradient-boosted trees) and historical backtesting against placement/sendout data — validation is a live side-by-side comparison against Mind's current output on real open roles.

## Capabilities

### New Capabilities
- `live-data-adapter`: Read-only integration that pulls live candidate records (`app.candidates`, `app.candidate_employment_agg`, `app.candidate_education_agg`, `derived.cv_parsed`, `derived.granola_notes`) and job records (`app.bullhorn_job_orders` / `app.dim_job_order`, including the Bullhorn job briefing) from Mothership's Supabase Postgres, mapping them into rec-engine's existing `Candidate` and `JobDescription` models.
- `automated-constraint-extraction`: LLM-driven extraction (via rec-engine's existing `extraction.py`) of typed, weighted constraints from a job's description and Bullhorn briefing text, with no manual gate configuration required.
- `funnel-rerank`: Two-stage LLM ranking over the constraint-engine-filtered candidate pool — coarse extraction of role requirements/flexibility, then fine-grained rerank producing a ranked list with per-candidate verdicts and recruiter-facing rationale — mirroring Mind's current filter → coarse LLM → fine LLM model.

### Modified Capabilities
(none — no existing baseline specs in this repo; all capabilities above are net-new)

## Impact

- New code in `rec-engine`: a Supabase data-adapter module, a constraint-extraction entry point wired to live JD + briefing text, and new coarse/fine LLM ranking modules alongside (not replacing) `scoring.py`/`ml_scoring.py`, which remain unused by this pipeline path.
- New runtime dependency: read-only Supabase Postgres access (`SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`) to Mothership's `app`/`derived` schemas — the same credentials and access pattern Mind already uses. No writes to any Mothership schema.
- No changes to Mind or Mothership codebases — this is a standalone prototype in `rec-engine`, on branch `poc/live-matchmaking`.
- Existing rec-engine capabilities unaffected: `feature-extraction`, `constraint-engine`, `explanation-generation`, and `api-backend` are reused as-is; `scoring-model` (weighted-linear/ML) and `dummy-data` are not used by this pipeline path but remain in place.
