## Purpose

Presents a completed live-matchmaking run's results in a layout and level of
per-candidate detail that lets a recruiter judge fit and act on a candidate
without re-reading raw pipeline output or opening Bullhorn separately to find
the candidate record.

## ADDED Requirements

### Requirement: Results view is split into a role pane and a candidates pane
The live results view SHALL present role/job details (title, company, coarse
brief summary, hard constraints and their flexibility judgment) and the
ranked candidate list as two distinct, simultaneously visible panes, rather
than a single combined panel.

#### Scenario: Viewing a completed run
- **WHEN** a user views a completed live pipeline run
- **THEN** role/job details are visible in one pane and the ranked candidate
  list is visible in a separate pane, both visible without switching views

### Requirement: Candidate cards show expanded fit detail
Each ranked candidate's card SHALL show, in addition to verdict and
rationale: matched and missing skills (from the pipeline's skill-fit
detail), years of experience, seniority level, and whether any constraint
match was flagged for review.

#### Scenario: Viewing a ranked candidate's card
- **WHEN** a user views a candidate card in the ranked results
- **THEN** the card shows the candidate's matched/missing skills, years of
  experience, seniority level, and flagged-for-review state, alongside the
  existing verdict and rationale

### Requirement: Candidate cards link to the Bullhorn record
Each ranked candidate's card SHALL display the candidate's Bullhorn ID and
provide a link that opens that candidate's record in Bullhorn.

#### Scenario: Viewing a candidate card
- **WHEN** a user views a candidate card in the ranked results
- **THEN** the card displays the candidate's Bullhorn ID

#### Scenario: Following the Bullhorn link
- **WHEN** a user activates the Bullhorn link on a candidate card
- **THEN** the candidate's record in Bullhorn opens
