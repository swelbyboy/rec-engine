## Context

The constraint pipeline has two phases where domain assumptions are encoded:

1. **Extraction** (`extraction.py`): The LLM is given a 16-key recruitment vocabulary and told to map constraints to those keys. The regex pre-scan also hardcodes salary and employment-specific patterns. Without domain guidance the LLM still extracts constraints, but without key consistency across documents.

2. **Matching** (`constraint_engine.py`): Two cross-pair rules handle cases where the vocabulary assigned different keys to the same concept (`salary_max`/`salary_min`, `office_days_per_week`/`remote_ok`). These rules exist *because* the vocabulary introduced the divergence. Three recruitment-specific constants also hard-code display labels, clearance flagging, and currency-check key names.

The operator-pair logic and semantic fallback are already domain-agnostic and unchanged.

## Goals / Non-Goals

**Goals:**
- Constraint extraction works for any professional domain without source code changes
- Constraint matching degrades gracefully when canonical keys diverge (semantic fallback)
- No regression on existing recruitment evaluation benchmarks (Kendall's tau, NDCG@5)
- Money regex guard retained — compensation constraints are universal and high-stakes

**Non-Goals:**
- Per-tenant config files or multi-tenant routing (Phase 2 as originally scoped)
- Changing the `Candidate` or `JobDescription` Pydantic models (feature vector stays recruitment-specific for now)
- Retraining ML models (domain-specific models are addressed by retraining on domain data)
- Expanding the regex pre-scan to cover domain-specific numeric patterns (e.g., publication counts)

## Decisions

### Decision 1: Replace prescribed vocabulary with consistency guidance

**Choice:** Remove the 16-key enumeration and replace with an instruction to assign consistent, descriptive snake_case keys — "choose the label another LLM would independently produce for the same concept."

**Why:** The vocabulary's primary function is extraction guidance (telling the LLM what to look for). A domain-neutral instruction achieves this without domain-specific enumeration. The secondary function — ensuring key consistency across JD and candidate — is better achieved by the consistency instruction than by a fixed list, because the LLM in a new domain would pick whatever keys make sense and apply them consistently.

**Alternative considered:** Per-tenant YAML config files with domain-specific vocabularies. Rejected — the user doesn't need multi-tenant config; a single generic system is the goal.

### Decision 2: Remove REMOTE_CROSS_PAIRS via root cause, not symptom treatment

**Choice:** Remove the `remote_ok`/`office_days_per_week` cross-pair rather than replacing it with semantic fallback.

**Why:** The cross-pair exists because the prescribed vocabulary defined two different keys for one concept. Without a prescribed vocabulary, the LLM will assign the same key to both "5 days in office" and "requires fully remote" (both describe physical presence requirements). They then match on exact canonical key in Phase 1, making the cross-pair unnecessary.

**Risk:** If the LLM diverges (e.g., one document gets `weekly_office_days`, another gets `remote_work_allowed`), the semantic fallback handles it — descriptions about physical presence have similarity well above 0.75.

**Alternative considered:** Lower SEMANTIC_THRESHOLD from 0.75 to 0.65 to catch borderline cross-domain matches. Rejected — increases false positives across all constraint matching, not just this case.

### Decision 3: Remove SALARY_CROSS_PAIRS without replacement

**Choice:** Remove the `salary_max`/`salary_min` cross-pair; rely entirely on semantic fallback.

**Why:** Empirically, salary constraint descriptions have ≥0.82 cosine similarity and fall clearly above the 0.75 threshold. Semantic fallback correctly routes them to `_evaluate_operator_pair()` which applies the numeric comparison. No regression risk.

### Decision 4: Generalise currency mismatch check via field presence

**Choice:** Change `employer_c.canonical_key in SALARY_CANONICAL_KEYS` to `employer_c.currency is not None or candidate_c.currency is not None`.

**Why:** The check's intent is domain-agnostic — flag any constraint pair where currencies differ. Keying off specific key names was an implementation accident. Using the `currency` field directly is strictly more correct: any matched constraint with a currency field should trigger the check, regardless of what it's called.

### Decision 5: Remove hint block office/remote patterns; keep money

**Choice:** Remove `_OFFICE_DAYS_RE` and `_REMOTE_RE`; retain `_MONEY_RE` and hint logic.

**Why:** Money/compensation is a universal high-stakes constraint in all professional domains. Office/remote patterns are employment-specific and meaningless for academic or medical matching. The LLM reliably extracts explicit location constraints without regex hints; the regex guard was only added for salary figures where silent drops cause hard eliminations.

## Risks / Trade-offs

**[LLM key divergence across documents]** → The LLM may occasionally assign different keys to the same concept across JD and candidate (e.g., `minimum_salary` vs `salary_floor`). The semantic fallback handles this, but adds an embedding API call and reduces the confidence of the match. Mitigation: the consistency instruction ("another LLM would produce the same key") substantially reduces divergence.

**[Clearance constraints no longer auto-flagged]** → Hard employer security clearance requirements with no candidate counterpart previously triggered a review flag. After removal, they are treated as compatible with a standard no-match message. Mitigation: these are surfaced in `unmatched_candidate_constraints`, and the hard constraint with no counterpart is already a conservative pass (candidate hasn't stated they lack clearance).

**[Office/remote extraction without regex guard]** → For recruitment deployments, the LLM must extract office/remote constraints reliably without the regex pre-scan hint. These are typically explicit in job descriptions ("5 days per week in office") and consistently extracted. The money regex guard remains for the highest-stakes case.

**[Cache invalidation]** → Existing `data/processed/*.json` files contain recruitment-specific canonical keys extracted under the old vocabulary. They remain valid but new extractions on the same candidates will produce different (generic) keys. This is expected and desirable — operators running a new domain should clear the cache.

## Migration Plan

1. Apply code changes (extraction.py, constraint_engine.py)
2. Existing cached candidates continue to work — no forced re-extraction
3. To re-extract with generic keys: delete `data/processed/` and restart server
4. Run evaluation suite (`GET /api/evaluate/job-001,002,003`) to confirm no regression
5. Rollback: `git revert` to restore recruitment-specific vocabulary if needed
