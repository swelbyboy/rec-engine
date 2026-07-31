## Purpose

Lets a user compare rec-engine's PoC ranking for a role against Mind's own
persisted rerank runs for the same role — live production and, once
available, a fixed-branch run — side by side, without leaving rec-engine or
re-deriving Mind's output by hand.

## ADDED Requirements

### Requirement: Mind's persisted runs are listable per role
The system SHALL support listing Mind's past rerank runs for a given role
(read-only, from `mind.shortlist_runs`), newest first, with enough summary
information (run id, started-at timestamp, scorer version, created-by) to
distinguish which run is which without opening each one.

#### Scenario: Listing Mind runs for a role with history
- **WHEN** a user requests Mind's run history for a role that has completed
  Mind reranks
- **THEN** the system returns those runs ordered newest-first, each with its
  run id, start timestamp, and scorer version

#### Scenario: Listing Mind runs for a role with no history
- **WHEN** a user requests Mind's run history for a role Mind has never
  reranked
- **THEN** the system returns an empty list, not an error

### Requirement: A specific Mind run's candidates are fetchable
The system SHALL support fetching one Mind run's full candidate list
(read-only, from `mind.shortlist_run_candidates`) by run id, including each
candidate's reranker rank, score, tier, and available rationale
(strengths/concerns/signals).

#### Scenario: Fetching an existing Mind run
- **WHEN** a user requests a Mind run by a run id that exists
- **THEN** the system returns that run's full candidate list ordered by
  reranker rank

#### Scenario: Fetching a Mind run id that does not exist
- **WHEN** a user requests a Mind run by a run id that isn't in
  `mind.shortlist_runs`
- **THEN** the system returns a clear not-found error, not a crash

### Requirement: Three-column comparison view
The comparison view SHALL present, for a single selected role, three columns
side by side: rec-engine's PoC ranking, a selected Mind run ("Live"), and a
second selected Mind run ("Fixed") — each independently selectable via its
own run-picker, sharing one role selector across all three.

#### Scenario: Viewing the comparison for a role
- **WHEN** a user selects a role in the comparison view
- **THEN** all three columns scope to that role, each showing its own
  available runs to pick from independently

#### Scenario: A column has no available run
- **WHEN** a role has no rec-engine PoC run, or no Mind run, for one or more
  columns
- **THEN** that column shows an empty/prompt state rather than blocking the
  other columns from displaying their own data
