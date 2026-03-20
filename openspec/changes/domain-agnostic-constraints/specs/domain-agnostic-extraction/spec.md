## ADDED Requirements

### Requirement: LLM assigns domain-free canonical keys
The extraction system SHALL instruct the LLM to assign canonical keys without reference to any predefined domain vocabulary. The guidance SHALL tell the LLM to choose a consistent, descriptive snake_case key that another LLM given the same constraint would independently produce.

#### Scenario: Recruitment constraint receives natural key
- **WHEN** a job description contains "Salary up to £85,000"
- **THEN** the extracted constraint has a canonical_key describing a compensation maximum (e.g. `salary_maximum`) without requiring the key to be `salary_max` specifically

#### Scenario: Academic constraint receives natural key
- **WHEN** a job description contains "Minimum 5 peer-reviewed publications required"
- **THEN** the extracted constraint has a canonical_key describing a publication minimum (e.g. `publication_count_min`) without any code change

#### Scenario: Novel domain constraint with null key
- **WHEN** a constraint is purely qualitative with no clear dimension key
- **THEN** the extracted constraint has `canonical_key: null` and the description captures the full constraint text

### Requirement: Extraction prompt is domain-neutral
The system prompt for both JD and candidate extraction SHALL NOT reference recruitment-specific roles, titles, or domain vocabulary. The prompt SHALL use neutral framing ("extract structured requirements") that applies to any professional matching domain.

#### Scenario: Prompt works for non-recruitment document
- **WHEN** an academic CV is submitted for extraction
- **THEN** the extracted Candidate object contains constraints appropriate to academic hiring (e.g. teaching load preferences, publication requirements) without any code change

### Requirement: Money regex guard is domain-agnostic
The `_build_hint_block()` function SHALL retain regex detection of monetary figures using currency symbols (£, $, €) and inject them as hints. The hint message SHALL reference "compensation constraint" generically rather than prescribing specific canonical key names.

#### Scenario: Salary figure detected and injected as hint
- **WHEN** a candidate document contains "£90,000"
- **THEN** the hint block instructs the LLM that this figure must appear as a compensation constraint in the output

#### Scenario: No office/remote hint injected
- **WHEN** a job description contains "5 days per week in office"
- **THEN** no regex hint is injected; the LLM extracts this as a constraint from the text directly

### Requirement: Employment-specific regex patterns removed
The `_OFFICE_DAYS_RE` and `_REMOTE_RE` regex patterns SHALL be removed from `_build_hint_block()`. These patterns are employment-specific and have no equivalent in other professional domains.

#### Scenario: Office-days constraint extracted without hint
- **WHEN** a document contains an explicit office attendance requirement
- **THEN** the LLM extracts it as a constraint without a regex hint injection
