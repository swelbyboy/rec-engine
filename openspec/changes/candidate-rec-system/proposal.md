## Why

Recruiting teams spend significant manual effort matching candidates to job descriptions — a process that is slow, inconsistent, and fails to systematically account for the heterogeneous constraints both employers and candidates carry (visa requirements, remote preferences, salary expectations, clearances, etc.). An AI-powered recommendation engine can automate structured feature extraction from unstructured text and apply a principled constraint-compatibility and scoring model, enabling recruiters to focus their attention on the shortlisted candidates rather than the filtering process.

## What Changes

- Introduce an LLM-powered feature extraction pipeline that parses raw job descriptions and candidate documents (CV, LinkedIn, interview notes) into structured JSON
- Introduce a dynamic constraint compatibility engine that matches employer and candidate constraints semantically — not via fixed schema fields
- Introduce a weighted scoring model that ranks candidates who pass hard constraints by overall fit
- Introduce an LLM-powered explanation layer that generates per-candidate rationale including constraint analysis
- Introduce a Streamlit demo UI with job input, ranked results, constraint detail, review flags, and live weight tuning
- Introduce a FastAPI backend that exposes the pipeline as a clean API
- Introduce pre-generated dummy data (3 jobs, 20 candidates) covering strong matches, hard constraint eliminations, soft mismatches, and novel constraints

## Capabilities

### New Capabilities

- `feature-extraction`: LLM pipeline (Claude API) that parses raw JD and candidate text into structured JSON conforming to the JD and Candidate schemas, including typed constraint lists with confidence scores
- `constraint-engine`: Compatibility engine that matches employer and candidate constraints via canonical key lookup and semantic/embedding fallback, producing pass/fail and soft-match scores
- `scoring-model`: Weighted linear scoring over extracted features and soft constraint aggregate for candidates that pass hard constraints
- `explanation-generation`: LLM call that produces human-readable per-candidate rationale from feature breakdown and constraint match results
- `demo-ui`: Streamlit single-page app with JD input, pipeline trigger, ranked results panel, constraint detail expansion, review flags, and live weight sliders
- `api-backend`: FastAPI backend wiring feature extraction → constraint engine → scoring → explanation into a single pipeline endpoint
- `dummy-data`: Pre-generated JSON fixtures for 3 job descriptions and 20 candidates designed to exercise all system paths

### Modified Capabilities

## Impact

- New Python project with no existing codebase — all capabilities are net-new
- External dependencies: Claude API (Anthropic SDK), embedding model (OpenAI or local), FastAPI, Uvicorn, Streamlit, NumPy, SQLite or in-memory store
- No existing APIs or services modified
