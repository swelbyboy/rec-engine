# Candidate Recommendation Engine — System Design

---

## 1. Problem

Recruitment is fundamentally a matching problem under uncertainty. A job description and a candidate profile both contain structured signals (skills, experience, seniority) and unstructured constraints (location requirements, compensation expectations, visa status, working preferences). Traditional keyword-matching systems handle the structured signals reasonably well but fail on constraints: they can't extract them reliably from free text, can't reason about compatibility between employer and candidate sides, and can't surface nuanced mismatches in a way recruiters can act on.

The goal of this system is to:

1. Accept raw, unstructured input on both sides (job descriptions; CV + LinkedIn + interview transcripts)
2. Extract structured features and constraints from that text using an LLM
3. Apply a constraint compatibility engine to eliminate hard-fail candidates and score soft mismatches
4. Rank surviving candidates by a weighted feature model
5. Return explainable results — ranked candidates with scores, constraint analysis, and natural-language recruiter notes

---

## 2. Architecture

The system runs a staged pipeline on each recommendation request. Stages are ordered by cost: cheap operations (vector maths) run first on the full pool; expensive operations (LLM calls) run last on a small set.

```
[OFFLINE — on first load]
candidates.json (raw free text: CV + LinkedIn + interview transcript)
  → regex pre-scan (salary figures, office-day mentions)
  → Claude Haiku tool-use extraction → structured Candidate object
  → OpenAI text-embedding-3-small → 1536-dim vector
  → cached to data/processed/<id>.json (invalidated by content hash)

[ON EACH REQUEST]
JD text
  ↓ 1. Claude Haiku tool-use → JobDescription (skills, constraints, seniority...)
  ↓ 2. OpenAI embed JD → cosine similarity over candidate matrix → top-K retrieved
  ↓ 3. Constraint engine (canonical key → semantic → no-match fallback) → eliminated / survived
  ↓ 4. Feature vector (10 dims, embedding-based skill/industry match) → weighted linear score
  ↓ 5. Claude Haiku → plain-prose recruiter explanation (top-N only)
  → JSON: ranked candidates + eliminated candidates + explanations
```

### 2.1 Extraction layer (`extraction.py`)

The LLM is used as a **structured extractor**, not a reasoner. Each call uses forced tool use — the API's mechanism for guaranteeing the model outputs a specific typed JSON schema. This is distinct from JSON mode: tool use validates field types against a declared schema and returns a typed Python dict, with no `json.loads()` or schema validation required on the application side.

Two schemas exist: one for job descriptions and one for candidates. Both extract a list of `Constraint` objects alongside standard fields (skills, seniority, experience).

The system prompt includes:
- A **canonical key vocabulary** (~15 keys: `office_days_per_week`, `salary_min`, `visa_sponsorship`, etc.) that the LLM maps matching constraints to
- **Few-shot examples** covering explicit, implicit, ambiguous, and missing-data cases
- A **regex hint block** prepended to each candidate prompt — a pre-scan of the raw text detects salary figures and office-day mentions and injects them as mandatory items the LLM must not omit

Candidate extraction uses a **single-pass approach**: all three source documents (CV, LinkedIn, interview transcript) are concatenated with section headers and sent in one call, rather than three separate calls followed by a merge. This reduces cost and avoids merge-step information loss.

### 2.2 Candidate store (`store.py`)

Candidates are expensive to process (LLM + embedding call per candidate). The store caches results to `data/processed/<id>.json`, keyed by an MD5 hash of the raw source data. On startup, only new or changed candidates are re-processed. A `CACHE_SCHEMA_VERSION` constant forces re-processing when the `Candidate` schema changes.

At query time, `embedding_matrix()` returns all candidate embeddings as a numpy matrix for fast batch cosine similarity.

### 2.3 Retrieval (`retrieval.py`)

The parsed JD is converted to a natural-language summary (mirroring the structure of candidate summaries) and embedded once. Cosine similarity is computed over the full candidate matrix in a single numpy operation. Candidates below a 0.25 similarity threshold are dropped — this handles discipline filtering without any hardcoded rules. The top-K (default 50) are passed to the constraint engine.

### 2.4 Constraint engine (`constraint_engine.py`)

The constraint engine is the most novel part of the system. It runs three matching phases in order for each employer constraint:

**Phase 1: Canonical key matching (deterministic)**
If employer and candidate constraints share a `canonical_key`, their values are compared using operator-pair logic. The six operators (`requires`, `min`, `max`, `prefers`, `excludes`, `one_of`) define ~20 operator-pair combinations. Special cross-key handling exists for `salary_max` vs `salary_min` and `office_days_per_week` vs `remote_ok`. Hard constraint failures eliminate the candidate.

**Phase 2: Semantic fallback (embedding-based)**
Unmatched employer constraints are batch-embedded and compared against batch-embedded candidate constraint descriptions. Pairs above 0.75 cosine similarity are considered matched and evaluated with the same operator-pair logic. Pairs in the 0.55–0.75 band are flagged for human review rather than auto-decided.

**Phase 3: No-match fallback**
If no candidate counterpart is found, the employer constraint is treated as compatible — the candidate hasn't expressed a conflicting preference. Security clearance constraints are flagged for review regardless.

All constraint engine calls across the top-K candidates run in a `ThreadPoolExecutor` in parallel.

### 2.5 Scoring model (`scoring.py`)

Non-eliminated candidates receive a 10-dimensional feature vector:

