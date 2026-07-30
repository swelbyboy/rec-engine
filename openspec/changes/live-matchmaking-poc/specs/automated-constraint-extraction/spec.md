## Purpose

Automatically derives structured, typed constraints for a job from its raw description and Bullhorn job briefing text using rec-engine's existing LLM extraction, removing the need for a recruiter to manually configure hard-cutoff gates before matching can run.

## ADDED Requirements

### Requirement: Constraint extraction from combined job text
The system SHALL extract a job's structured constraints from the combination of its raw Bullhorn description and its Bullhorn job briefing text, when briefing text is available.

#### Scenario: Job with both description and briefing
- **WHEN** a job has both a Bullhorn job order description and an associated job briefing
- **THEN** the extracted `JobDescription.constraints` SHALL reflect requirements present in either source

#### Scenario: Job with no briefing text
- **WHEN** a job has a description but no associated Bullhorn job briefing
- **THEN** the system SHALL still extract constraints from the description alone, without error

### Requirement: No manual gate configuration required
The pipeline SHALL NOT require a recruiter to manually specify hard-cutoff gate values (e.g. exact salary, experience, or notice-period thresholds) before constraints can be extracted and used for filtering.

#### Scenario: Running the pipeline for a new role
- **WHEN** a new job is submitted to the pipeline with only its description and briefing text
- **THEN** the system SHALL produce a usable set of constraints without any manually entered gate configuration

### Requirement: Constraint confidence and review flagging
Extracted constraints SHALL carry a confidence score, and constraints below the confidence threshold used by the constraint engine SHALL be eligible for the existing flagged-for-review path.

#### Scenario: Ambiguous requirement in the briefing
- **WHEN** the job briefing contains an ambiguous or vague requirement
- **THEN** the extracted constraint SHALL have a confidence score reflecting that ambiguity, allowing the downstream constraint engine to flag affected matches for review
