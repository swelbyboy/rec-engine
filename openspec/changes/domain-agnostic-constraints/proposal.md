## Why

The constraint extraction and matching pipeline is hardcoded for recruitment — a 16-key vocabulary, employment-specific regex patterns, and cross-pair logic that assumes `salary_max`/`salary_min` and `office_days_per_week`/`remote_ok` as known dimensions. This blocks white-labelling the system for other professional matching domains (academic hiring, legal placement, medical staffing) without source code changes.

## What Changes

- **BREAKING** Remove `CANONICAL_KEY_VOCABULARY` (16 recruitment-specific keys) from `extraction.py` and replace with open-ended canonical key guidance that instructs the LLM to choose consistent, descriptive keys for any domain
- Remove `_OFFICE_DAYS_RE` and `_REMOTE_RE` regex patterns from `_build_hint_block()` (employment-specific); retain `_MONEY_RE` (universal)
- Update hint block messages to reference constraint categories generically rather than prescribing specific key names
- Update system prompt framing from "expert recruiter" to domain-neutral language
- Remove `CLEARANCE_KEYS`, `SALARY_CANONICAL_KEYS`, `CANONICAL_KEY_DISPLAY` constants from `constraint_engine.py`
- Remove `SALARY_CROSS_PAIRS`, `REMOTE_CROSS_PAIRS`, and `_remote_office_cross_match()` from `constraint_engine.py`
- Simplify `canonical_key_match()` to exact same-key matching only; cross-key pairs fall through to the existing semantic fallback
- Generalise currency mismatch check: trigger on presence of `currency` field rather than specific key names

## Capabilities

### New Capabilities

- `domain-agnostic-extraction`: Constraint extraction from unstructured text using LLM-assigned canonical keys with no predefined domain vocabulary
- `domain-agnostic-matching`: Constraint compatibility matching that works for any canonical key pair via semantic fallback, with no hardcoded cross-pair rules

### Modified Capabilities

None — no existing spec files to delta against.

## Impact

- `src/extraction.py` — vocabulary constant, regex helpers, `_build_hint_block()`, system prompts
- `src/constraint_engine.py` — constants, `_remote_office_cross_match()`, `canonical_key_match()`, Phase 3 no-match fallback
- Existing processed candidate cache (`data/processed/*.json`) — cached constraints used recruitment keys; cache will remain valid but future re-extractions will produce domain-agnostic keys
- No API surface changes — `Constraint.canonical_key` remains a nullable string field; callers unaffected
- No model or scoring changes
