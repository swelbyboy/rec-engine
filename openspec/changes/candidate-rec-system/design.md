## Context

A greenfield Python project with no existing codebase. The system processes unstructured recruiter data (job descriptions, CVs, LinkedIn profiles, interview notes) through an LLM-powered pipeline and returns ranked, explainable candidate recommendations. The key architectural challenge is handling heterogeneous, job-specific constraints without a fixed schema — constraints vary across roles (security clearance, visa sponsorship, compressed hours, B-corp preference) and must be matched semantically rather than by field name.

External dependencies: Anthropic Claude API (feature extraction + explanations), an embedding model for semantic constraint matching (OpenAI text-embedding-3-small or a local alternative), FastAPI + Uvicorn (backend), Streamlit (demo UI), NumPy (scoring), SQLite or in-memory dict (storage for demo).

## Goals / Non-Goals

**Goals:**
- Parse unstructured JD and candidate text into validated JSON (JD schema + Candidate schema) via LLM structured output calls
- Dynamically extract typed constraint lists from both sides and match them via canonical key lookup first, embedding similarity fallback
- Eliminate candidates that fail hard constraints and score remaining candidates via weighted linear model
- Generate per-candidate LLM explanations that surface constraint analysis and review flags
- Expose the full pipeline via a single FastAPI endpoint
- Provide a Streamlit UI with live weight tuning without re-running LLM calls
- Include pre-generated dummy data covering all edge cases (strong match, hard fail, soft mismatch, novel constraints, low-confidence flags)

**Non-Goals:**
- Multi-tenant auth or production security hardening
- Learned weight optimisation from hiring outcomes (manual weights only for demo)
- Candidate-to-job reverse matching (only JD → candidate ranking for demo)
- Real-time integrations with ATS or LinkedIn API
- Persistent storage beyond demo session (SQLite acceptable for demo; no migrations needed)

## Decisions

### LLM for feature extraction: Claude API (Sonnet) with structured output

**Decision:** Use `claude-sonnet-4-6` with JSON mode / tool use to extract both feature fields and constraint lists in a single call per document type (one call for JD, one per candidate source, then a merge call).

**Rationale:** Claude's instruction-following and self-reported confidence make it the best fit for the extraction + confidence-scoring requirement. Structured output via tool use guarantees schema conformance without post-hoc parsing.

**Alternative considered:** GPT-4o with function calling — equivalent capability but adds a second vendor dependency with no advantage here.

### Constraint matching: canonical key first, embedding similarity fallback

**Decision:** Attempt canonical key matching (string equality on `canonical_key` field) first. If no match exists, compute cosine similarity between constraint description embeddings (OpenAI `text-embedding-3-small`). Only invoke a second LLM call for novel constraints where embedding similarity is ambiguous (0.55–0.75 band).

**Rationale:** Canonical key matching is deterministic and fast for the common cases. Embeddings handle novel constraints without an expensive LLM call on every pair. The LLM fallback is reserved for genuinely ambiguous pairs.

**Alternative considered:** LLM call for all constraint matching — more reliable but 10–20× slower and costlier at scale.

### Confidence thresholds: three-tier handling

**Decision:** Constraints with confidence ≥ 0.85 are applied automatically; 0.60–0.84 are applied but flagged in the UI; < 0.60 are excluded from the engine and surfaced as uncertain extractions.

**Rationale:** Prevents silent errors from low-quality extractions while not requiring human sign-off on clear-cut constraints. Thresholds are calibrated against typical LLM extraction behaviour and can be adjusted via config.

### Scoring: weighted linear sum, manually calibrated weights

**Decision:** `score = Σ(feature_i × weight_i)` over 10 features. Weights initialised manually from domain intuition. The weight vector is exposed in the UI as sliders to enable live re-ranking without re-running LLM calls.

**Rationale:** A linear model is fully inspectable, fast to compute, and sufficient for a demo. The weight sliders make the model transparent to recruiters. When real hiring outcome labels are available, the same feature matrix can feed a proper logistic regression.

**Alternative considered:** Embedding similarity between JD and candidate text as the sole score — simpler but opaque, loses the constraint compatibility signal, and doesn't support per-feature weight tuning.

### Separation of LLM calls and scoring

**Decision:** LLM extraction runs once per JD + candidate set, outputs are cached in memory (or SQLite). Scoring and re-ranking run entirely in Python/NumPy using cached extractions. Weight slider changes in the UI trigger only the scoring step, not LLM calls.

**Rationale:** LLM calls are the bottleneck. Caching structured extractions makes interactive weight tuning instant and avoids redundant API costs.

### Storage: in-memory dict with optional SQLite persistence

**Decision:** For the demo, structured extractions and constraint match results are held in an in-memory dict keyed by `(job_id, candidate_id)`. SQLite is available as a drop-in if the session needs to persist across restarts.

**Rationale:** No infra overhead, zero configuration. SQLite upgrade path is straightforward with the same data model.

## Risks / Trade-offs

- **LLM extraction inconsistency** → Mitigation: JSON schema enforcement via tool use + unit tests asserting required fields; low-confidence constraints are flagged rather than silently dropped
- **Embedding model cold start / latency** → Mitigation: batch all constraint descriptions in a single embedding API call at the start of each pipeline run; cache embeddings for the session
- **Canonical key vocabulary drift** (LLM uses different keys than expected) → Mitigation: canonical key list is included in the system prompt; few-shot examples anchor common cases; semantic fallback catches misses
- **Hard constraint false positives** (over-extraction of hard constraints) → Mitigation: prompt instructs the model to only mark `type: hard` when the source text is explicit ("must", "required", "no visa sponsorship"); confidence threshold enforced
- **Weight tuner UX complexity** → Mitigation: Streamlit sliders with live re-render keep it simple; default weights are pre-loaded so recruiters can explore without needing to understand the model

## Migration Plan

Greenfield project — no migration required. Deployment is local (`uvicorn` + `streamlit run`) for the demo. No rollback plan needed for demo scope.

## Open Questions

- Should the embedding fallback use OpenAI `text-embedding-3-small` or a local model (e.g. `sentence-transformers/all-MiniLM-L6-v2`) to avoid a second API vendor dependency?
- What is the target latency for a full pipeline run (3 JDs × 20 candidates)? If > 30s is acceptable, the sequential extraction approach is fine; otherwise parallelise candidate extraction calls.
- Should low-confidence constraints that are excluded from the engine still appear in the explanation layer output?
