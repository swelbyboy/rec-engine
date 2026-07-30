## Context

rec-engine already implements a 5-stage pipeline (extraction → embedding retrieval → constraint engine → weighted/ML scoring → LLM explanation) against synthetic fixtures (`data/candidates.json`, `data/jobs.json`). Mind's live data lives in Mothership's Supabase Postgres, `app`/`derived` schema layer, and is currently read by Mind directly via service-role credentials — there is no product-facing API. See `proposal.md` - Why for the regression hypothesis this change tests.

This is a same-day prototype (demo tomorrow), running on branch `poc/live-matchmaking`, not `main`.

## Goals / Non-Goals

**Goals:**
- Run rec-engine's constraint-engine filtering, fed by live Mind/Mothership data, ahead of an LLM ranking funnel shaped like Mind's current model.
- Produce a ranked candidate list with rationale for 2–3 real open roles, viewable in rec-engine's existing UI, for a live side-by-side comparison against Mind's current output.
- Keep the change isolated to `rec-engine` — no edits to Mind or Mothership code.

**Non-Goals:**
- Outreach funnel (candidate/HM comms, Slack cards, sendouts) — matchmaking only.
- Trained ML scoring (`ml_scoring.py`) or historical backtesting against `fct_placement`/`fct_sendout` — validation is live eyeballing, not an accuracy benchmark.
- A new UI framework or from-scratch UI — reuse rec-engine's existing React app where it accelerates the demo.
- Production hardening (retry/backoff, connection pooling, monitoring) — this is a prototype, not a deployable service.

## Decisions

**1. Reuse rec-engine's constraint engine unmodified; do not build a custom semantic-matching layer.**
`constraint_engine.py`'s 3-phase matching (exact canonical-key → semantic/embedding fallback → no-match-is-compatible) already does what the regression fix needs. Alternative considered: replace the OpenAI-embedding semantic fallback with a Claude-based per-pair compatibility check, to avoid provisioning a new API key. Rejected once an `OPENAI_API_KEY` was provisioned — the embedding approach is cheaper and faster at scale (batch-embed once, cheap cosine comparisons thereafter, vs. a live LLM call per ambiguous constraint pair), deterministic given cached vectors, and requires zero code changes since `constraint_engine.py` and `retrieval.py` already expect this key.

**2. Replace rec-engine's scoring stage with a Mind-shaped coarse→fine LLM funnel; do not use weighted-linear or trained-ML scoring.**
Three approaches were considered:
  - *(chosen)* Keep Mind's existing funnel shape (filter → coarse LLM → fine LLM), improving only the filter stage. Cleanest attribution of any observed uplift to the filtering fix specifically, since downstream ranking logic is analogous to what Mind already does.
  - Weighted-linear scoring with contextual, JD-derived weights (auto-generating a rubric instead of hand-authoring one, analogous to Mind's `RubricEditorModal`). Parked as a fast-follow: numeric weight extraction from unstructured text is less proven than the categorical/threshold constraint extraction rec-engine already does well, and it risks losing the rerank stage's explanation depth.
  - Trained ML model (logistic regression / gradient-boosted trees, as in `ml_scoring.py`). Rejected — trained on synthetic labels today, and a model-lifecycle isn't warranted for a PoC meant to reach prod soon.

**3. Live data access mirrors Mind's existing pattern exactly: direct Supabase read, no new API layer.**
There is no product-facing API for candidate/job data in Mothership today — Mind itself reads `app`/`derived` tables directly via service-role credentials. Building an API layer for this PoC would be scope creep; the adapter reads the same way Mind does.

**4. Candidates sourced from `app.candidates` (the newer 89-col gold table), not `app.bullhorn_candidates` (what Mind currently reads).**
`app.candidates` is available, hourly-refreshed, and wider than what Mind has adopted. Using it doesn't require Mind to change anything, and lets the PoC exercise the more complete data Mind hasn't yet moved to.

**5. Credentials reused from Mind's `.env`, not freshly provisioned (except `OPENAI_API_KEY`).**
`ANTHROPIC_API_KEY`, `SUPABASE_URL`, and `SUPABASE_SERVICE_ROLE_KEY` were copied read-only from `wave-mind/mind/.env` into `wave-mind/rec-engine/.env` (gitignored, `chmod 600`). `OPENAI_API_KEY` did not exist in either Mind's or Mothership's env and was newly provisioned by the user.

## Risks / Trade-offs

- **[Risk]** Live candidate pools per role may be large enough that running full extraction (Claude) + constraint matching over every candidate is slow for a live demo. → **Mitigation**: rec-engine's existing embedding-based `retrieval.py` top-K stage can be used as a cheap pre-filter ahead of the constraint engine if a role's pool is large; not required for small pools.
- **[Risk]** The exact Bullhorn job briefing field/table wasn't confirmed during exploration (only that it exists somewhere on or linked to `bullhorn_job_orders`). → **Mitigation**: confirm the column during the live-data-adapter build (task 4); constraint extraction still functions on description-only text if briefing is unavailable (see spec scenario).
- **[Risk]** Reusing Mind's live service-role credentials means any adapter bug has the same blast radius as Mind's own data access. → **Mitigation**: adapter is read-only by construction (no write paths implemented), and the Mothership platform owner should get a heads-up before this consumer starts querying, per repo convention.
- **[Trade-off]** No historical/ground-truth validation means "uplift" is a subjective, one-time judgment call during tomorrow's demo, not a reproducible metric. Accepted for this timeline; a backtest against `fct_placement`/`fct_sendout` remains a natural follow-up if this direction is pursued further.

## Migration Plan

Not applicable — this is a standalone prototype on a feature branch (`poc/live-matchmaking`) with no deployment target and no changes to `main` or to Mind/Mothership. If the direction is validated, a separate follow-on change would define the path to production (likely including the parked weighted-linear/contextual-rubric direction, and real backtesting).
