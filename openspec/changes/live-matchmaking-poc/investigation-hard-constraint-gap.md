# Investigation: hard-constraint filtering never eliminates anyone

## Symptom

Running the live pipeline against LightWork AI's Platform/Backend Engineer role
(job_order_id 1650): **100 considered, 100 passed filter, 0 eliminated.** The
ranked output (29 candidates surfaced to the fine LLM rerank) includes two
Product Managers with zero backend engineering skills — correctly scored
"Weak match" by the rerank LLM, but they should never have passed the hard-
constraint filter stage at all.

This isn't noise — it's the constraint engine behaving exactly as built. See
below.

## Root cause

`_build_candidate_constraints` (`src/live_data.py:230`) only ever derives
candidate-side constraints from six Mothership fields:

```
salary_normalized · notice_days · working_model · requires_visa · deal_breakers[] · drivers[]
```

Meanwhile `extraction.py` pulls whatever the JD text emphasizes as hard
constraints — for this role: degree requirement, years experience, Node.js/
NestJS depth, lead-engineer ownership, "must code not just manage," AI-tools-
essential, startup comfort. **None of these have a same-shaped counterpart on
the candidate side.**

```
 EMPLOYER constraints (from JD text)          CANDIDATE constraints (from app.candidates)
 ─────────────────────────────────            ───────────────────────────────────────────
 degree requirement          ─┐                salary_normalized
 years experience             │  no symmetric   notice_days
 Node.js/NestJS depth         │  candidate-side  working_model
 lead-engineer ownership      │  constraint      requires_visa
 "must code, not just lead"   │  exists for      deal_breakers[]  (free text)
 AI-tools-essential           │  any of these    drivers[]        (free text)
 startup-comfort             ─┘
```

`run_constraint_engine`'s phase 3 is "no candidate constraint found →
**compatible = True**" (`constraint_engine.py:530-539` — the deliberate
"no-match-is-compatible" design from `design.md` decision 1). For each of the
seven employer hard constraints above:

1. **Canonical key match** fails — no candidate constraint shares that key.
2. **Semantic match** compares employer constraint text against the
   candidate's `deal_breakers`/`drivers` embeddings — a PM's deal-breakers
   ("no weekend work," "remote only") don't cosine-match "deep Node.js/NestJS
   expertise" above `SEMANTIC_THRESHOLD = 0.75`, so no match.
3. Falls through to **no-match → auto-compatible**.

