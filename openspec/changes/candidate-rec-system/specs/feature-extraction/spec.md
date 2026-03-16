## ADDED Requirements

### Requirement: Parse job description into structured JSON
The system SHALL accept raw job description text and return a structured JD object conforming to the JD schema, including `title`, `required_skills`, `preferred_skills`, `min_years_experience`, `seniority`, `management_required`, `industries_preferred`, `industries_acceptable`, and a `constraints` array.

#### Scenario: Valid JD text is parsed successfully
- **WHEN** a raw JD text string is passed to the JD extraction function
- **THEN** the system returns a valid JD JSON object with all required fields populated and a non-empty `constraints` array

#### Scenario: JD text mentions no salary range
- **WHEN** the JD text contains no salary information
- **THEN** no salary constraint is added to the `constraints` array (system SHALL NOT infer missing data)

#### Scenario: JD text contains an implicit constraint
- **WHEN** the JD text contains a phrase like "fast-paced startup environment"
- **THEN** the system extracts a soft constraint of category `culture` with an appropriate description and confidence score

---

### Requirement: Parse candidate sources into structured JSON
The system SHALL accept one or more of CV text, LinkedIn text, and interview notes, and return a structured Candidate object conforming to the Candidate schema, including `years_experience`, `skills`, `industries`, `seniority_level`, `management_experience`, `education_level`, `career_trajectory`, `interview_score`, `culture_fit_score`, and a `constraints` array.

#### Scenario: All three candidate sources are provided
- **WHEN** CV, LinkedIn, and interview notes are all provided
- **THEN** the system makes separate extraction calls per source and a final merge call that deduplicates overlapping constraints

#### Scenario: Only CV is provided
- **WHEN** only CV text is provided (LinkedIn and notes are absent)
- **THEN** the system returns a valid Candidate object extracted from the CV alone, with missing source fields treated as absent (not inferred)

#### Scenario: Candidate states a salary expectation
- **WHEN** the CV or notes contain a salary expectation figure
- **THEN** the system extracts a hard constraint with `canonical_key: salary_min`, the numeric value, and `operator: min`

---

### Requirement: Assign confidence scores to all extracted constraints
The system SHALL include a `confidence` float (0.0–1.0) on every extracted constraint, representing the LLM's self-assessed certainty that the constraint was correctly extracted from the source text.

#### Scenario: Constraint is explicitly stated
- **WHEN** the source text contains a direct statement like "No visa sponsorship available"
- **THEN** the extracted constraint has `confidence >= 0.85`

#### Scenario: Constraint is ambiguous or inferred
- **WHEN** the source text is ambiguous (e.g. "we value work-life balance")
- **THEN** the extracted constraint has `confidence < 0.85` and is either flagged for review or excluded per the confidence threshold rules

---

### Requirement: Normalise constraints to canonical keys where possible
The system SHALL attempt to map extracted constraints to a shared canonical key vocabulary (e.g. `office_days_per_week`, `visa_sponsorship`, `salary_min`, `salary_max`, `four_day_week`, `security_clearance`). Where no canonical key applies, the raw description SHALL be preserved and the `canonical_key` field left null or set to a descriptive slug.

#### Scenario: Two equivalent expressions map to the same canonical key
- **WHEN** a JD says "must be in office full time" and a candidate says "max 2 days in office"
- **THEN** both constraints share `canonical_key: office_days_per_week` enabling direct operator comparison

#### Scenario: Novel constraint with no canonical key
- **WHEN** a candidate states "only works with B-corp certified companies"
- **THEN** the constraint is extracted with a descriptive slug as `canonical_key` and `confidence` reflecting extraction certainty; semantic matching handles it at runtime

---

### Requirement: Apply confidence threshold gating
The system SHALL gate constraint application based on confidence:
- `confidence >= 0.85`: applied automatically by the constraint engine
- `0.60 <= confidence < 0.85`: applied by the constraint engine AND flagged in the UI for human review
- `confidence < 0.60`: excluded from the constraint engine; surfaced as an uncertain extraction in the UI

#### Scenario: High-confidence constraint is applied automatically
- **WHEN** a constraint has `confidence: 0.97`
- **THEN** it is passed to the constraint engine without any review flag

#### Scenario: Low-confidence constraint is excluded
- **WHEN** a constraint has `confidence: 0.45`
- **THEN** it is excluded from the constraint engine and appears in the UI under "Uncertain Extractions"
