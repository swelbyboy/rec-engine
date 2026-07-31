# Candidate Recommendation Engine

AI-powered candidate ranking system. Parses unstructured raw job descriptions and candidate documents (CV, LinkedIn, interview transcripts) through a pipeline, applies a constraint compatibility engine, and returns ranked, explainable candidate recommendations.

## This branch (`poc/live-matchmaking`): quick start with real candidate data

Everything below the next heading documents the original fixture-based PoC
(30 hand-written candidates). This branch is different — it runs the same
kind of pipeline against **real production candidates and job orders**, and
adds a UI to compare its output against Mind's own live reranker. This
section is the fastest path to running it locally; see [Live PoC
branch](#live-poc-poclive-matchmaking-branch) further down for the full
explanation of what's gitignored and why, and
[`CHANGES_VS_MIND_MAIN.md`](CHANGES_VS_MIND_MAIN.md) for the architecture.

```bash
# 1. Install deps
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# 2. Configure API keys + Supabase (this branch needs both, not just the two
#    fixture-PoC keys — see .env.example for the full annotated list)
cp .env.example .env
# fill in: ANTHROPIC_API_KEY, OPENAI_API_KEY, SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY

# 3. Build the candidate embedding index — NOT committed (data/live_index/
#    is gitignored, ~100MB of real-candidate-PII-derived .npz files), so
#    every fresh clone has to generate its own from live Supabase data.
#    First run embeds ~2,100 candidates via OpenAI — takes a few minutes and
#    costs real (small) API spend; reruns are incremental and fast.
python -m src.candidate_index build

# 4. Run the API (terminal 1)
uvicorn src.api:app --reload          # http://localhost:8000

# 5. Run the UI (terminal 2)
cd ui && npm install && npm run dev   # http://localhost:5173
```

Open `http://localhost:5173` — the **Live PoC** tab runs the live filtering
funnel; the **Analysis** tab compares rec-engine's output against Mind's own
production run for the same role.

## ML / data science concepts

This PoC demonstrateds a real ML pipeline that can be extended, not a keyword filter or UI wrapper. The core concepts:

**Embeddings & cosine similarity.** Every skill, industry, and job description is converted to a ~1536-dimensional vector (via OpenAI `text-embedding-3-small`) that captures _meaning_, not just characters. Two skills are compared by the angle between their vectors — "distributed systems" matches "distributed systems design" even with no string overlap; "Python" does _not_ match "Ruby" despite both being languages. A threshold of 0.75 cosine similarity is the minimum for a skill to count as matched.

**Vector retrieval (semantic search).** Candidate embeddings are pre-computed and cached. On each query, the JD is embedded once, then ranked by cosine similarity against the full candidate matrix in a single numpy operation.

**Feature engineering.** Each candidate is represented as a 10-dimensional feature vector: required/preferred skill overlap, experience delta, seniority match, career trajectory, industry match, interview/culture signals, constraint compliance. 

**Weighted linear model.** The final score is a weighted sum: `score = 0.38 × required_skills + 0.10 × preferred_skills + ...`. Interpretable by design — every score can be decomposed and explained. Weights for the PoC are hand-tuned, these would be 'learned' after applying historic recruitment training data.

**LLM as a structured extractor.** Claude is used for information extraction from unstructured data. A JD or CV is passed in; a typed JSON object comes out (skills, constraints, salary, seniority, discipline). This replaces determinisic rules and handles ambiguous phrasing automatically. 

**Retrieval-augmented ranking pipeline.** The overall architecture uses — Retrieve → Filter → Score → Explain. Each stage progressively reduces the candidate set with increasingly expensive operations: vector maths (top-50) → rule-based constraint filtering → linear scoring → LLM explanation (top-10 only). This staged design is what makes it fast enough to be interactive.

---

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

The API starts on `http://localhost:8000`. On first run it processes all 30 candidate fixtures in the background (LLM + embedding calls); subsequent runs load from cache instantly.

## Endpoints

| Method | Path                | Description                                            |
| ------ | ------------------- | ------------------------------------------------------ |
| `GET`  | `/health`           | Health check + fixture counts                          |
| `GET`  | `/jobs`             | List loaded job fixtures                               |
| `GET`  | `/candidates`       | List loaded candidate fixtures                         |
| `POST` | `/recommend`        | Rank candidates for a JD (JSON body)                   |
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
  "weights_used": { "required_skills_overlap": 0.28, "...": "..." }
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

| Feature                    | Default weight | Notes                                           |
| -------------------------- | -------------- | ----------------------------------------------- |
| `required_skills_overlap`  | 0.38           | Embedding cosine similarity, asymmetric recall  |
| `preferred_skills_overlap` | 0.10           | Same method as required                         |
| `industry_preferred_match` | 0.12           | Best semantic match across candidate industries |
| `experience_delta`         | 0.10           | `clip((years - min) / 5, 0, 1)`                 |
| `seniority_match`          | 0.08           | Binary: exact=1.0, else=0.5                     |
| `career_trajectory_score`  | 0.05           | ascending=1.0, lateral=0.6, mixed=0.4           |
| `interview_score`          | 0.03           | LLM-assessed proxy — reduced to limit bias risk |
| `culture_fit_score`        | 0.02           | LLM-assessed proxy — reduced to limit bias risk |
| `management_match`         | 0.04           | Binary: match=1.0, mismatch=0.3                 |
| `soft_constraint_score`    | 0.08           | Mean of compatible constraint match scores      |

---

## Live PoC (`poc/live-matchmaking` branch)

Everything above describes the original fixture-based PoC (30 hand-written
candidates, `/recommend`). This branch adds a second, separate pipeline that
runs against **real production data** — live candidates and job orders read
from Mothership's Supabase, filtered and ranked, and comparable side by side
against Mind's own production reranker in a small UI. The two pipelines
share code (`extraction.py`, the constraint engine, the models) but are
otherwise independent — the live pipeline lives in `funnel_rerank.py` /
`live_data.py` / `candidate_index.py`, not `store.py` / `scoring.py`.

For a full technical write-up of how the live pipeline works, how it
compares to Mind's production system, and the reasoning behind every
deviation, see **[`CHANGES_VS_MIND_MAIN.md`](CHANGES_VS_MIND_MAIN.md)** —
that's the source of truth for the architecture; this section is just setup.

### 1. Extra env vars

On top of `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` above, the live pipeline
needs Supabase credentials — nothing here works without them, including the
basic candidate fetch:

```bash
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SERVICE_ROLE_KEY=...   # service-role key, not anon — needed to read
                                 # the `mind` schema (Accept-Profile) for the
                                 # Mind Live/Fixed comparison
```

Same Supabase project Mind's own `.env` points at — ask whoever owns that
for the service-role key rather than generating a new one.

### 2. Build the local candidate embedding index

The live pipeline needs an embedding index over every eligible candidate
(currently ~2,100 people) to do retrieval, skill-floor scoring, and title
matching. **This index is not committed** — `data/live_index/` is
gitignored, for two reasons: it's ~100MB of `.npz` files that would bloat
every clone, and more importantly it's derived from real candidate PII
(names, CVs, embeddings of both), so it can't sit in a shared git history
the way code can.

Build it locally instead:

```bash
python -m src.candidate_index build
```

This fetches every eligible candidate from Supabase and embeds them via
OpenAI (`text-embedding-3-small`) — three separate embedding sets (general
search, title-only, constraint text). **The first run is a real cost and
takes a few minutes** (~2,100 candidates × 3 embedding calls); after that,
`build` is incremental — it only re-embeds candidates whose data actually
changed, so re-running it is fast and cheap. Add `--force` to re-embed
everyone from scratch if you ever suspect the cache is stale.

The API server calls `candidate_index.get_cached()` lazily on first use, so
you don't strictly have to run this before starting the server — but the
first `/recommend`-style request will then pay that same build cost
inline instead, which is a bad experience for a first request. Run it
up front.

### 3. Run the backend + UI together

```bash
# Terminal 1 — API (same command as the fixture PoC, port 8000)
uvicorn src.api:app --reload

# Terminal 2 — UI (Vite dev server, port 5173, proxies /api to :8000)
cd ui
npm install
npm run dev
```

Open `http://localhost:5173`. The **Live PoC** tab runs the full filtering
funnel against real candidates; the **Analysis** tab lets you pick a role
and compare rec-engine's output against Mind's own production run for the
same role side by side (see `CHANGES_VS_MIND_MAIN.md` for what each of the
variants shown there actually means).

### 4. What else is gitignored, and why

Also excluded, same PII reasoning as the embedding index — all regenerate
automatically as you use the tool, none of it needs to be seeded:

- `data/live_runs/` — persisted rec-engine PoC pipeline runs
- `data/llm_only_runs/` — persisted rec-engine LLM-only comparison runs

Mind Live/Fixed runs aren't persisted locally at all — they're read live
from Supabase on every request (`mind_run_store.py`), so there's nothing to
seed there either.

## Project structure

```
rec-engine/
├── data/
│   ├── candidates.json       # 30 candidate fixtures (raw free-text)
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
