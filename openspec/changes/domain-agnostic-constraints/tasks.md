## 1. extraction.py — Remove recruitment vocabulary

- [x] 1.1 Replace `CANONICAL_KEY_VOCABULARY` constant with `CONSTRAINT_KEY_GUIDANCE` — open-ended instruction to assign consistent snake_case canonical keys without a predefined list
- [x] 1.2 Update `JD_SYSTEM_PROMPT` to use `CONSTRAINT_KEY_GUIDANCE` instead of `CANONICAL_KEY_VOCABULARY` and replace "expert recruiter parsing job descriptions" with domain-neutral framing
- [x] 1.3 Update `CANDIDATE_SYSTEM_PROMPT` similarly — domain-neutral framing, `CONSTRAINT_KEY_GUIDANCE`
- [x] 1.4 Update `MERGE_SYSTEM_PROMPT` and `CANDIDATE_FULL_SYSTEM_PROMPT` to use `CONSTRAINT_KEY_GUIDANCE`

## 2. extraction.py — Generalise hint block

- [x] 2.1 Remove `_OFFICE_DAYS_RE` regex pattern and all references
- [x] 2.2 Remove `_REMOTE_RE` regex pattern and all references
- [x] 2.3 Remove `_find_office_hints()` helper function
- [x] 2.4 Update `_build_hint_block()` to only use `_MONEY_RE` / `_find_salary_hints()` — remove office/remote hint injection
- [x] 2.5 Update money hint message: replace "each MUST appear as a salary_min or salary_max constraint" with "each MUST appear as a compensation constraint with an appropriate canonical_key"

## 3. constraint_engine.py — Remove domain-specific constants

- [x] 3.1 Remove `CLEARANCE_KEYS` constant
- [x] 3.2 Remove `SALARY_CANONICAL_KEYS` constant
- [x] 3.3 Remove `CANONICAL_KEY_DISPLAY` dict

## 4. constraint_engine.py — Remove cross-pair logic

- [x] 4.1 Remove `_remote_office_cross_match()` function entirely
- [x] 4.2 Remove `SALARY_CROSS_PAIRS` and `REMOTE_CROSS_PAIRS` from `canonical_key_match()`
- [x] 4.3 Simplify `canonical_key_match()` to exact same-key matching only — remove cross-pair routing block
- [x] 4.4 Replace label lookup (`CANONICAL_KEY_DISPLAY.get(...)`) with `.replace("_", " ").title()` fallback (already present at line 324 as the else branch)

## 5. constraint_engine.py — Generalise remaining checks

- [x] 5.1 Update currency mismatch check: replace `employer_c.canonical_key in SALARY_CANONICAL_KEYS` with `employer_c.currency is not None or candidate_c.currency is not None`
- [x] 5.2 Update Phase 3 no-match fallback: remove clearance key special flagging (`flagged = emp_c.canonical_key in CLEARANCE_KEYS and ...`)

## 6. Verification

- [x] 6.1 Run `pytest tests/` — confirm no unit test regressions
- [ ] 6.2 Run `GET /api/evaluate/job-001`, `job-002`, `job-003` and confirm elimination counts match ground truth