| Feature | Weight | Method |
|---|---|---|
| `required_skills_overlap` | 0.38 | Asymmetric recall: fraction of required skills matched by cosine similarity ≥ 0.75 |
| `preferred_skills_overlap` | 0.10 | Same |
| `industry_preferred_match` | 0.12 | Mean best cosine sim between candidate industries and job's preferred industries |
| `experience_delta` | 0.10 | 0 if below minimum; linear 0.5→1.0 from minimum to minimum+5 years |
| `seniority_match` | 0.08 | Ordinal distance on 5-level ladder |
| `career_trajectory_score` | 0.05 | ascending=0.85, lateral=0.65, mixed=0.60 |
| `interview_score` | 0.03 | LLM-assessed from transcript; zeroed if no transcript present |
| `culture_fit_score` | 0.02 | LLM-assessed from transcript; zeroed if no transcript present |
| `management_match` | 0.04 | Binary 1.0/0.3 |
| `soft_constraint_score` | 0.08 | Mean of all constraint match scores |

Skill and industry embeddings are LRU-cached — repeated scoring calls add zero API cost. When a candidate has no interview transcript, `interview_score` and `culture_fit_score` weights are zeroed and redistributed to `required_skills_overlap`; weights are then re-normalised to sum to 1.0.

Four named weight profiles are available (`balanced`, `skills_first`, `constraints_first`, `culture_fit`), selectable per request.

### 2.6 Explanation layer (`explanation.py`)

Top-N ranked candidates (default 10) each get a Claude call generating a 3-paragraph recruiter assessment: Strengths, Gaps, Practical Flags. The prompt is grounded in the computed feature vector and constraint match results — the model is instructed to discuss only what is in the data and not to describe compatible constraints as problems. Eliminated candidates receive deterministic string formatting without an LLM call.

Explanation calls fire in parallel via `ThreadPoolExecutor`. The streaming endpoint (`POST /recommend/stream`) emits the ranked list immediately after scoring via SSE, then streams explanations one-by-one as they complete.

---

## 3. Key Design Decisions

### LLM as extractor, not scorer
Claude is used only for information extraction (unstructured → structured) and explanation generation (structured → prose). All scoring logic is deterministic Python. This keeps the system interpretable: every score can be decomposed into its feature contributions and traced back to extracted data.

### Forced tool use over JSON mode
Tool use guarantees typed output — the API validates field types against the declared schema. JSON mode produces JSON-shaped text that may violate the schema. For a pipeline where downstream components depend on typed fields (e.g. `value: float` for salary comparison), type guarantees matter.

### Canonical key vocabulary + semantic fallback
A shared vocabulary of ~15 constraint keys enables fast, deterministic matching for the most common constraint types. Novel constraints (no canonical key) fall through to embedding-based semantic matching. This hybrid gives precision on common cases and coverage on novel ones, without requiring exhaustive enumeration of all possible constraint types.

### Regex pre-scan as LLM guard
Salary figures and office-day mentions are detected by regex before the LLM call and injected as mandatory hints. This prevents the single most damaging extraction failure mode: silently dropping numeric constraints that determine hard eliminations.

### Staged pipeline
Each stage reduces the candidate set before passing it to a more expensive operation: vector maths (all candidates → top-50) → constraint engine (top-50 → survivors) → LLM explanations (top-10 only). This is what makes the system interactive — total latency is bounded by the LLM calls, not by the size of the candidate pool.

### Interview/culture score weight suppression
LLM-assessed soft signals (`interview_score`, `culture_fit_score`) carry intentionally low weights (0.03 + 0.02) to limit bias risk from subjective assessments. When no transcript exists, these weights are zeroed entirely rather than contributing a neutral 0.5 constant that would make pre- and post-interview scores incomparable.

---

## 4. Limitations

### Hardcoded thresholds
The following values are set by hand with no empirical grounding:
- Skill match threshold: 0.75 cosine similarity
- Semantic constraint match threshold: 0.75
- Retrieval floor: 0.25
- Career trajectory scores: ascending=0.85, lateral=0.65, mixed=0.60
- Experience surplus cap: 5 years
- Default feature weights

None of these are learned from data. Different roles, industries, or hiring cultures would warrant different values.

### Static canonical key vocabulary
The ~15 canonical keys are hardcoded in `extraction.py`. Adding a new constraint type (e.g. `publication_count_min` for academic roles, `on_call_hours_per_week` for operational roles) requires both updating the prompt vocabulary and adding any special-case handling in the constraint engine. Novel constraints degrade gracefully to semantic matching, but lose numeric comparison precision and deterministic hard-fail behaviour.

### Feedback loop (partially addressed)
A basic feedback loop now exists: recruiter curation decisions (shortlist / remove) are captured as labelled feature-vector pairs and written to `data/feedback.jsonl`, and models can be retrained in-process via `POST /api/retrain`. However, the signal is coarse (binary outcome only, no reason for rejection), `job_id` is not stored (no per-role or per-recruiter stratification), and there is no guard against overfitting when the feedback set is small. The loop closes, but the data quality is limited until volume accumulates.

### Candidate-side hard constraints don't independently eliminate
The constraint engine iterates over employer constraints and checks them against candidate constraints. A candidate with a hard salary requirement (`salary_min: £150k`) is only eliminated if the employer also has a matching salary constraint (`salary_max`) that conflicts. If the employer specifies no salary budget, the candidate passes through — their requirement is surfaced in `candidate_requirements` but doesn't affect ranking. In practice, a human recruiter would catch this; the system cannot act on it without employer-side data.

