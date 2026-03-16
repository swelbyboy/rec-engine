## 1. Project Setup

- [x] 1.1 Create project directory structure (`src/`, `data/`, `tests/`)
- [x] 1.2 Create `pyproject.toml` with dependencies: `anthropic`, `openai`, `fastapi`, `uvicorn`, `numpy`, `pydantic`, `python-multipart`, `pypdf`
- [x] 1.3 Add `.env.example` with `ANTHROPIC_API_KEY` and `OPENAI_API_KEY` placeholders
- [x] 1.4 Confirm Claude API and embedding API keys are accessible from environment

## 2. Data Models

- [x] 2.1 Define `Constraint` Pydantic model with all fields: `id`, `type`, `side`, `category`, `description`, `canonical_key`, `value`, `operator`, `weight`, `confidence`
- [x] 2.2 Define `JobDescription` Pydantic model with all fields including `constraints: list[Constraint]`
- [x] 2.3 Define `Candidate` Pydantic model with all fields including `constraints: list[Constraint]`
- [x] 2.4 Define `ConstraintMatch` and `CompatibilityResult` Pydantic models for constraint engine output
- [x] 2.5 Define `FeatureVector`, `ScoredCandidate`, and `PipelineResult` Pydantic models

## 3. Dummy Data

- [x] 3.1 Generate `data/candidates.json` with 20 candidate fixtures, each containing `cv`, `linkedin`, and `interview_transcript` raw text fields
- [x] 3.2 Ensure candidate distribution: 6–9 strong matches across job types, 3 hard-fail eliminations, 3 soft-mismatch only, 2 low-confidence flags, 2 novel constraints, remainder mid-tier
- [x] 3.3 For at least 5 candidates, place a key constraint (salary, visa, notice period, or location) only in the interview transcript — not in the CV or LinkedIn text
- [x] 3.4 Manually verify at least one candidate per elimination category has the expected hard constraint conflict
- [x] 3.5 Verify at least 2 candidates have `confidence < 0.85` on at least one constraint

## 4. Feature Extraction — LLM Prompts

- [x] 4.1 Write `parse_job_description(raw_text) -> JobDescription` using Claude structured output (tool use / JSON mode)
- [x] 4.2 Write `parse_candidate_source(source_text, source_type) -> dict` for single-source extraction
- [x] 4.3 Write `merge_candidate_sources(cv_extract, linkedin_extract, notes_extract) -> Candidate` merge + deduplication call
- [x] 4.4 Include canonical key vocabulary list and few-shot examples (explicit, implicit, missing data) in system prompts
- [x] 4.5 Write unit test: parse a known JD text and assert required fields and at least one constraint are present
- [x] 4.6 Write unit test: parse a candidate fixture and assert confidence values are in 0.0–1.0 range

## 5. Constraint Compatibility Engine

- [x] 5.1 Implement `canonical_key_match(employer_c, candidate_c) -> ConstraintMatch | None`
- [x] 5.2 Implement operator logic for all operator pairs: `requires`, `max`, `min`, `prefers`, `excludes`, `one_of`
- [x] 5.3 Implement embedding-based semantic matching: batch-encode all constraint descriptions, compute cosine similarity matrix, apply 0.75 threshold
- [x] 5.4 Implement `check_compatibility(employer_c, candidate_c) -> ConstraintMatch` routing through canonical → semantic → no-match
- [x] 5.5 Implement `run_constraint_engine(job, candidate) -> CompatibilityResult` aggregating all pair results and setting `eliminated`
- [x] 5.6 Write unit test: office_days_per_week requires 5 vs max 2 → hard fail, eliminated
- [x] 5.7 Write unit test: salary_max 85000 vs salary_min 90000 → hard fail, eliminated
- [x] 5.8 Write unit test: soft mismatch (four_day_week) → compatible, score < 1.0, not eliminated
- [x] 5.9 Write unit test: employer hard constraint with no candidate counterpart → compatible, no penalty

## 6. Scoring Model

- [x] 6.1 Implement `build_feature_vector(job, candidate, constraint_result) -> FeatureVector` computing all 10 features
- [x] 6.2 Implement Jaccard similarity helper for skill overlap features
- [x] 6.3 Implement `score_candidate(feature_vector, weights) -> float` weighted linear sum
- [x] 6.4 Implement `rank_candidates(job, candidates, weights) -> PipelineResult` filtering eliminated candidates and sorting by score
- [x] 6.5 Write unit test: all features at 1.0 with default weights → score == 1.0
- [x] 6.6 Write unit test: experience_delta is clamped to 0 when candidate is under-experienced

## 7. Explanation Generation

- [x] 7.1 Write `generate_explanation(job, candidate, feature_vector, constraint_result) -> str` LLM call with structured context
- [x] 7.2 Ensure explanation prompt instructs model to include constraint analysis section and flag-for-review section when applicable
- [x] 7.3 Implement top-N threshold: only call explanation generation for top N candidates by score (default N=10)
- [x] 7.4 For eliminated candidates, format structured elimination reason string from `CompatibilityResult` (no LLM call)

## 8. API Backend

- [x] 8.1 Set up FastAPI app with `GET /health` endpoint
- [x] 8.2 Load candidate fixtures into memory at startup
- [x] 8.3 Implement `POST /recommend` accepting JSON body (`jd_text`) and running the full pipeline
- [x] 8.4 Add file upload support to `POST /recommend` (multipart form, plain-text or PDF)
- [ ] 8.5 Run the API locally and verify `POST /recommend` returns ranked candidates for a sample JD

## 9. Integration & Verification

- [ ] 9.1 Run pipeline end-to-end with a fintech data engineering JD and verify remote-only candidate is eliminated
- [ ] 9.2 Run pipeline with a remote PM JD and verify strong-match candidates rank at the top
- [ ] 9.3 Verify novel constraint candidate (e.g. B-corp) shows `match_type: semantic` in response
- [ ] 9.4 Verify low-confidence constraint candidate has review flag in response
- [x] 9.5 Write a `README.md` with setup instructions (`pip install`, env vars, `uvicorn` run command, example `curl` request)
