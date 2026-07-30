## Purpose

Provides read-only access to live candidate and job data from Mothership's Supabase Postgres `app` schema, mapped into rec-engine's existing `Candidate` and `JobDescription` models, so the matchmaking pipeline can run against real production data instead of synthetic fixtures.

## ADDED Requirements

### Requirement: Read-only live candidate retrieval
The system SHALL retrieve candidate records from Mothership's `app.candidates` table (plus `app.candidate_employment_agg`, `app.candidate_education_agg`, `derived.cv_parsed`, and `derived.granola_notes`) via the same Supabase service-role credentials Mind uses, and map each into a rec-engine `Candidate` object.

#### Scenario: Fetching candidates for a role's pool
- **WHEN** the adapter is asked for the live candidate pool for a role
- **THEN** it SHALL return `Candidate` objects populated from the live tables, with `raw_cv`, `raw_linkedin`, and `raw_interview_transcript` sourced from `derived.cv_parsed`, candidate enrichment data, and `derived.granola_notes` respectively

### Requirement: Read-only live job retrieval
The system SHALL retrieve a job order's description and Bullhorn job briefing text from `app.bullhorn_job_orders` / `app.dim_job_order` and map it into a rec-engine `JobDescription` object.

#### Scenario: Fetching a job for matching
- **WHEN** the adapter is asked for a job by its Bullhorn job order ID
- **THEN** it SHALL return a `JobDescription` object whose `raw_text` includes both the job description and the associated Bullhorn job briefing text, when the briefing is present

### Requirement: No write access to Mothership
The adapter SHALL NOT write, update, or delete any data in Mothership's `raw`, `app`, `derived`, or any other Mothership-owned schema.

#### Scenario: Adapter invoked as part of a pipeline run
- **WHEN** the live-data adapter executes any read operation
- **THEN** no INSERT, UPDATE, or DELETE statement SHALL be issued against any Mothership schema

### Requirement: Missing data resilience
When a candidate or job record is missing an expected field, the adapter SHALL substitute an empty value rather than failing the fetch.

#### Scenario: Candidate with no parsed CV
- **WHEN** a candidate record has no corresponding row in `derived.cv_parsed`
- **THEN** the adapter SHALL populate `raw_cv` as an empty string and SHALL NOT raise an error
