## ADDED Requirements

### Requirement: Canonical key matching is exact-match only
`canonical_key_match()` SHALL match employer and candidate constraints only when both share the exact same `canonical_key` string. No hardcoded cross-pair rules SHALL exist. Constraints with different canonical keys (even if semantically related) SHALL fall through to semantic matching.

#### Scenario: Same-key pair matched directly
- **WHEN** employer has `canonical_key: "weekly_office_days"` and candidate has `canonical_key: "weekly_office_days"`
- **THEN** they are matched in Phase 1 and evaluated by operator-pair logic

#### Scenario: Different-key pair falls to semantic
- **WHEN** employer has `canonical_key: "salary_maximum"` and candidate has `canonical_key: "salary_minimum"`
- **THEN** Phase 1 returns no match and Phase 2 semantic fallback evaluates the pair

### Requirement: Currency mismatch check is field-driven
The currency mismatch flag SHALL trigger when either matched constraint has a non-null `currency` field, regardless of `canonical_key` name. The check SHALL NOT reference any specific key names.

#### Scenario: Non-salary constraint with currency field flagged
- **WHEN** two matched constraints have `currency: "GBP"` and `currency: "USD"` respectively
- **THEN** the match is flagged for review with a currency mismatch reason

#### Scenario: Constraint without currency field not flagged
- **WHEN** two matched constraints have `currency: null`
- **THEN** no currency mismatch flag is raised

### Requirement: No hardcoded domain-specific constants
`constraint_engine.py` SHALL NOT contain `CLEARANCE_KEYS`, `SALARY_CANONICAL_KEYS`, `CANONICAL_KEY_DISPLAY`, `SALARY_CROSS_PAIRS`, or `REMOTE_CROSS_PAIRS` constants. Display labels for canonical keys SHALL be derived from the key string itself (`.replace("_", " ").title()`).

#### Scenario: Unknown key displays readable label
- **WHEN** a constraint has `canonical_key: "bar_admission_jurisdiction"`
- **THEN** the displayed label is "Bar Admission Jurisdiction" (title-cased from key)

### Requirement: No-match fallback is domain-neutral
The Phase 3 no-match fallback SHALL treat all unmatched employer constraints uniformly — compatible with a standard reason string. No special flagging SHALL occur based on canonical key name.

#### Scenario: Hard employer constraint with no candidate counterpart
- **WHEN** an employer has a hard constraint and no candidate constraint matches it
- **THEN** the result is `compatible: True`, `match_type: no_candidate_constraint`, not flagged for review based on key name alone

#### Scenario: Low-confidence constraint still flagged
- **WHEN** a matched constraint has `confidence < 0.85`
- **THEN** it is flagged for review (confidence-based flagging is domain-agnostic and retained)