### No overqualification signal
A principal-level candidate applying for a junior role scores 0.6 on seniority (two steps apart), the same as a junior applying for a senior role. Overqualification and underqualification are not modelled differently, despite having very different practical implications.

### Single LLM extraction pass with limited validation
If Claude miscategorises a skill, assigns the wrong canonical key, or drops a constraint, there is no correction pass. The regex hints cover salary and office days — the two highest-stakes cases — but other extraction errors are silent. There is no confidence threshold below which extractions are excluded (the confidence field is surfaced in the UI but doesn't gate the pipeline).

### Static candidate pool
Candidates are processed at startup from a static `candidates.json` file. There is no API to add, update, or remove candidates without restarting the server. A production system would need a dynamic ingestion pipeline.

---

## 5. Extensions

### 5.1 Learned weights (highest value)
The most impactful near-term extension. Once hiring outcomes are available (hired=1, rejected=0 per candidate-job pair), the 10-dimensional feature vector can be used as input to a logistic regression or gradient-boosted model. The current hand-tuned weights serve as a warm-start prior. This would also validate — or challenge — current assumptions about which features matter most.

### 5.2 Expanded canonical key vocabulary + constraint versioning
The vocabulary should be treated as a versioned artefact, not hardcoded strings. New keys should be addable via configuration, with the constraint engine auto-loading operator-pair logic from a registry. This would allow domain-specific vocabularies (legal, medical, academic) without code changes.

### 5.3 Bilateral elimination
The constraint engine should run in both directions: if a candidate has a hard constraint that the JD doesn't address, that should contribute to an elimination decision (or at minimum, a ranked penalty), not just a surface-level flag. This requires reasoning about what the employer would likely say about unstated constraints.

### 5.4 Dynamic candidate ingestion
A background ingestion pipeline that watches for new candidate documents, processes them asynchronously, and updates the store without downtime. The caching infrastructure (`CandidateStore`) already supports this pattern — it needs an ingestion endpoint and a queue.

### 5.5 Multi-job ranking (candidate perspective)
Invert the query: given a candidate, return the best-matching jobs from a pool. The pipeline is symmetric — JD and candidate embeddings are both produced from natural-language summaries using the same model — so retrieval works in both directions with minimal changes.

### 5.6 Confidence-gated extraction
Constraints below a confidence threshold (e.g. < 0.65) should be excluded from the constraint engine and surfaced only as UI annotations. Currently all extracted constraints enter the engine regardless of confidence. A low-confidence hard constraint can silently distort elimination decisions.

### 5.7 Explanation grounding verification
The explanation layer instructs Claude not to invent constraint issues, but this is not verified. A lightweight post-processing step could check that every claim in the explanation maps to a specific feature value or constraint match result, and strip unsupported assertions.

### 5.8 Structured evaluation harness
`ground_truth.json` and `GET /evaluate/{job_id}` provide Kendall's tau and NDCG@5 against hand-labelled rankings. This should be extended into a regression test suite that runs on every model or prompt change, so extraction quality and ranking accuracy can be tracked over time rather than assessed ad hoc.

---

## 6. Tech Stack

| Layer | Technology | Why |
|---|---|---|
| LLM extraction + explanation | Anthropic Claude Haiku | Forced tool use guarantees typed output; fast and cheap for extraction tasks |
| Embeddings | OpenAI text-embedding-3-small | 1536 dims; strong semantic discrimination; competitive cost |
| Scoring | Python + NumPy | Simple, inspectable, traceable — no black-box ML layer |
| API | FastAPI | Async, streaming (SSE), clean separation from business logic |
| UI | React + Vite | Served as static SPA from the same FastAPI process in production |
| Deployment | Railway (Docker) | `railway.toml` + `Dockerfile` in repo |

---

## 7. Technical Demo Walkthrough

This section traces a single candidate and a single job description through every transformation in the pipeline, showing the data state at each stage.

### Stage 0 — Raw inputs

**Candidate raw data** (`candidates.json` entry):
```
id: "cand_042"
name: "Priya Sharma"
cv: "Senior Data Engineer at Monzo... 7 years experience... Python, Spark, dbt,
     Airflow... £110,000 salary expectation... fully remote — non-negotiable..."
linkedin: "Senior Data Engineer | Fintech | 7 yrs | London → Remote"
interview_transcript: "...I need at least £105k. I won't do more than one day
                       in the office per month..."
```

**Job description** (raw text posted to `POST /recommend`):
```
"Senior Data Engineer — FinTech Scale-up. Must have Python and dbt.
 Airflow experience preferred. 5 days/week in our London office.
 Salary up to £100,000. Visa sponsorship not available."
```

---

### Stage 1 — Regex pre-scan (offline, candidate only)

Before the LLM sees the candidate text, `_build_hint_block()` scans all three source documents with regular expressions:

```
_MONEY_RE  → finds: £110,000 (CV), £105,000 (transcript)
_OFFICE_DAYS_RE → no match
_REMOTE_RE → finds: "fully remote" (CV)
```

This produces a HINTS block injected into the LLM prompt:
```
HINTS (from automated text scan — do NOT omit these from constraints):
  SALARY FIGURES DETECTED: £110,000 (CV), £105,000 (transcript) — MUST appear as salary_min
  OFFICE/REMOTE: fully remote preference/requirement (CV) — MUST appear as office_days_per_week or remote_ok
```

The hints act as a guard: if the LLM would otherwise miss a numeric constraint buried in prose, the hint forces it to include it.

---

### Stage 2 — LLM extraction (forced tool use)

**Claude Haiku** receives the concatenated sources and the hint block, with `tool_choice: {type: "tool", name: "extract_candidate_full"}`. The API call is forced to return a typed JSON payload — not free text, not JSON mode, but a validated tool-use response.

The candidate is parsed into a structured `Candidate` object:

```json
{
  "id": "cand_042",
  "name": "Priya Sharma",
  "years_experience": 7.0,
  "seniority_level": "senior",
  "skills": ["Python", "Apache Spark", "dbt", "Airflow", "SQL"],
  "industries": ["Fintech", "Banking"],
  "management_experience": false,
  "career_trajectory": "ascending",
  "interview_score": 0.82,
  "culture_fit_score": 0.75,
  "constraints": [
    {
      "canonical_key": "salary_min", "type": "hard", "operator": "min",
      "value": 105000, "currency": "GBP", "confidence": 0.97,
      "description": "Minimum salary £105,000 (stated in interview)"
    },
    {
      "canonical_key": "office_days_per_week", "type": "hard", "operator": "max",
      "value": 0, "confidence": 0.95,
      "description": "Requires fully remote; max 0 days in office"
    }
  ]
}
```

The JD is similarly extracted to a `JobDescription` object with `required_skills: ["Python", "dbt"]`, `preferred_skills: ["Airflow"]`, `seniority: "senior"`, and constraints including `salary_max: 100000` and `office_days_per_week requires 5`.

---

### Stage 3 — Embedding

The structured `Candidate` object is serialised into a search-optimised natural-language string by `candidate_to_search_text()`:

```
"Priya Sharma — senior with 7 years of experience. Skills: Python, Apache Spark,
 dbt, Airflow, SQL. Industries: Fintech, Banking. Minimum salary £105,000 (stated
 in interview). Requires fully remote; max 0 days in office."
```

This string (not the raw CV) is sent to **OpenAI `text-embedding-3-small`**, which returns a 1536-dimensional float32 vector. The result is cached to `data/processed/cand_042.json` alongside the structured fields. On every subsequent startup, this file is loaded from disk if the source hash is unchanged — no LLM or embedding API call is made.

The JD follows an identical path at query time via `job_to_search_text()`, producing a mirrored summary that describes skills, seniority, and constraints in the same prose style. Mirroring the format is deliberate: it ensures JD and candidate embeddings land in comparable regions of the vector space.

---

### Stage 4 — Retrieval (cosine similarity over candidate matrix)

At query time, `CandidateStore.embedding_matrix()` returns all cached embeddings stacked into a numpy matrix of shape `(n_candidates, 1536)`. The JD is embedded once (1 API call), then:

```python
job_norm      = job_emb / ||job_emb||           # unit vector
normed_matrix = candidate_matrix / ||each row|| # unit vectors
scores        = normed_matrix @ job_norm         # dot product = cosine sim
```

This produces a vector of cosine similarities in a single matrix multiply — sub-millisecond for hundreds of candidates. Priya scores 0.71 (Python/dbt/Airflow + fintech background matches well). Candidates below 0.25 are dropped. The top-50 by score proceed to the constraint engine.

---

### Stage 5 — Constraint engine

For each of the JD's constraints, the engine checks against Priya's constraints in three phases:

| JD constraint | Matched to | Result |
|---|---|---|
| `office_days_per_week requires 5` | `office_days_per_week max 0` (canonical key match) | **Hard fail — eliminated** |
| `salary_max 100000` | `salary_min 105000` (canonical key cross-match) | **Hard fail — eliminated** |
| `visa_sponsorship requires false` | No candidate counterpart | Pass (no-match fallback) |

Priya is **eliminated** with two reasons. The constraint engine exits immediately on the first hard failure per constraint — no unnecessary computation on a candidate who has already failed.

For a candidate who passes all hard constraints, soft mismatches contribute to `soft_constraint_score` in the feature vector rather than elimination.

---

### Stage 6 — Feature vector and scoring (survivors only)

For candidates who pass constraint checks, `build_feature_vector()` computes 10 features:

```
required_skills_overlap  → 0.95  (Python ✓, dbt ✓ — both matched via embedding)
preferred_skills_overlap → 1.0   (Airflow ✓)
industry_preferred_match → 0.88  (Fintech is a strong semantic match to "financial services")
experience_delta         → 0.85  (7 years vs 5 minimum → surplus of 2: 0.5 + 0.5*(2/5))
seniority_match          → 1.0   (senior vs senior)
career_trajectory_score  → 0.85  (ascending)
interview_score          → 0.82
culture_fit_score        → 0.75
management_match         → 1.0   (role doesn't require management; candidate has none)
soft_constraint_score    → 0.92  (minor location preference mismatch only)
```

The final score is the weighted dot product of this vector with the weight profile:
```
score = 0.95×0.38 + 1.0×0.10 + 0.88×0.12 + 0.85×0.10 + 1.0×0.08 + ... ≈ 0.91
```

---

### Stage 7 — Explanation (top-10 only)

For the top-10 ranked survivors, Claude Haiku generates a 3-paragraph plain-prose recruiter note grounded in the feature vector and constraint match data. The prompt explicitly forbids inventing issues not present in the data. Eliminated candidates like Priya receive a deterministic string summary without an LLM call:

```
Eliminated: office/remote conflict (requires 0 days, role requires 5);
            salary conflict (min £105k, budget £100k)
```

All explanation calls run in parallel via `ThreadPoolExecutor`.

---

## 8. Embeddings and Cosine Similarity

### What is an embedding?

An **embedding model** maps variable-length text to a fixed-length dense vector of floats. `text-embedding-3-small` maps any input string to a **1536-dimensional** float32 vector. The key property is that semantically similar inputs produce geometrically close vectors: `"Apache Airflow"` and `"Airflow"` land near each other; `"Airflow"` and `"payroll processing"` land far apart — even though no keyword rule was written.

This is distinct from keyword matching (which fails on synonyms, abbreviations, and paraphrases) and from BM25 (which matches token overlap). Embeddings capture meaning, not surface form.

### How the text is prepared before embedding

Raw CV text is not embedded directly — it contains noise (formatting, dates, boilerplate) that degrades retrieval precision. Instead, a structured natural-language summary is constructed from the extracted `Candidate` object:

```
"Priya Sharma — senior with 7 years of experience. Skills: Python, Apache Spark,
 dbt, Airflow, SQL. Industries: Fintech, Banking. Requires fully remote..."
```

The JD is summarised in the same prose template. Mirroring the structure of both summaries means both vectors are generated in the same semantic register — essential for cosine similarity to be meaningful across the two sides.

### Domain anchoring for skill embeddings

Individual skill names are embedded with a `"skill: "` prefix when used in skill matching (scoring stage):

```python
_embed_cached("skill: airflow")  # anchors to skill namespace
```

Without the prefix, `"airflow"` alone might land in a region shared with meteorology terms. The prefix shifts the embedding towards the tooling/technology neighbourhood of the model's learned space. This improves discrimination between name variants vs genuinely different skills:

```
"skill: airflow" vs "skill: apache airflow"  → cosine 0.77  (same tool, should match)
"skill: pyspark" vs "skill: spark"           → cosine 0.79  (same ecosystem, should match)
"skill: python"  vs "skill: javascript"      → cosine 0.64  (different, should not match)
```

No alias table or domain-specific rules are needed.

### Cosine similarity: the maths

Cosine similarity between two vectors A and B is:

```
cos(A, B) = (A · B) / (||A|| × ||B||)
```

The numerator is the dot product (element-wise multiply then sum). The denominator normalises by each vector's magnitude, so only direction (not scale) matters. The result is in [-1, 1], but in practice text embedding similarities are in [0, 1] — negative values are rare and indicate strong semantic opposition.

**Why cosine rather than Euclidean distance?** Embedding vectors vary in magnitude based on token count and phrasing. A long CV and a short one represent the same candidate but their raw vectors have different norms. Cosine similarity ignores magnitude — it measures the angle between vectors, not their distance from the origin.

### Optimised batch computation (retrieval)

At retrieval time, all candidate embeddings are pre-loaded into a `(n_candidates, 1536)` numpy matrix. The JD vector is embedded once, then all `n` cosine similarities are computed in a single matrix operation:

```python
job_norm      = job_emb / ||job_emb||           # normalise JD once
normed_matrix = candidate_matrix / ||each row|| # normalise each candidate row
scores        = normed_matrix @ job_norm         # shape: (n_candidates,)
                                                 # dot product of unit vectors = cosine sim
```

This is O(n × 1536) additions — for 500 candidates it completes in under a millisecond on CPU. No approximate nearest-neighbour index is needed at current scale; a flat scan is exact and faster than the overhead of an ANN library.

### Where cosine similarity is used in this system

| Location | Inputs compared | Threshold | Purpose |
|---|---|---|---|
| Retrieval (`retrieval.py`) | JD summary vs candidate summary (1536-dim) | 0.25 floor | Discipline filtering — drop semantically irrelevant candidates before expensive stages |
| Skill matching (`scoring.py`) | `"skill: X"` vs `"skill: Y"` (1536-dim) | 0.75 to count as matched | Asymmetric recall: fraction of required skills the candidate possesses |
| Industry matching (`scoring.py`) | industry name vs industry name (1536-dim) | None (raw score averaged) | Semantic proximity between candidate background and preferred industries |
| Constraint semantic fallback (`constraint_engine.py`) | constraint description vs constraint description (1536-dim) | 0.75 matched / 0.55–0.75 flagged | Match employer constraints to candidate constraints when no canonical key is shared |

---

## 9. ML Concepts in Use

This system uses several established ML concepts. None require training a model from scratch — they are applied as inference-time techniques over pre-trained models.

### Dense retrieval (vector search)

Encoding both queries (JDs) and documents (candidates) as dense vectors, then ranking documents by cosine similarity to the query. This is the same principle used in modern semantic search systems (e.g. bi-encoder models). Here, the "documents" are candidate summaries and the "query" is the JD summary.

### Approximate nearest-neighbour search (conceptual)

The retrieval stage performs an exact flat scan over all candidate vectors. For a pool of hundreds to low thousands, this is faster and simpler than an ANN index. At larger scale (tens of thousands of candidates), this stage would be replaced with an ANN index (HNSW, IVF, etc.) to maintain sub-millisecond latency.

### Weighted linear scoring (feature engineering)

A 10-dimensional feature vector is constructed per candidate, then dotted with a weight vector to produce a scalar score. This is the simplest interpretable ranking model — equivalent to a linear regression with fixed (not learned) coefficients. Each feature's contribution to the final score is directly readable.

### Asymmetric recall

Skill coverage is measured as *recall from the job's perspective*: what fraction of the required skills does the candidate cover? Extra skills the candidate has don't penalise the score. This is distinct from Jaccard similarity (which penalises asymmetry) and precision (which would favour candidates who only know the required skills). Asymmetric recall is the right metric for "does the candidate meet the bar?" questions.

### Ordinal encoding

Seniority levels are mapped to integers on a 5-point scale (junior=1, mid=2, senior=3, lead=4, principal=5). The distance between a candidate's level and the JD's level is used as a feature. This treats seniority as ordered rather than categorical — a junior applying for a senior role is penalised more than a mid applying for the same role.

### Embedding-based semantic similarity as a soft classifier

Rather than hardcoding synonyms or using keyword rules, the system uses cosine similarity between embeddings as a continuous similarity score, then thresholds that score to make a binary decision (matched / not matched). The threshold is a hyperparameter (0.75 for skills, 0.75 for constraint semantic matching) set by inspection rather than trained from data.

### LRU caching of embedding calls

Skill and industry names are short, stable strings. The same skill ("Python", "dbt") appears in many candidates and many JDs. `@lru_cache(maxsize=512)` ensures each unique string is embedded at most once per server process lifetime — subsequent comparisons are pure numpy arithmetic with no API call.

### Weight suppression for missing data

When a candidate has no interview transcript, the `interview_score` and `culture_fit_score` weights are zeroed and redistributed to `required_skills_overlap` before normalising. This is a simple form of *data-availability-aware scoring* — avoiding the alternative of imputing a neutral 0.5 constant, which would make pre- and post-interview scores non-comparable and introduce non-discriminative noise.

### Constraint satisfaction as a hard filter

Before scoring, candidates are passed through a constraint engine that acts as a hard binary classifier: pass or eliminate. Only survivors enter the scoring model. This is analogous to the pre-filtering stage in recommendation systems (eligibility filters before ranking). Hard constraints eliminate; soft constraints contribute a continuous penalty to the `soft_constraint_score` feature.

### Few-shot prompting as in-context learning

The extraction prompts include 9 labelled examples covering explicit, implicit, ambiguous, and missing-data constraint cases. This is few-shot in-context learning: the model adapts its extraction behaviour to the target schema without fine-tuning. The examples are part of the system prompt, not the user message, so they are shared across all extraction calls.

---

## 10. Roadmap

The roadmap is organised into phases ordered by impact and complexity. Each phase builds on the previous one.

### Phase 1 (current) — Rule-based baseline

**Status:** Complete.

Hand-tuned weights, hardcoded thresholds, static canonical key vocabulary. Extraction via prompted LLM; scoring via deterministic Python. Evaluation via offline `ground_truth.json` and Kendall's tau / NDCG@5.

**Ceiling:** Scores reflect the assumptions encoded at build time. No mechanism to improve from usage data.

---

### Phase 2 — Domain genericisation (white-label foundation)

**Goal:** Make the system deployable in any matching domain without code changes — legal, medical, academic hiring, or any other context where two sides must be matched against structured constraints.

The primary blocker to white-labelling is the hardcoded canonical key vocabulary in `extraction.py`. The ~16 keys (`office_days_per_week`, `salary_min`, `visa_sponsorship`, etc.) are specific to general-purpose recruitment. A law firm deployment needs `bar_admission_jurisdiction`, `practice_area`, `partnership_track`. An academic deployment needs `publication_count_min`, `h_index_min`, `teaching_load_preference`. Right now, adding any of these requires editing source code.

**Changes required:**

- **Externalise the vocabulary** into a per-tenant configuration file (YAML/JSON). The extraction prompt's canonical key block is rendered from this config at request time — the LLM is given exactly the keys relevant to the domain.
- **Externalise operator-pair logic** into the same config. Each key declaration specifies its comparison type (numeric range, boolean, set membership, ordinal) so the constraint engine applies the correct logic without hardcoded special-casing. The existing cross-key rules (`salary_max` vs `salary_min`, `office_days_per_week` vs `remote_ok`) become first-class config entries rather than branches in Python.
- **Externalise the feature vector schema.** The 10 features and their weights are currently hardcoded in `scoring.py`. A config-driven feature registry would allow domain-specific features (e.g. `publications_match` for academic, `bar_admissions_match` for legal) to be added without code changes, each declaring its computation type (skill-coverage, ordinal-distance, binary, etc.) and default weight.
- **Externalise few-shot extraction examples** per tenant. The current 9 examples are recruitment-specific. Domain-specific examples are stored alongside the vocabulary config and injected into the system prompt.
- **Multi-tenant routing:** each API request carries a `tenant_id`; the server loads the corresponding config and runs the pipeline with that domain's vocabulary, features, and examples. Configs are loaded at startup and hot-reloaded on change.

**What stays unchanged:** the pipeline stages, constraint engine logic, embedding model, scoring architecture, and explanation layer. Only the *content* of prompts and the *definition* of constraint keys changes per tenant.

**Key metric:** A second domain (e.g. academic) fully operational from config alone, with zero Python changes.

---

### Phase 3 — Recruiter feedback capture

**Status:** Implemented (basic).

**Goal:** Capture recruiter decisions to create a labelled dataset for learning.

The recruiter curation workflow (Phase 3 UI) surfaces shortlist decisions as implicit labels. On "Send to Hirer", kept candidates get `outcome=1` and removed candidates get `outcome=0`; both are written as NDJSON records to `data/feedback.jsonl` via `POST /api/feedback`. Each record stores `{candidate_id, job_id, features[10], outcome, source}`.

Remaining gaps: `job_id` is currently empty (the streaming meta event doesn't include it), so feedback cannot be stratified by role type. Manually-added candidates are excluded from feedback because their feature vectors were not produced by the pipeline. The signal is binary (shortlist/remove) only — no reason codes.

**Key metric:** Number of labelled (feature_vector, outcome) pairs accumulated.

---

### Phase 4 — Learned feature weights

**Status:** Implemented (in-process retraining; synthetic training data only so far).

**Goal:** Replace hand-tuned weights with weights learned from recruiter outcomes.

`POST /api/retrain` loads `data/training_data.json` and `data/feedback.jsonl`, merges them, and trains both models in a FastAPI threadpool (sync, ~1–2s). Models are saved to `models/` and the in-process cache is invalidated via `clear_model_cache()` so the next pipeline call uses the updated weights. `POST /api/training-data/upload` accepts `.csv` or `.json` to augment the training set without retraining.

The current training data (500 synthetic records) was generated with deliberate non-linear structure so GBT outperforms logistic regression on the test set (AUC 0.865 vs 0.823, Brier score 0.062 vs 0.140). On real recruiter feedback the relative advantage may differ.

Remaining gaps: no minimum-record guard before retraining is exposed (current floor is 10, which is insufficient for a reliable model); no model versioning or rollback; no A/B evaluation comparing retrained vs baseline NDCG@5 on held-out jobs before the new model goes live.

**Key metric:** NDCG@5 on held-out jobs vs current hand-tuned baseline.

---

### Phase 5 — Active learning and online weight updates

**Goal:** Continuously update weights as new recruiter decisions arrive, without retraining from scratch.

- **Online logistic regression** (SGD with warm start): each new recruiter decision updates the weights incrementally — no batch retraining.
- **Exploration vs exploitation:** periodically surface a candidate outside the current top-10 to the recruiter ("why not this one?"). Their feedback expands coverage of the feature space.
- **Confidence-gated extraction:** constraints below a confidence threshold (< 0.65) are excluded from the constraint engine and surfaced as review flags instead of acting as hard eliminators. This reduces silent distortion from low-confidence extractions.

---

### Phase 6 — Bilateral constraint elimination

**Goal:** Enforce candidate-side hard constraints even when the employer hasn't stated a counterpart.

Currently the constraint engine iterates over employer constraints only. A candidate with `salary_min: £150k` is only eliminated if the employer has a `salary_max` that conflicts — if the employer hasn't stated a budget, the candidate passes through.

The fix: run the constraint engine in both directions. For each candidate hard constraint with no employer counterpart, model a probable employer response (e.g. "no salary stated → assume standard market range for this seniority"). Hard candidate constraints with no plausible employer match contribute a ranked penalty and a flag rather than a silent pass.

This is the most structurally complex change — it requires reasoning about unstated employer constraints, which needs either a rule-based prior or an LLM reasoning step.

---

### Phase 7 — Dynamic candidate ingestion

**Goal:** Remove the restart-to-update limitation.

The `CandidateStore` caching infrastructure (`source_hash` invalidation, `CACHE_SCHEMA_VERSION`) already supports incremental processing. What's missing is an ingestion API:

- `POST /candidates` — accepts raw candidate documents, queues processing.
- Background worker (asyncio task or Celery job) runs LLM extraction + embedding, writes to cache.
- Store exposes a reload-from-cache path callable without restarting the server.

New candidates become queryable within seconds of ingestion with no downtime.

---

### Phase 8 — Evaluation harness as a regression suite

**Goal:** Prevent regressions in extraction quality and ranking accuracy as prompts and models evolve.

- `ground_truth.json` and `GET /evaluate/{job_id}` already exist for ad-hoc evaluation.
- Extend into a CI-triggered regression suite: on every prompt or extraction schema change, run the full pipeline over a fixed evaluation set and compare Kendall's tau and NDCG@5 against a stored baseline.
- Add extraction unit tests: for a fixed set of raw texts with known constraints, assert that the extracted constraint list matches expectations.

This gates model/prompt changes behind measurable quality thresholds rather than subjective review.

---

### Phase 9 — Multi-job ranking (candidate perspective)

**Goal:** Invert the query direction — given a candidate, return best-fit jobs.

The pipeline is symmetric: both JD and candidate are represented as natural-language summaries embedded by the same model. Retrieval works in both directions with minimal changes. The primary additions needed are:

- A job pool store (analogous to `CandidateStore`) with cached JD embeddings.
- An inverted constraint engine pass (candidate constraints checked against job constraints).
- A "candidate dashboard" API and UI surface.

This is primarily an infrastructure addition, not a modelling change.

---

## 11. Implemented Extensions

This section documents features added after the Phase 1 baseline, covering recruiter workflow, hirer view, feedback capture, in-process retraining, and model observability.

---

### 11.1 Recruiter curation workflow

The results panel now functions as an editable shortlist rather than a read-only ranked list.

**Shortlist initialisation:** on receipt of the `meta` SSE event, the ranked candidates are copied into a `shortlist` state object (`ShortlistEntry[]`). Each entry wraps the `RankedCandidate` with `note: string`, `removed: boolean`, and `manuallyAdded: boolean`. The original `result` state is preserved for feature/constraint detail views; the shortlist drives what the recruiter sees.

**Editing controls (per card):**
- Up/down arrows reorder within the active (non-removed) shortlist.
- × removes a candidate in-place; the card stays visible at muted opacity with strikethrough name and an "Undo" link. This preserves rank context — the recruiter can see who was removed and where they sat.
- Note textarea (in expanded card body) adds a recruiter annotation passed through to the hirer view.

**Add from pipeline:** a collapsible panel at the bottom of the list shows all pipeline candidates (ranked + eliminated) not currently active in the shortlist, searchable by name. "Add" inserts them with `manuallyAdded: true`; these are excluded from feedback submission because their feature vectors were not produced by the standard pipeline path.

---

### 11.2 Hirer view

A separate "Hirer" tab shows a clean card grid containing only what a hirer needs to see. No feature breakdown, constraint table, pipeline step data, or model internals are exposed.

**Card contents:** name, seniority badge, top-5 skill pills, match score % with colour bar, recruiter note (highlighted if present).

**State transition:** "Send to Hirer" (button in the results panel header) builds the `HirerCandidate[]` array from kept shortlist entries, enriched with `seniority_level` and `skills` from the `candidatePool` map (fetched once on app mount via `GET /api/candidates`), then sets `tab = "hirer"`. The hirer view shows an empty state until this action fires.

---

### 11.3 Feedback API

`POST /api/feedback` accepts `{records: [{candidate_id, job_id, features: float[10], outcome: 0|1, source}]}` and appends each record as a NDJSON line to `data/feedback.jsonl`. Returns `{saved, total_feedback}`.

**Implicit labelling via "Send to Hirer":** the send action constructs feedback records automatically from non-manually-added shortlist entries — kept entries get `outcome=1`, removed entries get `outcome=0`. The submission is fire-and-forget (non-blocking). The recruiter's curation act is the labelling act; no separate annotation UI is needed.

**Known limitation:** `job_id` is currently `""` in all feedback records because the streaming `meta` event doesn't include it. This prevents per-role stratification of the training data. Fixing it requires either propagating `job_id` through the streaming pipeline or deriving it client-side from the job title.

---

### 11.4 Training data upload and in-process retraining

**Upload:** `POST /api/training-data/upload` accepts a multipart file in two formats:
- CSV with columns matching `FEATURE_ORDER` (10 features) plus `outcome`
- JSON with `{records: [{features: float[10], outcome: 0|1}]}` or a bare array

Records are appended to `data/training_data.json` with auto-incrementing IDs. Returns `{records_added, total_records}`.

**Retrain:** `POST /api/retrain` merges `training_data.json` and `feedback.jsonl`, performs an 80/20 train/test split (random_state=42 for reproducibility), and trains:
- `Pipeline(StandardScaler, LogisticRegression(C=1.0, lbfgs))` — interpretable, linear
- `Pipeline(StandardScaler, GradientBoostingClassifier(n_estimators=200, max_depth=4, lr=0.05))` — non-linear, captures feature interactions

Both models are evaluated for AUC-ROC, Brier score (MSE of predicted probabilities), and log loss on the held-out test split. Results are written to `models/metadata.json` alongside `trained_at`. New joblib files overwrite the previous models. `clear_model_cache()` invalidates the in-process model cache so the next pipeline call loads the updated weights.

The retrain runs synchronously in a FastAPI threadpool (~1–2s). Minimum record guard is 10 (insufficient for a reliable model in production; a practical minimum is ~200 per class).

**Model status and metrics:** `GET /api/model/status` returns `metadata.json` contents plus `feedback_count` and `training_data_count` (live counts from disk). `GET /api/model/metrics` loads both models and recomputes AUC, Brier score, and log loss against the same 80/20 split — useful when metrics are not in metadata (e.g. models trained by the original `scripts/train_models.py` which predates these fields).

---

### 11.5 Model observability ("How it works" tab)

A fourth tab provides a technical overview of the system for stakeholders and for debugging.

**Pipeline diagram:** five cards (Parse → Retrieve → Constrain → Score → Explain) with a one-sentence description of each stage's operation and cost profile.

**Model comparison table:** fetched from `GET /api/model/metrics`. Shows AUC-ROC, Brier score, and log loss for both models on the held-out test set, with the winning model highlighted per metric and a footnote explaining why GBT outperforms logistic on the current training data.

**Feature weight visualisation:** fetched from `GET /api/model/weights`. Both models are shown side-by-side with rows in the same order (sorted by GBT importance descending, applied to both cards so rows align). Logistic regression shows centre-anchored bidirectional bars (green = increases shortlisting probability, pink = reduces it) with raw coefficient values. GBT shows left-anchored bars with importance percentages.

**Model Training panel:** collapsible panel in the recruiter tab left column, visible after a pipeline run completes. Shows training/feedback record counts, last trained date, AUC/CV-AUC metrics table, file upload control, and retrain button with spinner. After retraining, shows a before/after AUC comparison with delta (e.g. `82.3% → 84.1% (+0.018)`) and a "Models reloaded" notice.
