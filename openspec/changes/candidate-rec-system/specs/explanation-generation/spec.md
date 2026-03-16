## ADDED Requirements

### Requirement: Generate per-candidate LLM explanation for top-N candidates
The system SHALL pass each non-eliminated candidate's feature breakdown and constraint match results to the LLM and receive a human-readable rationale paragraph covering: skill match summary, experience delta, industry fit, interview signal, constraint analysis (hard passes, soft mismatches), and salary compatibility.

#### Scenario: Candidate with strong match and one soft mismatch
- **WHEN** a candidate scores highly but has one soft constraint mismatch (e.g. prefers four-day week, role does not offer it)
- **THEN** the explanation mentions the soft mismatch explicitly as a minor negative signal without recommending elimination

#### Scenario: Candidate with flagged constraint requiring review
- **WHEN** a candidate has a constraint flagged for human review (e.g. security clearance unconfirmed)
- **THEN** the explanation includes a "Flag for review" section noting the unresolved constraint

---

### Requirement: Include constraint analysis section in every explanation
The system SHALL structure explanations to include a dedicated "Constraint analysis" paragraph that lists: hard constraint outcomes (pass or fail reasoning), soft constraint outcomes (match or mismatch), and any constraints flagged for review.

#### Scenario: No constraint issues
- **WHEN** all hard constraints pass and no soft mismatches exist
- **THEN** the constraint analysis states "No hard constraint conflicts" and lists no soft mismatches

#### Scenario: Multiple soft mismatches
- **WHEN** a candidate has two soft constraint mismatches
- **THEN** both are listed individually in the constraint analysis with brief descriptions

---

### Requirement: Explanations are generated only for non-eliminated candidates
The system SHALL NOT generate full LLM explanations for eliminated candidates. Eliminated candidates SHALL receive a structured elimination reason string (from the constraint engine) rather than an LLM-generated narrative.

#### Scenario: Eliminated candidate
- **WHEN** a candidate is eliminated due to a hard constraint failure
- **THEN** the UI shows the structured elimination reason (e.g. "Candidate requires max 2 office days; role requires 5") without an LLM explanation call

#### Scenario: Top-N threshold
- **WHEN** the pipeline is configured to explain the top 10 candidates and 15 candidates pass constraints
- **THEN** LLM explanation calls are made for the top 10 by score only; candidates ranked 11–15 show score and feature breakdown without narrative
