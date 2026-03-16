# Candidate Recommendation Engine

AI-powered candidate ranking system. Parses raw job descriptions and candidate documents (CV, LinkedIn, interview transcripts) through an LLM pipeline, applies a constraint compatibility engine, and returns ranked, explainable candidate recommendations.

## How it works

The system runs a 5-stage pipeline on each `/recommend` request:

```
[OFFLINE — on first load]
candidates.json (raw text)
  → regex pre-scan (salary, office hints)
  → Claude (Haiku) tool-use extraction → structured Candidate
  → OpenAI embed (text-embedding-3-small) → 1536-dim vector
  → cached to data/processed/<id>.json (invalidated by content hash)

[ON EACH REQUEST]
JD text
  ↓ 1. Claude (Haiku) tool-use → JobDescription (skills, constraints, seniority...)
  ↓ 2. OpenAI embed JD → cosine similarity over candidate matrix → top-K retrieved
  ↓ 3. Constraint engine (canonical key → semantic → no-match fallback) → eliminated / survived
  ↓ 4. Feature vector (10 dims, embedding-based skill/industry match) → weighted linear score
  ↓ 5. Claude (Haiku) → plain-prose recruiter explanation (top-N only)
  → JSON: ranked candidates + eliminated candidates + explanations
```

### Stage 1: Candidate store (offline)

On startup, `CandidateStore.load()` processes each raw candidate. Three free-text documents (CV, LinkedIn, interview transcript) are concatenated with section headers and sent to Claude in a single call using forced tool use. A regex pre-scan runs first to detect salary figures (£/$/€ + k notation) and office/remote mentions; detected values are injected as explicit HINTS the LLM must not omit. Results are cached by MD5 content hash — only new or changed candidates are reprocessed on subsequent runs.

### Stage 2: JD parsing

A single Claude call with forced tool use extracts: title, company, required/preferred skills, seniority, min years experience, management requirement, preferred industries, and a list of `Constraint` objects. Constraints are typed as `hard`/`soft`, assigned a `canonical_key` from a shared vocabulary (e.g. `office_days_per_week`, `salary_max`, `visa_sponsorship`), and given a `confidence` score. The system prompt includes few-shot examples covering explicit, implicit, and ambiguous cases.

### Stage 3: Semantic retrieval

The parsed JD is converted to a natural-language summary and embedded. Cosine similarity is computed over the full candidate embedding matrix in a single numpy operation. The top-K candidates (default 50) are passed to the constraint engine.

### Stage 4: Constraint engine

For each (employer constraint, candidate) pair, three matching strategies run in order:

