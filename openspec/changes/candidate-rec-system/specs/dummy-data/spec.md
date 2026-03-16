## ADDED Requirements

### Requirement: Three job description fixtures covering distinct constraint profiles
The system SHALL include pre-generated JSON fixtures for three jobs:
1. **Fintech Data Engineer** — 5-day onsite London, no visa sponsorship, no management required, Python/SQL/dbt required
2. **Remote SaaS Product Manager** — fully remote, visa sponsorship available, strong B2B SaaS preference, management required
3. **Hybrid ML Engineer** — 2 days onsite, compressed hours available, security clearance preferred, Python/PyTorch required

#### Scenario: Fintech Data Engineer fixture loaded
- **WHEN** the system loads the Fintech Data Engineer fixture
- **THEN** it contains at least two hard constraints (`office_days_per_week: 5`, `visa_sponsorship: false`) and at least one soft constraint (industry preference)

#### Scenario: Hybrid ML Engineer fixture loaded
- **WHEN** the system loads the Hybrid ML Engineer fixture
- **THEN** it contains a soft constraint for `security_clearance` with `operator: prefers` and a soft constraint for compressed hours

---

### Requirement: Twenty candidate fixtures covering all system paths
The system SHALL include pre-generated JSON fixtures for 20 candidates distributed as follows:
- 2–3 strong matches per job (all dimensions align, pass hard constraints)
- 3 candidates eliminated by hard constraint failure (e.g. remote-only for onsite role, salary above max, requires visa sponsorship)
- 3 candidates with strong skills but soft mismatches (low score, not eliminated)
- 2 candidates with low-confidence constraints flagged for review
- 2 candidates with unusual novel constraints not in the canonical key vocabulary (e.g. "only works with B-corps", "requires sponsorship renewal within 12 months")
- Remainder: mid-tier candidates with mixed signals

Each candidate fixture SHALL include raw source text for all three input types:
- **CV** — 200–400 word plain-text CV covering work history, skills, and education
- **LinkedIn summary** — 100–150 word profile summary in first-person
- **Interview transcript** — 300–500 word excerpt of a structured interview, written as interviewer Q&A, covering motivations, working style preferences, salary expectations, and logistics (location, notice period, visa status). Constraints surfaced only in the transcript (not the CV) SHALL be present for at least 5 candidates, to exercise the multi-source merge path.

#### Scenario: Remote-only candidate applied to onsite role
- **WHEN** a remote-only candidate (office_days_per_week max 0) is matched against the Fintech Data Engineer job
- **THEN** the constraint engine eliminates the candidate with the office days conflict as the elimination reason

#### Scenario: Novel constraint candidate exercises semantic matching
- **WHEN** a candidate with a "B-corp only" constraint is matched against a job with no canonical key counterpart
- **THEN** the constraint engine uses embedding similarity to assess compatibility and the result appears in `constraint_matches` with `match_type: semantic`

#### Scenario: Low-confidence extraction flagged for review
- **WHEN** a candidate has a constraint with `confidence: 0.72`
- **THEN** it appears in the UI review flags and is included in the constraint engine output with a review indicator

#### Scenario: Constraint present only in interview transcript
- **WHEN** a candidate's salary expectation or visa requirement is stated only in the interview transcript and not in the CV or LinkedIn text
- **THEN** the merge step extracts it from the transcript source and it is present in the final candidate constraint list

---

### Requirement: Dummy data stored as importable JSON fixtures
All fixtures SHALL be stored as JSON files (or a Python module returning dicts) that the API backend loads at startup, enabling the demo to run without any external database or data entry.

#### Scenario: Application starts with fixtures loaded
- **WHEN** the FastAPI application starts
- **THEN** all 3 job fixtures and 20 candidate fixtures are available in memory and accessible via `GET /jobs` and `GET /candidates`