So the engine has no data structure capable of expressing "this candidate
lacks Node.js expertise" — that only exists in `candidate.skills` (a plain
list), which `scoring.skill_match_detail_batch` reads for **informational
text** fed into the fine-rerank LLM prompt (`funnel_rerank.py`'s "Role skill
fit" line), but which `constraint_engine.py` never touches. Skill fit is
currently a ranking signal only — never a gate.

The one deterministic safety-net that *does* exist for this class of gap —
`_apply_location_visa_check`'s UK/visa check — also caught nothing on this
run because the coarse briefing returned `unclear`/`unclear` for this
particular job, not a definitive `yes`.

## The design tension

Mind's original manual gates conflated two different kinds of filtering.
`extraction.py` faithfully reproduces both kinds as "hard constraints" from
the JD text, but only one kind can actually be checked against candidate data
today:

```
                    ┌─────────────────────────────────────┐
                    │   "Hard constraint" as extracted     │
                    │   from unstructured JD text           │
                    └───────────────┬───────────────────────┘
                                    │
              ┌─────────────────────┴─────────────────────┐
              ▼                                             ▼
   structured, symmetric fields              free-text skill/seniority/culture claims
   (salary, notice, visa, location,           (Node.js depth, lead-engineer, degree,
    working model)                             "must code not just manage")
              │                                             │
              ▼                                             ▼
   candidate side has the SAME field →         candidate side has NO matching field →
   constraint engine can genuinely gate        engine defaults to compatible, always
```

## Options to realign on

- **A — Extend candidate constraints to cover skills/seniority/education
  symmetrically**, so the existing 3-phase engine can match+eliminate on
  these dimensions too. Keeps a single engine; costs more extraction work per
  candidate (latency/$).
- **B — Add a dedicated deterministic skill-gate**, same pattern as the
  UK/visa safety net: `job.required_skills` vs `candidate.skills` is already
  structured on both sides — no embedding ambiguity needed for a "does the
  candidate have ≥N of the required skills" hard check ahead of the LLM
  stages.
- **C — Rein in what `extraction.py` is allowed to call "hard"** — restrict
  hard constraints to dimensions with a real candidate-side signal (salary,
  location, visa, notice, clearance); demote skill/seniority/culture claims
  to soft signals; make the fine-rerank LLM's "MISSING REQUIRED" skill line
  authoritative (e.g. auto-cap verdict at `weak_match` when a required skill
  is missing) instead of relying on the model to weigh it correctly.
- **D — Hybrid**: B's cheap deterministic skill floor + C's tighter hard-
  constraint scope, leaving the LLM funnel purely for nuance, not gating.

## Prior art on `main`: this isn't a novel problem

Before committing to an option, checked `main` (this PoC branch's baseline).
`scoring.py::skill_coverage()` already solves "does this candidate evidence
the skills this JD wants" — embedding cosine similarity with a domain-
anchoring prefix (`"skill: {name}"`, not the bare string), threshold 0.75,
LRU-cached. No training data, no regression, no GBT:

```
skill: airflow  vs  skill: apache airflow  → 0.77  (same tool)
skill: pyspark  vs  skill: spark           → 0.79  (same ecosystem)
skill: python   vs  skill: javascript      → 0.64  (different)
```

The PoC branch already ported a batched variant of it —
`scoring.skill_match_detail_batch()` — which is what currently feeds the
"Role skill fit" / "MISSING REQUIRED" line in the fine-rerank prompt as
**display text only**.

On `main`, this same function is the single heaviest-weighted input to the
(pre-PoC) weighted-linear score:

```python
DEFAULT_WEIGHTS = {
    "required_skills_overlap": 0.38,   # ← skill_coverage(), largest weight by far
    "preferred_skills_overlap": 0.10,  # ← skill_coverage(), again
    "industry_preferred_match": 0.12,
    "experience_delta": 0.10,          # ordinal years-vs-minimum, not embedding
    "seniority_match": 0.08,           # ordinal ladder distance, not embedding
    ...
}
```

Also confirmed on `main`: `constraint_engine.py`'s hard-constraint gating was
**always** scoped to structured/symmetric fields only (checked the synthetic
fixture, `data/candidates.json` — candidate "constraints" there are
visa/salary/location/notice-shaped too, never skills). Skill-fit was never
meant to be a constraint-engine concern on `main`; it lived in the
weighted-linear scoring stage instead.

**Conclusion: this gap isn't a regression the PoC introduced.** Design.md
decision 2 dropped the weighted-linear scoring stage entirely (in favor of
the LLM funnel) without carrying forward skill-fit's role as the dominant,
hard-ish signal it always was. `skill_coverage`/`skill_match_detail_batch`
got demoted from "38% of the score" to "text the LLM may or may not weigh
correctly." Option B is really "put back something that already existed and
was already tuned," not a new mechanism.

## Does a skill-gate fit the LLM funnel architecture? Yes — confirmed

The pipeline already has this shape, and a skill gate slots into an existing
seam rather than a new one:

```
constraint_engine.py          coarse_role_brief()        _apply_location_visa_check()      fine_rerank()
(generic 3-phase gate)   ───▶  (LLM: summary +      ───▶  (DETERMINISTIC gate on     ───▶  (LLM: verdict +
 eliminates on hard             flex judgment +             is_uk/needs_sponsorship,          rationale, ranks
 salary/visa/notice/            uk/visa Q&A)                cross-checked against             the SURVIVORS —
 working-model matches)                                     coarse brief's answers)            order only)
```

`_apply_location_visa_check` is already a deterministic, structured-data gate
sitting between the generic constraint engine and the fine rerank — built for
exactly this reason: the generic engine structurally can't judge this
dimension, but the underlying data is clean enough to check directly. A
skill-coverage floor is the same shape of fix, one more dimension over.

It doesn't collide with design.md decision 2, because that decision rejected
weighted-linear/ML as the **ranking** mechanism ("the final candidate order
comes solely from this coarse-then-fine LLM funnel") — it's about who decides
*order*. A skill-coverage gate doesn't touch order, only inclusion, same as
the constraint engine and the UK/visa check already do:

```
                    ┌───────────────────────────────────────┐
                    │  decision 2's boundary: LLM owns ORDER │
                    └───────────────────────────────────────┘
  ELIMINATION (deterministic, binary)  │  RANKING (LLM, ordinal)
  ───────────────────────────────────  │  ─────────────────────
  constraint_engine.py                 │  fine_rerank()
  _apply_location_visa_check()         │
  proposed: skill-coverage floor  ◀────┼──── stays on this side, untouched
```

## Recommended direction

**Option B, implemented as a new deterministic stage mirroring
`_apply_location_visa_check`** — e.g. `_apply_skill_floor_check(job,
passed_candidates)` running `skill_match_detail_batch()` and eliminating
anyone below a required-skill-coverage threshold, inserted in
`funnel_rerank.py` alongside the existing UK/visa check.

Rejected alternative: teaching `constraint_engine.py` itself to special-case
skill-category employer constraints against `candidate.skills` directly.
Conceptually tidier (one engine, one place hard constraints are evaluated),
but breaks design.md decision 1's "reuse constraint engine unmodified" and
changes its contract (it only ever sees `Constraint` objects today, never raw
`candidate.skills`).

### Open question for planning

Exact threshold/shape of the gate still needs a decision:
- Coverage-ratio cutoff (e.g. eliminate below 50% required-skill coverage), vs.
- Any-single-miss cutoff (e.g. eliminate if any constraint explicitly marked
  `type=hard` / flagged "Rigid" by the coarse brief has zero evidenced skill
  overlap).

Which failure mode matters more — false negatives (a good candidate wrongly
gated out by a rigid skill check) vs. false positives (what's happening now:
nobody ever gated at all) — should drive that choice.