1. **Canonical key match** — deterministic: if both sides share a `canonical_key`, compare values using operator-pair logic (`requires`/`max`/`min`/`prefers`/`excludes`/`one_of`). Hard failures on both sides eliminate the candidate.
2. **Semantic fallback** — if no canonical match, embed unmatched constraint descriptions and match by cosine similarity (threshold 0.75). Pairs in the 0.55–0.75 band are flagged for human review.
3. **No-match fallback** — if no candidate counterpart exists, treat as compatible (candidate hasn't expressed a conflicting preference). Security clearance constraints are flagged for review.

### Stage 5: Scoring

Non-eliminated candidates get a 10-feature vector. All skill and industry matching uses embedding cosine similarity with an LRU cache (zero extra API cost on repeated terms). The weighted linear sum (default weights sum to 1.0) produces a score in [0, 1]. Top-N candidates get LLM-generated recruiter assessments grounded strictly in the constraint match results. Eliminated candidates get structured string explanations without an LLM call.

## Setup

### 1. Install dependencies

Requires Python 3.11+.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

### 2. Configure API keys

```bash
cp .env.example .env
# Edit .env and fill in:
# ANTHROPIC_API_KEY=sk-ant-...   (extraction + explanation)
# OPENAI_API_KEY=sk-...          (embeddings for retrieval, skill/industry scoring, constraint semantic matching)
```

### 3. Run the API

```bash
uvicorn src.api:app --reload
```

The API starts on `http://localhost:8000`. On first run it processes all 20 candidate fixtures (LLM + embedding calls); subsequent runs load from cache instantly.

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Health check + fixture counts |
| `GET` | `/jobs` | List loaded job fixtures |
| `GET` | `/candidates` | List loaded candidate fixtures |
| `POST` | `/recommend` | Rank candidates for a JD (JSON body) |
| `POST` | `/recommend/upload` | Rank candidates for an uploaded JD (plain text or PDF) |

## Example: POST /recommend

```bash
curl -s -X POST http://localhost:8000/recommend \
  -H "Content-Type: application/json" \
  -d '{
    "jd_text": "Senior Data Engineer at Apex Fintech. 5 days onsite London. Python, SQL, dbt required. No visa sponsorship. Salary up to £85,000.",
    "top_n": 5
  }' | python3 -m json.tool
```

### Response shape

```json
{
  "job_id": "...",
  "job_title": "Senior Data Engineer",
  "retrieved_candidates": 20,
  "ranked_candidates": [
    {
      "rank": 1,
      "candidate_id": "cand-001",
      "name": "Priya Sharma",
      "score": 0.87,
      "explanation": "Priya is an exceptionally strong match for this senior data engineering role...",
      "feature_vector": {
        "required_skills_overlap": 0.92,
        "preferred_skills_overlap": 0.75,
        "industry_preferred_match": 0.88,
        "experience_delta": 0.4,
        "seniority_match": 1.0,
        "career_trajectory_score": 1.0,
        "interview_score": 0.85,
        "culture_fit_score": 0.8,
        "management_match": 0.3,
        "soft_constraint_score": 1.0
      },
      "flagged_for_review": [],
      "constraint_matches": [
        {
          "match_type": "canonical_key",
          "compatible": true,
          "score": 1.0,
          "reason": "Canonical key match on 'office_days_per_week': employer requires 5 vs candidate requires 5",
          "flagged": false
        }
      ]
    }
  ],
  "eliminated_candidates": [
    {
      "candidate_id": "cand-007",
      "name": "Marco Bellini",
      "elimination_reason": "ELIMINATED — Hard constraint failures:\n  • Hard constraint failure on 'office_days_per_week': ..."
    }
  ],
  "weights_used": { "required_skills_overlap": 0.28, "..." : "..." }
}
```

## Example: POST /recommend/upload

```bash
curl -s -X POST http://localhost:8000/recommend/upload \
  -F "file=@path/to/job_description.txt" \
  -F "top_n=10" | python3 -m json.tool
```

PDF files are also accepted.

## Running tests

```bash
# Pure-Python tests (no API keys required)
pytest tests/test_scoring.py tests/test_constraints.py -v

# Integration tests (requires ANTHROPIC_API_KEY)
pytest tests/test_extraction.py -v -m integration
```

> **Note:** `test_scoring.py` contains tests for `build_feature_vector` (e.g. `test_industry_preferred_match_hit`) that call the OpenAI embeddings API. These require `OPENAI_API_KEY` to be set and will fail without it, despite not being marked `integration`.

## Custom weights

Adjust scoring emphasis without re-running LLM calls by passing a `weights` object:

```bash
curl -s -X POST http://localhost:8000/recommend \
  -H "Content-Type: application/json" \
  -d '{
    "jd_text": "...",
    "weights": {
      "required_skills_overlap": 0.40,
      "preferred_skills_overlap": 0.10,
      "industry_preferred_match": 0.08,
      "experience_delta": 0.10,
      "seniority_match": 0.08,
      "career_trajectory_score": 0.05,
      "interview_score": 0.10,
      "culture_fit_score": 0.04,
      "management_match": 0.03,
      "soft_constraint_score": 0.02
    }
  }'
```

Weights do not need to sum to 1.0 (the score is clamped to [0, 1]), but scores will be most interpretable when they do.

## Scoring model: feature weights (defaults)

| Feature | Default weight | Notes |
|---------|---------------|-------|
| `required_skills_overlap` | 0.28 | Embedding cosine similarity, asymmetric recall |
| `preferred_skills_overlap` | 0.10 | Same method as required |
| `industry_preferred_match` | 0.12 | Best semantic match across candidate industries |
| `experience_delta` | 0.10 | `clip((years - min) / 5, 0, 1)` |
| `seniority_match` | 0.08 | Binary: exact=1.0, else=0.5 |
| `career_trajectory_score` | 0.07 | ascending=1.0, lateral=0.6, mixed=0.4 |
| `interview_score` | 0.10 | LLM-inferred from transcript |
| `culture_fit_score` | 0.05 | LLM-inferred from transcript |
| `management_match` | 0.04 | Binary: match=1.0, mismatch=0.3 |
| `soft_constraint_score` | 0.06 | Mean of compatible constraint match scores |

## Project structure

```
rec-engine/
├── data/
│   ├── candidates.json       # 20 candidate fixtures (raw free-text)
│   ├── jobs.json             # 3 job fixtures (raw free-text)
│   └── processed/            # LLM extraction + embedding cache (auto-generated)
│       └── <id>.json
├── src/
│   ├── models.py             # Pydantic data models + DEFAULT_WEIGHTS
│   ├── extraction.py         # Claude tool-use extraction (JD + candidate)
│   ├── store.py              # Candidate store with content-hash caching
│   ├── retrieval.py          # OpenAI embedding retrieval (top-K by cosine sim)
│   ├── constraint_engine.py  # Canonical key + semantic constraint matching
│   ├── scoring.py            # Feature vector + weighted linear score
│   ├── explanation.py        # LLM recruiter explanation generation
│   └── api.py                # FastAPI backend
├── tests/
│   ├── test_scoring.py       # Scoring unit tests (some require OpenAI key)
│   ├── test_constraints.py   # Constraint engine unit tests (no API)
│   └── test_extraction.py    # Extraction integration tests (requires Anthropic key)
├── pyproject.toml
└── .env.example
```

## API cost profile (approximate, per `/recommend` request with 20 candidates)

| Stage | Model | Calls | Tokens (approx) |
|-------|-------|-------|-----------------|
| JD parsing | claude-haiku-4-5 | 1 | ~2k |
| JD embedding | text-embedding-3-small | 1 | ~200 |
| Constraint semantic matching | text-embedding-3-small | 1 batch/candidate | ~50–200 |
| Skill/industry scoring | text-embedding-3-small | cached | 0 (after first run) |
| Explanation (top-10) | claude-haiku-4-5 | 10 | ~10k total |
| **Candidate processing** | _(first run only)_ | 20 | ~1.5M input, ~40k output |
