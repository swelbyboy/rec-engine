## Purpose

Lets a completed live-matchmaking pipeline run be retrieved later — by run id
or as part of a job's run history — without re-running the pipeline, since a
full-universe run can take several minutes end to end.

## ADDED Requirements

### Requirement: Run results are persisted on completion
When a live pipeline run (job + candidate pool + coarse brief + ranked list +
eliminated list + counts) finishes, the system SHALL store the full result
under a unique run id before returning it to the caller.

#### Scenario: A completed run is retrievable afterward
- **WHEN** a live pipeline run for a job completes successfully
- **THEN** the full result (ranked candidates, eliminated candidates, coarse
  brief, counts) is retrievable by its run id without re-running the pipeline

### Requirement: Run history is listable per job
The system SHALL support listing prior runs for a given job, newest first,
including enough summary information (run id, timestamp, counts) to identify
which run to open without loading its full detail.

#### Scenario: Listing runs for a job with prior history
- **WHEN** a user requests run history for a job that has completed runs
- **THEN** the system returns those runs ordered newest-first, each with its
  run id, completion timestamp, and summary counts (considered/passed/ranked)

#### Scenario: Listing runs for a job with no prior history
- **WHEN** a user requests run history for a job that has never been run
- **THEN** the system returns an empty list, not an error

### Requirement: A specific run is fetchable by id
The system SHALL support fetching one persisted run's full result by its run
id, returning the same shape as the original run response.

#### Scenario: Fetching an existing run id
- **WHEN** a user requests a run by a run id that exists
- **THEN** the system returns that run's full ranked/eliminated/coarse-brief
  result

#### Scenario: Fetching a run id that does not exist
- **WHEN** a user requests a run by a run id that was never persisted (or has
  been removed)
- **THEN** the system returns a clear not-found error, not a crash or an
  empty/malformed result

### Requirement: Persisted runs survive process restart
Persisted run results SHALL be durable across a restart of the backend
process — not held only in in-memory state — so a run remains viewable after
a deploy, crash, or local dev server reload.

#### Scenario: Backend restarts after a run completes
- **WHEN** the backend process restarts after a run has been persisted
- **THEN** that run is still listable and fetchable after the restart
