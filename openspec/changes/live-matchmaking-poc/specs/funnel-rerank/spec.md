## Purpose

Ranks the constraint-engine-filtered candidate pool using a two-stage LLM process — coarse requirement extraction then fine-grained rerank — mirroring Mind's current matching model, producing recruiter-facing verdicts and rationale in place of rec-engine's default weighted-linear/ML scoring.

## ADDED Requirements

### Requirement: Coarse requirement/flexibility extraction
The system SHALL derive coarse role requirements and flexibility signals from the job's extracted data before ranking candidates.

#### Scenario: Preparing to rank a filtered pool
- **WHEN** the constraint-engine-filtered candidate pool for a job is ready to be ranked
- **THEN** the system SHALL first produce a coarse summary of the role's requirements and flexibility signals used to guide ranking

### Requirement: Fine-grained rerank with verdicts
The system SHALL rerank the filtered candidate pool using an LLM call informed by the coarse requirements, producing an ordered list where each candidate has a verdict and a rationale string.

#### Scenario: Ranking a filtered pool
- **WHEN** the fine-grained rerank stage runs on a constraint-engine-filtered pool
- **THEN** it SHALL return candidates ordered by fit, each with a verdict label and a human-readable rationale grounded in the candidate's constraint match and coarse requirement fit

### Requirement: Weighted-linear/ML scoring not used
This ranking path SHALL NOT use rec-engine's weighted-linear scoring model or any trained ML model to determine candidate order.

#### Scenario: Running the live matchmaking pipeline
- **WHEN** a job is ranked through the live matchmaking pipeline
- **THEN** the final candidate order SHALL be determined solely by the coarse-then-fine LLM funnel, not by the weighted-linear or ML scoring modules

### Requirement: Elimination reasons preserved
Candidates eliminated by the constraint engine before reaching the rerank stage SHALL retain their elimination reasons for recruiter visibility.

#### Scenario: A candidate fails a hard constraint
- **WHEN** a candidate is eliminated by the constraint engine (e.g. missing required work authorization)
- **THEN** the eliminated candidate SHALL be returned with elimination reasons intact, separate from the ranked list
