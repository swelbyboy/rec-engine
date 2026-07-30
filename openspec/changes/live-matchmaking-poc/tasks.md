## 1. Environment & Access

- [x] 1.1 Set up Python 3.11+ venv and install rec-engine on branch `poc/live-matchmaking`
- [x] 1.2 Install OpenSpec CLI and confirm this proposal validates
- [x] 1.3 Reuse `ANTHROPIC_API_KEY`, `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY` from Mind's `.env`; provision `OPENAI_API_KEY` separately
- [x] 1.4 Smoke-test rec-engine's existing API against synthetic fixtures with all four credentials present

## 2. Live Data Adapter — Candidates

- [ ] 2.1 Write a Supabase client helper (PostgREST, `Accept-Profile: app`/`derived`) scoped to read-only access
- [ ] 2.2 Query `app.candidates` (+ `app.candidate_employment_agg`, `app.candidate_education_agg`) for a given role's candidate pool
- [ ] 2.3 Join in `derived.cv_parsed` and `derived.granola_notes` for `raw_cv` / `raw_interview_transcript`
- [ ] 2.4 Map joined rows into rec-engine's `Candidate` model; default missing fields to empty string rather than erroring
- [ ] 2.5 Spot-check mapped `Candidate` objects against 2-3 real candidates for plausibility

## 3. Live Data Adapter — Jobs

- [ ] 3.1 Query `app.bullhorn_job_orders` / `app.dim_job_order` for a given job order ID
- [ ] 3.2 Confirm the exact field/table holding the Bullhorn job briefing text and include it in the fetch
- [ ] 3.3 Map job order + briefing into rec-engine's `JobDescription` model, concatenating description and briefing into `raw_text`
- [ ] 3.4 Handle jobs with no briefing text gracefully (description-only extraction)

## 4. Automated Constraint Extraction

- [ ] 4.1 Wire live `JobDescription.raw_text` (description + briefing) through rec-engine's existing `extraction.py` (`parse_job_description`)
- [ ] 4.2 Run extraction against 1-2 real roles and sanity-check the resulting constraints (categories, canonical keys, confidence) by hand
- [ ] 4.3 Confirm constraint-engine's existing confidence threshold behavior (flagged-for-review path) works as expected on live-derived constraints

## 5. Funnel Rerank

- [ ] 5.1 Run live candidates through rec-engine's existing candidate extraction (`extraction.py`) and constraint engine (`constraint_engine.py`) unmodified, using live job constraints from Task 4
- [ ] 5.2 Implement coarse LLM stage: extract role requirements/flexibility signals from the job's extracted data
- [ ] 5.3 Implement fine-grained LLM rerank stage: rank the constraint-engine-filtered pool with per-candidate verdict + rationale, informed by the coarse stage
- [ ] 5.4 Ensure `scoring.py` / `ml_scoring.py` are not invoked anywhere in this pipeline path
- [ ] 5.5 Ensure eliminated candidates (failed hard constraints) are returned separately with elimination reasons intact

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
