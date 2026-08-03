# Candidate Recommendation Engine

AI-powered candidate ranking system. Parses unstructured raw job descriptions and candidate documents through a pipeline, applies a constraint compatibility engine, and returns ranked, explainable candidate recommendations.

**This branch (`poc/live-matchmaking`)** runs that pipeline against **real production candidates and job orders**, read live from Mothership's Supabase, and adds a UI to compare its output against Mind's own production reranker side by side. For the full technical write-up — how the live pipeline works, how it compares to Mind's production system, and the reasoning behind every deviation — see **[`CHANGES_VS_MIND_MAIN.md`](CHANGES_VS_MIND_MAIN.md)**; this README is setup only.

There's also an older, self-contained fixture-based demo (30 hand-written candidates, `/recommend`) still in this repo, unrelated to the live pipeline below — see [`docs/FIXTURE_POC.md`](docs/FIXTURE_POC.md) if you want that instead.

## Quick start

```bash
# 1. Install deps
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# 2. Configure API keys + Supabase
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

## Extra env vars this branch needs

On top of `ANTHROPIC_API_KEY` / `OPENAI_API_KEY`, the live pipeline needs
Supabase credentials — nothing here works without them, including the basic
candidate fetch:

```bash
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SERVICE_ROLE_KEY=...   # service-role key, not anon — needed to read
                                 # the `mind` schema (Accept-Profile) for the
                                 # Mind Live/Fixed comparison
```

Same Supabase project Mind's own `.env` points at — ask whoever owns that
for the service-role key rather than generating a new one.

## Building the local candidate embedding index

The live pipeline needs an embedding index over every eligible candidate
(currently ~2,100 people) to do retrieval, skill-floor scoring, and title
matching. **This index is not committed** — `data/live_index/` is
gitignored, for two reasons: it's ~100MB of `.npz` files that would bloat
every clone, and more importantly it's derived from real candidate PII
(names, CVs, embeddings of both), so it can't sit in a shared git history
the way code can.

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

## What else is gitignored, and why

Same PII reasoning as the embedding index — all regenerate automatically as
you use the tool, none of it needs to be seeded:

- `data/live_runs/` — persisted rec-engine PoC pipeline runs
- `data/llm_only_runs/` — persisted rec-engine LLM-only comparison runs

Mind Live/Fixed runs aren't persisted locally at all — they're read live
from Supabase on every request (`mind_run_store.py`), so there's nothing to
seed there either.

## Project structure

```
rec-engine/
├── CHANGES_VS_MIND_MAIN.md   # Architecture + Mind comparison — source of truth
├── data/
│   ├── live_index/           # Candidate embedding index (gitignored — see above)
│   ├── live_runs/            # Persisted rec-engine PoC runs (gitignored)
│   └── llm_only_runs/        # Persisted rec-engine LLM-only runs (gitignored)
├── src/
│   ├── models.py              # Pydantic data models
│   ├── extraction.py          # Claude tool-use extraction (JD + candidate)
│   ├── constraint_engine.py   # Canonical key + semantic constraint matching
│   ├── live_data.py           # Eligible candidate pool fetch (Supabase, eligibility filter)
│   ├── candidate_index.py     # Embedding index build/load (this file's `build` is the CLI entrypoint)
│   ├── funnel_rerank.py       # The live pipeline: gates, triage, fine-rerank, LLM-only variant
│   ├── live_run_store.py      # Persists rec-engine PoC runs
│   ├── llm_only_run_store.py  # Persists rec-engine LLM-only runs
│   ├── mind_run_store.py      # Reads Mind Live/Fixed runs (read-only, live Supabase)
│   ├── mind_rubric_store.py   # Reads Mind's per-role weighted rubric (mind.rubric_configs), injected into fine-rerank
│   └── api.py                 # FastAPI backend — /live/*, /llm-only/*, /recommend (fixture demo)
├── ui/                        # Vite + React comparison UI (Live PoC tab, Analysis tab)
├── docs/
│   └── FIXTURE_POC.md         # Docs for the older, unrelated fixture-based demo
├── tests/
├── pyproject.toml
└── .env.example
```
