# Fit-proxy report (`src/fit_proxy_report.py`)

A CLI tool that compares rec-engine PoC, rec-engine LLM-only, Mind Live, and
Mind Fixed on the same role using cheap, automatable, objective checks — not
a substitute for recruiter judgment, but a fast way to catch obvious
ranking-quality regressions across all four systems using one shared
definition.

## Why this exists, and what it deliberately doesn't prove

The real question — "does rec-engine recommend better-fit candidates than
Mind?" — needs either outcome data (placements, interview conversion) or
human judgment (a blind recruiter evaluation) to answer properly. Neither is
available cheaply right now: outcome sample sizes per role are too small to
be meaningful, and a blind evaluation needs real recruiter time to set up.

This tool is the layer in between: automatable, zero human time, but it only
proves (or disproves) whether each system's top-N candidates clear an
objective floor — not whether they're the *best* candidates. A candidate can
pass every check here and still be a mediocre recruiter call; a candidate
flagged here could still be a deliberate, defensible pick. Treat the output
as a regression/sanity signal, not a fit score.

## Method

For each role, the job's requirements are parsed **once**, fresh, via
`extraction.parse_job_description` — this is the report's own yardstick,
deliberately not any one system's self-reported score (Mind's
`reranker_score`, rec-engine's `verdict`), so no system is graded against its
own definitions. Every system's top-N candidates are then evaluated against
that single yardstick using the **exact same compliance logic already live
in `funnel_rerank.py`'s deterministic gates** — so "compliant" here literally
means "would survive rec-engine's own gates," applied uniformly to Mind's
candidates too, not a parallel metric invented just for this report.

## The four checks (`compute_candidate_fit`)

| Check | Reuses | Threshold | "No data" behavior |
|---|---|---|---|
| `skill_floor_ok` | `skill_match_detail_batch` | `SKILL_FLOOR_RATIO` (0.4) of required skills evidenced | no required skills → always passes |
| `experience_ok` | same delta logic as `_apply_experience_overqualification_check` | only checked when the role's own stated minimum is ≤ `EXPERIENCE_GATE_MAX_TARGET_YEARS` (3); tolerance `EXPERIENCE_ELIMINATION_YEARS` (6) | role states no minimum → always passes |
| `compensation_ok` | `_employer_salary_ceiling`, `_salary_over_ratio` | `COMPENSATION_ELIMINATION_RATIO` (0.30) above the role's ceiling | no ceiling or no candidate salary figure → always passes |
| `title_ok` | `_embed_title`, `_cosine`, same as `_apply_title_relevance_check` | `TITLE_RELEVANCE_FLOOR` (0.30) cosine similarity | either title embedding missing → always passes |

`fully_clean` = all four at once. It's the blunt, all-or-nothing composite —
failing even one dimension counts as not-clean, regardless of how well the
candidate does on the others.

**Not included: `working_model`.** Investigated live and found the
*general* constraint-engine path structurally broken for this dimension
(employer `office_days_per_week` never canonical-key-matches candidate
`working_arrangement`, and even a forced pairing evaluates as
compatible=True regardless of category/day-count). A real deterministic gate
now exists in rec-engine's own live pipeline
(`_apply_working_model_check`), but it hasn't been extended to this
cross-system report yet — would need the same reasoning applied to Mind's
`candidate_payload.workingModel` field.

## Where the data comes from, per system

- **rec-engine PoC / LLM-only**: top-N candidate IDs from the latest
  persisted run (`live_run_store` / `llm_only_run_store`), then the full
  `Candidate` object (skills, salary constraint, years) is re-fetched from
  the live embedding index (`candidate_index`) — the persisted run JSON only
  carries `matched_skills`/`missing_required_skills`/`years_experience`, not
  the raw data needed to recompute fit generically.
