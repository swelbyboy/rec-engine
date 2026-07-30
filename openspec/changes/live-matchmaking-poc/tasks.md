## 1. Environment & Access

- [x] 1.1 Set up Python 3.11+ venv and install rec-engine on branch `poc/live-matchmaking`
- [x] 1.2 Install OpenSpec CLI and confirm this proposal validates
- [x] 1.3 Reuse `ANTHROPIC_API_KEY`, `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY` from Mind's `.env`; provision `OPENAI_API_KEY` separately
- [x] 1.4 Smoke-test rec-engine's existing API against synthetic fixtures with all four credentials present

## 2. Live Data Adapter — Candidates

- [x] 2.1 Write a Supabase client helper (PostgREST, `Accept-Profile: app`) scoped to read-only access — `src/live_data.py`
- [x] 2.2 Query `app.candidates` for a candidate pool (revised: `app.candidate_employment_agg`/`_education_agg` not needed — `app.candidates` already carries current/previous roles and industries directly)
- [x] 2.3 ~~Join in `derived.cv_parsed` and `derived.granola_notes`~~ — revised: `app.candidates` already surfaces the derived narrative fields (`cv_summary`, `headline`, `prescreen_summary`, `current_situation`, `recruiter_assessment`) pre-joined, so no separate join is needed
- [x] 2.4 Map rows into rec-engine's `Candidate` model. Revised from the original plan: candidate-side `constraints` are built **deterministically from `app.candidates`' already-typed fields** (`salary_normalized`, `notice_days`, `working_model`, `requires_visa`, `deal_breakers`, `drivers`) rather than via LLM extraction — Mothership has already parsed these out of raw text upstream, so re-running `extraction.py`'s LLM pass over candidates here would be redundant cost/latency with no accuracy gain. `extraction.py` is still used for jobs (Task 4), where the JD/briefing text is genuinely unstructured.
- [x] 2.5 Spot-checked against live data (see below) — confirmed hard/soft constraints build correctly from real candidates, including nuanced deal-breakers (commute limits, ethical/company-type exclusions) that Mind's exact-match gates would likely miss

## 3. Live Data Adapter — Jobs

- [x] 3.1 Query `app.bullhorn_job_orders` (`raw_data` passthrough) + `app.dim_job_order` (for `company_name`) for a given job order ID
- [x] 3.2 Confirmed: the Bullhorn job briefing is the JobOrder entity's `description` field (internal brief written after intake); `publicDescription` (external ad copy) is a second, often-empty text field — both live inside `bullhorn_job_orders.raw_data` JSONB, not a separate table
- [x] 3.3 Map job order + briefing into raw fields (`id`, `title`, `company`, `raw_text` = `publicDescription` + `description` combined, HTML-stripped); `JobDescription` construction itself happens via `extraction.py` in Task 4
- [x] 3.4 Handles jobs with no briefing text gracefully (confirmed live: one sampled job order had only a placeholder `description`, no `publicDescription` — adapter returns empty `raw_text` without erroring)

## 4. Automated Constraint Extraction

- [x] 4.1 Wire live `JobDescription.raw_text` (description + briefing) through rec-engine's existing `extraction.py` (`parse_job_description`)
- [x] 4.2 Ran extraction against 3 real open roles by hand. Found and fixed two real bugs in `extraction.py` along the way (see commit `3381113`): (a) caller-supplied `title`/`company` were silently discarded in favour of the LLM's own guess/placeholder because the tool schema requires those keys; (b) the prompt extracted generic company benefits/perks (life assurance, pension, GP access...) as hard "requires" constraints, diluting genuine compatibility signal — scoped the prompt to fit-relevant categories only. Re-verified post-fix: skills/experience/culture extract cleanly, and genuine hard constraints (salary range, location, security clearance) still come through correctly
- [ ] 4.3 Confirm constraint-engine's confidence threshold behavior (flagged-for-review path) on live-derived constraints — deferred to Task 5 (Funnel Rerank), where the constraint engine actually runs against live candidates

## 5. Funnel Rerank

- [x] 5.1 Run live candidates (constraints built deterministically per Task 2.4) through `constraint_engine.py` unmodified, matched against live job constraints from Task 4. Added one deterministic safety-net on top (not instead of) the generic engine: testing found the employer-side canonical_key for the UK-based/visa dimension drifts across separate extraction runs of the *same* job, and even near-identical phrasings scored under the semantic-match threshold — so the coarse stage (5.2) now also answers two targeted yes/no questions cross-checked directly against candidate data for this one high-value, high-frequency dimension
- [x] 5.2 Implemented `coarse_role_brief()`: recruiter-facing summary + per-hard-constraint flexibility judgment + the two targeted location/visa questions above
- [x] 5.3 Implemented `fine_rerank()`: single batched LLM call ranking the filtered pool with verdict (`strong_match`/`good_match`/`possible`/`weak_match`) + rationale per candidate
- [x] 5.4 Confirmed — `scoring.py`/`ml_scoring.py` are not imported anywhere in `funnel_rerank.py`
- [x] 5.5 Confirmed — `run_live_pipeline()` returns `eliminated` (with reasons) and `ranked` as separate lists

Verified end-to-end against 2 real live roles (~55-60s for a 60-candidate pool each). Verdict ordering spot-checked by hand and looks sound, e.g. a junior full-stack engineer correctly demoted to `weak_match` for a senior cloud architect role despite passing all hard filters.

## 6. UI Wiring

- [ ] 6.1 Expose the live pipeline (data adapter → constraint engine → funnel rerank) via a new or adapted API endpoint
- [ ] 6.2 Point rec-engine's existing React UI results view at live pipeline output
- [ ] 6.3 Confirm ranked list, verdicts, rationale, and elimination reasons render correctly for a real role

## 7. Live Demo Validation

- [ ] 7.1 Select 2-3 real open roles with existing Mind-ranked output to compare against
- [ ] 7.2 Run the live pipeline for each selected role and capture the ranked output
- [ ] 7.3 Compare PoC output against Mind's current output for the same roles; note qualitative differences
- [ ] 7.4 Capture screenshots/notes from the comparison for use in the demo

## 8. Demo Prep

- [ ] 8.1 Draft a short walkthrough script: Mind's current output for a role, then the PoC's, narrating the filtering difference
- [ ] 8.2 Dry-run the walkthrough end-to-end before the live demo
