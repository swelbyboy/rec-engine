## ADDED Requirements

### Requirement: Match constraints via canonical key lookup
The system SHALL first attempt to match employer and candidate constraints that share the same `canonical_key` value. When a match is found, compatibility SHALL be determined by applying operator logic directly against the constraint values.

#### Scenario: Both sides share a canonical key and values are compatible
- **WHEN** the employer constraint is `office_days_per_week requires 3` and the candidate constraint is `office_days_per_week max 3`
- **THEN** the match result is `compatible: true` with `match_type: canonical_key`

#### Scenario: Both sides share a canonical key and values conflict
- **WHEN** the employer constraint is `office_days_per_week requires 5` and the candidate constraint is `office_days_per_week max 2`
- **THEN** the match result is `compatible: false`, `score: 0.0`, and the candidate is marked for elimination

---

### Requirement: Semantic fallback matching for unmatched constraints
The system SHALL use embedding cosine similarity to match employer and candidate constraints that have no shared `canonical_key`. A similarity threshold of > 0.75 SHALL be required to treat two constraints as addressing the same dimension. Pairs in the 0.55–0.75 band SHALL optionally trigger an LLM disambiguation call.

#### Scenario: Novel employer constraint matched semantically to candidate constraint
- **WHEN** the employer requires "UK SC clearance" and the candidate states "holds active government security clearance" with no shared canonical key
- **THEN** the system identifies these as addressing the same dimension via embedding similarity and evaluates compatibility

#### Scenario: No semantic match found for employer constraint
- **WHEN** an employer hard constraint has no matching candidate constraint (by canonical key or embedding)
- **THEN** the constraint is treated as compatible (candidate has not expressed a conflicting preference) with `match_type: no_candidate_constraint`

---

### Requirement: Hard constraint failure eliminates candidates
The system SHALL mark a candidate as `eliminated: true` when any hard employer constraint is incompatible with a hard candidate constraint, or when a hard employer constraint cannot be satisfied by the candidate's stated values.

#### Scenario: Hard constraint incompatibility on salary
- **WHEN** employer salary max is 85,000 and candidate salary min is 90,000
- **THEN** the candidate is eliminated with an elimination reason citing the salary conflict

#### Scenario: Multiple hard constraint failures
- **WHEN** a candidate fails two separate hard constraints
- **THEN** both failure reasons appear in `elimination_reasons` and the candidate is eliminated

---

### Requirement: Soft constraint mismatches apply score penalties
The system SHALL compute a partial compatibility score (0.0–1.0) for soft constraint pairs. Soft mismatches reduce the aggregate `soft_constraint_score` feature passed to the scoring model but do not eliminate candidates.

#### Scenario: Soft preference mismatch
- **WHEN** a candidate prefers a four-day week and the role does not offer it
- **THEN** the match result is `compatible: true` with a score < 1.0 reflecting the mismatch, and the candidate is not eliminated

#### Scenario: Soft preference match
- **WHEN** the employer prefers fintech background and the candidate has fintech experience
- **THEN** the match result is `compatible: true` with `score: 1.0` contributing positively to `soft_constraint_score`

---

### Requirement: Produce structured compatibility output per candidate
The system SHALL return a compatibility result object for each candidate containing: `eliminated`, `elimination_reasons`, `constraint_matches` (list of per-pair results), `unmatched_candidate_constraints`, and `flagged_for_review`.

#### Scenario: Candidate passes all hard constraints
- **WHEN** all hard constraint pairs are compatible
- **THEN** `eliminated: false` and `elimination_reasons` is an empty list

#### Scenario: Employer constraint with no candidate counterpart is flagged when clearance-type
- **WHEN** an employer hard constraint like `security_clearance` has no matching candidate constraint
- **THEN** the constraint ID appears in `flagged_for_review` rather than silently passing as compatible