- **Mind Live / Mind Fixed**: top-N by `reranker_rank` from
  `mind.shortlist_run_candidates` (via `mind_run_store`), distinguished by
  `scorer_version` containing `"legacy-score"` (mirrors
  `ComparePanel.tsx`'s `isFixedScorerVersion`). Mind's lean
  `candidate_payload` snapshot (id/name/skills/yearsExp/salary/title) is
  adapted into rec-engine's own `Candidate` model
  (`mind_payload_to_candidate`) — including parsing Mind's salary display
  strings (`"~£100k"`, `"£100k+"`, `"~£145k"`) into a numeric constraint —
  so every downstream check runs byte-identical code regardless of source
  system.

**Eligibility is inherited, not re-applied.** The report does no filtering
of its own — it reads whatever pool each system already narrowed itself to
before ranking (rec-engine's `candidate_index`, built from
`_ELIGIBILITY_FILTER`; Mind's own "Available candidates" funnel + gates +
`computePool`). A ~8% gap was found live between the two systems' own
eligible-candidate reproductions — the report doesn't reconcile that, it
just reflects it.

## Output format

```
=== job_order_id=1409: Product Engineer @ CoLoop ===
Yardstick: mid-level, 2+ yrs, salary ceiling GBP90,000 (JD text), 4 required skills: Node.js, React, TypeScript, PostgreSQL

system                   n   avg skill cov    exp ok   comp ok  title ok   fully clean
rec-engine PoC          10             98%      100%      100%      100%          100%
rec-engine LLM-only     10            100%       10%       60%      100%           10%
Mind Live               10             90%       60%       80%      100%           60%
Mind Fixed              10             90%       70%       80%      100%           70%
```

The "Yardstick" line shows exactly what every system's candidates were
checked against for that role, including whether the salary ceiling came
from explicit JD-text ("JD text") or the ATS's own structured field
("Bullhorn field") — see `_employer_salary_ceiling`'s fallback logic.

Per-system columns: `n` = candidates actually evaluated (can be less than
top-N if a candidate ID wasn't resolvable — e.g. missing from
`candidate_index`); `avg skill cov` = mean required-skill coverage; the rest
are `pct_*_ok` from `_summarize`.

## Running it

```bash
# Specific roles:
python -m src.fit_proxy_report 1409 1596 1360 --top-n 10

# Every currently pinned/active Mind role (same source as the UI's job
# picker, live_data.fetch_active_mind_roles) — no need to list ids by hand:
python -m src.fit_proxy_report --all --top-n 10
```

Multiple job_order_ids (explicit or via `--all`) run sequentially; a failure
on one role (e.g. no Mind run exists yet) prints to stderr and doesn't stop
the rest. Needs a working `ANTHROPIC_API_KEY` (one JD parse + title
embeddings per role) and `SUPABASE_URL`/`SUPABASE_SERVICE_ROLE_KEY` (same
creds as the rest of the live pipeline).

Whenever more than one role actually succeeds, an `AGGREGATE across N
roles` table prints at the end — every role's rows pooled per system before
summarizing once. This is the same pattern used to produce every aggregate
number quoted in this session's work; no separate script needed anymore.

## Known limitations

- **JD extraction is non-deterministic between calls.** Two separate report
  runs against the same `job_order_id` can produce a different
  `required_skills` list (seen live on Calibre: 3 skills one run, 2 the
  next) — the yardstick itself has some run-to-run variance, independent of
  anything either matchmaking system does.
- **`salary_normalized`'s real meaning is unverified.** `live_data.py`
  labels it "desired salary," but nothing in Mothership's own schema
  confirms that's not sometimes *current* salary — relevant if a
  `compensation_ok` result looks surprising for a specific candidate.
- **Small `required_skills` lists make `skill_floor_ok` coarse and
  discipline-blind** — see the `SKILL_FLOOR_RATIO` comment in
  `funnel_rerank.py` for the live-found Calibre case. Flagged as a known
  edge case, not fixed.
- **Not proof of "better fit."** See the top of this doc — this measures
  "clears an objective floor," not "is the best candidate."
