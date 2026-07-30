# rec-engine `poc/live-matchmaking` vs. Mind's `main`

This is a reference doc for anyone picking up this branch cold: what Mind's
production matching does today, what this branch does instead, and why. It's
a narrative comparison, not a git diff — Mind and rec-engine are separate
codebases with no shared history.

## Why this branch exists

Mind's candidate matchmaking regressed. The working hypothesis (see
`openspec/changes/live-matchmaking-poc/proposal.md`) is that a "gates-only
redesign" is the cause: 18 soft-matching signals that used to drive ranking
went dormant, candidates get filtered by brittle exact-match hard cutoffs,
and the order handed to the LLM reranker is driven by recency rather than
fit. This branch prototypes a fix — automated, semantic filtering feeding a
similarly-shaped LLM ranking funnel — against live production data, so it
can be judged side by side against what Mind produces today.

## Matching shape: today (Mind `main`) vs. this branch

| | Mind `main` | This branch |
|---|---|---|
| Candidate-side filtering | Manually configured gates, exact-match | Automated constraint extraction (`extraction.py`) + a 3-phase constraint engine: canonical-key match → semantic/embedding fallback → no-candidate-data-is-compatible |
| Skill fit | One of 18 soft signals, reportedly dormant post-redesign | A dedicated deterministic skill-floor gate (`_apply_skill_floor_check`, `SKILL_FLOOR_RATIO = 0.4`) — the constraint engine alone can't gate on skills at all, since candidate-side constraints are built from typed fields (salary/notice/visa/working-model), never skills |
| Title/discipline relevance | Implicit in the manual gates | An explicit, deliberately lenient gate (`_apply_title_relevance_check`) — title-only embedding similarity, low elimination floor, so a full-stack engineer still surfaces for a "Product Engineer" role; only catches genuinely wrong-discipline candidates |
| Candidate pool ordering into the LLM stage | Recency | Nothing — every candidate that clears the hard filters is either ranked by the LLM directly, or (above 100 candidates) coarsely triaged first; recency never enters into it |
| LLM ranking model | Haiku triage (cheap coarse bucketing) → Sonnet fine-rerank (rich per-candidate scoring) | Same two-stage shape, ported directly: Haiku triage (`triage_candidates`, `TRIAGE_TOP_N = 100`, same cutover threshold Mind uses) → Sonnet fine-rerank (`FINE_RERANK_MODEL`) |
| Handling large pools in the fine-rerank stage | Fixed-size batches (`RERANK_BATCH_SIZE = 50`), serial calls, merge by absolute score | Fixed-size batches (`RERANK_BATCH_SIZE = 40`), serial calls, merge by verdict-tier + skill-coverage tiebreak (no absolute-score rubric needed — see below) |
| Data source | `app.bullhorn_candidates` (older, narrower table) | `app.candidates` (newer 89-col gold table, hourly-refreshed) — wider data Mind hasn't adopted yet |

## Why each deviation from a straight Mind port

**Constraint extraction + 3-phase engine, not manual gates.** Manual gates
are exactly what's suspected of causing the regression (brittle exact-match,
easy to silently misconfigure). Automated extraction from JD + briefing text
means no manual gate configuration is needed at all, and the constraint
engine's semantic fallback catches phrasing variance a manual gate would
miss (confirmed live: nuanced deal-breakers like commute limits and
ethical/company-type exclusions matched correctly that an exact-match gate
would likely miss).

**A dedicated skill-floor gate.** Investigated and confirmed (see
`openspec/changes/live-matchmaking-poc/investigation-hard-constraint-gap.md`)
that the constraint engine structurally cannot gate on skill fit — candidate-
side constraints never include skills, so the engine's own "no candidate
constraint found → compatible" default let every candidate through
regardless of stack match. This isn't a new mechanism so much as restoring
something that was already load-bearing pre-redesign: on `main`,
`skill_coverage()`/`required_skills_overlap` was the single heaviest-weighted
signal (38%) in the weighted-linear scorer this PoC's funnel replaces.

**A lenient title/discipline gate, separate from the skill floor.** Nothing
else in the live pipeline checks title/discipline relevance at all —
`retrieval.py`'s general JD-vs-bio embedding similarity was deliberately kept
out of the pre-filter path (it conflates skills/constraints wording with
title, and was found in testing to drop genuinely qualified candidates
before their real constraints were even checked). This gate is narrower on
purpose: title text only, and a low floor so it only catches extreme
mismatches, never an adjacent discipline.

**Porting Mind's Haiku-triage-then-Sonnet-fine-rerank shape, not
reinventing it.** Confirmed by reading Mind's actual production rerank
(`mind/apps/web/src/lib/reranks/`) that a single LLM call over a large pool
isn't how Mind handles scale either — a fixed max_tokens-scaling formula
(this branch's original approach) hits Anthropic's output ceiling around
~32 candidates regardless of model. Mind's fix (fixed batch size + serial
calls, not concurrent — a prior production incident found concurrent
long-lived Sonnet streams starved the event loop) is the validated pattern,
so it's ported directly rather than re-derived. Also ported: fine-rerank
verdicts run on Sonnet, not Haiku — Mind's own reasoning ("Haiku's confidence
isn't calibrated enough for a fine score") applies directly, since this
branch's fine-rerank stage previously ran on the same single `LLM_MODEL`
(Haiku) used for extraction and coarse framing.

**Not ported: Mind's absolute/boost-only scoring rubric.** Mind's merge
across chunks only works because its score is an absolute 0-10 designed to
be comparable with zero shared context between chunks. This branch's
fine-rerank already produces a categorical verdict
(`strong_match`/`good_match`/`possible`/`weak_match`) judged against fixed
role criteria, not a batch-relative ranking — so merging by verdict tier,
then by already-computed skill-coverage count as a tiebreaker, is valid
without redesigning the scoring rubric or tool schema.

**Not ported: Mind's full repair-round machinery, dedicated rate-limit error
class, or per-call cost accounting.** Real production-hardening Mind needed
at its actual failure rate (50-60 candidates/call with rich multi-dimension
output actually truncated in production); this branch's shorter 2-3 sentence
rationale at a smaller batch size (40) stays well clear of that, so a
lighter touch (skip malformed/missing items into a flagged fallback, one
generic retry per chunk) covers this branch's actual exposure without
importing machinery a same-scope PoC doesn't need yet.

## Validated live, not just in theory

Both fixes were checked against real Mothership data, not just reasoned
about:

- **LightWork AI, Platform/Backend Engineer** (the original bug report,
  `job_order_id` 1650): full-universe run (17,664 candidates) completed in
  ~8.5 minutes post-fix, top 15 ranked candidates all showing 9-13 of 15
  required skills evidenced, sensible verdict tiering, 37 candidates cut by
  the title-relevance gate at 0.12-0.30 similarity (genuinely different
  disciplines).
- **Ankar AI, Product Engineer** (`job_order_id` 1360): same pattern — top
  candidates 5-6 of 6 required skills, no repeat of the "top-ranked survivor
  missing half the required stack" failure mode from the pre-fix baseline.
- The skill-floor threshold (`0.4`) was deliberately **not** raised despite
  looking loose on paper for short skill lists — fresh live runs didn't
  support tightening it once the real bottleneck (only 30 of 1,700+
  filter-passed candidates ever reaching the LLM stage, chosen by embedding
  similarity rather than real judgment) was fixed instead.

See `openspec/changes/live-matchmaking-poc/tasks.md` (section 9-10) for the
full tuning history and before/after numbers.
